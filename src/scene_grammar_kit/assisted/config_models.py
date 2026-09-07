"""Immutable construction controls for config schema version 0.1."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from scene_grammar_kit.assisted.annotation_models import DepthZone
from scene_grammar_kit.assisted.errors import ConstructionConfigValidationError
from scene_grammar_kit.grammar import Bounds3D

CONSTRUCTION_CONFIG_SCHEMA_VERSION = "0.1"


class ProjectionModel(str, Enum):
    """Supported non-metric projection proxy."""

    NORMALIZED_ORTHOGRAPHIC_PROXY = "normalized_orthographic_proxy"


class ConstructionAxisPolicy(str, Enum):
    """Policy for using explicitly supplied structural axis hints."""

    HINTS_THEN_GEOMETRY = "hints_then_geometry"
    HINTS_REQUIRED = "hints_required"


@dataclass(frozen=True, slots=True)
class DepthZoneInterval:
    """One configured world-z interval for a named depth zone."""

    depth_zone: DepthZone
    z_min: float
    z_max: float

    def __post_init__(self) -> None:
        if not isinstance(self.depth_zone, DepthZone):
            raise ConstructionConfigValidationError(
                "depth_zone must be foreground, midground, or background"
            )
        object.__setattr__(self, "z_min", _finite(self.z_min, "z_min"))
        object.__setattr__(self, "z_max", _finite(self.z_max, "z_max"))
        if self.z_min >= self.z_max:
            raise ConstructionConfigValidationError("z_min must be less than z_max")


@dataclass(frozen=True, slots=True)
class ConstructionConfig:
    """Strict controls for future deterministic constrained construction."""

    config_schema_version: str
    projection_model: ProjectionModel
    root_bounds: Bounds3D
    depth_zone_intervals: tuple[DepthZoneInterval, ...]
    axis_policy: ConstructionAxisPolicy
    minimum_normalized_region_extent: float = 0.01
    boundary_merge_tolerance: float = 0.02
    repeat_alignment_tolerance: float = 0.03
    repeat_size_tolerance: float = 0.20
    repeat_spacing_tolerance: float = 0.25
    maximum_grammar_depth: int = 16
    allow_repeat_fallback: bool = True
    require_complete_depth_coverage: bool = True

    def __post_init__(self) -> None:
        if self.config_schema_version != CONSTRUCTION_CONFIG_SCHEMA_VERSION:
            raise ConstructionConfigValidationError(
                f"config_schema_version must be {CONSTRUCTION_CONFIG_SCHEMA_VERSION!r}"
            )
        if not isinstance(self.projection_model, ProjectionModel):
            raise ConstructionConfigValidationError(
                "projection_model must be normalized_orthographic_proxy"
            )
        if not isinstance(self.root_bounds, Bounds3D):
            raise ConstructionConfigValidationError("root_bounds must be a Bounds3D")
        if not isinstance(self.depth_zone_intervals, tuple):
            raise ConstructionConfigValidationError(
                "depth_zone_intervals must be an ordered tuple"
            )
        if any(
            not isinstance(item, DepthZoneInterval)
            for item in self.depth_zone_intervals
        ):
            raise ConstructionConfigValidationError(
                "depth_zone_intervals must contain DepthZoneInterval values"
            )
        if not isinstance(self.axis_policy, ConstructionAxisPolicy):
            raise ConstructionConfigValidationError(
                "axis_policy must be hints_then_geometry or hints_required"
            )
        minimum = _finite_positive(
            self.minimum_normalized_region_extent,
            "minimum_normalized_region_extent",
        )
        object.__setattr__(
            self,
            "minimum_normalized_region_extent",
            minimum,
        )
        for name in (
            "boundary_merge_tolerance",
            "repeat_alignment_tolerance",
            "repeat_size_tolerance",
            "repeat_spacing_tolerance",
        ):
            object.__setattr__(
                self,
                name,
                _finite_nonnegative(getattr(self, name), name),
            )
        if (
            isinstance(self.maximum_grammar_depth, bool)
            or not isinstance(self.maximum_grammar_depth, int)
            or self.maximum_grammar_depth < 1
        ):
            raise ConstructionConfigValidationError(
                "maximum_grammar_depth must be a positive integer"
            )
        if not isinstance(self.allow_repeat_fallback, bool):
            raise ConstructionConfigValidationError(
                "allow_repeat_fallback must be a boolean"
            )
        if not isinstance(self.require_complete_depth_coverage, bool):
            raise ConstructionConfigValidationError(
                "require_complete_depth_coverage must be a boolean"
            )
        _validate_intervals(
            self.depth_zone_intervals,
            self.root_bounds,
            self.require_complete_depth_coverage,
        )


def _validate_intervals(
    intervals: tuple[DepthZoneInterval, ...],
    root_bounds: Bounds3D,
    require_complete: bool,
) -> None:
    expected = (
        DepthZone.FOREGROUND,
        DepthZone.MIDGROUND,
        DepthZone.BACKGROUND,
    )
    actual = tuple(item.depth_zone for item in intervals)
    if actual != expected:
        raise ConstructionConfigValidationError(
            "depth_zone_intervals must contain exactly foreground, midground, "
            "and background in that order"
        )
    root_min = root_bounds.minimum.z
    root_max = root_bounds.maximum.z
    for item in intervals:
        if item.z_min < root_min or item.z_max > root_max:
            raise ConstructionConfigValidationError(
                f"{item.depth_zone.value} interval must be inside root z bounds"
            )
    for first, second in zip(intervals, intervals[1:]):
        if first.z_max > second.z_min:
            raise ConstructionConfigValidationError(
                "depth-zone intervals must not overlap"
            )
        if require_complete and first.z_max != second.z_min:
            raise ConstructionConfigValidationError(
                "complete depth coverage requires adjacent shared boundaries"
            )
    if require_complete and (
        intervals[0].z_min != root_min or intervals[-1].z_max != root_max
    ):
        raise ConstructionConfigValidationError(
            "complete depth coverage must span the full root z interval"
        )


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConstructionConfigValidationError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ConstructionConfigValidationError(f"{name} must be finite")
    return normalized


def _finite_positive(value: object, name: str) -> float:
    normalized = _finite(value, name)
    if normalized <= 0:
        raise ConstructionConfigValidationError(f"{name} must be strictly positive")
    return normalized


def _finite_nonnegative(value: object, name: str) -> float:
    normalized = _finite(value, name)
    if normalized < 0:
        raise ConstructionConfigValidationError(f"{name} must be nonnegative")
    return normalized
