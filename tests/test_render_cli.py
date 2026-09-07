"""Semantic render command integration tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

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


def test_render_succeeds_and_writes_png_and_report(tmp_path: Path) -> None:
    """Valid grammar rendering returns zero with both required artifacts."""
    output = tmp_path / "nested" / "scene.png"
    result = run_module(
        "render",
        str(FIXTURES / "valid_nested_urban.json"),
        "--output",
        str(output),
        "--width",
        "480",
        "--height",
        "320",
    )
    assert result.returncode == 0
    assert output.is_file()
    report_path = output.with_suffix(".render.json")
    assert report_path.is_file()
    with Image.open(output) as image:
        assert image.size == (480, 320)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["success"] is True
    assert report["camera_preset"] == "isometric"
    assert "size=480x320" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("camera", ["isometric", "front", "top"])
def test_render_all_camera_presets(camera: str, tmp_path: Path) -> None:
    """Every required preset works through the public CLI."""
    output = tmp_path / f"{camera}.png"
    result = run_module(
        "render",
        str(FIXTURES / "valid_nested_urban.json"),
        "--output",
        str(output),
        "--camera",
        camera,
        "--width",
        "360",
        "--height",
        "240",
        "--supersampling",
        "1",
    )
    assert result.returncode == 0
    assert f"camera={camera}" in result.stdout
    with Image.open(output) as image:
        assert image.size == (360, 240)


def test_render_fails_cleanly_on_malformed_json(tmp_path: Path) -> None:
    """Malformed input produces no files and no ordinary traceback."""
    grammar = tmp_path / "bad.json"
    grammar.write_text('{"root":', encoding="utf-8")
    output = tmp_path / "scene.png"
    result = run_module("render", str(grammar), "--output", str(output))
    assert result.returncode == 2
    assert "RENDER FAILED" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not output.exists()


def test_render_fails_cleanly_on_semantic_invalidity(tmp_path: Path) -> None:
    """Duplicate symbolic identifiers fail before rendering or persistence."""
    output = tmp_path / "scene.png"
    result = run_module(
        "render",
        str(FIXTURES / "duplicate_node_ids.json"),
        "--output",
        str(output),
    )
    assert result.returncode == 2
    assert "duplicate_node_id" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not output.exists()


def test_render_fails_cleanly_on_repeat_fit_error(tmp_path: Path) -> None:
    """Impossible repeat geometry produces a concise domain failure."""
    output = tmp_path / "scene.png"
    result = run_module(
        "render",
        str(FIXTURES / "repeat_cannot_fit.json"),
        "--output",
        str(output),
    )
    assert result.returncode == 2
    assert "Repeat does not fit" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not output.exists()


def test_render_protects_existing_output_and_supports_overwrite(
    tmp_path: Path,
) -> None:
    """The CLI checks PNG and companion report before replacing either."""
    output = tmp_path / "scene.png"
    output.write_text("sentinel", encoding="utf-8")
    arguments = (
        "render",
        str(FIXTURES / "valid_terminal.json"),
        "--output",
        str(output),
        "--width",
        "320",
        "--height",
        "240",
    )
    refused = run_module(*arguments)
    assert refused.returncode == 2
    assert "--overwrite" in refused.stdout
    assert output.read_text(encoding="utf-8") == "sentinel"
    replaced = run_module(*arguments, "--overwrite")
    assert replaced.returncode == 0
    with Image.open(output) as image:
        assert image.format == "PNG"


def test_render_toggles_and_requested_dimensions_are_honored(
    tmp_path: Path,
) -> None:
    """CLI exposes bounds, ground, edge, and transparency configuration."""
    output = tmp_path / "configured.png"
    result = run_module(
        "render",
        str(FIXTURES / "valid_terminal.json"),
        "--output",
        str(output),
        "--width",
        "512",
        "--height",
        "256",
        "--show-bounds",
        "--no-ground",
        "--no-edges",
        "--transparent",
        "--supersampling",
        "1",
    )
    assert result.returncode == 0
    with Image.open(output) as image:
        assert image.size == (512, 256)
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0


def test_help_lists_render_and_existing_execute_still_works(
    tmp_path: Path,
) -> None:
    """The new command does not regress help or Batch 1.4 execution."""
    help_result = run_module("--help")
    execute_result = run_module(
        "execute",
        str(FIXTURES / "valid_terminal.json"),
        "--out",
        str(tmp_path / "execute"),
    )
    assert help_result.returncode == 0
    assert "render" in help_result.stdout
    assert execute_result.returncode == 0
