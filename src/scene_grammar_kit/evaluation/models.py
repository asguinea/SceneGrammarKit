"""Immutable records for evaluate policy version 0.1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

EVALUATION_POLICY_VERSION = "0.1"
METRIC_IMPLEMENTATION_VERSION = "0.1"
CASE_DEFINITION_VERSION = "0.1"


@dataclass(frozen=True, slots=True)
class ControlledCaseResult:
    """Canonical metrics and provenance for one controlled case."""

    case_id: str
    family: str
    constructor_success: bool
    grammar_validation_success: bool
    execution_success: bool
    source_observation_count: int
    represented_observation_count: int
    source_observation_coverage: float
    omitted_observation_count: int
    duplicate_observation_count: int
    key_split_axis: str
    key_split_boundary_errors: tuple[float, ...]
    maximum_key_split_boundary_error: float
    supplied_repeat_count: int
    produced_repeat_count: int
    repeat_count_exact: bool
    repeat_decision: str
    maximum_accepted_member_proxy_boundary_error: float
    split_only_symbolic_node_count: int
    repeat_grammar_symbolic_node_count: int
    split_only_canonical_bytes: int
    repeat_grammar_canonical_bytes: int
    byte_ratio: float
    flat_terminal_count: int
    flat_canonical_bytes: int
    flat_baseline_equivalent: bool
    predefined_edit_valid: bool
    pixel_difference_status: str
    changed_pixel_count: int
    case_definition_sha256: str
    annotation_sha256: str
    construction_config_sha256: str
    constructor_report_sha256: str
    split_only_grammar_sha256: str
    repeat_grammar_sha256: str
    metric_implementation_sha256: str
    evaluation_snapshot_id: str
    artifact_relative_paths: tuple[str, ...]
    runtime_diagnostic_key: str
    evaluation_policy_version: str = EVALUATION_POLICY_VERSION
    metric_implementation_version: str = METRIC_IMPLEMENTATION_VERSION
    case_definition_version: str = CASE_DEFINITION_VERSION


@dataclass(frozen=True, slots=True)
class RealCaseResult:
    """Descriptive, non-accuracy evidence for one frozen Open Images case."""

    case_key: str
    outcome: str
    supplied_observation_count: int
    accepted_repeat_count: int
    fallback_repeat_count: int
    primary_grammar: str
    split_symbolic_node_count: int
    repeat_symbolic_node_count: int
    split_grammar_bytes: int
    repeat_grammar_bytes: int
    primary_primitive_count: int
    edit_status: str
    warning_count: int
    limitation_description: str
    image_id: str
    source_license: str
    source_image_sha256: str
    annotation_sha256: str
    construction_config_sha256: str
    constructor_report_sha256: str
    primary_grammar_sha256: str
    metric_implementation_sha256: str
    evaluation_snapshot_id: str
    artifact_relative_paths: tuple[str, ...]
    evaluation_policy_version: str = EVALUATION_POLICY_VERSION
    metric_implementation_version: str = METRIC_IMPLEMENTATION_VERSION


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Returned result of one complete evaluation package build."""

    output_directory: Path
    controlled_rows: tuple[ControlledCaseResult, ...]
    real_rows: tuple[RealCaseResult, ...]
    controlled_summary: dict[str, Any]
    artifact_hashes: tuple[tuple[str, str], ...]
