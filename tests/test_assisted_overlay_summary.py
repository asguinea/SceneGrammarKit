"""Deterministic annotation drawing and summary tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from PIL import ImageChops

from scene_grammar_kit.assisted import (
    DEPTH_ZONE_COLORS,
    REPEAT_CONNECTOR_COLOR,
    AnnotationOverlayConfig,
    AnnotationRole,
    DepthZone,
    NormalizedPoint,
    NormalizedPolygon,
    annotation_review_summary_to_canonical_json,
    annotation_review_summary_to_text,
    build_annotation_review_summary,
    load_and_verify_source_image,
    load_annotation,
    render_annotation_overlay,
)
from scene_grammar_kit.grammar import Axis
from scene_grammar_kit.rendering.palette import KNOWN_SEMANTIC_COLORS, semantic_color

FIXTURES = Path(__file__).parent / "fixtures" / "assisted" / "valid"
URBAN_PATH = FIXTURES / "urban_minimal.annotation.json"
FACADE_PATH = FIXTURES / "facade_polygon.annotation.json"


def _load(path: Path):
    annotation = load_annotation(path)
    return annotation, load_and_verify_source_image(annotation, path)


def _quiet_config(**changes: object) -> AnnotationOverlayConfig:
    values = {
        "draw_region_ids": False,
        "draw_instance_ids": False,
        "draw_semantic_labels": False,
        "draw_depth_zone_labels": False,
        "draw_repeat_group_links": False,
        "draw_split_axis_hints": False,
        "draw_parent_links": False,
        "draw_legend": False,
    }
    values.update(changes)
    return AnnotationOverlayConfig(**values)


def _pixel_digest(image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def test_fixed_depth_zone_styles_are_stable_and_distinct() -> None:
    assert DEPTH_ZONE_COLORS == {
        DepthZone.FOREGROUND: (226, 55, 55, 255),
        DepthZone.MIDGROUND: (244, 174, 0, 255),
        DepthZone.BACKGROUND: (40, 112, 214, 255),
    }
    assert len(set(DEPTH_ZONE_COLORS.values())) == 3


def test_known_semantic_color_reuses_project_palette() -> None:
    assert semantic_color("road") == KNOWN_SEMANTIC_COLORS["road"]
    assert semantic_color("car") == KNOWN_SEMANTIC_COLORS["car"]


def test_unknown_semantic_fallback_is_sha256_deterministic() -> None:
    first = semantic_color("unlisted_semantic")
    second = semantic_color("unlisted_semantic")
    assert first == second
    assert first != semantic_color("another_unlisted_semantic")


def test_semantic_mapping_order_is_deterministic() -> None:
    annotation, verified = _load(URBAN_PATH)
    result = render_annotation_overlay(verified, annotation, _quiet_config())
    assert tuple(result.semantic_palette) == tuple(sorted(result.semantic_palette))


def test_rectangles_instances_and_open_space_render() -> None:
    annotation, verified = _load(URBAN_PATH)
    result = render_annotation_overlay(verified, annotation, _quiet_config())
    assert result.report.region_rectangles_drawn == 5
    assert result.report.region_polygons_drawn == 1
    assert result.report.instances_drawn == 3
    assert _pixel_digest(result.image) != _pixel_digest(verified.image)


def test_polygon_renders_with_supplied_vertices() -> None:
    annotation, verified = _load(FACADE_PATH)
    result = render_annotation_overlay(verified, annotation, _quiet_config())
    assert result.report.region_polygons_drawn == 1
    assert result.report.region_rectangles_drawn == 0
    expected = ((0.12, 0.88), (0.18, 0.12), (0.84, 0.1), (0.9, 0.88))
    polygon = annotation.regions[0].shape
    assert isinstance(polygon, NormalizedPolygon)
    assert tuple((point.u, point.v) for point in polygon.points) == expected


def test_role_styles_produce_distinct_transparent_pixels() -> None:
    annotation, verified = _load(URBAN_PATH)
    base = replace(
        annotation,
        instances=(),
        repeat_groups=(),
    )
    alphas = {}
    for role, region in (
        (AnnotationRole.STRUCTURAL_REGION, base.regions[1]),
        (AnnotationRole.TERMINAL_REGION, base.regions[2]),
        (AnnotationRole.OPEN_SPACE, base.regions[0]),
    ):
        one = replace(base, regions=(region,))
        one_verified = replace(verified, annotation=one)
        rendered = render_annotation_overlay(
            one_verified,
            one,
            _quiet_config(transparent_semantic_layer=True),
        )
        center = region.shape.centroid
        pixel = rendered.image.getpixel(
            (
                round(center.u * 479),
                round(center.v * 319),
            )
        )
        alphas[role] = pixel[3]
    assert len(set(alphas.values())) == 3


def test_split_axis_hints_change_pixels() -> None:
    annotation, verified = _load(URBAN_PATH)
    without = render_annotation_overlay(
        verified,
        annotation,
        _quiet_config(draw_split_axis_hints=False),
    )
    with_hints = render_annotation_overlay(
        verified,
        annotation,
        _quiet_config(draw_split_axis_hints=True),
    )
    assert ImageChops.difference(without.image, with_hints.image).getbbox()


def test_x_y_and_z_axis_hints_are_renderable() -> None:
    annotation, verified = _load(FACADE_PATH)
    base = annotation.regions[0]
    regions = tuple(
        replace(
            base,
            region_id=f"region_{axis.value}",
            shape=NormalizedPolygon(
                (
                    NormalizedPoint(0.1 + index * 0.3, 0.2),
                    NormalizedPoint(0.3 + index * 0.3, 0.2),
                    NormalizedPoint(0.2 + index * 0.3, 0.5),
                )
            ),
            split_axis_hint=axis,
        )
        for index, axis in enumerate((Axis.X, Axis.Y, Axis.Z))
    )
    modified = replace(annotation, regions=regions)
    result = render_annotation_overlay(
        replace(verified, annotation=modified),
        modified,
        _quiet_config(draw_split_axis_hints=True),
    )
    assert result.report.region_polygons_drawn == 3


def test_repeat_connector_and_order_change_pixels() -> None:
    annotation, verified = _load(URBAN_PATH)
    without = render_annotation_overlay(
        verified,
        annotation,
        _quiet_config(draw_repeat_group_links=False),
    )
    with_links = render_annotation_overlay(
        verified,
        annotation,
        _quiet_config(draw_repeat_group_links=True),
    )
    assert with_links.report.repeat_connectors_drawn == 1
    assert ImageChops.difference(without.image, with_links.image).getbbox()
    assert REPEAT_CONNECTOR_COLOR == (184, 48, 196, 255)

    group = annotation.repeat_groups[0]
    reversed_annotation = replace(
        annotation,
        repeat_groups=(
            replace(
                group,
                member_instance_ids=tuple(reversed(group.member_instance_ids)),
            ),
        ),
    )
    original_labeled = render_annotation_overlay(
        verified,
        annotation,
        AnnotationOverlayConfig(draw_legend=False),
    )
    reversed_result = render_annotation_overlay(
        replace(verified, annotation=reversed_annotation),
        reversed_annotation,
        AnnotationOverlayConfig(draw_legend=False),
    )
    assert _pixel_digest(original_labeled.image) != _pixel_digest(reversed_result.image)


def test_labels_and_legend_can_be_disabled() -> None:
    annotation, verified = _load(URBAN_PATH)
    default = render_annotation_overlay(
        verified,
        annotation,
        AnnotationOverlayConfig(),
    )
    no_labels = render_annotation_overlay(
        verified,
        annotation,
        AnnotationOverlayConfig(
            draw_region_ids=False,
            draw_instance_ids=False,
            draw_semantic_labels=False,
            draw_depth_zone_labels=False,
        ),
    )
    no_legend = render_annotation_overlay(
        verified,
        annotation,
        AnnotationOverlayConfig(draw_legend=False),
    )
    assert default.report.labels_drawn > 0
    assert no_labels.report.labels_drawn == 0
    assert default.report.legend_drawn is True
    assert no_legend.report.legend_drawn is False
    assert _pixel_digest(default.image) != _pixel_digest(no_labels.image)
    assert _pixel_digest(default.image) != _pixel_digest(no_legend.image)


def test_parent_links_are_off_by_default_and_optional() -> None:
    annotation, verified = _load(URBAN_PATH)
    default = render_annotation_overlay(
        verified,
        annotation,
        AnnotationOverlayConfig(),
    )
    parent_links = render_annotation_overlay(
        verified,
        annotation,
        AnnotationOverlayConfig(draw_parent_links=True),
    )
    assert default.report.success
    assert ImageChops.difference(default.image, parent_links.image).getbbox()


def test_summary_counts_and_frequencies() -> None:
    annotation, verified = _load(URBAN_PATH)
    summary = build_annotation_review_summary(annotation, verified)
    assert (summary.region_count, summary.instance_count) == (6, 3)
    assert summary.repeat_group_count == 1
    assert dict(summary.region_role_frequencies) == {
        "open_space": 1,
        "structural_region": 1,
        "terminal_region": 4,
    }
    assert summary.semantic_class_frequencies["car"] == 3
    assert summary.semantic_class_frequencies["sidewalk"] == 2
    assert dict(summary.depth_zone_frequencies) == {
        "background": 1,
        "foreground": 1,
        "midground": 7,
    }
    assert dict(summary.geometry_type_frequencies) == {
        "polygon": 1,
        "rectangle": 8,
    }
    assert dict(summary.split_axis_hint_frequencies) == {"x": 1}
    assert dict(summary.repeat_axis_hint_frequencies) == {"x": 1}
    assert summary.region_hierarchy_maximum_depth == 2


def test_summary_preserves_regions_and_repeat_member_order() -> None:
    annotation, verified = _load(URBAN_PATH)
    summary = build_annotation_review_summary(annotation, verified)
    assert summary.regions_by_depth_zone["midground"] == (
        "midground_layout",
        "left_sidewalk",
        "road",
        "right_sidewalk",
    )
    assert summary.instances_by_repeat_group["parked_cars"] == (
        "car_1",
        "car_2",
        "car_3",
    )


def test_summary_discloses_absent_derived_information() -> None:
    annotation, verified = _load(URBAN_PATH)
    summary = build_annotation_review_summary(annotation, verified)
    assert summary.explicitly_absent_derived_information == (
        "inferred depth",
        "inferred split boundaries",
        "inferred repeat spacing",
        "inferred grammar",
        "reconstructed geometry",
    )
    assert "repeat-member ordering" in summary.supplied_information


def test_summary_json_and_text_are_deterministic() -> None:
    annotation, verified = _load(URBAN_PATH)
    summary = build_annotation_review_summary(annotation, verified)
    first_json = annotation_review_summary_to_canonical_json(summary)
    second_json = annotation_review_summary_to_canonical_json(summary)
    first_text = annotation_review_summary_to_text(summary, annotation)
    second_text = annotation_review_summary_to_text(summary, annotation)
    assert first_json == second_json
    assert first_json == first_json.strip()
    assert first_text == second_text
    assert first_text.endswith("\n")
    assert not first_text.endswith("\n\n")
    assert "Not inferred in this artifact" in first_text
    assert "car_1,car_2,car_3" in first_text
