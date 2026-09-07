"""Strict model and fixture-loading tests for grammar schema v0.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from scene_grammar_kit.grammar import (
    Axis,
    Bounds3D,
    GeometryType,
    GrammarValidationError,
    RepeatNode,
    SceneGrammar,
    SplitNode,
    TerminalNode,
    Vector3,
    load_grammar,
)

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"


def test_axis_values_are_exactly_xyz() -> None:
    """Only the three frozen spatial axes are enumerated."""
    assert [axis.value for axis in Axis] == ["x", "y", "z"]
    assert Axis("x") is Axis.X
    assert Axis("y") is Axis.Y
    assert Axis("z") is Axis.Z


def test_invalid_axis_enum_value_is_rejected() -> None:
    """An unsupported axis cannot be constructed."""
    with pytest.raises(ValueError):
        Axis("w")


@pytest.mark.parametrize(
    ("fixture_name", "root_type"),
    [
        ("valid_terminal.json", TerminalNode),
        ("valid_split.json", SplitNode),
        ("valid_repeat.json", RepeatNode),
        ("valid_nested_urban.json", SplitNode),
    ],
)
def test_valid_grammar_fixtures_load(
    fixture_name: str, root_type: type[object]
) -> None:
    """Each required valid fixture loads into its expected root model."""
    grammar = load_grammar(FIXTURES / fixture_name)
    assert isinstance(grammar, SceneGrammar)
    assert isinstance(grammar.root, root_type)


@pytest.mark.parametrize(
    ("fixture_name", "message"),
    [
        ("invalid_node_type.json", "unknown node type"),
        ("invalid_axis.json", "axis"),
        ("invalid_repeat_count.json", "count"),
        ("invalid_negative_spacing.json", "spacing"),
        ("invalid_dimensions.json", "dimension"),
        ("missing_required_field.json", "semantic_class"),
        ("missing_node_type.json", "type is required"),
        ("unexpected_field.json", "unexpected field"),
    ],
)
def test_invalid_grammar_fixtures_are_rejected(fixture_name: str, message: str) -> None:
    """Required malformed fixtures produce useful domain validation errors."""
    with pytest.raises(GrammarValidationError, match=message):
        load_grammar(FIXTURES / fixture_name)


def test_empty_semantic_class_is_rejected() -> None:
    """Whitespace-only semantic labels are invalid."""
    with pytest.raises(GrammarValidationError, match="semantic_class"):
        TerminalNode(
            node_id="empty_label",
            semantic_class="  ",
            geometry=GeometryType.BOX,
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_coordinates_are_rejected(value: float) -> None:
    """Bounds coordinates cannot contain NaN or infinity."""
    with pytest.raises(GrammarValidationError, match="finite"):
        Vector3(value, 0, 0)


def test_direct_model_construction_requires_axis_enum() -> None:
    """Direct construction does not silently coerce arbitrary axis strings."""
    terminal = TerminalNode("terminal", "road", GeometryType.BOX)
    with pytest.raises(GrammarValidationError, match="axis"):
        RepeatNode("repeat", "x", 2, 0, terminal)  # type: ignore[arg-type]


def test_terminal_attribute_defaults_are_not_shared() -> None:
    """Terminal instances receive independent immutable attribute mappings."""
    first = TerminalNode("first", "road", GeometryType.BOX)
    second = TerminalNode("second", "road", GeometryType.BOX)
    assert first.attributes is not second.attributes
    with pytest.raises(TypeError):
        first.attributes["new"] = 1  # type: ignore[index]


def test_schema_version_is_not_package_version() -> None:
    """Only grammar schema version 0.1 is accepted."""
    bounds = Bounds3D(Vector3(0, 0, 0), Vector3(1, 1, 1))
    terminal = TerminalNode("root", "road", GeometryType.BOX)
    with pytest.raises(GrammarValidationError, match="schema_version"):
        SceneGrammar("1.0.0", "scene", "normalized", bounds, terminal)
