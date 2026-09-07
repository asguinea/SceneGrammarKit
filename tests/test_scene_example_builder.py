"""Deterministic complete scene-example builder tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from scene_grammar_kit.grammar import (
    grammar_to_canonical_json,
    grammar_tree_to_text,
    load_grammar,
)
from scene_grammar_kit.scene_examples import (
    SceneExampleBuildError,
    SceneExampleFileExistsError,
    build_report_to_canonical_json,
    build_scene_example,
)

SCENES = Path(__file__).resolve().parents[1] / "examples" / "scene_examples"
URBAN_MANIFEST = SCENES / "urban_street" / "scene_manifest.json"


def expected_urban_paths() -> set[str]:
    paths = {
        "build_report.json",
        "source/grammar.json",
        "source/grammar_tree.txt",
        "source/manifest.json",
        "original/primitives.json",
        "original/execution_report.json",
        "original/scene.glb",
        "original/semantic_index.json",
        "original/primary.png",
        "original/primary.render.json",
        "original/secondary.png",
        "original/secondary.render.json",
    }
    for edit_key in ("road_wider", "more_parked_cars"):
        paths.update(
            {
                f"edits/{edit_key}/grammar_before.json",
                f"edits/{edit_key}/grammar_after.json",
                f"edits/{edit_key}/edit_report.json",
                f"edits/{edit_key}/primitives_after.json",
                f"edits/{edit_key}/execution_report_after.json",
                f"edits/{edit_key}/scene_after.glb",
                f"edits/{edit_key}/semantic_index_after.json",
                f"edits/{edit_key}/before.png",
                f"edits/{edit_key}/before.render.json",
                f"edits/{edit_key}/after.png",
                f"edits/{edit_key}/after.render.json",
            }
        )
    return paths


def test_builder_writes_complete_canonical_artifact_tree(tmp_path: Path) -> None:
    output = tmp_path / "urban"
    result = build_scene_example(URBAN_MANIFEST, output)
    actual = {
        item.relative_to(output).as_posix()
        for item in output.rglob("*")
        if item.is_file()
    }
    assert actual == expected_urban_paths()
    assert set(result.report.artifact_paths) == actual
    source_grammar = load_grammar(output / "source/grammar.json")
    repository_grammar = load_grammar(SCENES / "urban_street" / "grammar.json")
    assert grammar_to_canonical_json(source_grammar) == (
        grammar_to_canonical_json(repository_grammar)
    )
    assert (output / "source/grammar_tree.txt").read_text("utf-8") == (
        grammar_tree_to_text(repository_grammar)
    )
    report_text = (output / "build_report.json").read_text("utf-8")
    assert report_text == build_report_to_canonical_json(result.report)
    assert str(tmp_path) not in report_text
    assert all(not Path(path).is_absolute() for path in result.report.artifact_paths)


def test_builder_protects_nonempty_and_explicitly_overwrites(
    tmp_path: Path,
) -> None:
    output = tmp_path / "urban"
    output.mkdir()
    sentinel = output / "note.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(SceneExampleFileExistsError, match="not empty"):
        build_scene_example(URBAN_MANIFEST, output)
    assert sentinel.read_text("utf-8") == "keep"
    build_scene_example(URBAN_MANIFEST, output, overwrite=True)
    assert sentinel.read_text("utf-8") == "keep"


def test_failed_build_has_no_success_report(tmp_path: Path) -> None:
    scene = tmp_path / "scene"
    scene.mkdir()
    grammar = SCENES / "urban_street" / "grammar.json"
    (scene / "grammar.json").write_bytes(grammar.read_bytes())
    data = json.loads(URBAN_MANIFEST.read_text("utf-8"))
    data["canonical_edits"][0]["parameters"]["split_node_id"] = "missing"
    manifest = scene / "scene_manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "failed"
    with pytest.raises(SceneExampleBuildError, match="missing"):
        build_scene_example(manifest, output)
    assert not (output / "build_report.json").exists()


def test_repeated_builds_have_identical_json_glb_and_png_pixels(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = SCENES / "repeated_facade" / "scene_manifest.json"
    build_scene_example(manifest, first)
    build_scene_example(manifest, second)
    for relative in (
        "source/grammar.json",
        "source/manifest.json",
        "build_report.json",
        "original/primitives.json",
        "original/execution_report.json",
        "edits/more_windows/edit_report.json",
        "original/primary.render.json",
        "edits/more_windows/after.render.json",
        "original/scene.glb",
        "edits/more_windows/scene_after.glb",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
    for relative in (
        "original/primary.png",
        "original/secondary.png",
        "edits/more_windows/before.png",
        "edits/more_windows/after.png",
    ):
        with (
            Image.open(first / relative) as left,
            Image.open(second / relative) as right,
        ):
            assert left.tobytes() == right.tobytes()
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
