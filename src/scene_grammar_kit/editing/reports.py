"""Immutable reports and result models for deterministic grammar editing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from scene_grammar_kit.editing.operations import (
    EDITING_POLICY_VERSION,
    EditOperation,
)
from scene_grammar_kit.geometry import ExecutedScene
from scene_grammar_kit.grammar import SceneGrammar


@dataclass(frozen=True, slots=True)
class SymbolicDiff:
    """Deterministic local-signature comparison of two grammar trees."""

    node_ids_before: tuple[str, ...]
    node_ids_after: tuple[str, ...]
    added_node_ids: tuple[str, ...]
    removed_node_ids: tuple[str, ...]
    directly_modified_node_ids: tuple[str, ...]
    affected_ancestor_node_ids: tuple[str, ...]
    unchanged_node_ids: tuple[str, ...]
    target_node_ids: tuple[str, ...]
    target_paths_before: tuple[str, ...]
    target_paths_after: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SplitWeightRealization:
    """Requested and realized direct split-child weight change."""

    operation_type: str
    split_node_id: str
    child_node_id: str
    old_stored_weight: float
    requested_new_stored_weight: float
    realized_new_stored_weight: float
    old_normalized_fraction: float
    new_normalized_fraction: float
    normalized_fraction_delta: float
    sibling_count: int
    sibling_weight_sum_before: float
    sibling_weight_sum_after: float
    direct_child_weight_sum_before: float
    direct_child_weight_sum_after: float


@dataclass(frozen=True, slots=True)
class RepeatCountRealization:
    """Requested and realized repeat-count change without materialization."""

    operation_type: str
    repeat_node_id: str
    old_count: int
    requested_count: int
    realized_count: int
    symbolic_terminal_count_in_element: int
    conceptual_terminal_count_in_element: int
    conceptual_expanded_terminal_count_before: int
    conceptual_expanded_terminal_count_after: int
    count_delta: int


@dataclass(frozen=True, slots=True)
class RepeatSpacingRealization:
    """Requested and realized repeat-spacing change."""

    operation_type: str
    repeat_node_id: str
    old_spacing: float
    requested_spacing: float
    realized_spacing: float
    repeat_count: int
    parent_axis_occurrence_count: int
    execution_verified: bool


@dataclass(frozen=True, slots=True)
class TerminalSubstitutionRealization:
    """Requested and realized terminal semantic substitution."""

    operation_type: str
    terminal_node_id: str
    old_semantic_class: str
    requested_semantic_class: str
    realized_semantic_class: str
    geometry_type_preserved: bool
    attributes_preserved: bool


EditRealization: TypeAlias = (
    SplitWeightRealization
    | RepeatCountRealization
    | RepeatSpacingRealization
    | TerminalSubstitutionRealization
)


@dataclass(frozen=True, slots=True)
class GeometryDiff:
    """Bounded deterministic summary of executed primitive changes."""

    primitive_count_before: int
    primitive_count_after: int
    added_primitive_count: int
    removed_primitive_count: int
    modified_primitive_count: int
    unchanged_primitive_count: int
    box_count_before: int
    box_count_after: int
    plane_count_before: int
    plane_count_after: int
    empty_terminal_count_before: int
    empty_terminal_count_after: int
    grammar_sha256_before: str
    grammar_sha256_after: str
    added_primitive_ids: tuple[str, ...]
    removed_primitive_ids: tuple[str, ...]
    modified_primitive_ids: tuple[str, ...]
    unchanged_primitive_ids: tuple[str, ...]
    detail_list_limit: int
    details_truncated: bool


@dataclass(frozen=True, slots=True)
class EditReport:
    """Canonical report for one successful atomic editing transaction."""

    success: bool
    grammar_schema_version: str
    original_grammar_sha256: str
    edited_grammar_sha256: str
    operations: tuple[EditOperation, ...]
    symbolic_diff: SymbolicDiff
    realizations: tuple[EditRealization, ...]
    geometry_diff: GeometryDiff | None
    validation_succeeded: bool
    execution_verification_succeeded: bool
    warnings: tuple[str, ...]
    editing_policy_version: str = EDITING_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class EditResult:
    """Original and edited immutable grammars plus deterministic evidence."""

    original_grammar: SceneGrammar
    edited_grammar: SceneGrammar
    operations: tuple[EditOperation, ...]
    report: EditReport
    original_execution: ExecutedScene | None
    edited_execution: ExecutedScene | None
