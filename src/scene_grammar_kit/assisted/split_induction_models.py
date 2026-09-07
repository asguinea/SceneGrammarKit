"""Immutable models for constrained split-induction policy version 0.1."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from scene_grammar_kit.assisted.annotation_models import SceneAnnotation
from scene_grammar_kit.assisted.config_models import ConstructionConfig
from scene_grammar_kit.assisted.lifting_models import LiftedSceneObservations
from scene_grammar_kit.assisted.split_induction_errors import (
    SplitInductionValidationError,
)
from scene_grammar_kit.geometry.models import ExecutedScene
from scene_grammar_kit.grammar import Axis, SceneGrammar, ValidationReport

SPLIT_INDUCTION_POLICY_VERSION = "0.1"


class InductionDiagnosticSeverity(str, Enum):
    """Severity of a deterministic induction diagnostic."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AxisSelectionSource(str, Enum):
    """Evidence source used to select a partition axis."""

    SUPPLIED_REGION_HINT = "supplied_region_hint"
    SUPPLIED_REPEAT_HINT = "supplied_repeat_hint"
    DERIVED_GEOMETRY = "derived_geometry"


class GapReason(str, Enum):
    """Reason an explicit empty partition segment was created."""

    LEADING_MARGIN = "leading_margin"
    INTERNAL_GAP = "internal_gap"
    TRAILING_MARGIN = "trailing_margin"


class RepeatCompressionStatus(str, Enum):
    """Batch boundary status for a supplied repeat candidate."""

    DEFERRED_TO_BATCH_2_5 = "deferred_to_batch_2_5"


@dataclass(frozen=True, slots=True)
class InductionDiagnostic:
    """One stable ordered split-induction finding."""

    code: str
    severity: InductionDiagnosticSeverity
    message: str
    source_annotation_id: str | None = None
    grammar_node_id: str | None = None
    structural_path: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.code, "diagnostic code")
        _nonempty(self.message, "diagnostic message")


@dataclass(frozen=True, slots=True)
class AxisCandidateScore:
    """Deterministic geometry score for one candidate partition axis."""

    axis: Axis
    valid: bool
    overlap_violations: int
    normalized_centroid_spread: float
    normalized_coverage: float
    explicit_gap_count: int

    def __post_init__(self) -> None:
        _nonnegative(self.overlap_violations, "overlap_violations")
        _nonnegative(self.explicit_gap_count, "explicit_gap_count")
        _finite(self.normalized_centroid_spread, "normalized_centroid_spread")
        _finite(self.normalized_coverage, "normalized_coverage")


@dataclass(frozen=True, slots=True)
class AxisDecision:
    """Recorded axis candidates and the selected source of authority."""

    parent_source_id: str
    candidate_scores: tuple[AxisCandidateScore, ...]
    selected_axis: Axis
    selection_source: AxisSelectionSource
    world_tolerance: float
    structural_path: str

    def __post_init__(self) -> None:
        _nonempty(self.parent_source_id, "parent_source_id")
        _typed_tuple(self.candidate_scores, AxisCandidateScore, "candidate_scores")
        _finite_nonnegative(self.world_tolerance, "world_tolerance")
        _nonempty(self.structural_path, "structural_path")


@dataclass(frozen=True, slots=True)
class IntervalDecision:
    """Source and final interval for one observation on a selected axis."""

    source_annotation_id: str
    source_minimum: float
    source_maximum: float
    final_minimum: float
    final_maximum: float

    def __post_init__(self) -> None:
        _nonempty(self.source_annotation_id, "source_annotation_id")
        for name in (
            "source_minimum",
            "source_maximum",
            "final_minimum",
            "final_maximum",
        ):
            _finite(getattr(self, name), name)
        if self.source_maximum <= self.source_minimum:
            raise SplitInductionValidationError(
                "source interval must have positive extent"
            )
        if self.final_maximum <= self.final_minimum:
            raise SplitInductionValidationError(
                "final interval must have positive extent"
            )


@dataclass(frozen=True, slots=True)
class BoundaryDecision:
    """Complete recorded boundary construction for one partition."""

    parent_source_id: str
    axis: Axis
    parent_interval: tuple[float, float]
    intervals: tuple[IntervalDecision, ...]
    final_boundaries: tuple[float, ...]
    final_weights: tuple[float, ...]
    world_tolerance: float
    affected_source_ids: tuple[str, ...]
    structural_path: str

    def __post_init__(self) -> None:
        _nonempty(self.parent_source_id, "parent_source_id")
        _positive_interval(self.parent_interval, "parent_interval")
        _typed_tuple(self.intervals, IntervalDecision, "intervals")
        _number_tuple(self.final_boundaries, "final_boundaries")
        _positive_number_tuple(self.final_weights, "final_weights")
        _finite_nonnegative(self.world_tolerance, "world_tolerance")
        _string_tuple(self.affected_source_ids, "affected_source_ids")
        _nonempty(self.structural_path, "structural_path")


@dataclass(frozen=True, slots=True)
class GapDecision:
    """One explicit empty gap or margin in the induced grammar."""

    parent_source_id: str
    axis: Axis
    gap_interval: tuple[float, float]
    reason: GapReason
    generated_empty_node_id: str
    structural_path: str

    def __post_init__(self) -> None:
        _nonempty(self.parent_source_id, "parent_source_id")
        _positive_interval(self.gap_interval, "gap_interval")
        _nonempty(self.generated_empty_node_id, "generated_empty_node_id")
        _nonempty(self.structural_path, "structural_path")


@dataclass(frozen=True, slots=True)
class NodeMapping:
    """Mapping from one supplied observation to generated grammar nodes."""

    source_annotation_type: str
    source_annotation_id: str
    generated_grammar_node_ids: tuple[str, ...]
    primary_generated_node_id: str
    represented_purpose: str

    def __post_init__(self) -> None:
        _nonempty(self.source_annotation_type, "source_annotation_type")
        _nonempty(self.source_annotation_id, "source_annotation_id")
        _string_tuple(
            self.generated_grammar_node_ids,
            "generated_grammar_node_ids",
        )
        _nonempty(self.primary_generated_node_id, "primary_generated_node_id")
        if self.primary_generated_node_id not in self.generated_grammar_node_ids:
            raise SplitInductionValidationError(
                "primary node must appear in generated node IDs"
            )
        _nonempty(self.represented_purpose, "represented_purpose")


@dataclass(frozen=True, slots=True)
class RepeatCandidateRecord:
    """Supplied repeat membership preserved as independent terminals."""

    repeat_group_id: str
    supplied_axis: Axis
    ordered_source_member_ids: tuple[str, ...]
    generated_independent_terminal_ids: tuple[str, ...]
    compression_status: RepeatCompressionStatus = (
        RepeatCompressionStatus.DEFERRED_TO_BATCH_2_5
    )

    def __post_init__(self) -> None:
        _nonempty(self.repeat_group_id, "repeat_group_id")
        _string_tuple(
            self.ordered_source_member_ids,
            "ordered_source_member_ids",
        )
        _string_tuple(
            self.generated_independent_terminal_ids,
            "generated_independent_terminal_ids",
        )


@dataclass(frozen=True, slots=True)
class RootConstructionDecision:
    """Frozen three-zone root split record."""

    root_node_id: str
    axis: Axis
    ordered_zones: tuple[str, ...]
    configured_intervals: tuple[tuple[float, float], ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        _nonempty(self.root_node_id, "root_node_id")
        _string_tuple(self.ordered_zones, "ordered_zones")
        if len(self.ordered_zones) != 3:
            raise SplitInductionValidationError(
                "root construction must contain exactly three zones"
            )
        if (
            not isinstance(self.configured_intervals, tuple)
            or len(self.configured_intervals) != 3
        ):
            raise SplitInductionValidationError(
                "root construction must record three intervals"
            )
        for interval in self.configured_intervals:
            _positive_interval(interval, "configured_interval")
        _positive_number_tuple(self.weights, "weights")
        if len(self.weights) != 3:
            raise SplitInductionValidationError(
                "root construction must record three weights"
            )


@dataclass(frozen=True, slots=True)
class SplitInductionReport:
    """Deterministic decisions, statistics, diagnostics, and nonclaims."""

    success: bool
    grammar_schema_version: str
    lifting_policy_version: str
    scene_id: str
    annotation_sha256: str
    construction_config_sha256: str
    lifted_observations_sha256: str
    induced_grammar_sha256: str
    root_construction_decision: RootConstructionDecision
    axis_decisions: tuple[AxisDecision, ...]
    boundary_decisions: tuple[BoundaryDecision, ...]
    gap_decisions: tuple[GapDecision, ...]
    node_mappings: tuple[NodeMapping, ...]
    repeat_candidates: tuple[RepeatCandidateRecord, ...]
    source_observation_count: int
    represented_observation_count: int
    omitted_observation_count: int
    split_node_count: int
    terminal_node_count: int
    empty_terminal_count: int
    repeat_node_count: int
    maximum_grammar_depth: int
    canonical_grammar_byte_size: int
    validation_status: bool
    execution_verification_status: bool
    supplied_information: tuple[str, ...]
    derived_information: tuple[str, ...]
    explicitly_not_inferred: tuple[str, ...]
    diagnostics: tuple[InductionDiagnostic, ...]
    warnings: tuple[str, ...]
    split_induction_policy_version: str = SPLIT_INDUCTION_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.split_induction_policy_version != SPLIT_INDUCTION_POLICY_VERSION:
            raise SplitInductionValidationError(
                "invalid split-induction policy version"
            )
        for name in (
            "annotation_sha256",
            "construction_config_sha256",
            "lifted_observations_sha256",
            "induced_grammar_sha256",
        ):
            _sha256(getattr(self, name), name)
        for name in (
            "source_observation_count",
            "represented_observation_count",
            "omitted_observation_count",
            "split_node_count",
            "terminal_node_count",
            "empty_terminal_count",
            "repeat_node_count",
            "maximum_grammar_depth",
            "canonical_grammar_byte_size",
        ):
            _nonnegative(getattr(self, name), name)
        if self.repeat_node_count != 0:
            raise SplitInductionValidationError(
                "Batch 2.4 report repeat-node count must be zero"
            )
        _typed_tuple(self.axis_decisions, AxisDecision, "axis_decisions")
        _typed_tuple(
            self.boundary_decisions,
            BoundaryDecision,
            "boundary_decisions",
        )
        _typed_tuple(self.gap_decisions, GapDecision, "gap_decisions")
        _typed_tuple(self.node_mappings, NodeMapping, "node_mappings")
        _typed_tuple(
            self.repeat_candidates,
            RepeatCandidateRecord,
            "repeat_candidates",
        )
        _typed_tuple(
            self.diagnostics,
            InductionDiagnostic,
            "diagnostics",
        )
        for name in (
            "supplied_information",
            "derived_information",
            "explicitly_not_inferred",
            "warnings",
        ):
            _string_tuple(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class SplitInductionResult:
    """Complete split-only induction result with immutable source inputs."""

    annotation: SceneAnnotation
    construction_config: ConstructionConfig
    lifted_observations: LiftedSceneObservations
    induced_grammar: SceneGrammar
    grammar_validation_report: ValidationReport
    execution_verification_result: ExecutedScene | None
    report: SplitInductionReport


@dataclass(frozen=True, slots=True)
class SavedSplitInductionResult:
    """Paths and result from one integrated persisted induction."""

    output_directory: Path
    annotation_path: Path
    construction_config_path: Path
    lifted_observations_path: Path
    induced_grammar_path: Path
    grammar_tree_path: Path
    report_json_path: Path
    report_text_path: Path
    execution_report_path: Path | None
    result: SplitInductionResult


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SplitInductionValidationError(f"{name} must be a nonempty string")
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SplitInductionValidationError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise SplitInductionValidationError(f"{name} must be finite")
    return result


def _finite_nonnegative(value: object, name: str) -> float:
    result = _finite(value, name)
    if result < 0:
        raise SplitInductionValidationError(f"{name} must be nonnegative")
    return result


def _nonnegative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SplitInductionValidationError(f"{name} must be a nonnegative integer")
    return value


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SplitInductionValidationError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return value


def _typed_tuple(value: object, item_type: type, name: str) -> None:
    if not isinstance(value, tuple) or any(
        not isinstance(item, item_type) for item in value
    ):
        raise SplitInductionValidationError(
            f"{name} must be a tuple of {item_type.__name__}"
        )


def _string_tuple(value: object, name: str) -> None:
    if not isinstance(value, tuple) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise SplitInductionValidationError(
            f"{name} must be a tuple of nonempty strings"
        )


def _number_tuple(value: object, name: str) -> None:
    if not isinstance(value, tuple):
        raise SplitInductionValidationError(f"{name} must be a tuple")
    for item in value:
        _finite(item, name)


def _positive_number_tuple(value: object, name: str) -> None:
    _number_tuple(value, name)
    if not value or any(float(item) <= 0 for item in value):
        raise SplitInductionValidationError(f"{name} must contain positive numbers")


def _positive_interval(value: object, name: str) -> None:
    if not isinstance(value, tuple) or len(value) != 2:
        raise SplitInductionValidationError(f"{name} must contain two numbers")
    low = _finite(value[0], name)
    high = _finite(value[1], name)
    if high <= low:
        raise SplitInductionValidationError(f"{name} must have positive extent")
