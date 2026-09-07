from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from scene_grammar_kit.real_cases import CASE_KEYS, build_open_images_cases
from scene_grammar_kit.real_cases.builder import RealCaseBuildError

REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built_cases(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("real-cases") / "results"
    build_open_images_cases(output, verify_determinism=True)
    return output


def test_frozen_manifests_are_complete_and_sources_match() -> None:
    for key in CASE_KEYS:
        root = REPOSITORY / "inputs" / "real_cases" / key
        manifest = json.loads((root / "case_manifest.json").read_text())
        source = root / manifest["source_image_path"]
        assert manifest["case_role"] == key
        assert manifest["dataset_name"] == "Open Images"
        assert manifest["dataset_version"] == "V7"
        assert manifest["split"] == "validation"
        assert manifest["author"]
        assert manifest["original_landing_page"]
        assert manifest["license_url"].startswith(
            "https://creativecommons.org/licenses/by/"
        )
        assert manifest["annotation_license_url"].endswith("/by/4.0/")
        assert (
            hashlib.sha256(source.read_bytes()).hexdigest()
            == manifest["source_image_sha256"]
        )


def test_annotation_provenance_is_explicit() -> None:
    for key in CASE_KEYS:
        root = REPOSITORY / "inputs" / "real_cases" / key
        annotation = json.loads((root / "annotation.json").read_text())
        manifest = json.loads((root / "case_manifest.json").read_text())
        assert annotation["annotation_notes"]
        assert "researcher-supplied" not in manifest["dataset_supplied_information"]
        assert manifest["researcher_supplied_information"]
        assert manifest["scene_grammar_kit_derived_information"]
        for region in annotation["regions"]:
            assert region["attributes"]["annotation_source"] == "manually_authored"


def test_all_case_outcomes_and_constructor_provenance(built_cases: Path) -> None:
    summary = json.loads((built_cases / "real_case_summary.json").read_text())
    outcomes = {item["case_key"]: item["outcome"] for item in summary["cases"]}
    assert outcomes == {
        "canonical_success": "success",
        "moderate_case": "success",
        "limitation_case": "degraded_success",
    }
    for item in summary["cases"]:
        checks = item["provenance_checks"]
        assert all(checks.values())
        grammar = built_cases / item["case_key"] / "primary" / "grammar.json"
        assert (
            hashlib.sha256(grammar.read_bytes()).hexdigest()
            == item["primary_grammar_sha256"]
        )


def test_summary_formats_have_consistent_order(built_cases: Path) -> None:
    summary = json.loads((built_cases / "real_case_summary.json").read_text())
    assert summary["case_order"] == list(CASE_KEYS)
    csv_lines = (built_cases / "real_case_summary.csv").read_text().splitlines()
    markdown = (built_cases / "real_case_summary.md").read_text()
    assert len(csv_lines) == 4
    assert [line.split(",", 1)[0] for line in csv_lines[1:]] == list(CASE_KEYS)
    positions = [markdown.index(key) for key in CASE_KEYS]
    assert positions == sorted(positions)


def test_review_panels_are_deterministic_and_disclosed(built_cases: Path) -> None:
    summary = json.loads((built_cases / "real_case_summary.json").read_text())
    for key in CASE_KEYS:
        evidence = summary["determinism"][key]
        assert evidence["performed"]
        assert evidence["review_panels_equal"]
        assert evidence["png_pixels_equal"]
        path = built_cases / "review" / f"{key}.png"
        with Image.open(path) as image:
            assert image.size == (2400, 700)
            assert image.mode == "RGB"


def test_limitation_is_precise_and_successfully_degraded(built_cases: Path) -> None:
    report = json.loads(
        (built_cases / "limitation_case" / "real_case_report.json").read_text()
    )
    assert report["outcome"] == "degraded_success"
    assert "axis-aligned" in report["limitation"]
    assert "curvature" in report["limitation"]
    assert report["constructor_success"]


def test_invalid_or_duplicate_case_selection_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RealCaseBuildError, match="invalid or duplicate"):
        build_open_images_cases(
            tmp_path / "bad",
            cases=("canonical_success", "canonical_success"),
        )


def test_cli_builds_one_case_and_reports_outcome(tmp_path: Path) -> None:
    output = tmp_path / "cli-result"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scene_grammar_kit",
            "build-open-images-cases",
            "--output",
            str(output),
            "--case",
            "limitation_case",
        ],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "OPEN IMAGES CASE BUILD COMPLETE" in completed.stdout
    assert "outcome=degraded_success" in completed.stdout
    assert (output / "limitation_case" / "real_case_report.json").is_file()
