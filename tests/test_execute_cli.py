"""Batch 1.4 execute command integration tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run_module(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the installed module CLI from the repository root."""
    return subprocess.run(
        [sys.executable, "-m", "scene_grammar_kit", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_execute_writes_complete_artifact_tree(tmp_path: Path) -> None:
    """Valid execution returns zero and writes every Batch 1.4 artifact."""
    output = tmp_path / "run"
    result = run_module(
        "execute",
        str(FIXTURES / "valid_nested_urban.json"),
        "--out",
        str(output),
    )
    assert result.returncode == 0
    expected = {
        "execution_report.json",
        "grammar/grammar.json",
        "grammar/grammar_canonical.json",
        "geometry/primitives.json",
        "geometry/scene.glb",
        "geometry/semantic_index.json",
    }
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert actual == expected
    assert (output / "grammar/grammar.json").read_bytes() == (
        output / "grammar/grammar_canonical.json"
    ).read_bytes()
    assert (
        json.loads((output / "execution_report.json").read_text(encoding="utf-8"))[
            "success"
        ]
        is True
    )
    assert "primitives=7" in result.stdout
    assert result.stderr == ""


def test_execute_fails_cleanly_on_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON returns a concise nonzero result and writes no run."""
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"root":', encoding="utf-8")
    output = tmp_path / "run"
    result = run_module("execute", str(malformed), "--out", str(output))
    assert result.returncode == 2
    assert "EXECUTION FAILED" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not output.exists()


def test_execute_fails_cleanly_on_semantic_error(tmp_path: Path) -> None:
    """Semantic invalidity is rejected before output directory creation."""
    output = tmp_path / "run"
    result = run_module(
        "execute",
        str(FIXTURES / "duplicate_node_ids.json"),
        "--out",
        str(output),
    )
    assert result.returncode == 2
    assert "duplicate_node_id" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not output.exists()


def test_execute_fails_cleanly_on_repeat_fit_error(tmp_path: Path) -> None:
    """An impossible repeat is rejected before any artifact is written."""
    output = tmp_path / "run"
    result = run_module(
        "execute",
        str(FIXTURES / "repeat_cannot_fit.json"),
        "--out",
        str(output),
    )
    assert result.returncode == 2
    assert "Repeat does not fit" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not output.exists()


def test_execute_enforces_primitive_limit(tmp_path: Path) -> None:
    """CLI exposes the executor's pre-materialization primitive safety limit."""
    output = tmp_path / "run"
    result = run_module(
        "execute",
        str(FIXTURES / "large_nested_repeats.json"),
        "--out",
        str(output),
        "--maximum-primitives",
        "1000",
    )
    assert result.returncode == 2
    assert "maximum_primitives=1000" in result.stdout
    assert not output.exists()


def test_execute_protects_nonempty_output_and_allows_explicit_reuse(
    tmp_path: Path,
) -> None:
    """Existing content survives refusal and explicit known-artifact overwrite."""
    output = tmp_path / "run"
    output.mkdir()
    sentinel = output / "user-note.txt"
    sentinel.write_text("keep", encoding="utf-8")
    arguments = (
        "execute",
        str(FIXTURES / "valid_terminal.json"),
        "--out",
        str(output),
    )
    refused = run_module(*arguments)
    assert refused.returncode == 2
    assert "not empty" in refused.stdout
    assert sentinel.read_text(encoding="utf-8") == "keep"
    reused = run_module(*arguments, "--overwrite")
    assert reused.returncode == 0
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_help_lists_execute_and_existing_commands_still_work() -> None:
    """Execute appears in help without regressing validate or inspect."""
    help_result = run_module("--help")
    validate_result = run_module(
        "validate",
        str(FIXTURES / "valid_nested_urban.json"),
    )
    inspect_result = run_module(
        "inspect",
        str(FIXTURES / "valid_nested_urban.json"),
    )
    assert help_result.returncode == 0
    assert "execute" in help_result.stdout
    assert validate_result.returncode == 0
    assert inspect_result.returncode == 0
