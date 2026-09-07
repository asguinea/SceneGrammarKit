"""Immutable public models for demo policy version 0.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from scene_grammar_kit.demo.errors import DemoConfigurationError
from scene_grammar_kit.scene_examples import SceneExampleBuildResult

DEMO_POLICY_VERSION = "0.1"
FULL_RENDER_WIDTH = 1200
FULL_RENDER_HEIGHT = 800
QUICK_RENDER_WIDTH = 640
QUICK_RENDER_HEIGHT = 426
CANONICAL_SCENE_KEYS = (
    "urban_street",
    "repeated_facade",
    "indoor_corridor",
)
REVIEW_IMAGE_SPECS = (
    ("urban_original.png", "urban_street", "original/primary.png"),
    (
        "urban_road_wider.png",
        "urban_street",
        "edits/road_wider/after.png",
    ),
    (
        "urban_more_cars.png",
        "urban_street",
        "edits/more_parked_cars/after.png",
    ),
    ("facade_original.png", "repeated_facade", "original/primary.png"),
    (
        "facade_more_windows.png",
        "repeated_facade",
        "edits/more_windows/after.png",
    ),
    ("corridor_original.png", "indoor_corridor", "original/primary.png"),
    (
        "corridor_wider.png",
        "indoor_corridor",
        "edits/corridor_wider/after.png",
    ),
)


class AcceptanceStatus(str, Enum):
    """Stable acceptance outcome values."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class DemoConfig:
    """Strict immutable integrated-demo configuration."""

    output_directory: Path
    selected_scene_keys: tuple[str, ...] = CANONICAL_SCENE_KEYS
    seed: int = 42
    quick: bool = False
    overwrite: bool = False
    width: int = FULL_RENDER_WIDTH
    height: int = FULL_RENDER_HEIGHT
    required_camera_policy: str = "manifest_primary_and_edit_recommended"
    verify_glb: bool = True
    calculate_hashes: bool = True
    verify_determinism: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "output_directory",
            Path(self.output_directory),
        )
        try:
            scenes = tuple(self.selected_scene_keys)
        except TypeError as exc:
            raise DemoConfigurationError(
                "selected_scene_keys must be an ordered collection"
            ) from exc
        if not scenes:
            raise DemoConfigurationError("at least one scene must be selected")
        if len(set(scenes)) != len(scenes):
            raise DemoConfigurationError("duplicate scene selections are not allowed")
        unknown = tuple(key for key in scenes if key not in CANONICAL_SCENE_KEYS)
        if unknown:
            raise DemoConfigurationError("unknown scene key(s): " + ", ".join(unknown))
        object.__setattr__(self, "selected_scene_keys", scenes)
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or self.seed < 0
        ):
            raise DemoConfigurationError("seed must be a nonnegative integer")
        for name in ("quick", "overwrite", "verify_glb", "calculate_hashes"):
            if not isinstance(getattr(self, name), bool):
                raise DemoConfigurationError(f"{name} must be a boolean")
        if not isinstance(self.verify_determinism, bool):
            raise DemoConfigurationError("verify_determinism must be a boolean")
        if self.quick and (
            self.width == FULL_RENDER_WIDTH and self.height == FULL_RENDER_HEIGHT
        ):
            object.__setattr__(self, "width", QUICK_RENDER_WIDTH)
            object.__setattr__(self, "height", QUICK_RENDER_HEIGHT)
        if (
            isinstance(self.width, bool)
            or not isinstance(self.width, int)
            or self.width < 1
            or isinstance(self.height, bool)
            or not isinstance(self.height, int)
            or self.height < 1
        ):
            raise DemoConfigurationError(
                "render width and height must be positive integers"
            )
        if self.required_camera_policy != "manifest_primary_and_edit_recommended":
            raise DemoConfigurationError("required_camera_policy is unsupported")


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    """One stable, ordered Phase 1 acceptance check."""

    code: str
    description: str
    status: AcceptanceStatus
    scene_key: str | None = None
    details: str = ""
    artifact_paths: tuple[str, ...] = field(default_factory=tuple)
    required: bool = True


@dataclass(frozen=True, slots=True)
class SceneAcceptance:
    """Acceptance outcome and check counts for one scene."""

    scene_key: str
    status: AcceptanceStatus
    total_checks: int
    passed_checks: int
    failed_checks: int
    skipped_checks: int


@dataclass(frozen=True, slots=True)
class Phase1AcceptanceReport:
    """Canonical structured Phase 1 acceptance report."""

    overall_status: AcceptanceStatus
    demo_policy_version: str
    package_version: str
    grammar_schema_version: str
    execution_policy_version: str
    renderer_policy_version: str
    editing_policy_version: str
    manifest_policy_version: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    skipped_checks: int
    scenes: tuple[SceneAcceptance, ...]
    checks: tuple[AcceptanceCheck, ...]
    artifact_index_path: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    """One hash-addressed persisted bundle artifact."""

    path: str
    category: str
    scene_key: str | None
    edit_key: str | None
    byte_size: int
    sha256: str
    required: bool


@dataclass(frozen=True, slots=True)
class DemoManifest:
    """Deterministic environment-free manifest for one integrated run."""

    demo_policy_version: str
    package_version: str
    scene_keys: tuple[str, ...]
    seed: int
    mode: str
    render_width: int
    render_height: int
    required_camera_policy: str
    verify_glb: bool
    calculate_hashes: bool
    policy_versions: tuple[tuple[str, str], ...]
    source_manifests: tuple[str, ...]
    review_images: tuple[str, ...]
    required_acceptance_checks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeterminismEvidence:
    """Results from a second temporary build."""

    requested: bool
    performed: bool
    canonical_json_mismatches: tuple[str, ...] = field(default_factory=tuple)
    png_pixel_mismatches: tuple[str, ...] = field(default_factory=tuple)
    png_byte_mismatches: tuple[str, ...] = field(default_factory=tuple)
    glb_byte_mismatches: tuple[str, ...] = field(default_factory=tuple)
    glb_structure_mismatches: tuple[str, ...] = field(default_factory=tuple)
    temporary_directory_removed: bool = True


@dataclass(frozen=True, slots=True)
class DemoResult:
    """Resolved bundle state returned by :func:`run_demo`."""

    output_directory: Path
    config: DemoConfig
    scene_results: tuple[SceneExampleBuildResult, ...]
    manifest: DemoManifest
    determinism: DeterminismEvidence
    acceptance_report: Phase1AcceptanceReport | None = None
