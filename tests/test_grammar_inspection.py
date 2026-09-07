"""Deterministic tree and summary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from scene_grammar_kit.grammar import (
    Axis,
    Bounds3D,
    GeometryType,
    GrammarExpansionLimitError,
    GrammarInspectionError,
    RepeatNode,
    SceneGrammar,
    SplitChild,
    SplitNode,
    TerminalNode,
    Vector3,
    grammar_to_canonical_json,
    grammar_tree_to_text,
    load_grammar,
    summarize_grammar,
)

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"


def test_tree_output_is_deterministic_and_newline_stable() -> None:
    """Tree rendering is byte-identical and ends in exactly one newline."""
    grammar = load_grammar(FIXTURES / "valid_nested_urban.json")
    first = grammar_tree_to_text(grammar)
    second = grammar_tree_to_text(grammar)
    assert first == second
    assert first.endswith("\n")
    assert not first.endswith("\n\n")
    assert first.isascii()


def test_tree_output_preserves_split_child_order() -> None:
    """Split children appear in their persisted order."""
    text = grammar_tree_to_text(load_grammar(FIXTURES / "valid_split.json"))
    assert text.index("id=left") < text.index("id=right")
    assert "root: Split id=split_root axis=x" in text
    assert "child[0] weight=1" in text
    assert "child[1] weight=2" in text


def test_tree_exposes_repeat_and_terminal_fields() -> None:
    """Repeat and terminal inspection includes all required fields."""
    text = grammar_tree_to_text(load_grammar(FIXTURES / "valid_repeat.json"))
    assert "Repeat id=repeat_root axis=z count=4 spacing=0.1" in text
    assert "Terminal id=car class=car geometry=box" in text


def test_excessive_depth_refuses_inspection_without_recursion_error() -> None:
    """Inspection reports an intentional domain failure for unsafe depth."""
    grammar = load_grammar(FIXTURES / "deeply_nested.json")
    with pytest.raises(GrammarInspectionError, match="maximum_depth_exceeded"):
        grammar_tree_to_text(grammar, max_depth=2)


def test_nested_urban_summary_counts() -> None:
    """Symbolic and expanded counts match the known nested urban fixture."""
    grammar = load_grammar(FIXTURES / "valid_nested_urban.json")
    summary = summarize_grammar(grammar)
    assert summary.total_node_count == 8
    assert summary.split_node_count == 2
    assert summary.repeat_node_count == 1
    assert summary.terminal_node_count == 5
    assert summary.maximum_depth == 3
    assert summary.total_split_child_count == 6
    assert summary.expanded_terminal_instance_count == 8
    assert summary.canonical_byte_size == len(
        grammar_to_canonical_json(grammar).encode("utf-8")
    )
    assert dict(summary.semantic_class_frequencies) == {
        "car": 1,
        "facade": 1,
        "foreground": 1,
        "sidewalk": 2,
    }
    assert dict(summary.geometry_type_frequencies) == {
        "box": 3,
        "empty": 1,
        "plane": 1,
    }


def test_terminal_expansion_count_is_one() -> None:
    """One symbolic terminal conceptually expands to one instance."""
    summary = summarize_grammar(load_grammar(FIXTURES / "valid_terminal.json"))
    assert summary.expanded_terminal_instance_count == 1
    assert summary.maximum_depth == 0


def test_repeat_expansion_count_uses_count() -> None:
    """A repeat multiplies the terminal instance count."""
    summary = summarize_grammar(load_grammar(FIXTURES / "valid_repeat.json"))
    assert summary.expanded_terminal_instance_count == 4


def test_nested_repeat_counts_multiply() -> None:
    """Nested repeats multiply counts without allocating instances."""
    summary = summarize_grammar(load_grammar(FIXTURES / "valid_nested_repeats.json"))
    assert summary.expanded_terminal_instance_count == 6
    assert summary.repeat_node_count == 2
    assert summary.maximum_depth == 2


def test_repeat_containing_split_multiplies_each_terminal() -> None:
    """A repeated split counts each contained terminal per repetition."""
    first = TerminalNode("first", "road", GeometryType.BOX)
    second = TerminalNode("second", "sidewalk", GeometryType.BOX)
    split = SplitNode(
        "split",
        Axis.X,
        (SplitChild(1, first), SplitChild(1, second)),
    )
    repeat = RepeatNode("repeat", Axis.Z, 3, 0, split)
    grammar = SceneGrammar(
        "0.1",
        "repeat_split",
        "normalized",
        Bounds3D(Vector3(0, 0, 0), Vector3(1, 1, 1)),
        repeat,
    )
    assert summarize_grammar(grammar).expanded_terminal_instance_count == 6


def test_expansion_safety_limit_is_enforced() -> None:
    """Huge nested repeats fail before materializing any instances."""
    grammar = load_grammar(FIXTURES / "large_nested_repeats.json")
    with pytest.raises(GrammarExpansionLimitError, match="safety limit"):
        summarize_grammar(grammar)


@pytest.mark.parametrize("limit", [0, -1, True, 2.5])
def test_invalid_expansion_limit_is_rejected(limit: object) -> None:
    """Expansion configuration must be a positive integer."""
    grammar = load_grammar(FIXTURES / "valid_terminal.json")
    with pytest.raises(ValueError, match="positive integer"):
        summarize_grammar(grammar, expansion_limit=limit)  # type: ignore[arg-type]
