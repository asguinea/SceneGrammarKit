"""Immutable records for assisted constructor policy version 0.1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from scene_grammar_kit.assisted.annotation_models import SceneAnnotation
from scene_grammar_kit.assisted.config_models import ConstructionConfig
from scene_grammar_kit.assisted.lifting_models import LiftingResult
from scene_grammar_kit.assisted.repeat_induction_models import RepeatInductionResult
from scene_grammar_kit.assisted.review_models import AnnotationReviewResult
from scene_grammar_kit.assisted.split_induction_models import SplitInductionResult
from scene_grammar_kit.editing import EditResult
from scene_grammar_kit.geometry import ExecutedScene
from scene_grammar_kit.grammar import SceneGrammar
from scene_grammar_kit.rendering import RenderResult

CONSTRUCTOR_POLICY_VERSION = "0.1"


class ConstructionStageOutcome(str, Enum):
    """One stage's auditable outcome."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


class PrimaryGrammarType(str, Enum):
    """Selected primary grammar family."""

    SPLIT_ONLY = "split_only"
    REPEAT = "repeat"


@dataclass(frozen=True, slots=True)
class ConstructionStageStatus:
    stage_name: str
    status: ConstructionStageOutcome
    detail: str
    artifact_paths: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConstructionArtifactRecord:
    relative_path: str
    category: str
    stage: str
    byte_size: int
    sha256: str
    required: bool
    grammar_type: str | None = None
    edit_key: str | None = None


@dataclass(frozen=True, slots=True)
class ConstructionArtifactIndex:
    records: tuple[ConstructionArtifactRecord, ...]
    constructor_policy_version: str = CONSTRUCTOR_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class DefaultEditDecision:
    applied: bool
    selection_policy: str
    operation_type: str | None
    target_node_id: str | None
    requested_value: str | None
    realized_value: str | None
    reason: str
    procedural_variation: bool


@dataclass(frozen=True, slots=True)
class GrammarConstructionSummary:
    grammar_type: PrimaryGrammarType
    symbolic_node_count: int
    split_node_count: int
    repeat_node_count: int
    terminal_node_count: int
    primitive_count: int
    canonical_byte_size: int


@dataclass(frozen=True, slots=True)
class AssistedConstructionReport:
    success: bool
    annotation_schema_version: str
    construction_config_schema_version: str
    review_policy_version: str
    lifting_policy_version: str
    split_induction_policy_version: str
    repeat_induction_policy_version: str
    grammar_schema_version: str
    execution_policy_version: str
    renderer_policy_version: str
    editing_policy_version: str
    scene_id: str
    image_id: str
    source_image_sha256: str | None
    annotation_sha256: str
    construction_config_sha256: str
    lifted_scene_sha256: str
    split_only_grammar_sha256: str
    repeat_grammar_sha256: str
    primary_grammar_sha256: str
    primary_grammar_type: PrimaryGrammarType
    primary_selection_reason: str
    supplied_repeat_group_count: int
    accepted_repeat_group_count: int
    fallback_repeat_group_count: int
    stage_statuses: tuple[ConstructionStageStatus, ...]
    artifact_relative_paths: tuple[str, ...]
    grammar_summaries: tuple[GrammarConstructionSummary, ...]
    construction_warnings: tuple[str, ...]
    edit_decision: DefaultEditDecision
    supplied_information: tuple[str, ...]
    configured_information: tuple[str, ...]
    derived_information: tuple[str, ...]
    explicitly_not_inferred: tuple[str, ...]
    constructor_policy_version: str = CONSTRUCTOR_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class AssistedConstructionResult:
    output_directory: Path
    annotation: SceneAnnotation
    construction_config: ConstructionConfig
    review_result: AnnotationReviewResult | None
    lifting_result: LiftingResult
    split_induction_result: SplitInductionResult
    repeat_induction_result: RepeatInductionResult
    primary_grammar: SceneGrammar
    primary_execution: ExecutedScene | None
    primary_render: RenderResult | None
    edited_grammar: SceneGrammar | None
    edited_execution: ExecutedScene | None
    edited_render: RenderResult | None
    edit_result: EditResult | None
    artifact_index: ConstructionArtifactIndex
    report: AssistedConstructionReport
