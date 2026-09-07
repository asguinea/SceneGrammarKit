"""CLI integration tests for complete canonical scene-example builds."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENES = REPOSITORY_ROOT / "examples" / "scene_examples"


def run_module(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scene_grammar_kit", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "scene_key",
    ("urban_street", "repeated_facade", "indoor_corridor"),
)
def test_each_scene_builds_through_cli(
    scene_key: str,
    tmp_path: Path,
) -> None:
    output = tmp_path / scene_key
    completed = run_module(
        "build-scene-example",
        str(SCENES / scene_key / "scene_manifest.json"),
        "--out",
        str(output),
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert f"SCENE EXAMPLE BUILT: {scene_key}" in completed.stdout
    assert (output / "build_report.json").is_file()


def test_invalid_manifest_fails_cleanly(tmp_path: Path) -> None:
    manifest = tmp_path / "invalid.json"
    manifest.write_text('{"manifest_version":', encoding="utf-8")
    completed = run_module(
        "build-scene-example",
        str(manifest),
        "--out",
        str(tmp_path / "output"),
    )
    assert completed.returncode == 2
    assert "SCENE EXAMPLE BUILD FAILED" in completed.stdout
    assert "Traceback" not in completed.stdout + completed.stderr


def copied_manifest_scene(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "scene"
    root.mkdir()
    source_manifest = SCENES / "repeated_facade" / "scene_manifest.json"
    data = json.loads(source_manifest.read_text("utf-8"))
    return root, data


def test_invalid_grammar_fails_cleanly(tmp_path: Path) -> None:
    root, data = copied_manifest_scene(tmp_path)
    (root / "grammar.json").write_text('{"root":', encoding="utf-8")
    manifest = root / "scene_manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    completed = run_module(
        "build-scene-example",
        str(manifest),
        "--out",
        str(tmp_path / "output"),
    )
    assert completed.returncode == 2
    assert "Traceback" not in completed.stdout + completed.stderr


def test_invalid_edit_fails_cleanly_without_success_report(
    tmp_path: Path,
) -> None:
    root, data = copied_manifest_scene(tmp_path)
    source_grammar = SCENES / "repeated_facade" / "grammar.json"
    (root / "grammar.json").write_bytes(source_grammar.read_bytes())
    data["canonical_edits"][0]["parameters"]["repeat_node_id"] = "missing"
    manifest = root / "scene_manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "output"
    completed = run_module(
        "build-scene-example",
        str(manifest),
        "--out",
        str(output),
    )
    assert completed.returncode == 2
    assert "Traceback" not in completed.stdout + completed.stderr
    assert not (output / "build_report.json").exists()


def test_nonempty_output_protection_and_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "note.txt"
    sentinel.write_text("keep", encoding="utf-8")
    arguments = (
        "build-scene-example",
        str(SCENES / "repeated_facade" / "scene_manifest.json"),
        "--out",
        str(output),
    )
    refused = run_module(*arguments)
    allowed = run_module(*arguments, "--overwrite")
    assert refused.returncode == 2
    assert "not empty" in refused.stdout
    assert allowed.returncode == 0
    assert sentinel.read_text("utf-8") == "keep"


def test_help_and_existing_commands_remain_functional() -> None:
    help_result = run_module("--help")
    validate_result = run_module(
        "validate",
        str(SCENES / "urban_street" / "grammar.json"),
    )
    version_result = run_module("version")
    assert help_result.returncode == 0
    assert "build-scene-example" in help_result.stdout
    assert validate_result.returncode == 0
    assert version_result.returncode == 0
