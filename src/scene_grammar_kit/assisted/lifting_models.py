"""Immutable models for non-metric lifting policy version 0.1."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from scene_grammar_kit.assisted.annotation_models import (
    AnnotationRole,
    AnnotationScalar,
    AnnotationShape,
    DepthZone,
    NormalizedPoint,
    NormalizedRectangle,
    SceneAnnotation,
)
from scene_grammar_kit.assisted.config_models import (
    ConstructionConfig,
    DepthZoneInterval,
    ProjectionModel,
)
from scene_grammar_kit.assisted.lifting_errors import LiftingValidationError
from scene_grammar_kit.assisted.review_models import VerifiedSourceImage
from scene_grammar_kit.grammar import Axis, Bounds3D, GeometryType, Vector3

LIFTING_POLICY_VERSION = "0.1"
INSTANCE_DEPTH_FRACTION = 0.05


class ObservationSourceType(str, Enum):
    """Kind of supplied annotation that produced an observation."""

    REGION = "region"
    INSTANCE = "instance"


class ObservationPurpose(str, Enum):
    """Non-rendering purpose assigned by supplied annotation role."""

    STRUCTURAL = "structural"
    TERMINAL_CANDIDATE = "terminal_candidate"
    OPEN_SPACE = "open_space"
    OBJECT_INSTANCE = "object_instance"


class DerivedDepthPolicy(str, Enum):
    """Frozen policy used to derive one proxy z interval."""

    FULL_ZONE_INTERVAL = "full_zone_interval"
    IMAGE_BOTTOM_PROXY_ANCHOR = "image_bottom_proxy_anchor"


class ProxyApproximation(str, Enum):
    """Image-shape approximation used by coarse world bounds."""

    RECTANGLE_BOUNDS = "rectangle_bounds"
    IMAGE_POLYGON_BOUNDING_BOX = "image_polygon_bounding_box"


@dataclass(frozen=True, slots=True)
class LiftingWarning:
    """One stable deterministic non-fatal lifting diagnostic."""

    code: str
    message: str
    annotation_id: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.code, "warning code")
        _nonempty(self.message, "warning message")
        if self.annotation_id is not None:
            _nonempty(self.annotation_id, "warning annotation_id")


@dataclass(frozen=True, slots=True)
class SuppliedObservationProvenance:
    """Values copied from supplied annotation evidence."""

    annotation_id: str
    semantic_class: str
    image_shape: AnnotationShape
    depth_zone: DepthZone
    region_role: AnnotationRole | None
    terminal_geometry: GeometryType | None
    parent_region_id: str | None
    repeat_group_id: str | None
    split_axis_hint: Axis | None
    repeat_axis_hint: Axis | None
    order_hint: int | None
    attributes: Mapping[str, AnnotationScalar]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", _frozen_attributes(self.attributes))


@dataclass(frozen=True, slots=True)
class ConfigurationObservationProvenance:
    """Configuration values used by deterministic proxy lifting."""

    root_bounds: Bounds3D
    depth_zone_interval: DepthZoneInterval
    projection_model: ProjectionModel
    construction_config_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.construction_config_sha256, "construction_config_sha256")


@dataclass(frozen=True, slots=True)
class DerivedObservationProvenance:
    """Proxy values derived by the frozen lifting equations."""

    world_bounds: Bounds3D
    world_centroid: Vector3
    depth_policy: DerivedDepthPolicy
    proxy_approximation: ProxyApproximation
    lifting_policy_version: str = LIFTING_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.lifting_policy_version != LIFTING_POLICY_VERSION:
            raise LiftingValidationError("invalid lifting policy version")


@dataclass(frozen=True, slots=True)
class ObservationProvenance:
    """Supplied, configured, and derived provenance partitions."""

    supplied: SuppliedObservationProvenance
    configuration: ConfigurationObservationProvenance
    derived: DerivedObservationProvenance


@dataclass(frozen=True, slots=True)
class LiftedObservation:
    """One coarse non-rendering semantic observation in the root volume."""

    observation_id: str
    source_annotation_type: ObservationSourceType
    source_annotation_id: str
    semantic_class: str
    depth_zone: DepthZone
    purpose: ObservationPurpose
    terminal_geometry: GeometryType | None
    normalized_source_shape: AnnotationShape
    normalized_source_bounds: NormalizedRectangle
    normalized_source_signed_area: float
    normalized_source_area: float
    normalized_source_centroid: NormalizedPoint
    world_bounds: Bounds3D
    world_centroid: Vector3
    depth_policy: DerivedDepthPolicy
    proxy_approximation: ProxyApproximation
    parent_region_id: str | None
    repeat_group_id: str | None
    supplied_split_axis_hint: Axis | None
    supplied_order_hint: int | None
    attributes: Mapping[str, AnnotationScalar]
    provenance: ObservationProvenance

    def __post_init__(self) -> None:
        expected_prefix = f"{self.source_annotation_type.value}:"
        if self.observation_id != expected_prefix + self.source_annotation_id:
            raise LiftingValidationError(
                "observation_id must be the source type and annotation ID"
            )
        _nonempty(self.semantic_class, "semantic_class")
        object.__setattr__(self, "attributes", _frozen_attributes(self.attributes))
        if self.normalized_source_signed_area != (
            self.normalized_source_shape.signed_area
        ):
            raise LiftingValidationError(
                "normalized signed area must match supplied shape evidence"
            )
        if self.normalized_source_area != self.normalized_source_shape.area:
            raise LiftingValidationError(
                "normalized area must match supplied shape evidence"
            )
        if self.normalized_source_centroid != (self.normalized_source_shape.centroid):
            raise LiftingValidationError(
                "normalized centroid must match supplied shape evidence"
            )
        if dict(self.attributes) != dict(self.provenance.supplied.attributes):
            raise LiftingValidationError(
                "observation attributes must match supplied provenance"
            )
        if self.world_bounds != self.provenance.derived.world_bounds:
            raise LiftingValidationError("world bounds must match derived provenance")
        if self.world_centroid != self.provenance.derived.world_centroid:
            raise LiftingValidationError("world centroid must match derived provenance")


@dataclass(frozen=True, slots=True)
class LiftedSceneObservations:
    """Ordered lifted observations and their portable source/config facts."""

    annotation_schema_version: str
    construction_config_schema_version: str
    scene_id: str
    image_id: str
    source_image_relative_path: str
    image_verification_status: bool
    verified_source_image_sha256: str | None
    annotation_sha256: str
    construction_config_sha256: str
    coordinate_system: str
    projection_model: ProjectionModel
    root_bounds: Bounds3D
    depth_zone_intervals: tuple[DepthZoneInterval, ...]
    observations: tuple[LiftedObservation, ...]
    source_pixels_used_for_geometric_inference: bool
    assumptions: tuple[str, ...]
    warnings: tuple[LiftingWarning, ...]
    lifting_policy_version: str = LIFTING_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.lifting_policy_version != LIFTING_POLICY_VERSION:
            raise LiftingValidationError("invalid lifting policy version")
        if not isinstance(self.image_verification_status, bool):
            raise LiftingValidationError("image_verification_status must be a boolean")
        if self.image_verification_status:
            if self.verified_source_image_sha256 is None:
                raise LiftingValidationError(
                    "verified image status requires a source-image hash"
                )
            _sha256(
                self.verified_source_image_sha256,
                "verified_source_image_sha256",
            )
        elif self.verified_source_image_sha256 is not None:
            raise LiftingValidationError(
                "unverified image status must not contain an image hash"
            )
        _sha256(self.annotation_sha256, "annotation_sha256")
        _sha256(self.construction_config_sha256, "construction_config_sha256")
        if (
            not isinstance(self.source_pixels_used_for_geometric_inference, bool)
            or self.source_pixels_used_for_geometric_inference
        ):
            raise LiftingValidationError(
                "source pixels used for geometric inference must be false"
            )
        _typed_tuple(self.depth_zone_intervals, DepthZoneInterval, "intervals")
        _typed_tuple(self.observations, LiftedObservation, "observations")
        _typed_tuple(self.warnings, LiftingWarning, "warnings")
        _string_tuple(self.assumptions, "assumptions")


@dataclass(frozen=True, slots=True)
class LiftingReport:
    """Deterministic counts, diagnostics, provenance, and nonclaims."""

    success: bool
    scene_id: str
    image_verification_status: bool
    source_image_sha256: str | None
    annotation_sha256: str
    construction_config_sha256: str
    region_observations_created: int
    instance_observations_created: int
    structural_observations: int
    terminal_candidate_observations: int
    open_space_observations: int
    object_instance_observations: int
    rectangle_source_count: int
    polygon_source_count: int
    depth_zone_frequency: Mapping[str, int]
    geometry_type_frequency: Mapping[str, int]
    observations_with_split_axis_hints: int
    observations_with_repeat_group_membership: int
    assumptions: tuple[str, ...]
    warnings: tuple[LiftingWarning, ...]
    supplied_information: tuple[str, ...]
    derived_information: tuple[str, ...]
    explicitly_not_inferred: tuple[str, ...]
    lifting_policy_version: str = LIFTING_POLICY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise LiftingValidationError("success must be a boolean")
        if not isinstance(self.image_verification_status, bool):
            raise LiftingValidationError("image_verification_status must be a boolean")
        if self.image_verification_status:
            if self.source_image_sha256 is None:
                raise LiftingValidationError(
                    "verified report requires a source-image hash"
                )
            _sha256(self.source_image_sha256, "source_image_sha256")
        elif self.source_image_sha256 is not None:
            raise LiftingValidationError(
                "unverified report must not invent an image hash"
            )
        _sha256(self.annotation_sha256, "annotation_sha256")
        _sha256(self.construction_config_sha256, "construction_config_sha256")
        for name in (
            "region_observations_created",
            "instance_observations_created",
            "structural_observations",
            "terminal_candidate_observations",
            "open_space_observations",
            "object_instance_observations",
            "rectangle_source_count",
            "polygon_source_count",
            "observations_with_split_axis_hints",
            "observations_with_repeat_group_membership",
        ):
            _nonnegative_integer(getattr(self, name), name)
        object.__setattr__(
            self,
            "depth_zone_frequency",
            _frozen_counts(self.depth_zone_frequency, "depth_zone_frequency"),
        )
        object.__setattr__(
            self,
            "geometry_type_frequency",
            _frozen_counts(self.geometry_type_frequency, "geometry_type_frequency"),
        )
        for name in (
            "assumptions",
            "supplied_information",
            "derived_information",
            "explicitly_not_inferred",
        ):
            _string_tuple(getattr(self, name), name)
        _typed_tuple(self.warnings, LiftingWarning, "warnings")
        if self.lifting_policy_version != LIFTING_POLICY_VERSION:
            raise LiftingValidationError("invalid lifting policy version")


@dataclass(frozen=True, slots=True)
class LiftingResult:
    """Complete model-only lifting output and immutable original inputs."""

    scene: LiftedSceneObservations
    report: LiftingReport
    annotation: SceneAnnotation
    construction_config: ConstructionConfig
    verified_source_image: VerifiedSourceImage | None = None


@dataclass(frozen=True, slots=True)
class SavedLiftingResult:
    """Paths and models from one persisted integrated lifting run."""

    output_directory: Path
    annotation_path: Path
    construction_config_path: Path
    lifted_scene_path: Path
    lifted_text_path: Path
    report_path: Path
    result: LiftingResult


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiftingValidationError(f"{name} must be a nonempty string")
    return value


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LiftingValidationError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LiftingValidationError(f"{name} must be a nonnegative integer")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise LiftingValidationError(f"{name} must be a tuple of nonempty strings")
    return value


def _typed_tuple(value: object, item_type: type, name: str) -> None:
    if not isinstance(value, tuple) or any(
        not isinstance(item, item_type) for item in value
    ):
        raise LiftingValidationError(
            f"{name} must be a tuple of {item_type.__name__} values"
        )


def _frozen_attributes(
    value: Mapping[str, AnnotationScalar],
) -> Mapping[str, AnnotationScalar]:
    if not isinstance(value, Mapping):
        raise LiftingValidationError("attributes must be a mapping")
    copied: dict[str, AnnotationScalar] = {}
    for key, item in value.items():
        _nonempty(key, "attribute key")
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise LiftingValidationError(
                "attribute values must be strings or finite scalars"
            )
        if isinstance(item, float) and not math.isfinite(item):
            raise LiftingValidationError("attribute values must be finite")
        copied[key] = item
    return MappingProxyType(dict(sorted(copied.items())))


def _frozen_counts(value: object, name: str) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise LiftingValidationError(f"{name} must be a mapping")
    copied = {}
    for key, count in value.items():
        _nonempty(key, f"{name} key")
        _nonnegative_integer(count, f"{name}[{key}]")
        copied[key] = count
    return MappingProxyType(dict(sorted(copied.items())))
