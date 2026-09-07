"""Integrated policy tests for Batch 2.6 assisted construction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from scene_grammar_kit.assisted import (
    CONSTRUCTOR_POLICY_VERSION,
    ConstructionStageOutcome,
    PrimaryGrammarType,
    construct_assisted_scene,
    load_annotation,
    load_construction_config,
    save_annotation,
)
from scene_grammar_kit.grammar import (
    RepeatNode,
    SplitNode,
    load_grammar,
    validate_grammar,
)

VALID = Path(__file__).parent / "fixtures" / "assisted" / "valid"
ANNOTATION = VALID / "urban_minimal.annotation.json"
CONFIG = VALID / "urban_minimal.construction.json"


@pytest.fixture(scope="module")
def urban_bundle(tmp_path_factory):
    output = tmp_path_factory.mktemp("constructor") / "urban"
    result = construct_assisted_scene(
        ANNOTATION,
        CONFIG,
        output,
        render_width=320,
        render_height=200,
    )
    return result


def _walk(node):
    yield node
    if isinstance(node, SplitNode):
        for child in node.children:
            yield from _walk(child.node)
    elif isinstance(node, RepeatNode):
        yield from _walk(node.element)


def test_constructor_policy_version_is_independent() -> None:
    assert CONSTRUCTOR_POLICY_VERSION == "0.1"


def test_canonical_urban_constructor_succeeds(urban_bundle) -> None:
    report = urban_bundle.report
    assert report.success
    assert report.scene_id == "urban_assisted_minimal"
    assert len(urban_bundle.lifting_result.scene.observations) == 9
    assert report.supplied_repeat_group_count == 1
    assert report.accepted_repeat_group_count == 1
    assert report.fallback_repeat_group_count == 0
    assert report.primary_grammar_type is PrimaryGrammarType.REPEAT
    assert (
        urban_bundle.primary_grammar
        == urban_bundle.repeat_induction_result.repeat_grammar
    )


def test_all_stage_statuses_are_complete_and_ordered(urban_bundle) -> None:
    expected = (
        "annotation_validation",
        "config_validation",
        "compatibility_validation",
        "image_verification",
        "annotation_review",
        "lifting",
        "split_induction",
        "repeat_induction",
        "grammar_validation",
        "execution",
        "export",
        "rendering",
        "default_edit",
        "persistence",
    )
    statuses = urban_bundle.report.stage_statuses
    assert tuple(item.stage_name for item in statuses) == expected
    assert all(item.status is ConstructionStageOutcome.PASS for item in statuses)


def test_expected_directory_tree_and_grammars_exist(urban_bundle) -> None:
    root = urban_bundle.output_directory
    expected_directories = {
        "input",
        "review",
        "lifting",
        "split_only",
        "repeat",
        "primary",
        "edit",
    }
    assert expected_directories.issubset(
        {item.name for item in root.iterdir() if item.is_dir()}
    )
    for relative in (
        "split_only/grammar.json",
        "repeat/grammar.json",
        "primary/grammar.json",
        "edit/grammar_after.json",
    ):
        grammar = load_grammar(root / relative)
        assert validate_grammar(grammar).is_valid


def test_source_image_is_copied_byte_for_byte(urban_bundle) -> None:
    annotation = urban_bundle.annotation
    source = ANNOTATION.parent / annotation.source_image.image_path
    copied = urban_bundle.output_directory / "input" / "source_image.png"
    assert source.read_bytes() == copied.read_bytes()
    digest = hashlib.sha256(copied.read_bytes()).hexdigest()
    assert digest == urban_bundle.report.source_image_sha256
    assert copied.suffix == source.suffix


def test_no_absolute_source_path_appears_in_canonical_reports(urban_bundle) -> None:
    root = urban_bundle.output_directory
    for relative in ("construction_report.json", "artifact_index.json"):
        text = (root / relative).read_text(encoding="utf-8")
        assert str(ANNOTATION.resolve()) not in text
        assert "C:\\" not in text


def test_both_outputs_execute_export_render_and_reopen(urban_bundle) -> None:
    import trimesh

    root = urban_bundle.output_directory
    for prefix in ("split_only", "repeat", "primary"):
        assert json.loads((root / prefix / "primitives.json").read_text())
        scene = trimesh.load(root / prefix / "scene.glb", force="scene")
        assert len(scene.geometry) > 0
        with Image.open(root / prefix / "render.png") as image:
            image.load()
            assert image.size == (320, 200)
        render_report = json.loads(
            (root / prefix / "render.json").read_text(encoding="utf-8")
        )
        grammar_bytes = (root / prefix / "grammar.json").read_bytes()
        assert render_report["executed_scene_grammar_sha256"] == (
            hashlib.sha256(grammar_bytes).hexdigest()
        )


def test_primary_artifacts_are_exact_repeat_copies(urban_bundle) -> None:
    root = urban_bundle.output_directory
    for name in (
        "grammar.json",
        "grammar_tree.txt",
        "primitives.json",
        "execution_report.json",
        "scene.glb",
        "semantic_index.json",
        "render.png",
        "render.json",
    ):
        assert (root / "primary" / name).read_bytes() == (
            root / "repeat" / name
        ).read_bytes()


def test_default_edit_is_procedural_repeat_count_variation(urban_bundle) -> None:
    decision = urban_bundle.report.edit_decision
    assert decision.applied
    assert decision.operation_type == "set_repeat_count"
    assert decision.requested_value == "4"
    assert decision.realized_value == "4"
    assert decision.procedural_variation
    assert "not claimed as observed or inferred" in decision.reason
    repeats = [
        item
        for item in _walk(urban_bundle.edited_grammar.root)
        if isinstance(item, RepeatNode)
    ]
    assert len(repeats) == 1
    assert repeats[0].count == 4


def test_edit_outputs_execute_reopen_and_change_pixels(urban_bundle) -> None:
    import trimesh

    root = urban_bundle.output_directory
    assert validate_grammar(load_grammar(root / "edit/grammar_after.json")).is_valid
    assert len(trimesh.load(root / "edit/scene_after.glb", force="scene").geometry) > 0
    before_report = json.loads(
        (root / "edit/before.render.json").read_text(encoding="utf-8")
    )
    after_report = json.loads(
        (root / "edit/after.render.json").read_text(encoding="utf-8")
    )
    assert before_report["camera_preset"] == after_report["camera_preset"]
    assert before_report["width"] == after_report["width"] == 320
    assert before_report["height"] == after_report["height"] == 200
    with Image.open(root / "edit/before.png") as before:
        with Image.open(root / "edit/after.png") as after:
            assert (
                ImageChops.difference(
                    before.convert("RGB"), after.convert("RGB")
                ).getbbox()
                is not None
            )


def test_disclosure_and_readme_are_explicit(urban_bundle) -> None:
    report = urban_bundle.report
    assert "repeat membership" in report.supplied_information
    assert "root bounds" in report.configured_information
    assert "repeat spacing" in report.derived_information
    assert "additional repeat members" in report.explicitly_not_inferred
    combined = (
        (urban_bundle.output_directory / "construction_report.txt").read_text()
        + (urban_bundle.output_directory / "README.md").read_text()
    ).lower()
    assert "annotation-assisted" in combined
    assert "automatic reconstruction" not in combined
    assert "procedural variation" in combined


def test_no_repeat_case_selects_split_only(tmp_path: Path) -> None:
    source = load_annotation(ANNOTATION)
    annotation = replace(
        source,
        instances=tuple(
            replace(item, repeat_group_id=None) for item in source.instances
        ),
        repeat_groups=(),
    )
    annotation_path = tmp_path / "annotation.json"
    save_annotation(annotation, annotation_path)
    result = construct_assisted_scene(
        annotation_path,
        CONFIG,
        tmp_path / "output",
        verify_image=False,
        verify_execution=False,
        apply_default_edit=False,
        render_width=160,
        render_height=120,
    )
    assert result.report.primary_grammar_type is PrimaryGrammarType.SPLIT_ONLY
    assert result.primary_grammar == result.split_induction_result.induced_grammar
    assert "no supplied repeat group was accepted" in (
        result.report.primary_selection_reason
    )


def test_skip_controls_are_explicit(tmp_path: Path) -> None:
    result = construct_assisted_scene(
        ANNOTATION,
        CONFIG,
        tmp_path / "output",
        verify_image=False,
        verify_execution=False,
        apply_default_edit=False,
        render_width=160,
        render_height=120,
    )
    statuses = {item.stage_name: item.status for item in result.report.stage_statuses}
    for name in (
        "image_verification",
        "annotation_review",
        "execution",
        "export",
        "rendering",
        "default_edit",
    ):
        assert statuses[name] is ConstructionStageOutcome.SKIP
    assert not (result.output_directory / "primary/render.png").exists()


def test_inputs_are_not_mutated(urban_bundle) -> None:
    assert load_annotation(ANNOTATION) == urban_bundle.annotation
    assert load_construction_config(CONFIG) == urban_bundle.construction_config


def test_existing_stage_apis_are_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scene_grammar_kit.assisted.constructor as constructor

    calls: dict[str, int] = {}
    for name in (
        "review_assisted_input",
        "lift_assisted_input",
        "induce_split_grammar",
        "induce_repeat_grammar",
    ):
        original = getattr(constructor, name)

        def wrapper(*args, _name=name, _original=original, **kwargs):
            calls[_name] = calls.get(_name, 0) + 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(constructor, name, wrapper)
    construct_assisted_scene(
        ANNOTATION,
        CONFIG,
        tmp_path / "output",
        render_width=180,
        render_height=120,
    )
    assert calls == {
        "review_assisted_input": 1,
        "lift_assisted_input": 1,
        "induce_split_grammar": 1,
        "induce_repeat_grammar": 1,
    }
