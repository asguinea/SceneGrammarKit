"""Integrated Phase 1 demo orchestration and deterministic verification."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from PIL import Image

from scene_grammar_kit import __version__
from scene_grammar_kit.demo.acceptance import (
    REQUIRED_ACCEPTANCE_CODES,
    run_phase1_acceptance,
)
from scene_grammar_kit.demo.errors import DemoBuildError
from scene_grammar_kit.demo.models import (
    DEMO_POLICY_VERSION,
    REVIEW_IMAGE_SPECS,
    ArtifactEntry,
    DemoConfig,
    DemoManifest,
    DemoResult,
    DeterminismEvidence,
)
from scene_grammar_kit.demo.persistence import (
    acceptance_report_to_canonical_json,
    acceptance_report_to_markdown,
    artifact_index_to_canonical_json,
    demo_manifest_to_canonical_json,
    demo_readme,
    save_text,
)
from scene_grammar_kit.editing import EDITING_POLICY_VERSION
from scene_grammar_kit.geometry import EXECUTION_POLICY_VERSION
from scene_grammar_kit.geometry.serialization import atomic_write_bytes
from scene_grammar_kit.grammar import SCHEMA_VERSION
from scene_grammar_kit.paths import OutputDirectoryError, create_output_directory
from scene_grammar_kit.rendering import RENDERER_POLICY_VERSION
from scene_grammar_kit.reproducibility import seed_everything
from scene_grammar_kit.scene_examples import (
    MANIFEST_POLICY_VERSION,
    SceneExampleError,
    build_scene_example,
)


def run_demo(config: DemoConfig) -> DemoResult:
    """Build, verify, index, and report one self-contained Phase 1 bundle."""
    if not isinstance(config, DemoConfig):
        raise TypeError("config must be a DemoConfig")
    try:
        root = create_output_directory(
            config.output_directory,
            allow_nonempty=config.overwrite,
        )
    except OutputDirectoryError as exc:
        raise DemoBuildError(str(exc)) from exc

    final_report = root / "phase1_acceptance.json"
    if config.overwrite:
        for stale_report in (
            final_report,
            root / "phase1_acceptance.md",
        ):
            if not stale_report.is_file():
                continue
            try:
                stale_report.unlink()
            except OSError as exc:
                raise DemoBuildError(
                    f"could not remove stale acceptance report: {exc}"
                ) from exc

    seed_everything(config.seed)
    repository = _repository_root()
    try:
        (root / "scenes").mkdir(exist_ok=True)
        (root / "review").mkdir(exist_ok=True)
        scene_results = tuple(
            build_scene_example(
                repository
                / "examples"
                / "scene_examples"
                / scene_key
                / "scene_manifest.json",
                root / "scenes" / scene_key,
                overwrite=config.overwrite,
                render_width=config.width,
                render_height=config.height,
            )
            for scene_key in config.selected_scene_keys
        )
        _copy_review_images(root, config)
        manifest = _demo_manifest(config)
        save_text(
            demo_manifest_to_canonical_json(manifest),
            root / "demo_manifest.json",
            overwrite=True,
        )
        determinism = _verify_determinism(config, root, repository)
        result = DemoResult(
            output_directory=root,
            config=config,
            scene_results=scene_results,
            manifest=manifest,
            determinism=determinism,
        )
        report = run_phase1_acceptance(
            result,
            verify_determinism=config.verify_determinism,
        )
        command = _reproduction_command(config)
        save_text(
            acceptance_report_to_markdown(
                report,
                reproduction_command=command,
            ),
            root / "phase1_acceptance.md",
            overwrite=True,
        )
        save_text(
            demo_readme(report, reproduction_command=command),
            root / "README.md",
            overwrite=True,
        )
        entries = build_artifact_index(root)
        save_text(
            artifact_index_to_canonical_json(entries),
            root / "artifact_index.json",
            overwrite=True,
        )
        # This is deliberately the last success/failure report write. A required
        # verification failure can therefore never leave a stale overall PASS.
        save_text(
            acceptance_report_to_canonical_json(report),
            final_report,
            overwrite=True,
        )
        return replace(result, acceptance_report=report)
    except (DemoBuildError, SceneExampleError):
        raise
    except Exception as exc:
        raise DemoBuildError(f"integrated demo failed: {exc}") from exc


def build_artifact_index(root: Path) -> tuple[ArtifactEntry, ...]:
    """Hash final persisted bundle bytes, excluding recursive report targets."""
    resolved = Path(root).resolve()
    entries: list[ArtifactEntry] = []
    files = [item for item in resolved.rglob("*") if item.is_file()]
    for path in sorted(
        files,
        key=lambda item: item.relative_to(resolved).as_posix(),
    ):
        relative = path.relative_to(resolved).as_posix()
        if relative in {"artifact_index.json", "phase1_acceptance.json"}:
            continue
        if path.name.endswith(".tmp") or path.name.startswith("."):
            continue
        data = path.read_bytes()
        scene_key, edit_key = _path_context(relative)
        entries.append(
            ArtifactEntry(
                path=relative,
                category=_artifact_category(relative),
                scene_key=scene_key,
                edit_key=edit_key,
                byte_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                required=True,
            )
        )
    return tuple(entries)


def compare_scene_builds(first: Path, second: Path) -> DeterminismEvidence:
    """Compare two scene-build roots at canonical, pixel, byte, and GLB levels."""
    first = Path(first).resolve()
    second = Path(second).resolve()
    json_mismatches: list[str] = []
    pixel_mismatches: list[str] = []
    png_mismatches: list[str] = []
    glb_mismatches: list[str] = []
    structure_mismatches: list[str] = []
    relative_paths = sorted(
        path.relative_to(first).as_posix()
        for path in first.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".png", ".glb"}
    )
    second_paths = {
        path.relative_to(second).as_posix()
        for path in second.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".png", ".glb"}
    }
    for relative in sorted(set(relative_paths) | second_paths):
        left = first / relative
        right = second / relative
        if not left.is_file() or not right.is_file():
            suffix = Path(relative).suffix.lower()
            target = (
                json_mismatches
                if suffix == ".json"
                else png_mismatches
                if suffix == ".png"
                else glb_mismatches
            )
            target.append(relative + " missing")
            continue
        suffix = left.suffix.lower()
        if suffix == ".json" and left.read_bytes() != right.read_bytes():
            json_mismatches.append(relative)
        elif suffix == ".png":
            if left.read_bytes() != right.read_bytes():
                png_mismatches.append(relative)
            if _decoded_png(left) != _decoded_png(right):
                pixel_mismatches.append(relative)
        elif suffix == ".glb":
            if left.read_bytes() != right.read_bytes():
                glb_mismatches.append(relative)
            try:
                if _glb_structure(left) != _glb_structure(right):
                    structure_mismatches.append(relative)
            except Exception:
                structure_mismatches.append(relative + " reopen failed")
    return DeterminismEvidence(
        requested=True,
        performed=True,
        canonical_json_mismatches=tuple(json_mismatches),
        png_pixel_mismatches=tuple(pixel_mismatches),
        png_byte_mismatches=tuple(png_mismatches),
        glb_byte_mismatches=tuple(glb_mismatches),
        glb_structure_mismatches=tuple(structure_mismatches),
        temporary_directory_removed=False,
    )


def _verify_determinism(
    config: DemoConfig,
    root: Path,
    repository: Path,
) -> DeterminismEvidence:
    if not config.verify_determinism:
        return DeterminismEvidence(requested=False, performed=False)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{root.name}.verify-",
            dir=root.parent,
        )
    ).resolve()
    evidence: DeterminismEvidence | None = None
    removed = False
    try:
        second_scenes = temporary / "scenes"
        second_scenes.mkdir()
        for scene_key in config.selected_scene_keys:
            build_scene_example(
                repository
                / "examples"
                / "scene_examples"
                / scene_key
                / "scene_manifest.json",
                second_scenes / scene_key,
                render_width=config.width,
                render_height=config.height,
            )
        evidence = compare_scene_builds(root / "scenes", second_scenes)
    finally:
        if temporary.parent == root.parent.resolve() and temporary.name.startswith(
            f".{root.name}.verify-"
        ):
            shutil.rmtree(temporary)
            removed = not temporary.exists()
    if evidence is None:
        raise DemoBuildError("determinism verification build did not complete")
    return replace(evidence, temporary_directory_removed=removed)


def _copy_review_images(root: Path, config: DemoConfig) -> None:
    selected = set(config.selected_scene_keys)
    for name, scene_key, source_relative in REVIEW_IMAGE_SPECS:
        if scene_key not in selected:
            continue
        source = root / "scenes" / scene_key / source_relative
        if not source.is_file():
            raise DemoBuildError(
                f"required review source is missing: {source_relative}"
            )
        atomic_write_bytes(
            source.read_bytes(),
            root / "review" / name,
            overwrite=True,
            create_parents=True,
        )


def _demo_manifest(config: DemoConfig) -> DemoManifest:
    review_names = tuple(
        name
        for name, scene_key, _ in REVIEW_IMAGE_SPECS
        if scene_key in config.selected_scene_keys
    )
    return DemoManifest(
        demo_policy_version=DEMO_POLICY_VERSION,
        package_version=__version__,
        scene_keys=config.selected_scene_keys,
        seed=config.seed,
        mode="quick" if config.quick else "full",
        render_width=config.width,
        render_height=config.height,
        required_camera_policy=config.required_camera_policy,
        verify_glb=config.verify_glb,
        calculate_hashes=config.calculate_hashes,
        policy_versions=(
            ("editing", EDITING_POLICY_VERSION),
            ("execution", EXECUTION_POLICY_VERSION),
            ("grammar_schema", SCHEMA_VERSION),
            ("manifest", MANIFEST_POLICY_VERSION),
            ("renderer", RENDERER_POLICY_VERSION),
        ),
        source_manifests=tuple(
            f"examples/scene_examples/{key}/scene_manifest.json"
            for key in config.selected_scene_keys
        ),
        review_images=review_names,
        required_acceptance_checks=REQUIRED_ACCEPTANCE_CODES,
    )


def _reproduction_command(config: DemoConfig) -> str:
    output = "runs/phase1_demo_quick" if config.quick else "runs/phase1_demo"
    selection = (
        "--all"
        if config.selected_scene_keys
        == ("urban_street", "repeated_facade", "indoor_corridor")
        else " ".join(f"--scene {key}" for key in config.selected_scene_keys)
    )
    flags = [
        "python -m scene_grammar_kit demo",
        f"--output {output}",
        selection,
        f"--seed {config.seed}",
    ]
    if config.quick:
        flags.append("--quick")
    if config.verify_determinism:
        flags.append("--verify-determinism")
    return " ".join(flags)


def _artifact_category(relative: str) -> str:
    name = PurePathName(relative)
    if relative == "phase1_acceptance.md":
        return "acceptance_report"
    if relative == "README.md":
        return "documentation"
    if name == "grammar.json" or name.startswith("grammar_"):
        return "grammar"
    if name in {"manifest.json", "demo_manifest.json"}:
        return "manifest"
    if name == "grammar_tree.txt":
        return "grammar_tree"
    if "primitives" in name:
        return "primitives"
    if "execution_report" in name:
        return "execution_report"
    if name.endswith(".glb"):
        return "GLB"
    if "semantic_index" in name:
        return "semantic_index"
    if name.endswith(".png"):
        return "PNG"
    if "render.json" in name:
        return "render_report"
    if name == "edit_report.json":
        return "edit_report"
    if name == "build_report.json":
        return "build_report"
    return "documentation"


def _path_context(relative: str) -> tuple[str | None, str | None]:
    parts = relative.split("/")
    scene_key = parts[1] if len(parts) > 2 and parts[0] == "scenes" else None
    edit_key = (
        parts[3]
        if len(parts) > 4 and parts[0] == "scenes" and parts[2] == "edits"
        else None
    )
    return scene_key, edit_key


def _decoded_png(path: Path) -> tuple[tuple[int, int], bytes]:
    with Image.open(path) as image:
        converted = image.convert("RGBA")
        return converted.size, converted.tobytes()


def _glb_structure(path: Path) -> tuple[tuple[str, int, int], ...]:
    import trimesh

    loaded = trimesh.load(path, file_type="glb", force="scene", process=False)
    return tuple(
        sorted(
            (
                str(name),
                int(len(mesh.vertices)),
                int(len(mesh.faces)),
            )
            for name, mesh in loaded.geometry.items()
        )
    )


def PurePathName(relative: str) -> str:
    """Return the final portable path component without host path semantics."""
    return relative.rsplit("/", 1)[-1]


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]
