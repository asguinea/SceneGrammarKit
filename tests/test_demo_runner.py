from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import trimesh
from PIL import Image

from scene_grammar_kit.demo import (
    REQUIRED_ACCEPTANCE_CODES,
    AcceptanceStatus,
    DemoBuildError,
    DemoConfig,
    acceptance_report_to_markdown,
    run_demo,
    run_phase1_acceptance,
    scan_scope,
)


@pytest.fixture(scope="module")
def urban_demo(tmp_path_factory: pytest.TempPathFactory):
    return run_demo(
        DemoConfig(
            tmp_path_factory.mktemp("demo-urban") / "bundle",
            selected_scene_keys=("urban_street",),
            quick=True,
        )
    )


@pytest.fixture(scope="module")
def all_demo(tmp_path_factory: pytest.TempPathFactory):
    return run_demo(
        DemoConfig(
            tmp_path_factory.mktemp("demo-all") / "bundle",
            quick=True,
        )
    )


@pytest.fixture(scope="module")
def deterministic_demo(tmp_path_factory: pytest.TempPathFactory):
    return run_demo(
        DemoConfig(
            tmp_path_factory.mktemp("demo-deterministic") / "bundle",
            selected_scene_keys=("urban_street",),
            quick=True,
            verify_determinism=True,
        )
    )


def test_single_scene_demo_succeeds_with_expected_tree(urban_demo) -> None:
    root = urban_demo.output_directory
    assert urban_demo.acceptance_report.overall_status is AcceptanceStatus.PASS
    for name in (
        "demo_manifest.json",
        "phase1_acceptance.json",
        "phase1_acceptance.md",
        "artifact_index.json",
        "README.md",
    ):
        assert (root / name).is_file()
    assert (root / "scenes" / "urban_street" / "build_report.json").is_file()


def test_required_stable_check_codes_are_present(urban_demo) -> None:
    actual = {item.code for item in urban_demo.acceptance_report.checks}
    assert set(REQUIRED_ACCEPTANCE_CODES) <= actual


def test_all_scene_demo_and_review_set_succeed(all_demo) -> None:
    root = all_demo.output_directory
    assert all_demo.acceptance_report.overall_status is AcceptanceStatus.PASS
    assert {path.name for path in (root / "scenes").iterdir()} == {
        "urban_street",
        "repeated_facade",
        "indoor_corridor",
    }
    assert len(tuple((root / "review").glob("*.png"))) == 7


def test_review_images_are_byte_identical(urban_demo) -> None:
    root = urban_demo.output_directory
    pairs = (
        ("urban_original.png", "original/primary.png"),
        ("urban_road_wider.png", "edits/road_wider/after.png"),
        ("urban_more_cars.png", "edits/more_parked_cars/after.png"),
    )
    for review, source in pairs:
        assert (root / "review" / review).read_bytes() == (
            root / "scenes" / "urban_street" / source
        ).read_bytes()


def test_all_json_png_and_glb_artifacts_reopen(urban_demo) -> None:
    root = urban_demo.output_directory
    for path in root.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    for path in root.rglob("*.png"):
        with Image.open(path) as image:
            image.load()
            assert image.size == (640, 426)
    for path in root.rglob("*.glb"):
        loaded = trimesh.load(path, file_type="glb", force="scene", process=False)
        assert loaded.geometry


def test_artifact_index_is_sorted_relative_and_hashes_final_bytes(urban_demo) -> None:
    root = urban_demo.output_directory
    data = json.loads((root / "artifact_index.json").read_text(encoding="utf-8"))
    paths = [item["path"] for item in data["entries"]]
    assert paths == sorted(paths)
    assert "artifact_index.json" not in paths
    assert "phase1_acceptance.json" not in paths
    for item in data["entries"]:
        assert not Path(item["path"]).is_absolute()
        payload = (root / item["path"]).read_bytes()
        assert item["byte_size"] == len(payload)
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()


def test_demo_manifest_has_no_environment_metadata(urban_demo) -> None:
    text = (urban_demo.output_directory / "demo_manifest.json").read_text(
        encoding="utf-8"
    )
    assert "timestamp" not in text.lower()
    assert "username" not in text.lower()
    assert str(urban_demo.output_directory) not in text


def test_nonempty_output_is_protected_and_overwrite_preserves_unrelated(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    unrelated = root / "notes.txt"
    unrelated.write_text("preserve me", encoding="utf-8")
    with pytest.raises(DemoBuildError):
        run_demo(
            DemoConfig(
                root,
                selected_scene_keys=("urban_street",),
                quick=True,
            )
        )
    result = run_demo(
        DemoConfig(
            root,
            selected_scene_keys=("urban_street",),
            quick=True,
            overwrite=True,
        )
    )
    assert result.acceptance_report.overall_status is AcceptanceStatus.PASS
    assert unrelated.read_text(encoding="utf-8") == "preserve me"


def test_determinism_compares_json_pixels_png_and_glb_and_cleans_temp(
    deterministic_demo,
) -> None:
    evidence = deterministic_demo.determinism
    assert evidence.performed
    assert evidence.temporary_directory_removed
    assert not evidence.canonical_json_mismatches
    assert not evidence.png_pixel_mismatches
    assert not evidence.png_byte_mismatches
    assert not evidence.glb_byte_mismatches
    assert not evidence.glb_structure_mismatches
    assert deterministic_demo.output_directory.is_dir()
    prefix = f".{deterministic_demo.output_directory.name}.verify-"
    assert not any(
        child.name.startswith(prefix)
        for child in deterministic_demo.output_directory.parent.iterdir()
    )


@pytest.mark.parametrize(
    ("relative", "mutation", "expected_code"),
    [
        (
            "scenes/urban_street/original/execution_report.json",
            lambda path: path.write_text("{", encoding="utf-8"),
            "EXECUTION_ARTIFACTS",
        ),
        (
            "scenes/urban_street/original/primary.png",
            lambda path: path.write_bytes(b"not a PNG"),
            "RENDERING_ARTIFACTS",
        ),
        (
            "scenes/urban_street/original/scene.glb",
            lambda path: path.write_bytes(b"not a GLB"),
            "GLB_REOPEN",
        ),
    ],
)
def test_corrupt_artifacts_cause_acceptance_failure(
    urban_demo,
    tmp_path: Path,
    relative: str,
    mutation,
    expected_code: str,
) -> None:
    result = _copied_result(urban_demo, tmp_path)
    mutation(result.output_directory / relative)
    report = run_phase1_acceptance(result, verify_determinism=False)
    assert report.overall_status is AcceptanceStatus.FAIL
    assert any(
        item.code == expected_code and item.status is AcceptanceStatus.FAIL
        for item in report.checks
    )


def test_missing_artifact_causes_acceptance_failure(
    urban_demo,
    tmp_path: Path,
) -> None:
    result = _copied_result(urban_demo, tmp_path)
    (result.output_directory / "scenes/urban_street/original/primary.png").unlink()
    report = run_phase1_acceptance(result, verify_determinism=False)
    assert report.overall_status is AcceptanceStatus.FAIL


@pytest.mark.parametrize(
    ("relative", "modify", "expected_code"),
    [
        (
            "scenes/urban_street/original/primary.render.json",
            lambda data: data.__setitem__("width", 1),
            "RENDERING_ARTIFACTS",
        ),
        (
            "scenes/urban_street/original/primary.render.json",
            lambda data: data.__setitem__("renderer_policy_version", "9.9"),
            "RENDERING_ARTIFACTS",
        ),
        (
            "scenes/urban_street/edits/road_wider/edit_report.json",
            lambda data: data["symbolic_diff"]["node_ids_after"].append("new_node"),
            "EDITING_ARTIFACTS",
        ),
        (
            "scenes/urban_street/edits/road_wider/edit_report.json",
            lambda data: data["realizations"][0].__setitem__(
                "realized_new_stored_weight", 999
            ),
            "EDITING_ARTIFACTS",
        ),
    ],
)
def test_semantic_report_corruption_causes_failure(
    urban_demo,
    tmp_path: Path,
    relative: str,
    modify,
    expected_code: str,
) -> None:
    result = _copied_result(urban_demo, tmp_path)
    path = result.output_directory / relative
    data = json.loads(path.read_text(encoding="utf-8"))
    modify(data)
    path.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    report = run_phase1_acceptance(result, verify_determinism=False)
    assert report.overall_status is AcceptanceStatus.FAIL
    assert any(
        item.code == expected_code and item.status is AcceptanceStatus.FAIL
        for item in report.checks
    )


def test_unchanged_before_after_pixels_cause_failure(
    urban_demo,
    tmp_path: Path,
) -> None:
    result = _copied_result(urban_demo, tmp_path)
    edit = result.output_directory / "scenes/urban_street/edits/road_wider"
    shutil.copyfile(edit / "before.png", edit / "after.png")
    report = run_phase1_acceptance(result, verify_determinism=False)
    assert any(
        item.code == "RENDERING_ARTIFACTS" and item.status is AcceptanceStatus.FAIL
        for item in report.checks
    )


def test_optional_skips_have_explicit_reasons(urban_demo) -> None:
    report = urban_demo.acceptance_report
    skipped = [item for item in report.checks if item.status is AcceptanceStatus.SKIP]
    assert skipped
    assert all(not item.required and item.details for item in skipped)


def test_markdown_is_derived_and_contains_status_totals_command_and_limits(
    urban_demo,
) -> None:
    report = urban_demo.acceptance_report
    markdown = acceptance_report_to_markdown(
        report,
        reproduction_command="python -m scene_grammar_kit demo --output runs/test",
    )
    assert f"Overall status: **{report.overall_status.value}**" in markdown
    assert f"- Total: {report.total_checks}" in markdown
    assert "python -m scene_grammar_kit demo" in markdown
    assert "Grammars are hand-authored" in markdown
    assert str(urban_demo.output_directory) not in markdown


def test_scope_scan_detects_representative_forbidden_source(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    bundle = tmp_path / "bundle"
    repository.mkdir()
    bundle.mkdir()
    (repository / "late_phase.cu").write_text("// representative", encoding="utf-8")
    findings = scan_scope(repository, bundle)
    assert findings["cpp_cuda"] == ("late_phase.cu",)


def _copied_result(result, tmp_path: Path):
    target = tmp_path / "bundle"
    shutil.copytree(result.output_directory, target)
    return replace(result, output_directory=target)
