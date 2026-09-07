"""CLI tests for semantic validation and deterministic inspection."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run_module(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the module CLI from the repository root."""
    return subprocess.run(
        [sys.executable, "-m", "scene_grammar_kit", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_validate_succeeds_on_valid_grammar() -> None:
    """Validate returns zero and concise statistics for a valid grammar."""
    path = FIXTURES / "valid_nested_urban.json"
    result = run_module("validate", str(path))
    assert result.returncode == 0
    assert f"VALID: {path}" in result.stdout
    assert "nodes=8 splits=2 repeats=1 terminals=5 max_depth=3" in result.stdout
    assert result.stderr == ""


def test_validate_fails_cleanly_on_invalid_json(tmp_path: Path) -> None:
    """Invalid JSON returns a domain error without a traceback."""
    path = tmp_path / "invalid.json"
    path.write_text('{"root":', encoding="utf-8")
    result = run_module("validate", str(path))
    assert result.returncode == 2
    assert "INVALID:" in result.stdout
    assert "ERROR grammar_load_failed" in result.stdout
    assert "Traceback" not in result.stdout
    assert result.stderr == ""


def test_validate_fails_on_semantic_duplicate() -> None:
    """A parseable semantic error returns nonzero structured diagnostics."""
    path = FIXTURES / "duplicate_node_ids.json"
    result = run_module("validate", str(path))
    assert result.returncode == 1
    assert "ERROR duplicate_node_id" in result.stdout
    assert "path=root.children[1].node" in result.stdout
    assert "Traceback" not in result.stdout


def test_validate_accepts_valid_grammar_above_summary_expansion_limit() -> None:
    """Expansion summary limits do not make a grammar semantically invalid."""
    path = FIXTURES / "large_nested_repeats.json"
    result = run_module("validate", str(path))
    assert result.returncode == 0
    assert f"VALID: {path}" in result.stdout
    assert "WARNING summary_expansion_limit" in result.stdout
    assert "Traceback" not in result.stdout


def test_inspect_prints_tree_and_summary() -> None:
    """Inspect prints deterministic tree content and statistics."""
    path = FIXTURES / "valid_nested_urban.json"
    result = run_module("inspect", str(path))
    assert result.returncode == 0
    assert "Scene nested_urban_example [schema=0.1, units=normalized]" in result.stdout
    assert "root: Split id=depth_zones axis=z" in result.stdout
    assert "Summary" in result.stdout
    assert "expanded_terminals=8" in result.stdout
    assert result.stderr == ""


def test_inspect_fails_cleanly_on_invalid_grammar() -> None:
    """Inspect refuses a grammar with semantic errors."""
    path = FIXTURES / "duplicate_node_ids.json"
    result = run_module("inspect", str(path))
    assert result.returncode == 1
    assert "INVALID:" in result.stdout
    assert "duplicate_node_id" in result.stdout
    assert "Traceback" not in result.stdout


def test_help_lists_validation_and_inspection_commands() -> None:
    """Existing help now documents both new commands."""
    result = run_module("--help")
    assert result.returncode == 0
    assert "validate" in result.stdout
    assert "inspect" in result.stdout
