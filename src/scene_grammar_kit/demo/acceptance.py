"""Formal, deterministic Phase 1 acceptance verification."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image

from scene_grammar_kit import __version__
from scene_grammar_kit.demo.models import (
    REVIEW_IMAGE_SPECS,
    AcceptanceCheck,
    AcceptanceStatus,
    DemoResult,
    Phase1AcceptanceReport,
    SceneAcceptance,
)
from scene_grammar_kit.editing import EDITING_POLICY_VERSION
from scene_grammar_kit.geometry import EXECUTION_POLICY_VERSION
from scene_grammar_kit.grammar import (
    SCHEMA_VERSION,
    grammar_tree_to_text,
    load_grammar,
    summarize_grammar,
    validate_grammar,
)
from scene_grammar_kit.rendering import RENDERER_POLICY_VERSION
from scene_grammar_kit.scene_examples import MANIFEST_POLICY_VERSION

EXPECTED_PROTOCOL_FILES = (
    "README.md",
    "scope.md",
    "system.md",
    "metrics.md",
)

REQUIRED_ACCEPTANCE_CODES = (
    "PROTOCOL_FILES",
    "CANONICAL_SCENE_SOURCES",
    "PACKAGE_VERSION",
    "PYTHON_311_COMPATIBILITY",
    "RUNTIME_DEPENDENCIES",
    "FORBIDDEN_DEPENDENCIES",
    "DEMO_MANIFEST",
    "REVIEW_IMAGES",
    "GRAMMAR_LOAD_VALIDATE",
    "GRAMMAR_INSPECTION",
    "GRAMMAR_SCHEMA_AND_IDS",
    "GRAMMAR_COMPLEXITY",
    "EXECUTION_ARTIFACTS",
    "EXECUTION_BOUNDS_AND_PRIMITIVES",
    "GLB_REOPEN",
    "RENDERING_ARTIFACTS",
    "EDITING_ARTIFACTS",
    "REPORT_PATHS_RELATIVE",
    "DETERMINISM_CANONICAL_JSON",
    "DETERMINISM_PNG_PIXELS",
    "DETERMINISM_PNG_BYTES",
    "DETERMINISM_GLB_BYTES",
    "DETERMINISM_GLB_STRUCTURE",
    "SCOPE_NO_IMAGE_INDUCTION",
    "SCOPE_NO_NEURAL_PERCEPTION",
    "SCOPE_NO_GENERATED_PDF",
    "SCOPE_NO_GAUSSIAN_SPLATTING",
    "SCOPE_NO_GUI",
    "SCOPE_NO_CPP_CUDA",
    "SCOPE_NO_EVALUATION_CLAIMS",
)


def run_phase1_acceptance(
    demo_result: DemoResult,
    *,
    verify_determinism: bool,
) -> Phase1AcceptanceReport:
    """Rescan a built bundle and return ordered factual acceptance evidence."""
    root = demo_result.output_directory.resolve()
    repository = _repository_root()
    checks: list[AcceptanceCheck] = []

    protocol = repository / "protocols" / "evaluation_v0_1"
    missing_protocol = tuple(
        name for name in EXPECTED_PROTOCOL_FILES if not (protocol / name).is_file()
    )
    checks.append(
        _check(
            "PROTOCOL_FILES",
            "The versioned evaluation protocol is complete.",
            not missing_protocol,
            (
                "all protocol files found"
                if not missing_protocol
                else "missing: " + ", ".join(missing_protocol)
            ),
            tuple(
                f"protocols/evaluation_v0_1/{name}" for name in EXPECTED_PROTOCOL_FILES
            ),
        )
    )

    missing_sources = tuple(
        key
        for key in demo_result.config.selected_scene_keys
        if not (
            repository / "examples" / "scene_examples" / key / "scene_manifest.json"
        ).is_file()
        or not (
            repository / "examples" / "scene_examples" / key / "grammar.json"
        ).is_file()
    )
    checks.append(
        _check(
            "CANONICAL_SCENE_SOURCES",
            "Selected canonical scene sources exist.",
            not missing_sources,
            "all selected scene sources found"
            if not missing_sources
            else "missing: " + ", ".join(missing_sources),
        )
    )
    checks.extend(_package_checks(repository))

    manifest_path = root / "demo_manifest.json"
    manifest_ok, manifest_detail = _valid_json_file(manifest_path)
    checks.append(
        _check(
            "DEMO_MANIFEST",
            "The canonical demo manifest parses and contains no absolute paths.",
            manifest_ok and not _json_contains_absolute_path(manifest_path),
            manifest_detail,
            ("demo_manifest.json",),
        )
    )

    review_failures: list[str] = []
    review_paths: list[str] = []
    selected = set(demo_result.config.selected_scene_keys)
    for name, scene_key, source_relative in REVIEW_IMAGE_SPECS:
        if scene_key not in selected:
            continue
        review = root / "review" / name
        source = root / "scenes" / scene_key / source_relative
        review_paths.append(f"review/{name}")
        if not review.is_file() or not source.is_file():
            review_failures.append(name + " missing")
        elif review.read_bytes() != source.read_bytes():
            review_failures.append(name + " is not a byte-identical copy")
    checks.append(
        _check(
            "REVIEW_IMAGES",
            "Required review images exist as byte-identical builder copies.",
            not review_failures,
            "all selected review copies match"
            if not review_failures
            else "; ".join(review_failures),
            tuple(review_paths),
        )
    )

    for key in demo_result.config.selected_scene_keys:
        checks.extend(
            _scene_checks(
                root, key, demo_result.config.width, demo_result.config.height
            )
        )

    checks.extend(_determinism_checks(demo_result, verify_determinism))
    checks.extend(_scope_checks(repository, root))

    scene_summaries = tuple(
        _scene_summary(key, checks) for key in demo_result.config.selected_scene_keys
    )
    passed = sum(item.status is AcceptanceStatus.PASS for item in checks)
    failed = sum(item.status is AcceptanceStatus.FAIL for item in checks)
    skipped = sum(item.status is AcceptanceStatus.SKIP for item in checks)
    required_failure = any(
        item.required and item.status is AcceptanceStatus.FAIL for item in checks
    )
    scene_failure = any(
        scene.status is AcceptanceStatus.FAIL for scene in scene_summaries
    )
    overall = (
        AcceptanceStatus.FAIL
        if required_failure or scene_failure
        else AcceptanceStatus.PASS
    )
    warnings = (
        "Scope checks use deterministic dependency, path, extension, and output-name scans; "
        "they do not prove absence of every possible future behavior.",
    )
    return Phase1AcceptanceReport(
        overall_status=overall,
        demo_policy_version=demo_result.manifest.demo_policy_version,
        package_version=__version__,
        grammar_schema_version=SCHEMA_VERSION,
        execution_policy_version=EXECUTION_POLICY_VERSION,
        renderer_policy_version=RENDERER_POLICY_VERSION,
        editing_policy_version=EDITING_POLICY_VERSION,
        manifest_policy_version=MANIFEST_POLICY_VERSION,
        total_checks=len(checks),
        passed_checks=passed,
        failed_checks=failed,
        skipped_checks=skipped,
        scenes=scene_summaries,
        checks=tuple(checks),
        artifact_index_path="artifact_index.json",
        warnings=warnings,
    )


def scan_scope(repository: Path, bundle: Path) -> dict[str, tuple[str, ...]]:
    """Run the documented practical scope scan and return findings by class."""
    ignored = {
        ".git",
        ".venv",
        ".test-tmp",
        ".local-temp",
        ".pytest_cache",
        "runs",
        "__pycache__",
    }
    paths = [
        path
        for path in repository.rglob("*")
        if path.is_file()
        and not any(part in ignored for part in path.relative_to(repository).parts)
    ]
    lowered_parts = {
        part.lower().replace("-", "_")
        for path in paths
        for part in path.relative_to(repository).parts
    }
    source_suffixes = tuple(
        path.relative_to(repository).as_posix()
        for path in paths
        if path.suffix.lower() in {".cpp", ".cc", ".cxx", ".cu", ".cuh"}
    )
    generated_pdfs = tuple(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*.pdf")
        if path.is_file()
    )
    generated_claims = tuple(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file()
        and any(
            token in path.name.lower()
            for token in ("benchmark_results", "recovery_metrics", "evaluation_results")
        )
    )
    return {
        "image_induction": tuple(
            part
            for part in lowered_parts
            if part in {"image_induction", "grammar_induction"}
        ),
        "neural_perception": tuple(
            part
            for part in lowered_parts
            if part in {"neural_perception", "object_detection", "depth_estimation"}
        ),
        "gaussian_splatting": tuple(
            part
            for part in lowered_parts
            if part in {"gaussian_splatting", "gaussian_splats"}
        ),
        "gui": tuple(part for part in lowered_parts if part in {"gui", "desktop_gui"}),
        "cpp_cuda": source_suffixes,
        "generated_pdf": generated_pdfs,
        "evaluation_claims": generated_claims,
    }


def _scene_checks(
    root: Path, scene_key: str, width: int, height: int
) -> list[AcceptanceCheck]:
    scene = root / "scenes" / scene_key
    prefix = f"scenes/{scene_key}"
    checks: list[AcceptanceCheck] = []
    source_grammar = scene / "source" / "grammar.json"
    try:
        grammar = load_grammar(source_grammar)
        validation = validate_grammar(grammar)
        grammar_ok = validation.is_valid
        grammar_detail = (
            "grammar loaded and semantic validation passed"
            if grammar_ok
            else "semantic validation failed"
        )
    except Exception as exc:
        grammar = None
        grammar_ok = False
        grammar_detail = f"grammar load failed: {exc}"
    checks.append(
        _scene_check(
            "GRAMMAR_LOAD_VALIDATE",
            "Grammar loads and validates.",
            scene_key,
            grammar_ok,
            grammar_detail,
            (f"{prefix}/source/grammar.json",),
        )
    )

    try:
        assert grammar is not None
        inspection = grammar_tree_to_text(grammar)
        inspection_ok = (
            bool(inspection)
            and (scene / "source" / "grammar_tree.txt").read_text(encoding="utf-8")
            == inspection
        )
        inspection_detail = (
            "inspection text is deterministic and matches the persisted tree"
        )
    except Exception as exc:
        inspection_ok = False
        inspection_detail = f"inspection failed: {exc}"
    checks.append(
        _scene_check(
            "GRAMMAR_INSPECTION",
            "Grammar inspection succeeds and matches the persisted tree.",
            scene_key,
            inspection_ok,
            inspection_detail,
            (f"{prefix}/source/grammar_tree.txt",),
        )
    )

    try:
        source_data = _read_json(source_grammar)
        node_ids = _collect_values(source_data, "node_id")
        schema_ids_ok = (
            source_data.get("schema_version") == SCHEMA_VERSION
            and len(node_ids) == len(set(node_ids))
            and bool(node_ids)
        )
        schema_detail = f"schema={source_data.get('schema_version')}; node_ids={len(node_ids)}; unique={len(set(node_ids))}"
    except Exception as exc:
        source_data = {}
        schema_ids_ok = False
        schema_detail = f"schema/node-ID check failed: {exc}"
    checks.append(
        _scene_check(
            "GRAMMAR_SCHEMA_AND_IDS",
            "Schema is 0.1 and node IDs are unique.",
            scene_key,
            schema_ids_ok,
            schema_detail,
        )
    )

    try:
        assert grammar is not None
        summary = summarize_grammar(grammar)
        complexity_ok = summary.total_node_count > 0 and summary.maximum_depth > 0
        complexity_detail = f"nodes={summary.total_node_count}; maximum_depth={summary.maximum_depth}; canonical_bytes={summary.canonical_byte_size}"
    except Exception as exc:
        complexity_ok = False
        complexity_detail = f"complexity inspection failed: {exc}"
    checks.append(
        _scene_check(
            "GRAMMAR_COMPLEXITY",
            "The bounded grammar complexity inspection succeeds.",
            scene_key,
            complexity_ok,
            complexity_detail,
        )
    )

    json_paths = tuple(sorted(scene.rglob("*.json")))
    json_errors: list[str] = []
    parsed: dict[Path, Any] = {}
    for path in json_paths:
        try:
            parsed[path] = _read_json(path)
        except Exception as exc:
            json_errors.append(f"{path.relative_to(scene).as_posix()}: {exc}")
    original_report = parsed.get(scene / "original" / "execution_report.json", {})
    primitive_data = parsed.get(scene / "original" / "primitives.json", {})
    semantic_data = parsed.get(scene / "original" / "semantic_index.json", {})
    execution_ok = (
        not json_errors
        and original_report.get("success") is True
        and original_report.get("execution_policy_version") == EXECUTION_POLICY_VERSION
        and isinstance(primitive_data.get("primitives"), list)
        and isinstance(semantic_data.get("primitives"), list)
    )
    checks.append(
        _scene_check(
            "EXECUTION_ARTIFACTS",
            "All JSON reopens and execution artifacts use policy 0.1.",
            scene_key,
            execution_ok,
            "all scene JSON parsed" if not json_errors else "; ".join(json_errors[:3]),
            (
                f"{prefix}/original/primitives.json",
                f"{prefix}/original/execution_report.json",
                f"{prefix}/original/semantic_index.json",
            ),
        )
    )

    primitives = (
        primitive_data.get("primitives", []) if isinstance(primitive_data, dict) else []
    )
    root_bounds = (
        primitive_data.get("root_bounds") if isinstance(primitive_data, dict) else None
    )
    bounds_ok = (
        bool(primitives)
        and root_bounds is not None
        and all(
            _bounds_contains(root_bounds, item.get("bounds"))
            and item.get("geometry") in {"box", "plane"}
            for item in primitives
            if isinstance(item, dict)
        )
    )
    checks.append(
        _scene_check(
            "EXECUTION_BOUNDS_AND_PRIMITIVES",
            "Original primitives are nonempty, canonical, and inside root bounds.",
            scene_key,
            bounds_ok,
            f"primitive_count={len(primitives)}",
        )
    )

    glb_paths = tuple(sorted(scene.rglob("*.glb")))
    glb_errors: list[str] = []
    for path in glb_paths:
        try:
            _reopen_glb(path)
        except Exception as exc:
            glb_errors.append(f"{path.relative_to(scene).as_posix()}: {exc}")
    checks.append(
        _scene_check(
            "GLB_REOPEN",
            "Every generated GLB exists and reopens.",
            scene_key,
            bool(glb_paths) and not glb_errors,
            f"reopened={len(glb_paths)}"
            if not glb_errors
            else "; ".join(glb_errors[:3]),
            tuple(
                f"{prefix}/{path.relative_to(scene).as_posix()}" for path in glb_paths
            ),
        )
    )

    png_paths = tuple(sorted(scene.rglob("*.png")))
    render_errors: list[str] = []
    try:
        build_report_data = _read_json(scene / "build_report.json")
        original_hash = build_report_data["grammar_sha256"]
    except Exception:
        original_hash = None
    for path in png_paths:
        report_path = path.with_suffix(".render.json")
        try:
            with Image.open(path) as image:
                image.load()
                if image.size != (width, height):
                    raise ValueError(f"dimensions={image.size}")
            report = _read_json(report_path)
            if report.get("renderer_policy_version") != RENDERER_POLICY_VERSION:
                raise ValueError("renderer policy mismatch")
            if (report.get("width"), report.get("height")) != (width, height):
                raise ValueError("render report dimensions mismatch")
            expected_hash = original_hash
            if "edits" in path.parts:
                edit_report = _read_json(path.parent / "edit_report.json")
                expected_hash = (
                    edit_report["edited_grammar_sha256"]
                    if path.name == "after.png"
                    else edit_report["original_grammar_sha256"]
                )
            if report.get("executed_scene_grammar_sha256") != expected_hash:
                raise ValueError("render report grammar hash mismatch")
        except Exception as exc:
            render_errors.append(f"{path.relative_to(scene).as_posix()}: {exc}")
    for edit_dir in (
        sorted((scene / "edits").glob("*")) if (scene / "edits").is_dir() else ()
    ):
        before = edit_dir / "before.png"
        after = edit_dir / "after.png"
        try:
            if _png_pixels(before) == _png_pixels(after):
                render_errors.append(f"{edit_dir.name}: before/after pixels unchanged")
            before_report = _read_json(before.with_suffix(".render.json"))
            after_report = _read_json(after.with_suffix(".render.json"))
            if (
                before_report.get("camera_preset") != after_report.get("camera_preset")
                or before_report.get("width") != after_report.get("width")
                or before_report.get("height") != after_report.get("height")
            ):
                render_errors.append(
                    f"{edit_dir.name}: before/after camera or dimensions differ"
                )
        except Exception as exc:
            render_errors.append(f"{edit_dir.name}: {exc}")
    checks.append(
        _scene_check(
            "RENDERING_ARTIFACTS",
            "All PNGs and reports reopen with policy, size, camera, hash, and before/after checks.",
            scene_key,
            bool(png_paths) and not render_errors,
            f"verified_pngs={len(png_paths)}"
            if not render_errors
            else "; ".join(render_errors[:4]),
            tuple(
                f"{prefix}/{path.relative_to(scene).as_posix()}" for path in png_paths
            ),
        )
    )

    edit_errors: list[str] = []
    try:
        manifest = _read_json(scene / "source" / "manifest.json")
        expected_edits = {
            item["edit_key"]: item for item in manifest["canonical_edits"]
        }
    except Exception as exc:
        expected_edits = {}
        edit_errors.append(f"manifest edits unavailable: {exc}")
    edit_dirs = (
        tuple(sorted((scene / "edits").glob("*"))) if (scene / "edits").is_dir() else ()
    )
    for edit_dir in edit_dirs:
        try:
            report = _read_json(edit_dir / "edit_report.json")
            before_grammar = _read_json(edit_dir / "grammar_before.json")
            after_grammar = _read_json(edit_dir / "grammar_after.json")
            symbolic = report["symbolic_diff"]
            if report.get("editing_policy_version") != EDITING_POLICY_VERSION:
                raise ValueError("editing policy mismatch")
            if report.get("original_grammar_sha256") == report.get(
                "edited_grammar_sha256"
            ):
                raise ValueError("grammar hashes did not change")
            if before_grammar.get("root_bounds") != after_grammar.get("root_bounds"):
                raise ValueError("root bounds changed")
            if symbolic.get("node_ids_before") != symbolic.get("node_ids_after"):
                raise ValueError("node-ID set changed")
            if len(symbolic.get("directly_modified_node_ids", [])) != 1:
                raise ValueError("single edit did not modify exactly one node")
            if not report.get("validation_succeeded") or not report.get(
                "execution_verification_succeeded"
            ):
                raise ValueError("edited grammar validation or execution failed")
            if edit_dir.name not in expected_edits:
                raise ValueError("unexpected edit key")
            expected_operation = {
                "operation_type": expected_edits[edit_dir.name]["operation_type"],
                **expected_edits[edit_dir.name]["parameters"],
            }
            if report.get("operations") != [expected_operation]:
                raise ValueError("edit target or requested value differs from manifest")
            if not _realization_agrees(report.get("realizations", [])):
                raise ValueError("requested and realized values differ")
        except Exception as exc:
            edit_errors.append(f"{edit_dir.name}: {exc}")
    if set(path.name for path in edit_dirs) != set(expected_edits):
        edit_errors.append("required edit directory set differs from manifest")
    checks.append(
        _scene_check(
            "EDITING_ARTIFACTS",
            "Every manifest edit has valid provenance, unchanged bounds/IDs, one direct target, and realized values.",
            scene_key,
            bool(edit_dirs) and not edit_errors,
            f"verified_edits={len(edit_dirs)}"
            if not edit_errors
            else "; ".join(edit_errors[:4]),
            tuple(f"{prefix}/edits/{path.name}/edit_report.json" for path in edit_dirs),
        )
    )

    try:
        build_report = _read_json(scene / "build_report.json")
        report_paths = build_report.get("artifact_paths", [])
        paths_ok = bool(report_paths) and all(
            _portable_relative(item) for item in report_paths
        )
        path_detail = f"relative_artifact_paths={len(report_paths)}"
    except Exception as exc:
        paths_ok = False
        path_detail = f"build report path check failed: {exc}"
    checks.append(
        _scene_check(
            "REPORT_PATHS_RELATIVE",
            "Canonical build-report artifact paths are portable and relative.",
            scene_key,
            paths_ok,
            path_detail,
            (f"{prefix}/build_report.json",),
        )
    )
    return checks


def _determinism_checks(
    demo_result: DemoResult, required: bool
) -> list[AcceptanceCheck]:
    evidence = demo_result.determinism
    fields = (
        (
            "DETERMINISM_CANONICAL_JSON",
            "Canonical grammar, primitive, build, edit, and render JSON bytes are stable.",
            evidence.canonical_json_mismatches,
        ),
        (
            "DETERMINISM_PNG_PIXELS",
            "Repeated decoded PNG pixels are stable.",
            evidence.png_pixel_mismatches,
        ),
        (
            "DETERMINISM_PNG_BYTES",
            "Same-environment PNG bytes are stable.",
            evidence.png_byte_mismatches,
        ),
        (
            "DETERMINISM_GLB_BYTES",
            "Same-environment GLB bytes are stable.",
            evidence.glb_byte_mismatches,
        ),
        (
            "DETERMINISM_GLB_STRUCTURE",
            "Repeated GLB structures reopen equivalently.",
            evidence.glb_structure_mismatches,
        ),
    )
    checks: list[AcceptanceCheck] = []
    for code, description, mismatches in fields:
        if not required:
            checks.append(
                AcceptanceCheck(
                    code=code,
                    description=description,
                    status=AcceptanceStatus.SKIP,
                    details="determinism verification was not requested",
                    required=False,
                )
            )
        else:
            ok = (
                evidence.performed
                and evidence.temporary_directory_removed
                and not mismatches
            )
            checks.append(
                _check(
                    code,
                    description,
                    ok,
                    "second build matched and temporary directory was removed"
                    if ok
                    else "mismatches: " + ", ".join(mismatches),
                )
            )
    return checks


def _scope_checks(repository: Path, root: Path) -> list[AcceptanceCheck]:
    findings = scan_scope(repository, root)
    mapping = (
        (
            "SCOPE_NO_IMAGE_INDUCTION",
            "No automatic image induction module is present.",
            "image_induction",
        ),
        (
            "SCOPE_NO_NEURAL_PERCEPTION",
            "No neural perception module is present.",
            "neural_perception",
        ),
        ("SCOPE_NO_GENERATED_PDF", "No PDF is generated by the demo.", "generated_pdf"),
        (
            "SCOPE_NO_GAUSSIAN_SPLATTING",
            "No Gaussian Splatting integration is present.",
            "gaussian_splatting",
        ),
        ("SCOPE_NO_GUI", "No GUI is introduced.", "gui"),
        ("SCOPE_NO_CPP_CUDA", "No C++ or CUDA source is introduced.", "cpp_cuda"),
        (
            "SCOPE_NO_EVALUATION_CLAIMS",
            "No benchmark or recovery-result claims are generated.",
            "evaluation_claims",
        ),
    )
    return [
        _check(
            code,
            description,
            not findings[key],
            "scan found no representative paths, extensions, or generated outputs"
            if not findings[key]
            else "found: " + ", ".join(findings[key]),
        )
        for code, description, key in mapping
    ]


def _package_checks(repository: Path) -> list[AcceptanceCheck]:
    try:
        data = tomllib.loads(
            (repository / "pyproject.toml").read_text(encoding="utf-8")
        )
        project = data["project"]
        dependencies = tuple(
            str(item).lower() for item in project.get("dependencies", [])
        )
        package_ok = bool(__version__)
        python_ok = "3.11" in str(project.get("requires-python", ""))
        runtime_ok = any(item.startswith("pillow") for item in dependencies) and any(
            item.startswith("trimesh") for item in dependencies
        )
        forbidden_names = (
            "torch",
            "pytorch",
            "open3d",
            "bpy",
            "cuda",
            "pyqt",
            "pyside",
            "tkinter",
        )
        forbidden = tuple(
            item
            for item in dependencies
            if any(name in item for name in forbidden_names)
        )
    except Exception as exc:
        package_ok = python_ok = runtime_ok = False
        dependencies = ()
        forbidden = (str(exc),)
    return [
        _check(
            "PACKAGE_VERSION",
            "The package version is available.",
            package_ok,
            f"package_version={__version__}",
        ),
        _check(
            "PYTHON_311_COMPATIBILITY",
            "Python compatibility includes 3.11.",
            python_ok,
            "requires-python includes 3.11",
        ),
        _check(
            "RUNTIME_DEPENDENCIES",
            "Required Pillow and trimesh runtime dependencies are declared.",
            runtime_ok,
            "declared dependencies: " + ", ".join(dependencies),
        ),
        _check(
            "FORBIDDEN_DEPENDENCIES",
            "No forbidden heavy or GUI dependency is declared.",
            not forbidden,
            "none found" if not forbidden else "found: " + ", ".join(forbidden),
        ),
    ]


def _scene_summary(scene_key: str, checks: list[AcceptanceCheck]) -> SceneAcceptance:
    selected = [item for item in checks if item.scene_key == scene_key]
    passed = sum(item.status is AcceptanceStatus.PASS for item in selected)
    failed = sum(item.status is AcceptanceStatus.FAIL for item in selected)
    skipped = sum(item.status is AcceptanceStatus.SKIP for item in selected)
    return SceneAcceptance(
        scene_key=scene_key,
        status=AcceptanceStatus.FAIL if failed else AcceptanceStatus.PASS,
        total_checks=len(selected),
        passed_checks=passed,
        failed_checks=failed,
        skipped_checks=skipped,
    )


def _check(
    code: str, description: str, passed: bool, details: str, paths: tuple[str, ...] = ()
) -> AcceptanceCheck:
    return AcceptanceCheck(
        code=code,
        description=description,
        status=AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
        details=details,
        artifact_paths=paths,
    )


def _scene_check(
    code: str,
    description: str,
    scene_key: str,
    passed: bool,
    details: str,
    paths: tuple[str, ...] = (),
) -> AcceptanceCheck:
    return AcceptanceCheck(
        code=code,
        description=description,
        status=AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
        scene_key=scene_key,
        details=details,
        artifact_paths=paths,
    )


def _valid_json_file(path: Path) -> tuple[bool, str]:
    try:
        _read_json(path)
        return True, "canonical JSON parses"
    except Exception as exc:
        return False, f"JSON parse failed: {exc}"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_contains_absolute_path(path: Path) -> bool:
    try:
        value = _read_json(path)
    except Exception:
        return True
    for text in _all_strings(value):
        if "\\" in text or (len(text) > 2 and text[1:3] in {":/", ":\\"}):
            return True
        if text.startswith("/") and "/" in text[1:]:
            return True
    return False


def _all_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _all_strings(key)
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)


def _collect_values(value: Any, key: str) -> list[Any]:
    result: list[Any] = []
    if isinstance(value, dict):
        for item_key, item in value.items():
            if item_key == key:
                result.append(item)
            result.extend(_collect_values(item, key))
    elif isinstance(value, list):
        for item in value:
            result.extend(_collect_values(item, key))
    return result


def _portable_relative(value: Any) -> bool:
    if not isinstance(value, str) or "\\" in value or ":" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def _bounds_contains(root: Any, child: Any) -> bool:
    try:
        rmin, rmax = _bounds_vectors(root)
        cmin, cmax = _bounds_vectors(child)
        return all(
            low <= value <= high for low, value, high in zip(rmin, cmin, rmax)
        ) and all(low <= value <= high for low, value, high in zip(rmin, cmax, rmax))
    except Exception:
        return False


def _bounds_vectors(
    bounds: dict[str, Any],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    low = bounds.get("min", bounds.get("minimum"))
    high = bounds.get("max", bounds.get("maximum"))
    if isinstance(low, dict):
        low = tuple(low[axis] for axis in ("x", "y", "z"))
        high = tuple(high[axis] for axis in ("x", "y", "z"))
    return tuple(low), tuple(high)


def _realization_agrees(realizations: Any) -> bool:
    if not isinstance(realizations, list) or len(realizations) != 1:
        return False
    item = realizations[0]
    pairs = (
        ("requested_new_stored_weight", "realized_new_stored_weight"),
        ("requested_count", "realized_count"),
        ("requested_spacing", "realized_spacing"),
        ("requested_semantic_class", "realized_semantic_class"),
    )
    present = [(left, right) for left, right in pairs if left in item]
    return len(present) == 1 and item[present[0][0]] == item.get(present[0][1])


def _png_pixels(path: Path) -> tuple[tuple[int, int], bytes]:
    with Image.open(path) as image:
        converted = image.convert("RGBA")
        return converted.size, converted.tobytes()


def _reopen_glb(path: Path) -> tuple[int, tuple[str, ...]]:
    import trimesh

    loaded = trimesh.load(path, file_type="glb", force="scene", process=False)
    names = tuple(sorted(str(name) for name in loaded.geometry))
    return len(names), names


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]
