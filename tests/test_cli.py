"""Tests for the CPU-safe command-line foundation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scene_grammar_kit.cli import main

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run_module(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the installed module from the repository root."""
    return subprocess.run(
        [sys.executable, "-m", "scene_grammar_kit", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_help() -> None:
    """CLI help is available through the module entry point."""
    result = run_module("--help")
    assert result.returncode == 0
    assert "usage: scene-grammar" in result.stdout
    assert "doctor" in result.stdout


def test_version_command(capsys: object) -> None:
    """The directly testable version command reports both versions."""
    assert main(["version"]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "SceneGrammarKit 0.1.0" in output
    assert f"Python {sys.version.split()[0]}" in output


def test_doctor_command() -> None:
    """Doctor succeeds from the repository root without requiring a GPU."""
    result = run_module("doctor")
    assert result.returncode == 0
    assert "SceneGrammarKit version: 0.1.0" in result.stdout
    assert "Evaluation protocol: PASS" in result.stdout
    assert "Temporary directory writable: PASS" in result.stdout
    assert "Overall status: PASS" in result.stdout
