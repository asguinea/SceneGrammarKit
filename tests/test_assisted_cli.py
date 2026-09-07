"""CLI tests for strict assisted-input validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"
ROOT = Path(__file__).resolve().parents[1]


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scene_grammar_kit", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_valid_assisted_input_returns_zero_and_factual_counts() -> None:
    result = _run(
        "validate-assisted-input",
        str(FIXTURES / "valid" / "urban_minimal.annotation.json"),
        "--config",
        str(FIXTURES / "valid" / "urban_minimal.construction.json"),
    )
    assert result.returncode == 0
    assert "VALID ASSISTED INPUT" in result.stdout
    assert "scene=urban_assisted_minimal" in result.stdout
    assert "regions=6" in result.stdout
    assert "instances=3" in result.stdout
    assert "repeat_groups=1" in result.stdout
    assert "depth_zones=foreground,midground,background" in result.stdout
    assert result.stderr == ""


def test_invalid_annotation_json_fails_cleanly(tmp_path: Path) -> None:
    annotation = tmp_path / "invalid.json"
    annotation.write_text("{", encoding="utf-8")
    result = _run(
        "validate-assisted-input",
        str(annotation),
        "--config",
        str(FIXTURES / "valid" / "default.construction.json"),
    )
    assert result.returncode == 2
    assert "assisted_input_load_failed" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_invalid_config_fails_cleanly() -> None:
    result = _run(
        "validate-assisted-input",
        str(FIXTURES / "valid" / "facade_polygon.annotation.json"),
        "--config",
        str(FIXTURES / "invalid" / "invalid_tolerance.construction.json"),
    )
    assert result.returncode == 2
    assert "INVALID ASSISTED INPUT" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_document_validation_failure_returns_nonzero() -> None:
    result = _run(
        "validate-assisted-input",
        str(FIXTURES / "invalid" / "missing_parent.annotation.json"),
        "--config",
        str(FIXTURES / "valid" / "default.construction.json"),
    )
    assert result.returncode == 1
    assert "missing_parent_region" in result.stdout
    assert "domain=annotation" in result.stdout


def test_compatibility_failure_returns_nonzero(tmp_path: Path) -> None:
    data = json.loads(
        (FIXTURES / "valid" / "urban_minimal.annotation.json").read_text(
            encoding="utf-8"
        )
    )
    data["regions"][2]["depth_zone"] = "foreground"
    annotation = tmp_path / "incompatible.json"
    annotation.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    result = _run(
        "validate-assisted-input",
        str(annotation),
        "--config",
        str(FIXTURES / "valid" / "default.construction.json"),
    )
    assert result.returncode == 1
    assert "incompatible_parent_child_depth_zone" in result.stdout
    assert "domain=compatibility" in result.stdout


def test_help_includes_assisted_command() -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "validate-assisted-input" in result.stdout


def test_existing_version_command_remains_functional() -> None:
    result = _run("version")
    assert result.returncode == 0
    assert "SceneGrammarKit 0.1.0" in result.stdout
