"""CLI integration for the frozen minimal evaluation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def _run(
    *arguments: str,
    cwd: Path = REPOSITORY,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scene_grammar_kit", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_help_includes_evaluation() -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "evaluate" in result.stdout


def test_full_cli_evaluation_passes(tmp_path: Path) -> None:
    output = tmp_path / "evaluation"
    result = _run(
        "evaluate",
        "--output",
        str(output),
        "--verify-determinism",
    )
    assert result.returncode == 0
    assert "EVALUATION PASS" in result.stdout
    assert "controlled_cases=12 real_cases=3" in result.stdout
    summary = json.loads((output / "controlled_summary.json").read_text())
    assert summary["valid_grammar_rate"] == {
        "denominator": 12,
        "numerator": 12,
        "rate": 1.0,
    }


def test_nonempty_output_fails_cleanly(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    result = _run(
        "evaluate",
        "--output",
        str(output),
    )
    assert result.returncode == 2
    assert "not empty" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_missing_repository_evidence_fails_cleanly(tmp_path: Path) -> None:
    result = _run(
        "evaluate",
        "--output",
        str(tmp_path / "output"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "repository evidence is missing" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
