"""Immutable records for repeat-induction policy version 0.1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from scene_grammar_kit.assisted.annotation_models import SceneAnnotation
from scene_grammar_kit.assisted.config_models import ConstructionConfig
from scene_grammar_kit.assisted.lifting_models import LiftedSceneObservations
from scene_grammar_kit.assisted.repeat_induction_errors import (
    RepeatInductionValidationError,
)
from scene_grammar_kit.assisted.split_induction_models import SplitInductionResult
from scene_grammar_kit.geometry import ExecutedScene
from scene_grammar_kit.grammar import (
    Axis,
    Bounds3D,
    GeometryType,
    SceneGrammar,
    ValidationReport,
)

REPEAT_INDUCTION_POLICY_VERSION = "0.1"


class RepeatDecision(str, Enum):
    """Outcome for one supplied repeat group."""

    ACCEPTED = "accepted"
    REJECTED_FALLBACK = "rejected_fallback"
    REJECTED_FATAL = "rejected_fatal"


class RepeatRepresentationStatus(str, Enum):
    """Conceptual representation of one supplied member."""

    COMPRESSED_REPEAT_INSTANCE = "compressed_repeat_instance"
    INDEPENDENT_FALLBACK = "independent_fallback"
    FATAL_REJECTION = "fatal_rejection"


class RepeatDiagnosticSeverity(str, Enum):
    """Severity of one repeat diagnostic."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RepeatDiagnostic:
    code: str
    severity: RepeatDiagnosticSeverity
    message: str
    repeat_group_id: str | None = None
    member_id: str | None = None
    grammar_node_id: str | None = None
    structural_path: str | None = None


@dataclass(frozen=True, slots=True)
class RepeatRegularityMetrics:
    group_id: str
    supplied_axis: Axis
    member_count: int
    member_intervals: tuple[tuple[float, float], ...]
    member_extents: tuple[tuple[float, float, float], ...]
    pairwise_gaps: tuple[float, ...]
    group_span: tuple[float, float]
    estimated_spacing: float
    implied_element_extent: float
    cross_axis_median_centers: tuple[tuple[str, float], ...]
    cross_axis_median_extents: tuple[tuple[str, float], ...]
    alignment_error: float
    size_error: float
    spacing_error: float
    positional_residual: float
    alignment_tolerance: float
    size_tolerance: float
    spacing_tolerance: float


@dataclass(frozen=True, slots=True)
class RepeatGroupDecision:
    group_id: str
    decision: RepeatDecision
    ordered_member_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    repeat_node_id: str | None
    representative_element_id: str | None
    metrics: RepeatRegularityMetrics
    source_parent_id: str | None
    supplied_semantic_class: str
    geometry_type: GeometryType


@dataclass(frozen=True, slots=True)
class RepeatMemberMapping:
    repeat_group_id: str
    source_instance_id: str
    supplied_member_index: int
    repeat_node_id: str | None
    representative_element_node_id: str | None
    fallback_terminal_node_id: str | None
    observed_world_bounds: Bounds3D
    predicted_world_bounds: Bounds3D | None
    boundary_residual: float
    representation_status: RepeatRepresentationStatus


@dataclass(frozen=True, slots=True)
class RepeatCompressionSummary:
    split_only_symbolic_node_count: int
    repeat_symbolic_node_count: int
    split_only_split_count: int
    repeat_split_count: int
    split_only_terminal_count: int
    repeat_terminal_count: int
    split_only_repeat_count: int
    repeat_repeat_count: int
    split_only_canonical_bytes: int
    repeat_canonical_bytes: int
    absolute_byte_difference: int
    byte_ratio: float
    symbolic_node_difference: int
    primitive_count_before: int
    primitive_count_after: int


@dataclass(frozen=True, slots=True)
class RepeatFidelitySummary:
    source_backed_conceptual_count_before: int
    source_backed_conceptual_count_after: int
    maximum_accepted_member_boundary_error: float
    maximum_non_repeat_observation_change: float
    root_bounds_equal: bool
    split_only_execution_success: bool
    repeat_execution_success: bool


@dataclass(frozen=True, slots=True)
class RepeatInductionReport:
    success: bool
    annotation_schema_version: str
    construction_config_schema_version: str
    lifting_policy_version: str
    split_induction_policy_version: str
    grammar_schema_version: str
    execution_policy_version: str
    scene_id: str
    annotation_sha256: str
    construction_config_sha256: str
    lifted_observations_sha256: str
    split_only_grammar_sha256: str
    repeat_grammar_sha256: str
    supplied_repeat_group_count: int
    accepted_group_count: int
    fallback_group_count: int
    fatal_group_count: int
    group_decisions: tuple[RepeatGroupDecision, ...]
    member_mappings: tuple[RepeatMemberMapping, ...]
    compression_summary: RepeatCompressionSummary
    fidelity_summary: RepeatFidelitySummary
    repeat_node_count: int
    validation_status: bool
    execution_status: bool
    supplied_information: tuple[str, ...]
    derived_information: tuple[str, ...]
    explicitly_not_inferred: tuple[str, ...]
    diagnostics: tuple[RepeatDiagnostic, ...]
    warnings: tuple[str, ...]
    repeat_induction_policy_version: str = REPEAT_INDUCTION_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.repeat_induction_policy_version != REPEAT_INDUCTION_POLICY_VERSION:
            raise RepeatInductionValidationError(
                "invalid repeat-induction policy version"
            )
        if self.repeat_node_count != self.accepted_group_count:
            raise RepeatInductionValidationError(
                "repeat-node count must equal accepted-group count"
            )


@dataclass(frozen=True, slots=True)
class RepeatInductionResult:
    annotation: SceneAnnotation
    construction_config: ConstructionConfig
    lifted_observations: LiftedSceneObservations
    split_induction_result: SplitInductionResult
    repeat_grammar: SceneGrammar
    grammar_validation_report: ValidationReport
    split_only_execution: ExecutedScene | None
    repeat_execution: ExecutedScene | None
    report: RepeatInductionReport


@dataclass(frozen=True, slots=True)
class SavedRepeatInductionResult:
    output_directory: Path
    annotation_path: Path
    construction_config_path: Path
    lifted_observations_path: Path
    split_only_grammar_path: Path
    split_only_grammar_tree_path: Path
    repeat_grammar_path: Path
    repeat_grammar_tree_path: Path
    split_induction_report_path: Path
    report_json_path: Path
    report_text_path: Path
    split_only_execution_report_path: Path | None
    repeat_execution_report_path: Path | None
    result: RepeatInductionResult
