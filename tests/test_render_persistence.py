"""Deterministic PNG and canonical render-report persistence tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from scene_grammar_kit.geometry import execute_grammar
from scene_grammar_kit.grammar import load_grammar
from scene_grammar_kit.rendering import (
    RenderConfig,
    RenderFileExistsError,
    RenderResult,
    RenderWriteError,
    render_executed_scene,
    render_report_to_canonical_json,
    save_render,
    save_render_report,
)

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"


def rendered_result() -> RenderResult:
    """Return a small deterministic render for persistence tests."""
    scene = execute_grammar(load_grammar(FIXTURES / "valid_nested_urban.json"))
    return render_executed_scene(
        scene,
        RenderConfig(width=400, height=300, supersampling=1),
    )


def test_saved_png_is_valid_reopenable_exact_size_and_metadata_free(
    tmp_path: Path,
) -> None:
    """PNG persistence embeds no variable timestamps or path metadata."""
    result = rendered_result()
    output = save_render(
        result,
        tmp_path / "nested" / "scene.png",
        create_parents=True,
    )
    with Image.open(output) as reopened:
        reopened.load()
        assert reopened.size == (400, 300)
        assert reopened.mode == "RGBA"
        assert reopened.info == {}


def test_png_parent_creation_and_overwrite_are_explicit(tmp_path: Path) -> None:
    """Missing parents and existing targets are protected by default."""
    result = rendered_result()
    target = tmp_path / "missing" / "scene.png"
    with pytest.raises(RenderWriteError, match="create_parents=True"):
        save_render(result, target)
    target.parent.mkdir()
    target.write_text("sentinel", encoding="utf-8")
    with pytest.raises(RenderFileExistsError, match="overwrite=True"):
        save_render(result, target)
    assert target.read_text(encoding="utf-8") == "sentinel"
    save_render(result, target, overwrite=True)
    with Image.open(target) as reopened:
        assert reopened.format == "PNG"


def test_render_report_is_canonical_valid_json(tmp_path: Path) -> None:
    """Report JSON is compact, ordered, path-free, and byte-exact on disk."""
    result = rendered_result()
    report = result.report
    text = render_report_to_canonical_json(report)
    output = save_render_report(
        report,
        tmp_path / "nested" / "scene.render.json",
        create_parents=True,
    )
    data = json.loads(text)
    assert data["renderer_policy_version"] == "0.1"
    assert tuple(data["palette_mapping"]) == tuple(sorted(data["palette_mapping"]))
    assert not text.endswith("\n")
    assert "timestamp" not in text.lower()
    assert str(tmp_path) not in text
    assert output.read_bytes() == text.encode("utf-8")


def test_png_and_report_bytes_are_deterministic(tmp_path: Path) -> None:
    """Fresh saves of repeated renders have matching bytes and SHA-256."""
    first = rendered_result()
    second = rendered_result()
    first_png = save_render(
        first,
        tmp_path / "first" / "scene.png",
        create_parents=True,
    )
    second_png = save_render(
        second,
        tmp_path / "second" / "scene.png",
        create_parents=True,
    )
    first_report = save_render_report(
        first.report,
        tmp_path / "first" / "scene.render.json",
    )
    second_report = save_render_report(
        second.report,
        tmp_path / "second" / "scene.render.json",
    )
    assert first.image.tobytes() == second.image.tobytes()
    assert first_png.read_bytes() == second_png.read_bytes()
    assert first_report.read_bytes() == second_report.read_bytes()
    assert (
        hashlib.sha256(first_png.read_bytes()).digest()
        == hashlib.sha256(second_png.read_bytes()).digest()
    )


def test_report_does_not_silently_overwrite(tmp_path: Path) -> None:
    """Canonical report persistence preserves an existing file."""
    result = rendered_result()
    target = tmp_path / "scene.render.json"
    target.write_text("sentinel", encoding="utf-8")
    with pytest.raises(RenderFileExistsError):
        save_render_report(result.report, target)
    assert target.read_text(encoding="utf-8") == "sentinel"
