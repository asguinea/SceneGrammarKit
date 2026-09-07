"""Public API for deterministic canonical scene-example builds."""

from scene_grammar_kit.scene_examples.builder import (
    build_scene_example,
    operation_from_edit_spec,
)
from scene_grammar_kit.scene_examples.errors import (
    ManifestError,
    ManifestFileNotFoundError,
    ManifestJSONError,
    ManifestReadError,
    ManifestSerializationError,
    ManifestValidationError,
    SceneExampleBuildError,
    SceneExampleError,
    SceneExampleFileExistsError,
    SceneExamplePersistenceError,
)
from scene_grammar_kit.scene_examples.models import (
    MANIFEST_POLICY_VERSION,
    CanonicalEditSpec,
    SceneExampleBuildReport,
    SceneExampleBuildResult,
    SceneExampleEditBuild,
    SceneExampleStatistics,
    SceneManifest,
)
from scene_grammar_kit.scene_examples.persistence import (
    build_report_to_canonical_json,
    load_scene_manifest,
    save_build_report,
    save_scene_manifest,
    scene_manifest_from_json,
    scene_manifest_to_canonical_json,
)

__all__ = [
    "MANIFEST_POLICY_VERSION",
    "CanonicalEditSpec",
    "ManifestError",
    "ManifestFileNotFoundError",
    "ManifestJSONError",
    "ManifestReadError",
    "ManifestSerializationError",
    "ManifestValidationError",
    "SceneExampleBuildError",
    "SceneExampleBuildReport",
    "SceneExampleBuildResult",
    "SceneExampleEditBuild",
    "SceneExampleError",
    "SceneExampleFileExistsError",
    "SceneExamplePersistenceError",
    "SceneExampleStatistics",
    "SceneManifest",
    "build_scene_example",
    "build_report_to_canonical_json",
    "load_scene_manifest",
    "operation_from_edit_spec",
    "save_build_report",
    "save_scene_manifest",
    "scene_manifest_from_json",
    "scene_manifest_to_canonical_json",
]
