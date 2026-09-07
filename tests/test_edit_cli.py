"""Integration tests for the four Batch 1.6 edit CLI subcommands."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"
EDITABLE = FIXTURES / "editable_urban.json"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run_module(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scene_grammar_kit", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("subcommand", "options", "operation_type"),
    [
        (
            "split-weight",
            (
                "--split-id",
                "midground_layout",
                "--child-id",
                "road_region",
                "--weight",
                "8",
            ),
            "set_split_child_weight",
        ),
        (
            "repeat-count",
            ("--repeat-id", "parked_cars", "--count", "6"),
            "set_repeat_count",
        ),
        (
            "repeat-spacing",
            ("--repeat-id", "parked_cars", "--spacing", "0.08"),
            "set_repeat_spacing",
        ),
        (
            "substitute-terminal",
            ("--terminal-id", "street_tree", "--semantic-class", "lamp_post"),
            "substitute_terminal_class",
        ),
    ],
)
def test_each_edit_subcommand_succeeds(
    subcommand: str,
    options: tuple[str, ...],
    operation_type: str,
    tmp_path: Path,
) -> None:
    output = tmp_path / subcommand
    completed = run_module(
        "edit",
        subcommand,
        str(EDITABLE),
        *options,
        "--out",
        str(output),
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert "EDITED:" in completed.stdout
    assert f"operation={operation_type}" in completed.stdout
    assert {item.name for item in output.iterdir()} == {
        "grammar_before.json",
        "grammar_after.json",
        "edit_report.json",
    }
    report = json.loads((output / "edit_report.json").read_text("utf-8"))
    assert report["operations"][0]["operation_type"] == operation_type
    assert report["execution_verification_succeeded"] is True


@pytest.mark.parametrize(
    "arguments",
    [
        (
            "repeat-count",
            "--repeat-id",
            "missing",
            "--count",
            "6",
        ),
        (
            "repeat-count",
            "--repeat-id",
            "road_surface",
            "--count",
            "6",
        ),
        (
            "split-weight",
            "--split-id",
            "midground_layout",
            "--child-id",
            "road_region",
            "--weight",
            "0",
        ),
        (
            "repeat-spacing",
            "--repeat-id",
            "parked_cars",
            "--spacing",
            "1",
        ),
    ],
)
def test_expected_edit_failures_are_clean_and_write_nothing(
    arguments: tuple[str, ...],
    tmp_path: Path,
) -> None:
    output = tmp_path / "failed"
    completed = run_module(
        "edit",
        arguments[0],
        str(EDITABLE),
        *arguments[1:],
        "--out",
        str(output),
    )
    assert completed.returncode == 2
    assert "EDIT FAILED" in completed.stdout
    assert "Traceback" not in completed.stdout + completed.stderr
    assert not output.exists()


def test_no_verify_execution_is_explicit_in_cli_and_report(tmp_path: Path) -> None:
    output = tmp_path / "unverified"
    completed = run_module(
        "edit",
        "repeat-count",
        str(EDITABLE),
        "--repeat-id",
        "parked_cars",
        "--count",
        "6",
        "--out",
        str(output),
        "--no-verify-execution",
    )
    assert completed.returncode == 0
    assert "execution_verification=disabled" in completed.stdout
    report = json.loads((output / "edit_report.json").read_text("utf-8"))
    assert report["execution_verification_succeeded"] is False
    assert report["geometry_diff"] is None
    assert report["warnings"] == ["execution verification was explicitly disabled"]


def test_nonempty_output_requires_overwrite_and_preserves_unrelated_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / "edit"
    output.mkdir()
    sentinel = output / "note.txt"
    sentinel.write_text("keep", encoding="utf-8")
    arguments = (
        "edit",
        "repeat-count",
        str(EDITABLE),
        "--repeat-id",
        "parked_cars",
        "--count",
        "6",
        "--out",
        str(output),
    )
    refused = run_module(*arguments)
    assert refused.returncode == 2
    assert "not empty" in refused.stdout
    assert sentinel.read_text("utf-8") == "keep"
    allowed = run_module(*arguments, "--overwrite")
    assert allowed.returncode == 0
    assert sentinel.read_text("utf-8") == "keep"


def test_help_lists_edit_and_existing_commands_still_work() -> None:
    help_result = run_module("--help")
    validate_result = run_module("validate", str(EDITABLE))
    inspect_result = run_module("inspect", str(EDITABLE))
    assert help_result.returncode == 0
    assert "edit" in help_result.stdout
    assert validate_result.returncode == 0
    assert inspect_result.returncode == 0
