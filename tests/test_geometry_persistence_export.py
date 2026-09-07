"""Canonical primitive persistence and headless GLB export tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import trimesh

from scene_grammar_kit.geometry import (
    GeometryFileExistsError,
    GeometryWriteError,
    execute_grammar,
    executed_scene_to_canonical_json,
    execution_report_to_canonical_json,
    export_scene,
    save_executed_scene,
    save_execution_report,
)
from scene_grammar_kit.grammar import load_grammar

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"


def test_canonical_scene_json_is_compact_finite_and_environment_free() -> None:
    """Primitive JSON obeys the frozen canonical representation rules."""
    scene = execute_grammar(load_grammar(FIXTURES / "valid_nested_urban.json"))
    text = executed_scene_to_canonical_json(scene)
    data = json.loads(text)
    assert text == executed_scene_to_canonical_json(scene)
    assert not text.endswith("\n")
    assert ": " not in text
    assert data["execution_policy_version"] == "0.1"
    assert "report" not in data
    assert "timestamp" not in text.lower()
    assert str(FIXTURES.resolve()) not in text


def test_primitive_and_report_save_as_valid_canonical_json(tmp_path: Path) -> None:
    """Explicit parent creation writes exact UTF-8 canonical bytes."""
    scene = execute_grammar(load_grammar(FIXTURES / "terminal_types.json"))
    primitive_path = save_executed_scene(
        scene,
        tmp_path / "nested" / "primitives.json",
        create_parents=True,
    )
    report_path = save_execution_report(
        scene.report,
        tmp_path / "nested" / "execution_report.json",
    )
    assert json.loads(primitive_path.read_text(encoding="utf-8"))["scene_id"]
    assert json.loads(report_path.read_text(encoding="utf-8"))["success"] is True
    assert primitive_path.read_bytes() == executed_scene_to_canonical_json(
        scene
    ).encode("utf-8")
    assert report_path.read_bytes() == execution_report_to_canonical_json(
        scene.report
    ).encode("utf-8")


def test_persistence_requires_explicit_parents_and_overwrite(tmp_path: Path) -> None:
    """Missing parents and existing targets are preserved by default."""
    scene = execute_grammar(load_grammar(FIXTURES / "valid_terminal.json"))
    missing_parent = tmp_path / "missing" / "primitives.json"
    with pytest.raises(GeometryWriteError, match="create_parents=True"):
        save_executed_scene(scene, missing_parent)
    existing = tmp_path / "primitives.json"
    existing.write_text("sentinel", encoding="utf-8")
    with pytest.raises(GeometryFileExistsError, match="overwrite=True"):
        save_executed_scene(scene, existing)
    assert existing.read_text(encoding="utf-8") == "sentinel"
    save_executed_scene(scene, existing, overwrite=True)
    assert existing.read_text(encoding="utf-8") != "sentinel"


def test_glb_export_reopens_and_preserves_semantic_sidecar(tmp_path: Path) -> None:
    """Headless GLB contains renderables while sidecar retains their labels."""
    scene = execute_grammar(load_grammar(FIXTURES / "terminal_types.json"))
    result = export_scene(
        scene,
        tmp_path / "nested" / "scene.glb",
        create_parents=True,
    )
    assert result.glb_path.stat().st_size > 0
    reopened = trimesh.load(result.glb_path, force="scene")
    assert len(reopened.geometry) == 2
    index = json.loads(result.semantic_index_path.read_text(encoding="utf-8"))
    assert [item["semantic_class"] for item in index["primitives"]] == [
        "building",
        "ground",
    ]
    assert all(item["geometry"] != "empty" for item in index["primitives"])


def test_empty_scene_exports_valid_deterministic_empty_glb(tmp_path: Path) -> None:
    """Empty terminals produce a reopenable GLB scene with zero geometries."""
    scene = execute_grammar(load_grammar(FIXTURES / "valid_empty_scene.json"))
    first = export_scene(
        scene,
        tmp_path / "first" / "scene.glb",
        create_parents=True,
    )
    second = export_scene(
        scene,
        tmp_path / "second" / "scene.glb",
        create_parents=True,
    )
    reopened = trimesh.load(first.glb_path, force="scene")
    assert len(reopened.geometry) == 0
    assert first.glb_sha256 == second.glb_sha256
    assert first.semantic_index_path.read_bytes() == (
        second.semantic_index_path.read_bytes()
    )


def test_export_does_not_overwrite_and_is_byte_deterministic(tmp_path: Path) -> None:
    """Repeated fresh exports match while an existing target is protected."""
    scene = execute_grammar(load_grammar(FIXTURES / "valid_nested_urban.json"))
    first = export_scene(
        scene,
        tmp_path / "first" / "scene.glb",
        create_parents=True,
    )
    second = export_scene(
        scene,
        tmp_path / "second" / "scene.glb",
        create_parents=True,
    )
    assert first.glb_path.read_bytes() == second.glb_path.read_bytes()
    assert first.glb_sha256 == hashlib.sha256(first.glb_path.read_bytes()).hexdigest()
    with pytest.raises(GeometryFileExistsError, match="overwrite=True"):
        export_scene(scene, first.glb_path)
