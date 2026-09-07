"""Immutable value types for annotation-review policy version 0.1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from PIL import Image

from scene_grammar_kit.assisted.annotation_models import SceneAnnotation
from scene_grammar_kit.assisted.review_errors import AnnotationOverlayConfigError
from scene_grammar_kit.rendering.models import Color, normalize_color

ANNOTATION_REVIEW_POLICY_VERSION = "0.1"
MAXIMUM_OVERLAY_DIMENSION = 8192
MAXIMUM_OVERLAY_PIXELS = 16_000_000
MAXIMUM_LABEL_SCALE = 4


class OverlayOutputWidthPolicy(str, Enum):
    """Supported deterministic overlay sizing policy."""

    FIT_WITHIN_MAXIMUM = "fit_within_maximum"


@dataclass(frozen=True, slots=True)
class VerifiedSourceImage:
    """A safely decoded RGBA source image and its verified portable facts."""

    image: Image.Image
    annotation: SceneAnnotation
    relative_path: str
    pixel_width: int
    pixel_height: int
    byte_sha256: str
    image_format: str

    def __post_init__(self) -> None:
        if not isinstance(self.image, Image.Image) or self.image.mode != "RGBA":
            raise AnnotationOverlayConfigError(
                "verified source image must be a Pillow RGBA image"
            )
        if self.image.size != (self.pixel_width, self.pixel_height):
            raise AnnotationOverlayConfigError(
                "verified source image dimensions must match its image"
            )
        if not isinstance(self.annotation, SceneAnnotation):
            raise AnnotationOverlayConfigError(
                "verified source annotation must be a SceneAnnotation"
            )
        _sha256(self.byte_sha256, "byte_sha256")
        if self.image_format not in {"PNG", "JPEG"}:
            raise AnnotationOverlayConfigError(
                "verified image format must be PNG or JPEG"
            )


@dataclass(frozen=True, slots=True)
class AnnotationOverlayConfig:
    """Validated controls for a portable deterministic annotation overlay."""

    output_width_policy: OverlayOutputWidthPolicy | str = (
        OverlayOutputWidthPolicy.FIT_WITHIN_MAXIMUM
    )
    maximum_output_dimension: int = 1600
    line_width: int = 3
    region_fill_opacity: int = 56
    instance_fill_opacity: int = 96
    draw_region_ids: bool = True
    draw_instance_ids: bool = True
    draw_semantic_labels: bool = True
    draw_depth_zone_labels: bool = True
    draw_repeat_group_links: bool = True
    draw_split_axis_hints: bool = True
    draw_parent_links: bool = False
    draw_legend: bool = True
    label_scale: int = 1
    transparent_semantic_layer: bool = False
    maximum_pixel_count: int = MAXIMUM_OVERLAY_PIXELS
    review_policy_version: str = ANNOTATION_REVIEW_POLICY_VERSION

    def __post_init__(self) -> None:
        try:
            policy = OverlayOutputWidthPolicy(self.output_width_policy)
        except (TypeError, ValueError) as exc:
            raise AnnotationOverlayConfigError(
                "output_width_policy must be fit_within_maximum"
            ) from exc
        object.__setattr__(self, "output_width_policy", policy)
        _positive_integer(
            self.maximum_output_dimension,
            "maximum_output_dimension",
        )
        if self.maximum_output_dimension > MAXIMUM_OVERLAY_DIMENSION:
            raise AnnotationOverlayConfigError(
                f"maximum_output_dimension must not exceed {MAXIMUM_OVERLAY_DIMENSION}"
            )
        _positive_integer(self.line_width, "line_width")
        for name in ("region_fill_opacity", "instance_fill_opacity"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise AnnotationOverlayConfigError(
                    f"{name} must be an integer from 0 through 255"
                )
            if not 0 <= value <= 255:
                raise AnnotationOverlayConfigError(f"{name} must be within [0, 255]")
        _positive_integer(self.label_scale, "label_scale")
        if self.label_scale > MAXIMUM_LABEL_SCALE:
            raise AnnotationOverlayConfigError(
                f"label_scale must not exceed {MAXIMUM_LABEL_SCALE}"
            )
        _positive_integer(self.maximum_pixel_count, "maximum_pixel_count")
        if self.maximum_pixel_count > MAXIMUM_OVERLAY_PIXELS:
            raise AnnotationOverlayConfigError(
                f"maximum_pixel_count must not exceed {MAXIMUM_OVERLAY_PIXELS}"
            )
        if (
            self.maximum_output_dimension * self.maximum_output_dimension
            > self.maximum_pixel_count
        ):
            raise AnnotationOverlayConfigError(
                "maximum output dimensions exceed the configured pixel budget"
            )
        for name in (
            "draw_region_ids",
            "draw_instance_ids",
            "draw_semantic_labels",
            "draw_depth_zone_labels",
            "draw_repeat_group_links",
            "draw_split_axis_hints",
            "draw_parent_links",
            "draw_legend",
            "transparent_semantic_layer",
        ):
            if not isinstance(getattr(self, name), bool):
                raise AnnotationOverlayConfigError(f"{name} must be a boolean")
        if self.review_policy_version != ANNOTATION_REVIEW_POLICY_VERSION:
            raise AnnotationOverlayConfigError(
                f"review_policy_version must be {ANNOTATION_REVIEW_POLICY_VERSION!r}"
            )


@dataclass(frozen=True, slots=True)
class AnnotationReviewReport:
    """Canonical deterministic facts about one annotation overlay."""

    success: bool
    scene_id: str
    image_verification_status: str
    source_image_sha256: str
    annotation_sha256: str
    construction_config_sha256: str | None
    overlay_width: int
    overlay_height: int
    region_polygons_drawn: int
    region_rectangles_drawn: int
    instances_drawn: int
    repeat_connectors_drawn: int
    labels_drawn: int
    legend_drawn: bool
    warnings: tuple[str, ...]
    semantic_palette: Mapping[str, Color]
    review_policy_version: str = ANNOTATION_REVIEW_POLICY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise AnnotationOverlayConfigError("success must be a boolean")
        for name in (
            "overlay_width",
            "overlay_height",
        ):
            _positive_integer(getattr(self, name), name)
        for name in (
            "region_polygons_drawn",
            "region_rectangles_drawn",
            "instances_drawn",
            "repeat_connectors_drawn",
            "labels_drawn",
        ):
            _nonnegative_integer(getattr(self, name), name)
        if not isinstance(self.legend_drawn, bool):
            raise AnnotationOverlayConfigError("legend_drawn must be a boolean")
        _sha256(self.source_image_sha256, "source_image_sha256")
        _sha256(self.annotation_sha256, "annotation_sha256")
        if self.construction_config_sha256 is not None:
            _sha256(
                self.construction_config_sha256,
                "construction_config_sha256",
            )
        object.__setattr__(
            self,
            "semantic_palette",
            _frozen_palette(self.semantic_palette),
        )
        _string_tuple(self.warnings, "warnings")
        if self.review_policy_version != ANNOTATION_REVIEW_POLICY_VERSION:
            raise AnnotationOverlayConfigError(
                "invalid annotation-review policy version"
            )


@dataclass(frozen=True, slots=True)
class AnnotationOverlayResult:
    """Rendered RGBA overlay paired with its report and resolved palette."""

    image: Image.Image
    report: AnnotationReviewReport
    semantic_palette: Mapping[str, Color]
    overlay_width: int
    overlay_height: int
    source_image_sha256: str
    annotation_sha256: str
    construction_config_sha256: str | None = None
    review_policy_version: str = ANNOTATION_REVIEW_POLICY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.image, Image.Image) or self.image.mode != "RGBA":
            raise AnnotationOverlayConfigError(
                "annotation overlay must be a Pillow RGBA image"
            )
        if self.image.size != (self.overlay_width, self.overlay_height):
            raise AnnotationOverlayConfigError(
                "overlay dimensions must match the image"
            )
        palette = _frozen_palette(self.semantic_palette)
        if dict(palette) != dict(self.report.semantic_palette):
            raise AnnotationOverlayConfigError("overlay palette must match the report")
        object.__setattr__(self, "semantic_palette", palette)


@dataclass(frozen=True, slots=True)
class AnnotationReviewSummary:
    """Deterministic supplied-evidence inventory for one annotation."""

    annotation_schema_version: str
    scene_id: str
    image_id: str
    source_image_relative_path: str
    declared_image_dimensions: tuple[int, int]
    verified_image_dimensions: tuple[int, int]
    source_image_sha256: str
    coordinate_system: str
    region_count: int
    instance_count: int
    repeat_group_count: int
    region_role_frequencies: Mapping[str, int]
    semantic_class_frequencies: Mapping[str, int]
    depth_zone_frequencies: Mapping[str, int]
    geometry_type_frequencies: Mapping[str, int]
    split_axis_hint_frequencies: Mapping[str, int]
    repeat_axis_hint_frequencies: Mapping[str, int]
    region_hierarchy_maximum_depth: int
    regions_by_depth_zone: Mapping[str, tuple[str, ...]]
    instances_by_repeat_group: Mapping[str, tuple[str, ...]]
    supplied_information: tuple[str, ...]
    explicitly_absent_derived_information: tuple[str, ...]
    warnings: tuple[str, ...]
    review_policy_version: str = ANNOTATION_REVIEW_POLICY_VERSION

    def __post_init__(self) -> None:
        for name in (
            "region_count",
            "instance_count",
            "repeat_group_count",
            "region_hierarchy_maximum_depth",
        ):
            _nonnegative_integer(getattr(self, name), name)
        for name in (
            "region_role_frequencies",
            "semantic_class_frequencies",
            "depth_zone_frequencies",
            "geometry_type_frequencies",
            "split_axis_hint_frequencies",
            "repeat_axis_hint_frequencies",
        ):
            object.__setattr__(
                self,
                name,
                _frozen_counts(getattr(self, name), name),
            )
        for name in ("regions_by_depth_zone", "instances_by_repeat_group"):
            object.__setattr__(
                self,
                name,
                _frozen_string_lists(getattr(self, name), name),
            )
        for name in (
            "supplied_information",
            "explicitly_absent_derived_information",
            "warnings",
        ):
            _string_tuple(getattr(self, name), name)
        _sha256(self.source_image_sha256, "source_image_sha256")
        if self.review_policy_version != ANNOTATION_REVIEW_POLICY_VERSION:
            raise AnnotationOverlayConfigError(
                "invalid annotation-review policy version"
            )


@dataclass(frozen=True, slots=True)
class AnnotationReviewResult:
    """Complete in-memory result and six persisted review artifact paths."""

    output_directory: Path
    annotation_path: Path
    construction_config_path: Path
    overlay_path: Path
    summary_json_path: Path
    summary_text_path: Path
    report_path: Path
    overlay: AnnotationOverlayResult
    summary: AnnotationReviewSummary
    report: AnnotationReviewReport


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AnnotationOverlayConfigError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AnnotationOverlayConfigError(f"{name} must be a nonnegative integer")
    return value


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AnnotationOverlayConfigError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise AnnotationOverlayConfigError(
            f"{name} must be an ordered tuple of nonempty strings"
        )
    return value


def _frozen_counts(value: object, name: str) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise AnnotationOverlayConfigError(f"{name} must be a mapping")
    copied: dict[str, int] = {}
    for key, count in value.items():
        if not isinstance(key, str) or not key:
            raise AnnotationOverlayConfigError(f"{name} keys must be nonempty strings")
        _nonnegative_integer(count, f"{name}[{key!r}]")
        copied[key] = count
    return MappingProxyType(dict(sorted(copied.items())))


def _frozen_string_lists(
    value: object,
    name: str,
) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise AnnotationOverlayConfigError(f"{name} must be a mapping")
    copied: dict[str, tuple[str, ...]] = {}
    for key, items in value.items():
        if not isinstance(key, str) or not key:
            raise AnnotationOverlayConfigError(f"{name} keys must be nonempty strings")
        copied[key] = _string_tuple(items, f"{name}[{key!r}]")
    return MappingProxyType(dict(sorted(copied.items())))


def _frozen_palette(value: object) -> Mapping[str, Color]:
    if not isinstance(value, Mapping):
        raise AnnotationOverlayConfigError("semantic palette must be a mapping")
    copied = {
        semantic_class: normalize_color(color, semantic_class)
        for semantic_class, color in value.items()
    }
    return MappingProxyType(dict(sorted(copied.items())))
