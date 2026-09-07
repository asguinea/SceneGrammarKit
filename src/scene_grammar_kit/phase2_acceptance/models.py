"""Immutable records for Phase 2 acceptance policy version 0.1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

PHASE2_ACCEPTANCE_POLICY_VERSION = "0.1"


class AcceptanceStatus(str, Enum):
    """Stable outcome for one acceptance check or the complete report."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class Phase2AcceptanceCheck:
    code: str
    description: str
    status: AcceptanceStatus
    required: bool
    details: str
    case_key: str | None = None
    artifact_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Phase2CaseAcceptance:
    case_key: str
    image_id: str
    expected_outcome: str
    observed_outcome: str
    constructor_status: str
    primary_grammar: str
    accepted_repeat_groups: int
    fallback_repeat_groups: int
    status: AcceptanceStatus


@dataclass(frozen=True, slots=True)
class Phase2AcceptanceReport:
    overall_status: AcceptanceStatus
    policy_versions: tuple[tuple[str, str], ...]
    cases: tuple[Phase2CaseAcceptance, ...]
    checks: tuple[Phase2AcceptanceCheck, ...]
    total_checks: int
    passed_checks: int
    failed_checks: int
    skipped_checks: int
    required_failed_checks: int
    reproduction_command: str
    known_limitations: tuple[str, ...]
    next_step: str
    artifact_paths: tuple[str, ...]
    phase2_acceptance_policy_version: str = PHASE2_ACCEPTANCE_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class Phase2EvidenceRow:
    case_key: str
    open_images_id: str
    case_role: str
    constructor_status: str
    source_width: int
    source_height: int
    supplied_region_count: int
    supplied_instance_count: int
    supplied_repeat_group_count: int
    lifted_observation_count: int
    split_symbolic_node_count: int
    split_terminal_count: int
    split_grammar_bytes: int
    repeat_symbolic_node_count: int
    repeat_terminal_count: int
    repeat_grammar_bytes: int
    accepted_repeat_groups: int
    fallback_repeat_groups: int
    primary_grammar: str
    primary_primitive_count: int
    default_edit_type: str
    default_edit_status: str
    warning_count: int
    limitation_code: str
    source_license: str


@dataclass(frozen=True, slots=True)
class Phase2ArtifactRecord:
    relative_path: str
    category: str
    byte_size: int
    sha256: str
    required: bool
