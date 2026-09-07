"""Safe source-image verification and deterministic annotation overlays."""

from __future__ import annotations

import hashlib
import io
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from scene_grammar_kit.assisted.annotation_models import (
    AnnotationRole,
    AnnotationShape,
    DepthZone,
    NormalizedPoint,
    NormalizedPolygon,
    NormalizedRectangle,
    SceneAnnotation,
    shape_centroid,
)
from scene_grammar_kit.assisted.review_errors import (
    AnnotationOverlayRenderError,
    SourceImageDimensionError,
    SourceImageFormatError,
    SourceImageHashError,
    SourceImageNotFoundError,
    SourceImagePathError,
    SourceImageReadError,
)
from scene_grammar_kit.assisted.review_models import (
    AnnotationOverlayConfig,
    AnnotationOverlayResult,
    AnnotationReviewReport,
    AnnotationReviewSummary,
    VerifiedSourceImage,
)
from scene_grammar_kit.assisted.serialization import annotation_to_canonical_json
from scene_grammar_kit.grammar import Axis
from scene_grammar_kit.rendering.models import Color
from scene_grammar_kit.rendering.palette import resolve_palette

SUPPORTED_SOURCE_IMAGE_FORMATS = ("PNG", "JPEG")
MAXIMUM_SOURCE_IMAGE_PIXELS = 64_000_000

DEPTH_ZONE_COLORS: Mapping[DepthZone, Color] = {
    DepthZone.FOREGROUND: (226, 55, 55, 255),
    DepthZone.MIDGROUND: (244, 174, 0, 255),
    DepthZone.BACKGROUND: (40, 112, 214, 255),
}
REPEAT_CONNECTOR_COLOR: Color = (184, 48, 196, 255)
PARENT_CONNECTOR_COLOR: Color = (235, 235, 235, 180)
LABEL_BACKGROUND: Color = (20, 24, 31, 220)

SUPPLIED_INFORMATION = (
    "semantic regions",
    "object instances",
    "foreground/midground/background assignments",
    "parent-region relationships",
    "split-axis hints",
    "repeat-group membership",
    "repeat-axis hints",
    "repeat-member ordering",
    "annotation identifiers",
)
ABSENT_DERIVED_INFORMATION = (
    "inferred depth",
    "inferred split boundaries",
    "inferred repeat spacing",
    "inferred grammar",
    "reconstructed geometry",
)


def load_and_verify_source_image(
    annotation: SceneAnnotation,
    annotation_path: Path,
) -> VerifiedSourceImage:
    """Resolve, decode, and verify one source image relative to its annotation.

    Batch 2.2 supports PNG and JPEG. Resolution is confined to the annotation
    file's directory, and no fallback search or silent resize is performed.
    """
    if not isinstance(annotation, SceneAnnotation):
        raise TypeError("annotation must be a SceneAnnotation")
    annotation_file = Path(annotation_path).expanduser().resolve()
    annotation_directory = annotation_file.parent
    relative_path = annotation.source_image.image_path
    candidate = annotation_directory.joinpath(*relative_path.split("/"))
    try:
        resolved_image_path = candidate.resolve(strict=False)
    except OSError as exc:
        raise SourceImagePathError(
            f"Could not resolve source image path {relative_path!r}: {exc}"
        ) from exc
    if not resolved_image_path.is_relative_to(annotation_directory):
        raise SourceImagePathError(
            "Resolved source image path escapes the annotation directory"
        )
    if not resolved_image_path.is_file():
        raise SourceImageNotFoundError(
            f"Referenced source image does not exist: {relative_path}"
        )
    try:
        image_bytes = resolved_image_path.read_bytes()
    except OSError as exc:
        raise SourceImageReadError(
            f"Could not read referenced source image {relative_path}: {exc}"
        ) from exc

    byte_sha256 = hashlib.sha256(image_bytes).hexdigest()
    declared_sha256 = annotation.source_image.sha256
    if declared_sha256 is not None and declared_sha256 != byte_sha256:
        raise SourceImageHashError(
            "Referenced source image SHA-256 does not match the annotation"
        )
    declared_pixels = (
        annotation.source_image.pixel_width * annotation.source_image.pixel_height
    )
    if declared_pixels > MAXIMUM_SOURCE_IMAGE_PIXELS:
        raise SourceImageDimensionError(
            "Declared source dimensions exceed the source-image pixel limit"
        )

    try:
        with Image.open(io.BytesIO(image_bytes)) as decoded:
            image_format = (decoded.format or "").upper()
            if image_format not in SUPPORTED_SOURCE_IMAGE_FORMATS:
                raise SourceImageFormatError(
                    f"Unsupported source image format {image_format or 'unknown'}; "
                    "Batch 2.2 supports PNG and JPEG"
                )
            decoded.load()
            actual_width, actual_height = decoded.size
            if actual_width * actual_height > MAXIMUM_SOURCE_IMAGE_PIXELS:
                raise SourceImageDimensionError(
                    "Decoded source dimensions exceed the source-image pixel limit"
                )
            if actual_width != annotation.source_image.pixel_width:
                raise SourceImageDimensionError(
                    f"Source image width is {actual_width}, but annotation "
                    f"declares {annotation.source_image.pixel_width}"
                )
            if actual_height != annotation.source_image.pixel_height:
                raise SourceImageDimensionError(
                    f"Source image height is {actual_height}, but annotation "
                    f"declares {annotation.source_image.pixel_height}"
                )
            rgba = decoded.convert("RGBA").copy()
    except (
        SourceImageDimensionError,
        SourceImageFormatError,
    ):
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise SourceImageFormatError(
            f"Could not decode source image {relative_path} as PNG or JPEG: {exc}"
        ) from exc

    return VerifiedSourceImage(
        image=rgba,
        annotation=annotation,
        relative_path=relative_path,
        pixel_width=actual_width,
        pixel_height=actual_height,
        byte_sha256=byte_sha256,
        image_format=image_format,
    )


def normalized_point_to_pixel(
    point: NormalizedPoint,
    width: int,
    height: int,
) -> tuple[int, int]:
    """Map normalized UV to pixels using round(value * (dimension - 1))."""
    if not isinstance(point, NormalizedPoint):
        raise TypeError("point must be a NormalizedPoint")
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or width < 1
        or isinstance(height, bool)
        or not isinstance(height, int)
        or height < 1
    ):
        raise ValueError("width and height must be positive integers")
    return (
        round(point.u * (width - 1)),
        round(point.v * (height - 1)),
    )


def shape_to_pixels(
    shape: AnnotationShape,
    width: int,
    height: int,
) -> tuple[tuple[int, int], ...]:
    """Convert a rectangle or ordered polygon to deterministic pixel points."""
    if isinstance(shape, NormalizedRectangle):
        return (
            normalized_point_to_pixel(
                NormalizedPoint(shape.u_min, shape.v_min),
                width,
                height,
            ),
            normalized_point_to_pixel(
                NormalizedPoint(shape.u_max, shape.v_max),
                width,
                height,
            ),
        )
    if isinstance(shape, NormalizedPolygon):
        return tuple(
            normalized_point_to_pixel(point, width, height) for point in shape.points
        )
    raise TypeError("shape must be a normalized rectangle or polygon")


def overlay_dimensions(
    source_width: int,
    source_height: int,
    config: AnnotationOverlayConfig,
) -> tuple[int, int]:
    """Fit dimensions within the configured maximum without aspect distortion."""
    if not isinstance(config, AnnotationOverlayConfig):
        raise TypeError("config must be an AnnotationOverlayConfig")
    if source_width < 1 or source_height < 1:
        raise ValueError("source dimensions must be positive")
    longest = max(source_width, source_height)
    if longest <= config.maximum_output_dimension:
        width, height = source_width, source_height
    elif source_width >= source_height:
        width = config.maximum_output_dimension
        height = max(1, round(source_height * width / source_width))
    else:
        height = config.maximum_output_dimension
        width = max(1, round(source_width * height / source_height))
    if width * height > config.maximum_pixel_count:
        raise AnnotationOverlayRenderError(
            "Resolved overlay dimensions exceed the configured pixel budget"
        )
    return width, height


def render_annotation_overlay(
    verified_image: VerifiedSourceImage,
    annotation: SceneAnnotation,
    config: AnnotationOverlayConfig | None = None,
    *,
    construction_config_sha256: str | None = None,
    warnings: Sequence[str] = (),
) -> AnnotationOverlayResult:
    """Render supplied annotation evidence in the fixed Batch 2.2 draw order."""
    if not isinstance(verified_image, VerifiedSourceImage):
        raise TypeError("verified_image must be a VerifiedSourceImage")
    if not isinstance(annotation, SceneAnnotation):
        raise TypeError("annotation must be a SceneAnnotation")
    if annotation != verified_image.annotation:
        raise AnnotationOverlayRenderError(
            "verified source image belongs to a different annotation"
        )
    overlay_config = config or AnnotationOverlayConfig()
    width, height = overlay_dimensions(
        verified_image.pixel_width,
        verified_image.pixel_height,
        overlay_config,
    )
    semantic_classes = tuple(
        region.semantic_class for region in annotation.regions
    ) + tuple(instance.semantic_class for instance in annotation.instances)
    palette = resolve_palette(semantic_classes)
    try:
        if overlay_config.transparent_semantic_layer:
            image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        elif verified_image.image.size == (width, height):
            image = verified_image.image.copy()
        else:
            image = verified_image.image.resize(
                (width, height),
                resample=Image.Resampling.LANCZOS,
            )

        # 1. Source image is the base above. 2-3. Region and instance fills.
        fill_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        fill_draw = ImageDraw.Draw(fill_layer, "RGBA")
        for region in annotation.regions:
            opacity = _region_opacity(region.role, overlay_config)
            _draw_shape_fill(
                fill_draw,
                region.shape,
                width,
                height,
                (*palette[region.semantic_class][:3], opacity),
            )
        for instance in annotation.instances:
            _draw_shape_fill(
                fill_draw,
                instance.shape,
                width,
                height,
                (
                    *palette[instance.semantic_class][:3],
                    overlay_config.instance_fill_opacity,
                ),
            )
        image = Image.alpha_composite(image, fill_layer)
        draw = ImageDraw.Draw(image, "RGBA")

        # 4. Outlines.
        region_rectangles = 0
        region_polygons = 0
        for region in annotation.regions:
            _draw_shape_outline(
                draw,
                region.shape,
                width,
                height,
                DEPTH_ZONE_COLORS[region.depth_zone],
                _role_line_width(region.role, overlay_config.line_width),
                dashed=region.role is AnnotationRole.OPEN_SPACE,
            )
            if isinstance(region.shape, NormalizedRectangle):
                region_rectangles += 1
            else:
                region_polygons += 1
        for instance in annotation.instances:
            _draw_shape_outline(
                draw,
                instance.shape,
                width,
                height,
                (255, 255, 255, 230),
                overlay_config.line_width + 2,
            )
            _draw_shape_outline(
                draw,
                instance.shape,
                width,
                height,
                DEPTH_ZONE_COLORS[instance.depth_zone],
                overlay_config.line_width,
            )

        instance_by_id = {
            instance.instance_id: instance for instance in annotation.instances
        }
        region_by_id = {region.region_id: region for region in annotation.regions}

        # 5. Repeat connectors, with supplied order and axis.
        repeat_connectors = 0
        repeat_label_items: list[tuple[tuple[int, int], str]] = []
        if overlay_config.draw_repeat_group_links:
            for group in annotation.repeat_groups:
                points = [
                    normalized_point_to_pixel(
                        shape_centroid(instance_by_id[member].shape),
                        width,
                        height,
                    )
                    for member in group.member_instance_ids
                ]
                if len(points) >= 2:
                    draw.line(
                        points,
                        fill=REPEAT_CONNECTOR_COLOR,
                        width=max(1, overlay_config.line_width),
                    )
                    for order, point in enumerate(points, start=1):
                        radius = max(3, overlay_config.line_width + 1)
                        draw.ellipse(
                            (
                                point[0] - radius,
                                point[1] - radius,
                                point[0] + radius,
                                point[1] + radius,
                            ),
                            fill=REPEAT_CONNECTOR_COLOR,
                        )
                        draw.text(
                            (point[0] - 3, point[1] - 5),
                            str(order),
                            font=ImageFont.load_default(),
                            fill=(255, 255, 255, 255),
                        )
                    repeat_label_items.append(
                        (
                            points[0],
                            f"group:{group.repeat_group_id}\n"
                            f"members={len(points)} | "
                            f"supplied axis={group.axis_hint.value}",
                        )
                    )
                    repeat_connectors += 1

        # 6. Optional parent links.
        if overlay_config.draw_parent_links:
            for region in annotation.regions:
                if region.parent_region_id is not None:
                    _draw_parent_link(
                        draw,
                        region.shape,
                        region_by_id[region.parent_region_id].shape,
                        width,
                        height,
                        overlay_config.line_width,
                    )
            for instance in annotation.instances:
                if instance.parent_region_id is not None:
                    _draw_parent_link(
                        draw,
                        instance.shape,
                        region_by_id[instance.parent_region_id].shape,
                        width,
                        height,
                        overlay_config.line_width,
                    )

        # 7. Supplied split-axis hints.
        if overlay_config.draw_split_axis_hints:
            for region in annotation.regions:
                if region.split_axis_hint is None:
                    continue
                center = normalized_point_to_pixel(
                    shape_centroid(region.shape),
                    width,
                    height,
                )
                _draw_axis_hint(
                    draw,
                    center,
                    region.split_axis_hint,
                    overlay_config.line_width,
                )

        # 8. Compact deterministic labels.
        occupied: list[tuple[int, int, int, int]] = []
        labels_drawn = 0
        font = _default_font(overlay_config.label_scale)
        labels_enabled = any(
            (
                overlay_config.draw_region_ids,
                overlay_config.draw_instance_ids,
                overlay_config.draw_semantic_labels,
                overlay_config.draw_depth_zone_labels,
            )
        )
        if labels_enabled:
            for region in annotation.regions:
                text = _region_label(region, overlay_config)
                if text:
                    bounds = region.shape.bounding_rectangle
                    anchor = normalized_point_to_pixel(
                        NormalizedPoint(bounds.u_min, bounds.v_min),
                        width,
                        height,
                    )
                    if _draw_label(draw, anchor, text, font, occupied, image.size):
                        labels_drawn += 1
            for instance in annotation.instances:
                text = _instance_label(instance, overlay_config)
                if text:
                    bounds = instance.shape.bounding_rectangle
                    anchor = normalized_point_to_pixel(
                        NormalizedPoint(bounds.u_min, bounds.v_min),
                        width,
                        height,
                    )
                    if _draw_label(draw, anchor, text, font, occupied, image.size):
                        labels_drawn += 1
            for anchor, text in repeat_label_items:
                if _draw_label(draw, anchor, text, font, occupied, image.size):
                    labels_drawn += 1

        # 9. Legend.
        legend_drawn = False
        if overlay_config.draw_legend:
            _draw_legend(
                draw,
                font,
                overlay_config.line_width,
                image.size,
            )
            legend_drawn = True

        annotation_sha256 = hashlib.sha256(
            annotation_to_canonical_json(annotation).encode("utf-8")
        ).hexdigest()
        report = AnnotationReviewReport(
            success=True,
            scene_id=annotation.scene_id,
            image_verification_status="verified",
            source_image_sha256=verified_image.byte_sha256,
            annotation_sha256=annotation_sha256,
            construction_config_sha256=construction_config_sha256,
            overlay_width=width,
            overlay_height=height,
            region_polygons_drawn=region_polygons,
            region_rectangles_drawn=region_rectangles,
            instances_drawn=len(annotation.instances),
            repeat_connectors_drawn=repeat_connectors,
            labels_drawn=labels_drawn,
            legend_drawn=legend_drawn,
            warnings=tuple(warnings),
            semantic_palette=palette,
        )
        return AnnotationOverlayResult(
            image=image,
            report=report,
            semantic_palette=palette,
            overlay_width=width,
            overlay_height=height,
            source_image_sha256=verified_image.byte_sha256,
            annotation_sha256=annotation_sha256,
            construction_config_sha256=construction_config_sha256,
        )
    except AnnotationOverlayRenderError:
        raise
    except (OSError, ValueError) as exc:
        raise AnnotationOverlayRenderError(
            f"Could not render deterministic annotation overlay: {exc}"
        ) from exc


def build_annotation_review_summary(
    annotation: SceneAnnotation,
    verified_image: VerifiedSourceImage,
    *,
    warnings: Sequence[str] = (),
) -> AnnotationReviewSummary:
    """Build a complete deterministic supplied-versus-derived inventory."""
    if annotation != verified_image.annotation:
        raise AnnotationOverlayRenderError(
            "verified source image belongs to a different annotation"
        )
    role_counts = Counter(region.role.value for region in annotation.regions)
    for role in AnnotationRole:
        role_counts.setdefault(role.value, 0)
    semantic_counts = Counter(
        item.semantic_class for item in annotation.regions + annotation.instances
    )
    zone_counts = Counter(
        item.depth_zone.value for item in annotation.regions + annotation.instances
    )
    for zone in DepthZone:
        zone_counts.setdefault(zone.value, 0)
    geometry_counts = Counter(
        item.shape.type.value for item in annotation.regions + annotation.instances
    )
    split_hint_counts = Counter(
        region.split_axis_hint.value
        for region in annotation.regions
        if region.split_axis_hint is not None
    )
    repeat_hint_counts = Counter(
        group.axis_hint.value for group in annotation.repeat_groups
    )
    regions_by_zone = {
        zone.value: tuple(
            region.region_id
            for region in annotation.regions
            if region.depth_zone is zone
        )
        for zone in DepthZone
    }
    instances_by_group = {
        group.repeat_group_id: group.member_instance_ids
        for group in annotation.repeat_groups
    }
    ungrouped = tuple(
        instance.instance_id
        for instance in annotation.instances
        if instance.repeat_group_id is None
    )
    if ungrouped:
        instances_by_group["ungrouped"] = ungrouped
    return AnnotationReviewSummary(
        annotation_schema_version=annotation.annotation_schema_version,
        scene_id=annotation.scene_id,
        image_id=annotation.source_image.image_id,
        source_image_relative_path=annotation.source_image.image_path,
        declared_image_dimensions=(
            annotation.source_image.pixel_width,
            annotation.source_image.pixel_height,
        ),
        verified_image_dimensions=(
            verified_image.pixel_width,
            verified_image.pixel_height,
        ),
        source_image_sha256=verified_image.byte_sha256,
        coordinate_system=annotation.coordinate_system,
        region_count=len(annotation.regions),
        instance_count=len(annotation.instances),
        repeat_group_count=len(annotation.repeat_groups),
        region_role_frequencies=dict(role_counts),
        semantic_class_frequencies=dict(semantic_counts),
        depth_zone_frequencies=dict(zone_counts),
        geometry_type_frequencies=dict(geometry_counts),
        split_axis_hint_frequencies=dict(split_hint_counts),
        repeat_axis_hint_frequencies=dict(repeat_hint_counts),
        region_hierarchy_maximum_depth=_hierarchy_depth(annotation),
        regions_by_depth_zone=regions_by_zone,
        instances_by_repeat_group=instances_by_group,
        supplied_information=SUPPLIED_INFORMATION,
        explicitly_absent_derived_information=ABSENT_DERIVED_INFORMATION,
        warnings=tuple(warnings),
    )


def annotation_review_summary_to_text(
    summary: AnnotationReviewSummary,
    annotation: SceneAnnotation,
) -> str:
    """Format an ASCII-structured deterministic summary with one newline."""
    lines = [
        "SceneGrammarKit annotation review",
        "============================",
        f"Scene: {summary.scene_id}",
        f"Image: {summary.image_id}",
        (
            f"Source dimensions: {summary.verified_image_dimensions[0]} x "
            f"{summary.verified_image_dimensions[1]} pixels"
        ),
        (
            f"Annotations: regions={summary.region_count}, "
            f"instances={summary.instance_count}, "
            f"repeat_groups={summary.repeat_group_count}"
        ),
        "",
        "Depth-zone breakdown",
        "--------------------",
    ]
    lines.extend(
        f"- {key}: {value}" for key, value in summary.depth_zone_frequencies.items()
    )
    lines.extend(("", "Semantic-class breakdown", "------------------------"))
    lines.extend(
        f"- {key}: {value}" for key, value in summary.semantic_class_frequencies.items()
    )
    lines.extend(
        ("", "Repeat groups (supplied order)", "------------------------------")
    )
    if annotation.repeat_groups:
        for group in annotation.repeat_groups:
            lines.append(
                f"- {group.repeat_group_id}: axis={group.axis_hint.value}; "
                f"members={','.join(group.member_instance_ids)}"
            )
    else:
        lines.append("- none")
    lines.extend(("", "Region hierarchy", "----------------"))
    lines.extend(_hierarchy_text(annotation))
    lines.extend(("", "Supplied split-axis hints", "-------------------------"))
    hinted = [
        f"- {region.region_id}: axis={region.split_axis_hint.value}"
        for region in annotation.regions
        if region.split_axis_hint is not None
    ]
    lines.extend(hinted or ["- none"])
    lines.extend(("", "Warnings", "--------"))
    lines.extend([f"- {warning}" for warning in summary.warnings] or ["- none"])
    lines.extend(("", "Supplied information", "--------------------"))
    lines.extend(f"- {item}" for item in summary.supplied_information)
    lines.extend(("", "Not inferred in this artifact", "-----------------------------"))
    lines.extend(f"- {item}" for item in summary.explicitly_absent_derived_information)
    return "\n".join(lines) + "\n"


def _draw_shape_fill(
    draw: ImageDraw.ImageDraw,
    shape: AnnotationShape,
    width: int,
    height: int,
    fill: Color,
) -> None:
    points = shape_to_pixels(shape, width, height)
    if isinstance(shape, NormalizedRectangle):
        draw.rectangle((points[0], points[1]), fill=fill)
    else:
        draw.polygon(points, fill=fill)


def _draw_shape_outline(
    draw: ImageDraw.ImageDraw,
    shape: AnnotationShape,
    width: int,
    height: int,
    color: Color,
    line_width: int,
    *,
    dashed: bool = False,
) -> None:
    points = shape_to_pixels(shape, width, height)
    if isinstance(shape, NormalizedRectangle):
        first, second = points
        polygon = (
            first,
            (second[0], first[1]),
            second,
            (first[0], second[1]),
        )
    else:
        polygon = points
    closed = polygon + (polygon[0],)
    if dashed:
        for start, end in zip(closed, closed[1:]):
            _draw_dashed_line(draw, start, end, color, line_width)
    else:
        draw.line(closed, fill=color, width=line_width, joint="curve")


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: Color,
    width: int,
) -> None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return
    dash, gap = 8, 5
    distance = 0.0
    while distance < length:
        stop = min(length, distance + dash)
        first = (
            round(start[0] + dx * distance / length),
            round(start[1] + dy * distance / length),
        )
        second = (
            round(start[0] + dx * stop / length),
            round(start[1] + dy * stop / length),
        )
        draw.line((first, second), fill=color, width=width)
        distance += dash + gap


def _draw_parent_link(
    draw: ImageDraw.ImageDraw,
    child: AnnotationShape,
    parent: AnnotationShape,
    width: int,
    height: int,
    line_width: int,
) -> None:
    child_point = normalized_point_to_pixel(shape_centroid(child), width, height)
    parent_point = normalized_point_to_pixel(shape_centroid(parent), width, height)
    draw.line(
        (child_point, parent_point),
        fill=PARENT_CONNECTOR_COLOR,
        width=max(1, line_width - 1),
    )


def _draw_axis_hint(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    axis: Axis,
    line_width: int,
) -> None:
    color = (255, 255, 255, 240)
    radius = 18
    if axis is Axis.X:
        start, end = (
            (center[0] - radius, center[1]),
            (center[0] + radius, center[1]),
        )
        draw.line((start, end), fill=color, width=line_width)
        _arrow_head(draw, end, (1, 0), color, line_width)
    elif axis is Axis.Y:
        start, end = (
            (center[0], center[1] + radius),
            (center[0], center[1] - radius),
        )
        draw.line((start, end), fill=color, width=line_width)
        _arrow_head(draw, end, (0, -1), color, line_width)
    else:
        draw.ellipse(
            (
                center[0] - 7,
                center[1] - 7,
                center[0] + 7,
                center[1] + 7,
            ),
            outline=color,
            width=line_width,
        )
        draw.line(
            (
                (center[0] - 5, center[1] - 5),
                (center[0] + 5, center[1] + 5),
            ),
            fill=color,
            width=line_width,
        )
        draw.line(
            (
                (center[0] + 5, center[1] - 5),
                (center[0] - 5, center[1] + 5),
            ),
            fill=color,
            width=line_width,
        )


def _arrow_head(
    draw: ImageDraw.ImageDraw,
    end: tuple[int, int],
    direction: tuple[int, int],
    color: Color,
    width: int,
) -> None:
    perpendicular = (-direction[1], direction[0])
    back = (end[0] - direction[0] * 7, end[1] - direction[1] * 7)
    draw.line(
        (
            end,
            (back[0] + perpendicular[0] * 4, back[1] + perpendicular[1] * 4),
        ),
        fill=color,
        width=width,
    )
    draw.line(
        (
            end,
            (back[0] - perpendicular[0] * 4, back[1] - perpendicular[1] * 4),
        ),
        fill=color,
        width=width,
    )


def _region_label(region: object, config: AnnotationOverlayConfig) -> str:
    first_line = []
    second_line = []
    third_line = []
    if config.draw_region_ids:
        first_line.append(f"{_role_prefix(region.role)}:{region.region_id}")
    if config.draw_semantic_labels:
        second_line.append(region.semantic_class)
    if config.draw_depth_zone_labels:
        second_line.append(region.depth_zone.value)
    if region.split_axis_hint is not None and config.draw_split_axis_hints:
        third_line.append(f"supplied hint={region.split_axis_hint.value}")
    return "\n".join(
        " | ".join(line) for line in (first_line, second_line, third_line) if line
    )


def _instance_label(instance: object, config: AnnotationOverlayConfig) -> str:
    first_line = []
    second_line = []
    third_line = []
    if config.draw_instance_ids:
        first_line.append(f"I:{instance.instance_id}")
    if config.draw_semantic_labels:
        second_line.append(instance.semantic_class)
    if config.draw_depth_zone_labels:
        second_line.append(instance.depth_zone.value)
    if instance.repeat_group_id is not None:
        third_line.append(f"group={instance.repeat_group_id}")
    return "\n".join(
        " | ".join(line) for line in (first_line, second_line, third_line) if line
    )


def _default_font(scale: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=10 * scale)
    except TypeError:
        return ImageFont.load_default()


def _draw_label(
    draw: ImageDraw.ImageDraw,
    anchor: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    occupied: list[tuple[int, int, int, int]],
    image_size: tuple[int, int],
) -> bool:
    if not text:
        return False
    text_box = draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    pad = 3
    box_width = text_width + pad * 2
    box_height = text_height + pad * 2
    candidates = (
        (anchor[0] + 4, anchor[1] - box_height - 4),
        (anchor[0] + 4, anchor[1] + 4),
        (anchor[0] - box_width - 4, anchor[1] - box_height - 4),
        (anchor[0] - box_width - 4, anchor[1] + 4),
    )
    selected: tuple[int, int, int, int] | None = None
    for x, y in candidates:
        box = _clamp_box(x, y, box_width, box_height, image_size)
        if not any(_boxes_overlap(box, previous) for previous in occupied):
            selected = box
            break
    if selected is None:
        step_x = max(24, box_width // 2)
        step_y = max(16, box_height + 3)
        for y in range(3, max(4, image_size[1] - box_height), step_y):
            for x in range(3, max(4, image_size[0] - box_width), step_x):
                box = _clamp_box(x, y, box_width, box_height, image_size)
                if not any(_boxes_overlap(box, previous) for previous in occupied):
                    selected = box
                    break
            if selected is not None:
                break
    if selected is None:
        selected = _clamp_box(
            candidates[0][0],
            candidates[0][1],
            box_width,
            box_height,
            image_size,
        )
    draw.rectangle(selected, fill=LABEL_BACKGROUND)
    draw.text(
        (selected[0] + pad, selected[1] + pad),
        text,
        font=font,
        fill=(255, 255, 255, 255),
    )
    occupied.append(selected)
    return True


def _draw_legend(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    line_width: int,
    image_size: tuple[int, int],
) -> None:
    labels = (
        "Supplied annotation",
        "depth: FG / MG / BG",
        "roles: S structural | T terminal",
        "O open space | I instance",
        "repeat: magenta, supplied order",
        "hint: supplied axis x / y / z",
        "parent link: optional",
    )
    boxes = [draw.textbbox((0, 0), label, font=font) for label in labels]
    text_width = max(box[2] - box[0] for box in boxes)
    text_height = max(box[3] - box[1] for box in boxes)
    panel_width = min(image_size[0], text_width + 22)
    panel_height = min(image_size[1], len(labels) * (text_height + 4) + 14)
    left = max(0, image_size[0] - panel_width)
    top = max(0, image_size[1] - panel_height)
    draw.rectangle(
        (left, top, image_size[0] - 1, image_size[1] - 1),
        fill=(20, 24, 31, 218),
        outline=(255, 255, 255, 210),
        width=max(1, line_width - 1),
    )
    y = top + 7
    for index, label in enumerate(labels):
        color = (255, 255, 255, 255)
        if index == 1:
            x = left + 7
            for zone in DepthZone:
                draw.line(
                    ((x, y + text_height // 2), (x + 10, y + text_height // 2)),
                    fill=DEPTH_ZONE_COLORS[zone],
                    width=max(1, line_width),
                )
                x += 14
            text_x = x + 2
        else:
            text_x = left + 7
        draw.text((text_x, y), label, font=font, fill=color)
        y += text_height + 4


def _clamp_box(
    x: int,
    y: int,
    width: int,
    height: int,
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    left = min(max(0, x), max(0, image_size[0] - width))
    top = min(max(0, y), max(0, image_size[1] - height))
    return (
        left,
        top,
        min(image_size[0] - 1, left + width),
        min(image_size[1] - 1, top + height),
    )


def _boxes_overlap(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _region_opacity(
    role: AnnotationRole,
    config: AnnotationOverlayConfig,
) -> int:
    if role is AnnotationRole.STRUCTURAL_REGION:
        return round(config.region_fill_opacity * 0.65)
    if role is AnnotationRole.OPEN_SPACE:
        return round(config.region_fill_opacity * 0.35)
    return config.region_fill_opacity


def _role_line_width(role: AnnotationRole, base: int) -> int:
    if role is AnnotationRole.STRUCTURAL_REGION:
        return base + 2
    if role is AnnotationRole.OPEN_SPACE:
        return max(1, base - 1)
    return base


def _role_prefix(role: AnnotationRole) -> str:
    return {
        AnnotationRole.STRUCTURAL_REGION: "S",
        AnnotationRole.TERMINAL_REGION: "T",
        AnnotationRole.OPEN_SPACE: "O",
    }[role]


def _hierarchy_depth(annotation: SceneAnnotation) -> int:
    parent_by_id = {
        region.region_id: region.parent_region_id for region in annotation.regions
    }
    maximum = 0
    for region in annotation.regions:
        depth = 1
        parent = region.parent_region_id
        while parent is not None:
            depth += 1
            parent = parent_by_id.get(parent)
        maximum = max(maximum, depth)
    return maximum


def _hierarchy_text(annotation: SceneAnnotation) -> list[str]:
    children: dict[str | None, list[str]] = {}
    for region in annotation.regions:
        children.setdefault(region.parent_region_id, []).append(region.region_id)
    lines: list[str] = []
    stack = [(region_id, 0) for region_id in reversed(children.get(None, []))]
    while stack:
        region_id, depth = stack.pop()
        lines.append(f"{'  ' * depth}- {region_id}")
        stack.extend(
            (child_id, depth + 1) for child_id in reversed(children.get(region_id, []))
        )
    return lines or ["- none"]
