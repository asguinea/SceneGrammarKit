"""Immutable annotation models for assisted schema version 0.1."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TypeAlias

from scene_grammar_kit.assisted.errors import AnnotationValidationError
from scene_grammar_kit.grammar import Axis, GeometryType

ANNOTATION_SCHEMA_VERSION = "0.1"
NORMALIZED_IMAGE_COORDINATE_SYSTEM = "normalized_image_uv"

AnnotationScalar: TypeAlias = str | int | float


class DepthZone(str, Enum):
    """Human-supplied coarse image-space depth zone."""

    FOREGROUND = "foreground"
    MIDGROUND = "midground"
    BACKGROUND = "background"


class AnnotationRole(str, Enum):
    """Role of a human-supplied semantic region."""

    STRUCTURAL_REGION = "structural_region"
    TERMINAL_REGION = "terminal_region"
    OPEN_SPACE = "open_space"


class AnnotationShapeType(str, Enum):
    """Supported normalized image annotation geometry."""

    RECTANGLE = "rectangle"
    POLYGON = "polygon"


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    """One finite normalized image coordinate in top-left-origin UV space."""

    u: float
    v: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "u", _normalized(self.u, "u"))
        object.__setattr__(self, "v", _normalized(self.v, "v"))


@dataclass(frozen=True, slots=True)
class NormalizedRectangle:
    """Strict positive-area axis-aligned normalized image rectangle."""

    u_min: float
    v_min: float
    u_max: float
    v_max: float
    type: AnnotationShapeType = field(
        default=AnnotationShapeType.RECTANGLE,
        init=False,
    )

    def __post_init__(self) -> None:
        for name in ("u_min", "v_min", "u_max", "v_max"):
            object.__setattr__(
                self,
                name,
                _normalized(getattr(self, name), name),
            )
        if self.u_min >= self.u_max:
            raise AnnotationValidationError("u_min must be less than u_max")
        if self.v_min >= self.v_max:
            raise AnnotationValidationError("v_min must be less than v_max")

    @property
    def bounding_rectangle(self) -> NormalizedRectangle:
        """Return this rectangle as its deterministic normalized bounds."""
        return self

    @property
    def width(self) -> float:
        """Return normalized horizontal extent."""
        return self.u_max - self.u_min

    @property
    def height(self) -> float:
        """Return normalized vertical extent."""
        return self.v_max - self.v_min

    @property
    def centroid(self) -> NormalizedPoint:
        """Return the rectangle center."""
        return NormalizedPoint(
            (self.u_min + self.u_max) / 2.0,
            (self.v_min + self.v_max) / 2.0,
        )

    @property
    def signed_area(self) -> float:
        """Return positive signed area for canonical rectangle orientation."""
        return self.width * self.height

    @property
    def area(self) -> float:
        """Return normalized absolute area."""
        return self.signed_area


@dataclass(frozen=True, slots=True)
class NormalizedPolygon:
    """Ordered, positive-area normalized image polygon."""

    points: tuple[NormalizedPoint, ...]
    type: AnnotationShapeType = field(
        default=AnnotationShapeType.POLYGON,
        init=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.points, tuple):
            raise AnnotationValidationError("polygon points must be an ordered tuple")
        if len(self.points) < 3:
            raise AnnotationValidationError(
                "polygon must contain at least three points"
            )
        if any(not isinstance(point, NormalizedPoint) for point in self.points):
            raise AnnotationValidationError(
                "polygon points must be NormalizedPoint values"
            )
        if self.points[0] == self.points[-1]:
            raise AnnotationValidationError(
                "polygon must not repeat its first point as a closing point"
            )
        distinct = {(point.u, point.v) for point in self.points}
        if len(distinct) < 3:
            raise AnnotationValidationError(
                "polygon must contain at least three distinct points"
            )
        if self.signed_area == 0.0:
            raise AnnotationValidationError("polygon must have nonzero area")

    @property
    def bounding_rectangle(self) -> NormalizedRectangle:
        """Return the smallest axis-aligned normalized bounding rectangle."""
        return NormalizedRectangle(
            min(point.u for point in self.points),
            min(point.v for point in self.points),
            max(point.u for point in self.points),
            max(point.v for point in self.points),
        )

    @property
    def width(self) -> float:
        """Return normalized bounding-box width."""
        return self.bounding_rectangle.width

    @property
    def height(self) -> float:
        """Return normalized bounding-box height."""
        return self.bounding_rectangle.height

    @property
    def signed_area(self) -> float:
        """Return the signed shoelace area while preserving point order."""
        doubled = math.fsum(
            current.u * following.v - following.u * current.v
            for current, following in zip(
                self.points,
                self.points[1:] + self.points[:1],
            )
        )
        return doubled / 2.0

    @property
    def area(self) -> float:
        """Return the absolute normalized polygon area."""
        return abs(self.signed_area)

    @property
    def centroid(self) -> NormalizedPoint:
        """Return the deterministic geometric centroid."""
        cross_values = tuple(
            current.u * following.v - following.u * current.v
            for current, following in zip(
                self.points,
                self.points[1:] + self.points[:1],
            )
        )
        factor = 1.0 / (6.0 * self.signed_area)
        return NormalizedPoint(
            math.fsum(
                (current.u + following.u) * cross
                for current, following, cross in zip(
                    self.points,
                    self.points[1:] + self.points[:1],
                    cross_values,
                )
            )
            * factor,
            math.fsum(
                (current.v + following.v) * cross
                for current, following, cross in zip(
                    self.points,
                    self.points[1:] + self.points[:1],
                    cross_values,
                )
            )
            * factor,
        )


AnnotationShape: TypeAlias = NormalizedRectangle | NormalizedPolygon


@dataclass(frozen=True, slots=True)
class SourceImageReference:
    """Portable metadata reference to one source image without opening it."""

    image_id: str
    image_path: str
    pixel_width: int
    pixel_height: int
    sha256: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.image_id, "image_id")
        _relative_posix_path(self.image_path, "image_path")
        _positive_integer(self.pixel_width, "pixel_width")
        _positive_integer(self.pixel_height, "pixel_height")
        if self.sha256 is not None:
            _sha256(self.sha256, "sha256")
        _optional_note(self.description, "description")


@dataclass(frozen=True, slots=True)
class RegionAnnotation:
    """One human-supplied semantic image region."""

    region_id: str
    semantic_class: str
    shape: AnnotationShape
    depth_zone: DepthZone
    role: AnnotationRole
    parent_region_id: str | None = None
    split_axis_hint: Axis | None = None
    order_hint: int | None = None
    terminal_geometry: GeometryType | None = None
    attributes: Mapping[str, AnnotationScalar] = field(default_factory=dict)
    note: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.region_id, "region_id")
        _nonempty(self.semantic_class, "semantic_class")
        _shape(self.shape)
        _enum(self.depth_zone, DepthZone, "depth_zone")
        _enum(self.role, AnnotationRole, "role")
        _optional_nonempty(self.parent_region_id, "parent_region_id")
        if self.parent_region_id == self.region_id:
            raise AnnotationValidationError(
                "a region may not name itself as its parent"
            )
        if self.split_axis_hint is not None:
            _enum(self.split_axis_hint, Axis, "split_axis_hint")
        _optional_nonnegative_integer(self.order_hint, "order_hint")
        if self.terminal_geometry is not None:
            _enum(self.terminal_geometry, GeometryType, "terminal_geometry")
        if (
            self.role is AnnotationRole.TERMINAL_REGION
            and self.terminal_geometry is None
        ):
            raise AnnotationValidationError(
                "terminal_region must provide terminal_geometry"
            )
        if self.role is AnnotationRole.OPEN_SPACE:
            if self.terminal_geometry is not GeometryType.EMPTY:
                raise AnnotationValidationError(
                    "open_space must use terminal_geometry empty"
                )
        object.__setattr__(
            self,
            "attributes",
            _attributes(self.attributes, "attributes"),
        )
        _optional_note(self.note, "note")


@dataclass(frozen=True, slots=True)
class InstanceAnnotation:
    """One explicitly annotated visible object instance."""

    instance_id: str
    semantic_class: str
    shape: AnnotationShape
    depth_zone: DepthZone
    terminal_geometry: GeometryType
    parent_region_id: str | None = None
    repeat_group_id: str | None = None
    order_hint: int | None = None
    attributes: Mapping[str, AnnotationScalar] = field(default_factory=dict)
    note: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.instance_id, "instance_id")
        _nonempty(self.semantic_class, "semantic_class")
        _shape(self.shape)
        _enum(self.depth_zone, DepthZone, "depth_zone")
        _enum(self.terminal_geometry, GeometryType, "terminal_geometry")
        _optional_nonempty(self.parent_region_id, "parent_region_id")
        _optional_nonempty(self.repeat_group_id, "repeat_group_id")
        _optional_nonnegative_integer(self.order_hint, "order_hint")
        object.__setattr__(
            self,
            "attributes",
            _attributes(self.attributes, "attributes"),
        )
        _optional_note(self.note, "note")


@dataclass(frozen=True, slots=True)
class RepeatGroupAnnotation:
    """Human-supplied repeat membership and axis, without derived spacing."""

    repeat_group_id: str
    member_instance_ids: tuple[str, ...]
    axis_hint: Axis
    semantic_class: str | None = None
    allow_fallback_to_individuals: bool = True
    note: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.repeat_group_id, "repeat_group_id")
        if not isinstance(self.member_instance_ids, tuple):
            raise AnnotationValidationError(
                "member_instance_ids must be an ordered tuple"
            )
        if len(self.member_instance_ids) < 2:
            raise AnnotationValidationError(
                "a repeat group must contain at least two member IDs"
            )
        for member in self.member_instance_ids:
            _nonempty(member, "member_instance_ids")
        if len(set(self.member_instance_ids)) != len(self.member_instance_ids):
            raise AnnotationValidationError("repeat-group member IDs must be unique")
        _enum(self.axis_hint, Axis, "axis_hint")
        _optional_nonempty(self.semantic_class, "semantic_class")
        if not isinstance(self.allow_fallback_to_individuals, bool):
            raise AnnotationValidationError(
                "allow_fallback_to_individuals must be a boolean"
            )
        _optional_note(self.note, "note")


@dataclass(frozen=True, slots=True)
class SceneAnnotation:
    """Root annotation document containing only supplied visible evidence."""

    annotation_schema_version: str
    scene_id: str
    source_image: SourceImageReference
    coordinate_system: str
    regions: tuple[RegionAnnotation, ...]
    instances: tuple[InstanceAnnotation, ...]
    repeat_groups: tuple[RepeatGroupAnnotation, ...]
    description: str | None = None
    annotation_notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.annotation_schema_version != ANNOTATION_SCHEMA_VERSION:
            raise AnnotationValidationError(
                f"annotation_schema_version must be {ANNOTATION_SCHEMA_VERSION!r}"
            )
        _nonempty(self.scene_id, "scene_id")
        if not isinstance(self.source_image, SourceImageReference):
            raise AnnotationValidationError(
                "source_image must be a SourceImageReference"
            )
        if self.coordinate_system != NORMALIZED_IMAGE_COORDINATE_SYSTEM:
            raise AnnotationValidationError(
                f"coordinate_system must be {NORMALIZED_IMAGE_COORDINATE_SYSTEM!r}"
            )
        _typed_tuple(self.regions, RegionAnnotation, "regions")
        _typed_tuple(self.instances, InstanceAnnotation, "instances")
        _typed_tuple(
            self.repeat_groups,
            RepeatGroupAnnotation,
            "repeat_groups",
        )
        _optional_note(self.description, "description")
        if not isinstance(self.annotation_notes, tuple):
            raise AnnotationValidationError("annotation_notes must be an ordered tuple")
        for note in self.annotation_notes:
            _nonempty(note, "annotation_notes")


def shape_bounding_rectangle(shape: AnnotationShape) -> NormalizedRectangle:
    """Return one shape's deterministic normalized bounding rectangle."""
    return _shape(shape).bounding_rectangle


def shape_width(shape: AnnotationShape) -> float:
    """Return one shape's normalized bounding width."""
    return _shape(shape).width


def shape_height(shape: AnnotationShape) -> float:
    """Return one shape's normalized bounding height."""
    return _shape(shape).height


def shape_centroid(shape: AnnotationShape) -> NormalizedPoint:
    """Return one shape's deterministic centroid."""
    return _shape(shape).centroid


def shape_signed_area(shape: AnnotationShape) -> float:
    """Return one shape's signed normalized area."""
    return _shape(shape).signed_area


def shape_area(shape: AnnotationShape) -> float:
    """Return one shape's absolute normalized area."""
    return _shape(shape).area


def _normalized(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnnotationValidationError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise AnnotationValidationError(f"{name} must be finite")
    if not 0.0 <= normalized <= 1.0:
        raise AnnotationValidationError(f"{name} must be within [0, 1]")
    return normalized


def _shape(value: object) -> AnnotationShape:
    if not isinstance(value, (NormalizedRectangle, NormalizedPolygon)):
        raise AnnotationValidationError(
            "shape must be a NormalizedRectangle or NormalizedPolygon"
        )
    return value


def _enum(value: object, enum_type: type[Enum], name: str) -> Enum:
    if not isinstance(value, enum_type):
        allowed = ", ".join(item.value for item in enum_type)
        raise AnnotationValidationError(f"{name} must be one of: {allowed}")
    return value


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnnotationValidationError(f"{name} must be a nonempty string")
    return value


def _optional_nonempty(value: object, name: str) -> str | None:
    if value is not None:
        return _nonempty(value, name)
    return None


def _optional_note(value: object, name: str) -> str | None:
    return _optional_nonempty(value, name)


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AnnotationValidationError(f"{name} must be a positive integer")
    return value


def _optional_nonnegative_integer(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AnnotationValidationError(f"{name} must be a nonnegative integer")
    return value


def _relative_posix_path(value: object, name: str) -> str:
    text = _nonempty(value, name)
    if "\\" in text or ":" in text or text.startswith("/"):
        raise AnnotationValidationError(f"{name} must be a relative POSIX-style path")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in text.split("/")):
        raise AnnotationValidationError(
            f"{name} must not contain empty, dot, or parent segments"
        )
    return text


def _sha256(value: object, name: str) -> str:
    text = _nonempty(value, name)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise AnnotationValidationError(
            f"{name} must be 64 lowercase hexadecimal characters"
        )
    return text


def _attributes(
    value: object,
    name: str,
) -> Mapping[str, AnnotationScalar]:
    if not isinstance(value, Mapping):
        raise AnnotationValidationError(f"{name} must be a mapping")
    copied: dict[str, AnnotationScalar] = {}
    forbidden = {"timestamp", "username", "path"}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise AnnotationValidationError(f"{name} keys must be nonempty strings")
        lowered = key.lower()
        if (
            lowered in forbidden
            or lowered.endswith("_timestamp")
            or lowered.endswith("_username")
            or lowered.endswith("_path")
        ):
            raise AnnotationValidationError(f"{name}.{key} is prohibited metadata")
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise AnnotationValidationError(
                f"{name}.{key} must be a JSON-safe string or scalar"
            )
        if isinstance(item, float) and not math.isfinite(item):
            raise AnnotationValidationError(f"{name}.{key} must be finite")
        copied[key] = item
    return MappingProxyType(copied)


def _typed_tuple(value: object, item_type: type, name: str) -> None:
    if not isinstance(value, tuple):
        raise AnnotationValidationError(f"{name} must be an ordered tuple")
    if any(not isinstance(item, item_type) for item in value):
        raise AnnotationValidationError(
            f"{name} must contain only {item_type.__name__} values"
        )
