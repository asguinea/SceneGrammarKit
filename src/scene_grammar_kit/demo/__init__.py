"""Public API for the integrated SceneGrammarKit Phase 1 demonstration."""

from scene_grammar_kit.demo.acceptance import (
    REQUIRED_ACCEPTANCE_CODES,
    run_phase1_acceptance,
    scan_scope,
)
from scene_grammar_kit.demo.errors import (
    DemoBuildError,
    DemoConfigurationError,
    DemoError,
    DemoPersistenceError,
)
from scene_grammar_kit.demo.models import (
    CANONICAL_SCENE_KEYS,
    DEMO_POLICY_VERSION,
    FULL_RENDER_HEIGHT,
    FULL_RENDER_WIDTH,
    QUICK_RENDER_HEIGHT,
    QUICK_RENDER_WIDTH,
    AcceptanceCheck,
    AcceptanceStatus,
    ArtifactEntry,
    DemoConfig,
    DemoManifest,
    DemoResult,
    DeterminismEvidence,
    Phase1AcceptanceReport,
    SceneAcceptance,
)
from scene_grammar_kit.demo.persistence import (
    acceptance_report_to_canonical_json,
    acceptance_report_to_markdown,
    artifact_index_to_canonical_json,
    demo_manifest_to_canonical_json,
)
from scene_grammar_kit.demo.runner import (
    build_artifact_index,
    compare_scene_builds,
    run_demo,
)

__all__ = [
    "CANONICAL_SCENE_KEYS",
    "DEMO_POLICY_VERSION",
    "FULL_RENDER_HEIGHT",
    "FULL_RENDER_WIDTH",
    "QUICK_RENDER_HEIGHT",
    "QUICK_RENDER_WIDTH",
    "AcceptanceCheck",
    "AcceptanceStatus",
    "ArtifactEntry",
    "DemoBuildError",
    "DemoConfig",
    "DemoConfigurationError",
    "DemoError",
    "DemoManifest",
    "DemoPersistenceError",
    "DemoResult",
    "DeterminismEvidence",
    "Phase1AcceptanceReport",
    "REQUIRED_ACCEPTANCE_CODES",
    "SceneAcceptance",
    "acceptance_report_to_canonical_json",
    "acceptance_report_to_markdown",
    "artifact_index_to_canonical_json",
    "build_artifact_index",
    "compare_scene_builds",
    "demo_manifest_to_canonical_json",
    "run_demo",
    "run_phase1_acceptance",
    "scan_scope",
]
