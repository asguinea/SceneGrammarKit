"""Transactional editing, diff, realization, and execution tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from scene_grammar_kit.editing import (
    EditChildNotFoundError,
    EditExecutionError,
    EditTargetNotFoundError,
    EditTargetTypeError,
    EditValidationError,
    InvalidEditValueError,
    SetRepeatCount,
    SetRepeatSpacing,
    SetSplitChildWeight,
    SubstituteTerminalClass,
    apply_edit,
    apply_edits,
)
from scene_grammar_kit.editing.diff import build_node_index, geometry_diff
from scene_grammar_kit.geometry import execute_grammar
from scene_grammar_kit.grammar import (
    RepeatNode,
    SplitNode,
    TerminalNode,
    grammar_to_canonical_json,
    load_grammar,
    validate_grammar,
)
from scene_grammar_kit.rendering import RenderConfig, render_executed_scene

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"
EDITABLE = FIXTURES / "editable_urban.json"


def editable():
    return load_grammar(EDITABLE)


def node(grammar, node_id: str):
    return build_node_index(grammar)[node_id].node


def test_split_weight_edit_is_immutable_local_and_executable() -> None:
    original = editable()
    original_bytes = grammar_to_canonical_json(original)
    original_index = build_node_index(original)
    result = apply_edit(
        original,
        SetSplitChildWeight("midground_layout", "road_region", 8),
    )
    edited_split = node(result.edited_grammar, "midground_layout")
    original_split = node(original, "midground_layout")
    assert isinstance(original_split, SplitNode)
    assert isinstance(edited_split, SplitNode)
    assert [item.weight for item in original_split.children] == [2.0, 5.0, 2.0]
    assert [item.weight for item in edited_split.children] == [2.0, 8.0, 2.0]
    assert [item.node.node_id for item in edited_split.children] == [
        "left_sidewalk",
        "road_region",
        "right_sidewalk",
    ]
    assert grammar_to_canonical_json(original) == original_bytes
    assert result.original_grammar is original
    assert result.edited_grammar is not original
    assert (
        build_node_index(result.edited_grammar)["background_facade"].node
        is original_index["background_facade"].node
    )
    assert validate_grammar(result.edited_grammar).is_valid
    assert result.edited_execution is not None
    realization = result.report.realizations[0]
    assert realization.old_normalized_fraction == pytest.approx(5 / 9)
    assert realization.new_normalized_fraction == pytest.approx(8 / 12)
    assert realization.normalized_fraction_delta == pytest.approx(1 / 9)
    assert realization.sibling_count == 2
    assert realization.sibling_weight_sum_before == 4
    assert realization.sibling_weight_sum_after == 4
    assert realization.direct_child_weight_sum_before == 9
    assert realization.direct_child_weight_sum_after == 12
    assert result.report.geometry_diff is not None
    assert result.report.geometry_diff.modified_primitive_count == 8
    assert result.report.geometry_diff.unchanged_primitive_count == 1


def test_road_region_executed_bounds_widen() -> None:
    result = apply_edit(
        editable(),
        SetSplitChildWeight("midground_layout", "road_region", 8),
    )
    assert result.original_execution is not None
    assert result.edited_execution is not None
    before = next(
        item
        for item in result.original_execution.primitives
        if item.source_terminal_id == "road_surface"
    )
    after = next(
        item
        for item in result.edited_execution.primitives
        if item.source_terminal_id == "road_surface"
    )
    before_width = before.bounds.maximum.x - before.bounds.minimum.x
    after_width = after.bounds.maximum.x - after.bounds.minimum.x
    assert after_width > before_width


@pytest.mark.parametrize(
    ("operation", "error"),
    [
        (SetRepeatCount("absent", 2), EditTargetNotFoundError),
        (SetRepeatCount("road_surface", 2), EditTargetTypeError),
        (
            SetSplitChildWeight("midground_layout", "parked_car", 2),
            EditChildNotFoundError,
        ),
        (
            SetSplitChildWeight("midground_layout", "absent", 2),
            EditChildNotFoundError,
        ),
    ],
)
def test_targeting_failures_are_explicit(operation, error) -> None:
    with pytest.raises(error):
        apply_edit(editable(), operation)


def test_duplicate_ids_fail_validation_before_targeting() -> None:
    invalid = load_grammar(FIXTURES / "duplicate_node_ids.json")
    with pytest.raises(EditValidationError, match="duplicate_node_id"):
        apply_edit(invalid, SubstituteTerminalClass("duplicate", "lamp_post"))


def test_failed_edit_preserves_original_bytes() -> None:
    original = editable()
    before = grammar_to_canonical_json(original)
    with pytest.raises(EditTargetNotFoundError):
        apply_edit(original, SetRepeatCount("absent", 3))
    assert grammar_to_canonical_json(original) == before


def test_noop_edit_is_rejected() -> None:
    with pytest.raises(InvalidEditValueError, match="must change"):
        apply_edit(editable(), SetRepeatCount("parked_cars", 4))


def test_repeat_count_preserves_structure_and_reports_expansion() -> None:
    original = editable()
    result = apply_edit(original, SetRepeatCount("parked_cars", 6))
    before = node(original, "parked_cars")
    after = node(result.edited_grammar, "parked_cars")
    assert isinstance(before, RepeatNode)
    assert isinstance(after, RepeatNode)
    assert after.count == 6
    assert after.axis == before.axis
    assert after.spacing == before.spacing
    assert after.element is before.element
    realization = result.report.realizations[0]
    assert realization.symbolic_terminal_count_in_element == 1
    assert realization.conceptual_terminal_count_in_element == 1
    assert realization.conceptual_expanded_terminal_count_before == 4
    assert realization.conceptual_expanded_terminal_count_after == 6
    assert realization.count_delta == 2
    geometry = result.report.geometry_diff
    assert geometry is not None
    assert geometry.primitive_count_before == 9
    assert geometry.primitive_count_after == 11
    assert geometry.added_primitive_count == 2
    assert geometry.modified_primitive_count == 4
    assert geometry.unchanged_primitive_count == 5


def test_repeat_count_primitive_limit_fails_cleanly() -> None:
    original = editable()
    before = grammar_to_canonical_json(original)
    with pytest.raises(EditExecutionError, match="maximum_primitives=10"):
        apply_edit(
            original,
            SetRepeatCount("parked_cars", 20),
            maximum_primitives=10,
        )
    assert grammar_to_canonical_json(original) == before


def test_repeat_spacing_preserves_count_axis_and_element() -> None:
    original = editable()
    result = apply_edit(original, SetRepeatSpacing("parked_cars", 0.08))
    before = node(original, "parked_cars")
    after = node(result.edited_grammar, "parked_cars")
    assert isinstance(before, RepeatNode)
    assert isinstance(after, RepeatNode)
    assert after.spacing == 0.08
    assert after.count == before.count
    assert after.axis == before.axis
    assert after.element is before.element
    realization = result.report.realizations[0]
    assert realization.repeat_count == 4
    assert realization.parent_axis_occurrence_count == 1
    assert realization.execution_verified is True


def test_impossible_repeat_spacing_fails_transactionally() -> None:
    original = editable()
    before = grammar_to_canonical_json(original)
    with pytest.raises((EditValidationError, EditExecutionError), match="fit"):
        apply_edit(original, SetRepeatSpacing("parked_cars", 1.0))
    assert grammar_to_canonical_json(original) == before


def test_terminal_substitution_preserves_geometry_attributes_and_position() -> None:
    original = editable()
    result = apply_edit(
        original,
        SubstituteTerminalClass("street_tree", "lamp_post"),
    )
    before = node(original, "street_tree")
    after = node(result.edited_grammar, "street_tree")
    assert isinstance(before, TerminalNode)
    assert isinstance(after, TerminalNode)
    assert after.semantic_class == "lamp_post"
    assert after.geometry is before.geometry
    assert dict(after.attributes) == dict(before.attributes)
    assert after.attributes is not before.attributes
    with pytest.raises(TypeError):
        after.attributes["role"] = "changed"  # type: ignore[index]
    before_path = build_node_index(original)["street_tree"].path
    after_path = build_node_index(result.edited_grammar)["street_tree"].path
    assert before_path == after_path
    realization = result.report.realizations[0]
    assert realization.geometry_type_preserved is True
    assert realization.attributes_preserved is True
    geometry = result.report.geometry_diff
    assert geometry is not None
    assert geometry.modified_primitive_count == 1
    assert geometry.unchanged_primitive_count == 8


def test_terminal_substitution_changes_palette_and_pixels_deterministically() -> None:
    result = apply_edit(
        editable(),
        SubstituteTerminalClass("street_tree", "lamp_post"),
    )
    assert result.original_execution is not None
    assert result.edited_execution is not None
    config = RenderConfig(width=360, height=240, supersampling=1)
    before = render_executed_scene(result.original_execution, config)
    first_after = render_executed_scene(result.edited_execution, config)
    second_after = render_executed_scene(result.edited_execution, config)
    assert "tree" in before.report.palette_mapping
    assert "lamp_post" in first_after.report.palette_mapping
    assert before.image.tobytes() != first_after.image.tobytes()
    assert first_after.image.tobytes() == second_after.image.tobytes()


def test_atomic_sequence_succeeds_in_order_on_same_target() -> None:
    operations = (
        SetRepeatCount("parked_cars", 6),
        SetRepeatSpacing("parked_cars", 0.08),
    )
    result = apply_edits(editable(), operations)
    repeat = node(result.edited_grammar, "parked_cars")
    assert isinstance(repeat, RepeatNode)
    assert (repeat.count, repeat.spacing) == (6, 0.08)
    assert result.operations == operations
    assert result.report.operations == operations
    assert [item.operation_type for item in result.report.realizations] == [
        "set_repeat_count",
        "set_repeat_spacing",
    ]


def test_atomic_sequence_failure_returns_no_partial_result() -> None:
    original = editable()
    before = grammar_to_canonical_json(original)
    with pytest.raises(EditTargetNotFoundError):
        apply_edits(
            original,
            (
                SetRepeatCount("parked_cars", 6),
                SetRepeatSpacing("missing", 0.08),
            ),
        )
    assert grammar_to_canonical_json(original) == before


def test_empty_sequence_is_rejected() -> None:
    with pytest.raises(InvalidEditValueError, match="must not be empty"):
        apply_edits(editable(), ())


@pytest.mark.parametrize(
    ("operation", "modified"),
    [
        (
            SetSplitChildWeight("midground_layout", "road_region", 8),
            "midground_layout",
        ),
        (SetRepeatCount("parked_cars", 6), "parked_cars"),
        (SetRepeatSpacing("parked_cars", 0.08), "parked_cars"),
        (
            SubstituteTerminalClass("street_tree", "lamp_post"),
            "street_tree",
        ),
    ],
)
def test_symbolic_diff_is_local_complete_and_deterministic(
    operation, modified: str
) -> None:
    first = apply_edit(editable(), operation)
    second = apply_edit(editable(), operation)
    diff = first.report.symbolic_diff
    assert diff == second.report.symbolic_diff
    assert diff.directly_modified_node_ids == (modified,)
    assert diff.added_node_ids == ()
    assert diff.removed_node_ids == ()
    assert len(diff.node_ids_before) == 13
    assert diff.node_ids_before == diff.node_ids_after
    assert len(diff.unchanged_node_ids) == 12
    assert modified not in diff.affected_ancestor_node_ids
    assert diff.target_paths_before == diff.target_paths_after


def test_no_execution_verification_is_explicit() -> None:
    result = apply_edit(
        editable(),
        SetRepeatCount("parked_cars", 6),
        verify_execution=False,
    )
    assert result.original_execution is None
    assert result.edited_execution is None
    assert result.report.geometry_diff is None
    assert result.report.execution_verification_succeeded is False
    assert result.report.warnings == ("execution verification was explicitly disabled",)


def test_geometry_diff_is_content_based_deterministic_and_bounded() -> None:
    before = execute_grammar(editable())
    result = apply_edit(editable(), SetRepeatCount("parked_cars", 6))
    assert result.edited_execution is not None
    first = geometry_diff(before, result.edited_execution, detail_limit=1)
    second = geometry_diff(before, result.edited_execution, detail_limit=1)
    assert first == second
    assert first.added_primitive_count == 2
    assert len(first.added_primitive_ids) == 1
    assert len(first.modified_primitive_ids) == 1
    assert len(first.unchanged_primitive_ids) == 1
    assert first.detail_list_limit == 1
    assert first.details_truncated is True
    identical = geometry_diff(before, execute_grammar(editable()))
    assert identical.modified_primitive_count == 0
    assert identical.unchanged_primitive_count == 9
    assert identical.grammar_sha256_before == identical.grammar_sha256_after
