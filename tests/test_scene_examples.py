"""Canonical scene grammar, execution, export, render, and edit tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import trimesh

from scene_grammar_kit.editing import apply_edit
from scene_grammar_kit.editing.diff import build_node_index
from scene_grammar_kit.geometry import execute_grammar, export_scene
from scene_grammar_kit.grammar import (
    RepeatNode,
    SplitNode,
    TerminalNode,
    grammar_to_canonical_json,
    load_grammar,
    summarize_grammar,
    validate_grammar,
)
from scene_grammar_kit.rendering import RenderConfig, render_executed_scene
from scene_grammar_kit.scene_examples import (
    load_scene_manifest,
    operation_from_edit_spec,
)

SCENES = Path(__file__).resolve().parents[1] / "examples" / "scene_examples"
SCENE_KEYS = ("urban_street", "repeated_facade", "indoor_corridor")


def paths(scene_key: str) -> tuple[Path, Path]:
    root = SCENES / scene_key
    return root / "grammar.json", root / "scene_manifest.json"


@pytest.mark.parametrize("scene_key", SCENE_KEYS)
def test_scene_grammar_is_valid_small_executable_and_expected(
    scene_key: str,
) -> None:
    grammar_path, manifest_path = paths(scene_key)
    grammar = load_grammar(grammar_path)
    manifest = load_scene_manifest(manifest_path)
    report = validate_grammar(grammar)
    summary = summarize_grammar(grammar)
    index = build_node_index(grammar)
    semantic = {
        record.node.semantic_class
        for record in index.values()
        if isinstance(record.node, TerminalNode)
    }
    assert report.is_valid
    assert set(manifest.expected_split_node_ids) == {
        node_id
        for node_id, record in index.items()
        if isinstance(record.node, SplitNode)
    }
    assert set(manifest.expected_repeat_node_ids) == {
        node_id
        for node_id, record in index.items()
        if isinstance(record.node, RepeatNode)
    }
    assert set(manifest.expected_semantic_classes) == semantic
    assert summary.total_node_count <= 30
    assert summary.maximum_depth <= 7
    assert summary.canonical_byte_size < 10_000
    scene = execute_grammar(grammar)
    assert scene.report.primitive_count <= 50


@pytest.mark.parametrize("scene_key", SCENE_KEYS)
def test_scene_exports_reopenable_glb_and_renders_required_views(
    scene_key: str,
    tmp_path: Path,
) -> None:
    grammar_path, manifest_path = paths(scene_key)
    grammar = load_grammar(grammar_path)
    manifest = load_scene_manifest(manifest_path)
    scene = execute_grammar(grammar)
    exported = export_scene(
        scene,
        tmp_path / f"{scene_key}.glb",
        create_parents=True,
    )
    reopened = trimesh.load(exported.glb_path, force="scene")
    assert isinstance(reopened, trimesh.Scene)
    assert len(reopened.geometry) == scene.report.primitive_count
    for camera in ("isometric", manifest.primary_camera.value):
        rendered = render_executed_scene(
            scene,
            RenderConfig(
                width=480,
                height=320,
                camera_preset=camera,
                supersampling=1,
            ),
        )
        assert rendered.image.size == (480, 320)
        assert rendered.report.primitive_count_considered == len(scene.primitives)


@pytest.mark.parametrize(
    ("scene_key", "edit_key"),
    [
        ("urban_street", "road_wider"),
        ("urban_street", "more_parked_cars"),
        ("repeated_facade", "more_windows"),
        ("indoor_corridor", "corridor_wider"),
    ],
)
def test_required_edit_changes_only_target_and_renders_deterministically(
    scene_key: str,
    edit_key: str,
) -> None:
    grammar_path, manifest_path = paths(scene_key)
    grammar = load_grammar(grammar_path)
    manifest = load_scene_manifest(manifest_path)
    spec = next(item for item in manifest.canonical_edits if item.edit_key == edit_key)
    operation = operation_from_edit_spec(spec)
    before_bytes = grammar_to_canonical_json(grammar)
    result = apply_edit(grammar, operation)
    assert grammar_to_canonical_json(grammar) == before_bytes
    assert validate_grammar(result.edited_grammar).is_valid
    assert result.edited_execution is not None
    assert result.original_grammar.root_bounds == result.edited_grammar.root_bounds
    diff = result.report.symbolic_diff
    assert len(diff.directly_modified_node_ids) == 1
    assert diff.added_node_ids == ()
    assert diff.removed_node_ids == ()
    assert diff.node_ids_before == diff.node_ids_after
    config = RenderConfig(
        width=480,
        height=320,
        camera_preset=spec.recommended_render_camera,
        supersampling=1,
    )
    assert result.original_execution is not None
    before = render_executed_scene(result.original_execution, config)
    first_after = render_executed_scene(result.edited_execution, config)
    second_after = render_executed_scene(result.edited_execution, config)
    assert before.image.size == first_after.image.size
    assert before.image.tobytes() != first_after.image.tobytes()
    assert first_after.image.tobytes() == second_after.image.tobytes()


def test_urban_edit_values_are_explicit() -> None:
    grammar_path, manifest_path = paths("urban_street")
    grammar = load_grammar(grammar_path)
    manifest = load_scene_manifest(manifest_path)
    road = apply_edit(
        grammar,
        operation_from_edit_spec(manifest.canonical_edits[0]),
    )
    cars = apply_edit(
        grammar,
        operation_from_edit_spec(manifest.canonical_edits[1]),
    )
    road_realization = road.report.realizations[0]
    car_realization = cars.report.realizations[0]
    assert road_realization.old_stored_weight == 6
    assert road_realization.realized_new_stored_weight == 10
    assert road_realization.old_normalized_fraction == pytest.approx(0.6)
    assert road_realization.new_normalized_fraction == pytest.approx(10 / 14)
    assert road.report.geometry_diff is not None
    assert road.report.geometry_diff.primitive_count_before == (
        road.report.geometry_diff.primitive_count_after
    )
    assert car_realization.old_count == 5
    assert car_realization.realized_count == 7


def test_facade_and_corridor_edit_values_are_explicit() -> None:
    facade_grammar, facade_manifest = paths("repeated_facade")
    corridor_grammar, corridor_manifest = paths("indoor_corridor")
    facade = apply_edit(
        load_grammar(facade_grammar),
        operation_from_edit_spec(
            load_scene_manifest(facade_manifest).canonical_edits[0]
        ),
    )
    corridor = apply_edit(
        load_grammar(corridor_grammar),
        operation_from_edit_spec(
            load_scene_manifest(corridor_manifest).canonical_edits[0]
        ),
    )
    assert facade.report.realizations[0].old_count == 5
    assert facade.report.realizations[0].realized_count == 8
    assert corridor.report.realizations[0].old_stored_weight == 6
    assert corridor.report.realizations[0].realized_new_stored_weight == 10
