"""Offline acceptance tests for the complete frozen Phase 2 workflow."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from scene_grammar_kit.phase2_acceptance import (
    CASE_ORDER,
    PHASE2_ACCEPTANCE_POLICY_VERSION,
    AcceptanceStatus,
    Phase2AcceptanceCheck,
    Phase2AcceptanceError,
    run_phase2_acceptance,
)
from scene_grammar_kit.phase2_acceptance.persistence import EVIDENCE_FIELDS

REPOSITORY = Path(__file__).resolve().parents[1]
CASES = REPOSITORY / "inputs" / "real_cases"
RESULTS = REPOSITORY / "results" / "real_cases"
REGRESSION = (
    REPOSITORY / "tests" / "fixtures" / "phase2" / "phase2_regression_manifest.json"
)
EXPECTED_IDS = (
    "736a482693c18962",
    "40992cf7a7bbf20e",
    "692c5c6be088dbf8",
)
EXPECTED_HASHES = (
    "2db45d10647afbf91f19606e1c669f919a9904e482e83227129d4df1766210c3",
    "630eb7f7e4b23f17e932a100a0340ac48755e7467b7de09e4cdd345c94022ca8",
    "841b72cf084b7760566006851610c2f36aaa2b5102ba69a781220a28532cecf5",
)


@pytest.fixture(scope="module")
def accepted_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("phase2-acceptance") / "package"
    result = run_phase2_acceptance(
        CASES,
        RESULTS,
        output,
        verify_determinism=True,
    )
    assert result.report.overall_status is AcceptanceStatus.PASS
    return output


def _copy_inputs(tmp_path: Path) -> tuple[Path, Path]:
    cases = tmp_path / "cases"
    results = tmp_path / "results"
    shutil.copytree(CASES, cases)
    shutil.copytree(RESULTS, results)
    return cases, results


def _write_json(path: Path, data: object) -> None:
    path.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def _run_corrupt(
    tmp_path: Path,
    *,
    mutate_cases=None,
    mutate_results=None,
):
    cases, results = _copy_inputs(tmp_path)
    if mutate_cases:
        mutate_cases(cases)
    if mutate_results:
        mutate_results(results)
    return run_phase2_acceptance(
        cases,
        results,
        tmp_path / "output",
        verify_determinism=False,
    ).report


def _status(report, code: str, case_key: str | None = None) -> AcceptanceStatus:
    return next(
        item.status
        for item in report.checks
        if item.code == code and item.case_key == case_key
    )


def test_policy_and_models_are_immutable() -> None:
    assert PHASE2_ACCEPTANCE_POLICY_VERSION == "0.1"
    check = Phase2AcceptanceCheck(
        "CODE", "description", AcceptanceStatus.PASS, True, "details"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        check.code = "OTHER"  # type: ignore[misc]


def test_frozen_roles_ids_hashes_and_attribution() -> None:
    assert CASE_ORDER == (
        "canonical_success",
        "moderate_case",
        "limitation_case",
    )
    for key, image_id, digest in zip(CASE_ORDER, EXPECTED_IDS, EXPECTED_HASHES):
        root = CASES / key
        manifest = json.loads((root / "case_manifest.json").read_text())
        source = root / manifest["source_image_path"]
        assert manifest["case_role"] == key
        assert manifest["image_id"] == image_id
        assert manifest["author"]
        assert manifest["original_landing_page"]
        assert manifest["license_url"].endswith("/by/2.0/")
        assert manifest["annotation_license_url"].endswith("/by/4.0/")
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_valid_real_case_package_passes(accepted_package: Path) -> None:
    report = json.loads((accepted_package / "phase2_acceptance.json").read_text())
    assert report["overall_status"] == "PASS"
    assert report["required_failed_checks"] == 0
    assert report["phase2_acceptance_policy_version"] == "0.1"
    assert [item["case_key"] for item in report["cases"]] == list(CASE_ORDER)


def test_missing_case_fails(tmp_path: Path) -> None:
    def mutate(cases: Path) -> None:
        shutil.rmtree(cases / "moderate_case")

    report = _run_corrupt(tmp_path, mutate_cases=mutate)
    assert report.overall_status is AcceptanceStatus.FAIL
    assert _status(report, "CASE_SET") is AcceptanceStatus.FAIL


def test_unexpected_fourth_result_bundle_fails(tmp_path: Path) -> None:
    cases, results = _copy_inputs(tmp_path)
    shutil.copytree(
        results / "canonical_success",
        results / "unexpected_fourth_case",
    )
    result = run_phase2_acceptance(
        cases,
        results,
        tmp_path / "output",
        verify_determinism=False,
    )
    assert result.report.overall_status is AcceptanceStatus.FAIL
    assert _status(result.report, "RESULT_SET") is AcceptanceStatus.FAIL


def test_changed_source_hash_fails(tmp_path: Path) -> None:
    def mutate(cases: Path) -> None:
        path = cases / "canonical_success" / "case_manifest.json"
        data = json.loads(path.read_text())
        data["source_image_sha256"] = "0" * 64
        _write_json(path, data)

    report = _run_corrupt(tmp_path, mutate_cases=mutate)
    assert _status(report, "SOURCE_HASH", "canonical_success") is AcceptanceStatus.FAIL


def test_missing_attribution_fails(tmp_path: Path) -> None:
    def mutate(cases: Path) -> None:
        path = cases / "moderate_case" / "case_manifest.json"
        data = json.loads(path.read_text())
        data["author"] = ""
        _write_json(path, data)

    report = _run_corrupt(tmp_path, mutate_cases=mutate)
    assert (
        _status(report, "ATTRIBUTION_COMPLETE", "moderate_case")
        is AcceptanceStatus.FAIL
    )


def test_manually_substituted_grammar_fails(tmp_path: Path) -> None:
    def mutate(results: Path) -> None:
        root = results / "canonical_success"
        shutil.copyfile(
            root / "split_only" / "grammar.json",
            root / "primary" / "grammar.json",
        )

    report = _run_corrupt(tmp_path, mutate_results=mutate)
    assert (
        _status(report, "CONSTRUCTOR_PROVENANCE", "canonical_success")
        is AcceptanceStatus.FAIL
    )


def test_render_not_matching_grammar_fails(tmp_path: Path) -> None:
    def mutate(results: Path) -> None:
        path = results / "moderate_case" / "primary" / "render.json"
        data = json.loads(path.read_text())
        data["executed_scene_grammar_sha256"] = "0" * 64
        _write_json(path, data)

    report = _run_corrupt(tmp_path, mutate_results=mutate)
    assert (
        _status(report, "CONSTRUCTOR_PROVENANCE", "moderate_case")
        is AcceptanceStatus.FAIL
    )


def test_incorrect_expected_outcome_fails(tmp_path: Path) -> None:
    def mutate(results: Path) -> None:
        path = results / "limitation_case" / "real_case_report.json"
        data = json.loads(path.read_text())
        data["outcome"] = "failure"
        _write_json(path, data)

    report = _run_corrupt(tmp_path, mutate_results=mutate)
    assert (
        _status(report, "EXPECTED_OUTCOME", "limitation_case") is AcceptanceStatus.FAIL
    )


def test_incorrect_repeat_counts_fail(tmp_path: Path) -> None:
    def mutate(results: Path) -> None:
        path = results / "moderate_case" / "construction_report.json"
        data = json.loads(path.read_text())
        data["accepted_repeat_group_count"] = 0
        data["fallback_repeat_group_count"] = 1
        _write_json(path, data)

    report = _run_corrupt(tmp_path, mutate_results=mutate)
    assert _status(report, "EXPECTED_OUTCOME", "moderate_case") is AcceptanceStatus.FAIL


def test_hidden_automatic_reconstruction_wording_fails(tmp_path: Path) -> None:
    def mutate(cases: Path) -> None:
        path = cases / "canonical_success" / "case_manifest.json"
        data = json.loads(path.read_text())
        data["factual_notes"].append("This is automatic reconstruction.")
        _write_json(path, data)

    report = _run_corrupt(tmp_path, mutate_cases=mutate)
    assert (
        _status(report, "ASSISTED_DISCLOSURE", "canonical_success")
        is AcceptanceStatus.FAIL
    )


def test_evidence_json_csv_markdown_agree(accepted_package: Path) -> None:
    rows = json.loads((accepted_package / "phase2_evidence_summary.json").read_text())
    with (accepted_package / "phase2_evidence_summary.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        csv_rows = list(csv.DictReader(handle))
    markdown = (accepted_package / "phase2_evidence_summary.md").read_text()
    assert len(rows) == len(csv_rows) == 3
    assert tuple(row["case_key"] for row in rows) == CASE_ORDER
    assert tuple(row["case_key"] for row in csv_rows) == CASE_ORDER
    assert set(rows[0]) == set(EVIDENCE_FIELDS)
    assert all(markdown.index(key) >= 0 for key in CASE_ORDER)
    assert not any(
        word in markdown.casefold()
        for word in ("p-value", "performance ranking", "mean accuracy")
    )


def test_evidence_required_fields_and_empty_missing_value(
    accepted_package: Path,
) -> None:
    rows = json.loads((accepted_package / "phase2_evidence_summary.json").read_text())
    assert all(set(row) == set(EVIDENCE_FIELDS) for row in rows)
    assert rows[0]["limitation_code"] == ""
    assert rows[1]["limitation_code"] == ""
    assert rows[2]["limitation_code"] == "axis_aligned_proxy_curvature_loss"


def test_attribution_json_and_markdown_agree(accepted_package: Path) -> None:
    records = json.loads((accepted_package / "attribution.json").read_text())
    markdown = (accepted_package / "ATTRIBUTION.md").read_text()
    assert tuple(item["image_id"] for item in records) == EXPECTED_IDS
    for item in records:
        assert item["license_url"] in markdown
        assert item["author"] in markdown
        assert item["original_landing_page"] in markdown
        assert len(item["asset_paths"]) == 3


def test_regression_manifest_locks_current_sources_and_update_process() -> None:
    manifest = json.loads(REGRESSION.read_text())
    assert manifest["case_order"] == list(CASE_ORDER)
    assert len(manifest["cases"]) == 3
    assert "intentional frozen-case change" in manifest["update_instructions"]
    assert "Never edit one hash in isolation" in manifest["update_policy"]
    for key, locked in zip(CASE_ORDER, manifest["cases"]):
        source = CASES / key / "source.jpg"
        assert (
            hashlib.sha256(source.read_bytes()).hexdigest()
            == locked["source_image_sha256"]
        )


def test_hero_candidate_is_exact_and_reopenable(accepted_package: Path) -> None:
    path = accepted_package / "review" / "overview_candidate.png"
    with Image.open(path) as image:
        assert image.size == (2400, 1350)
        assert image.mode == "RGB"
        image.verify()


def test_hero_candidate_pixels_and_bytes_are_deterministic(
    accepted_package: Path,
    tmp_path: Path,
) -> None:
    rebuilt = tmp_path / "rebuilt"
    run_phase2_acceptance(
        CASES,
        RESULTS,
        rebuilt,
        verify_determinism=False,
    )
    first = accepted_package / "review" / "overview_candidate.png"
    second = rebuilt / "review" / "overview_candidate.png"
    assert first.read_bytes() == second.read_bytes()
    with Image.open(first) as first_image, Image.open(second) as second_image:
        assert first_image.tobytes() == second_image.tobytes()


def test_review_images_are_byte_identical(accepted_package: Path) -> None:
    for name in (*CASE_ORDER, "three_case_overview"):
        assert (accepted_package / "review" / f"{name}.png").read_bytes() == (
            RESULTS / "review" / f"{name}.png"
        ).read_bytes()


def test_artifact_index_is_relative_and_deterministic(
    accepted_package: Path,
) -> None:
    path = accepted_package / "artifact_index.json"
    first = path.read_bytes()
    records = json.loads(first)
    assert records
    assert all(not Path(item["relative_path"]).is_absolute() for item in records)
    assert all("\\" not in item["relative_path"] for item in records)
    assert first == path.read_bytes()


def test_required_output_tree_exists(accepted_package: Path) -> None:
    expected = {
        "README.md",
        "phase2_acceptance.json",
        "phase2_acceptance.md",
        "phase2_evidence_summary.json",
        "phase2_evidence_summary.csv",
        "phase2_evidence_summary.md",
        "artifact_index.json",
        "attribution.json",
        "ATTRIBUTION.md",
        "phase2_regression_manifest.json",
        "review/canonical_success.png",
        "review/moderate_case.png",
        "review/limitation_case.png",
        "review/three_case_overview.png",
        "review/overview_candidate.png",
    }
    actual = {
        path.relative_to(accepted_package).as_posix()
        for path in accepted_package.rglob("*")
        if path.is_file()
    }
    assert actual == expected


def test_determinism_checks_all_pass(accepted_package: Path) -> None:
    report = json.loads((accepted_package / "phase2_acceptance.json").read_text())
    checks = [
        item for item in report["checks"] if item["code"].startswith("DETERMINISM_")
    ]
    assert len(checks) == 11
    assert all(item["status"] == "PASS" for item in checks)


def test_overwrite_preserves_unrelated_file(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(Phase2AcceptanceError, match="not empty"):
        run_phase2_acceptance(CASES, RESULTS, output)
    result = run_phase2_acceptance(
        CASES,
        RESULTS,
        output,
        overwrite=True,
        verify_determinism=False,
    )
    assert result.report.overall_status is AcceptanceStatus.FAIL
    assert sentinel.read_text(encoding="utf-8") == "keep"
    indexed = json.loads((output / "artifact_index.json").read_text())
    assert "keep.txt" not in {item["relative_path"] for item in indexed}


def test_stale_pass_does_not_survive_required_failure(
    accepted_package: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    shutil.copytree(accepted_package, output)
    cases, results = _copy_inputs(tmp_path / "corrupt")
    manifest = cases / "canonical_success" / "case_manifest.json"
    data = json.loads(manifest.read_text())
    data["author"] = ""
    _write_json(manifest, data)
    result = run_phase2_acceptance(
        cases,
        results,
        output,
        overwrite=True,
        verify_determinism=False,
    )
    persisted = json.loads((output / "phase2_acceptance.json").read_text())
    assert result.report.overall_status is AcceptanceStatus.FAIL
    assert persisted["overall_status"] == "FAIL"
