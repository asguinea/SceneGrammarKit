"""CLI integration for formal Phase 2 acceptance."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
CASES = REPOSITORY / "inputs" / "real_cases"
RESULTS = REPOSITORY / "results" / "real_cases"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scene_grammar_kit", *arguments],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )


def test_help_includes_phase2_acceptance() -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "phase2-acceptance" in result.stdout


def test_full_cli_acceptance_passes(tmp_path: Path) -> None:
    output = tmp_path / "acceptance"
    result = _run(
        "phase2-acceptance",
        "--cases",
        str(CASES),
        "--results",
        str(RESULTS),
        "--output",
        str(output),
        "--verify-determinism",
    )
    assert result.returncode == 0
    assert "PHASE 2 ACCEPTANCE PASS" in result.stdout
    assert (
        json.loads((output / "phase2_acceptance.json").read_text())["overall_status"]
        == "PASS"
    )


def test_missing_input_fails_cleanly(tmp_path: Path) -> None:
    result = _run(
        "phase2-acceptance",
        "--cases",
        str(tmp_path / "missing"),
        "--results",
        str(RESULTS),
        "--output",
        str(tmp_path / "output"),
        "--verify-determinism",
    )
    assert result.returncode == 1
    assert "PHASE 2 ACCEPTANCE FAIL" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_corrupted_result_fails_cleanly(tmp_path: Path) -> None:
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    (results / "canonical_success" / "construction_report.json").write_text(
        "{", encoding="utf-8"
    )
    result = _run(
        "phase2-acceptance",
        "--cases",
        str(CASES),
        "--results",
        str(results),
        "--output",
        str(tmp_path / "output"),
    )
    assert result.returncode == 1
    assert "PHASE 2 ACCEPTANCE FAIL" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_expected_limitation_is_accepted_without_determinism(
    tmp_path: Path,
) -> None:
    result = _run(
        "phase2-acceptance",
        "--cases",
        str(CASES),
        "--results",
        str(RESULTS),
        "--output",
        str(tmp_path / "output"),
    )
    assert result.returncode == 1
    assert "outcome=degraded_success status=PASS" in result.stdout
    assert "skipped=11" in result.stdout


def test_unexpected_limitation_fails(tmp_path: Path) -> None:
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    path = results / "limitation_case" / "real_case_report.json"
    data = json.loads(path.read_text())
    data["outcome"] = "failure"
    path.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    result = _run(
        "phase2-acceptance",
        "--cases",
        str(CASES),
        "--results",
        str(results),
        "--output",
        str(tmp_path / "output"),
    )
    assert result.returncode == 1
    assert "case=limitation_case" in result.stdout
    assert "status=FAIL" in result.stdout


def test_cli_overwrite_protection(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    result = _run(
        "phase2-acceptance",
        "--cases",
        str(CASES),
        "--results",
        str(RESULTS),
        "--output",
        str(output),
    )
    assert result.returncode == 2
    assert "not empty" in result.stdout
