"""Deterministic grammar-to-geometry executor tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scene_grammar_kit.geometry import (
    EXECUTION_POLICY_VERSION,
    ExecutionDepthError,
    GeometryValidationError,
    PrimitiveLimitError,
    RepeatFitError,
    bounds_contain,
    execute_grammar,
    executed_scene_to_canonical_json,
)
from scene_grammar_kit.grammar import (
    Axis,
    Bounds3D,
    GeometryType,
    RepeatNode,
    SceneGrammar,
    SplitChild,
    SplitNode,
    TerminalNode,
    Vector3,
    grammar_to_canonical_json,
    load_grammar,
)

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"


def test_box_terminal_preserves_semantics_attributes_and_provenance() -> None:
    """A box emits one immutable semantic primitive with deterministic identity."""
    grammar = load_grammar(FIXTURES / "valid_terminal.json")
    first = execute_grammar(grammar)
    second = execute_grammar(grammar)
    primitive = first.primitives[0]
    assert first == second
    assert primitive.geometry is GeometryType.BOX
    assert primitive.source_terminal_id == grammar.root.node_id
    assert primitive.semantic_class == grammar.root.semantic_class
    assert dict(primitive.attributes) == dict(grammar.root.attributes)
    assert primitive.instance_path == "root"
    assert primitive.repeat_indices == ()
    assert primitive.primitive_id == (
        "primitive-" + hashlib.sha256(b"root").hexdigest()
    )


def test_box_plane_and_empty_terminal_policies_and_counts() -> None:
    """Boxes and proxy planes render while empty terminals only affect reports."""
    scene = execute_grammar(load_grammar(FIXTURES / "terminal_types.json"))
    assert [item.geometry for item in scene.primitives] == [
        GeometryType.BOX,
        GeometryType.PLANE,
    ]
    assert [item.semantic_class for item in scene.primitives] == [
        "building",
        "ground",
    ]
    assert scene.report.primitive_count == 2
    assert scene.report.box_count == 1
    assert scene.report.plane_count == 1
    assert scene.report.empty_terminal_count == 1


def test_split_execution_preserves_order_and_exact_coverage() -> None:
    """Unequal split children occupy ordered exact thirds of the root."""
    scene = execute_grammar(load_grammar(FIXTURES / "valid_split.json"))
    left, right = scene.primitives
    assert [item.source_terminal_id for item in scene.primitives] == [
        "left",
        "right",
    ]
    assert left.bounds.minimum.x == scene.root_bounds.minimum.x
    assert left.bounds.maximum.x == right.bounds.minimum.x
    assert right.bounds.maximum.x == scene.root_bounds.maximum.x
    assert left.bounds.maximum.x == pytest.approx(1.0 / 3.0)
    assert left.bounds.minimum.y == right.bounds.minimum.y
    assert left.bounds.maximum.z == right.bounds.maximum.z


def test_nested_split_repeat_order_indices_paths_and_report() -> None:
    """Nested urban traversal follows symbolic order then increasing repeats."""
    scene = execute_grammar(load_grammar(FIXTURES / "valid_nested_urban.json"))
    assert [item.source_terminal_id for item in scene.primitives] == [
        "sidewalk_left",
        "car",
        "car",
        "car",
        "car",
        "sidewalk_right",
        "background",
    ]
    cars = scene.primitives[1:5]
    assert [item.repeat_indices for item in cars] == [(0,), (1,), (2,), (3,)]
    assert [item.instance_path for item in cars] == [
        f"root.children[1].node.children[1].node.instances[{index}].element"
        for index in range(4)
    ]
    assert scene.report.symbolic_node_count_visited == 8
    assert scene.report.primitive_count == 7
    assert scene.report.box_count == 6
    assert scene.report.plane_count == 1
    assert scene.report.empty_terminal_count == 1
    assert scene.report.maximum_execution_depth == 3
    assert scene.execution_policy_version == EXECUTION_POLICY_VERSION == "0.1"


def test_repeat_count_one_and_zero_spacing_fixture_bounds() -> None:
    """Count-one and zero-spacing fixtures execute their frozen policies."""
    one = execute_grammar(load_grammar(FIXTURES / "count_one_repeat.json"))
    assert one.primitives[0].bounds == one.root_bounds
    zero = execute_grammar(load_grammar(FIXTURES / "repeat_zero_spacing.json"))
    assert len(zero.primitives) == 3
    for previous, current in zip(zero.primitives, zero.primitives[1:]):
        assert previous.bounds.maximum.z == current.bounds.minimum.z


def test_nested_repeats_multiply_in_deterministic_order() -> None:
    """Ordinary recursive execution multiplies nested repeats."""
    scene = execute_grammar(load_grammar(FIXTURES / "valid_nested_repeats.json"))
    assert len(scene.primitives) == 6
    assert [item.repeat_indices for item in scene.primitives] == [
        (0, 0),
        (0, 1),
        (0, 2),
        (1, 0),
        (1, 1),
        (1, 2),
    ]


def test_repeat_containing_split_expands_each_ordered_child() -> None:
    """A split is independently applied inside every repeat instance."""
    bounds = Bounds3D(Vector3(0, 0, 0), Vector3(3, 2, 1))
    left = TerminalNode("left", "left", GeometryType.BOX)
    right = TerminalNode("right", "right", GeometryType.BOX)
    split = SplitNode(
        "split",
        Axis.Y,
        (SplitChild(1, left), SplitChild(1, right)),
    )
    grammar = SceneGrammar(
        "0.1",
        "repeat_split",
        "normalized",
        bounds,
        RepeatNode("repeat", Axis.X, 3, 0.0, split),
    )
    scene = execute_grammar(grammar)
    assert len(scene.primitives) == 6
    assert [item.source_terminal_id for item in scene.primitives] == [
        "left",
        "right",
        "left",
        "right",
        "left",
        "right",
    ]
    assert [item.repeat_indices for item in scene.primitives] == [
        (0,),
        (0,),
        (1,),
        (1,),
        (2,),
        (2,),
    ]


def test_repeat_fit_failure_is_clear() -> None:
    """An unavailable repeat element extent raises a specific domain error."""
    with pytest.raises(RepeatFitError, match="Repeat does not fit"):
        execute_grammar(load_grammar(FIXTURES / "repeat_cannot_fit.json"))


def test_large_repeat_preflights_primitive_limit() -> None:
    """Conceptual output limits fail before huge repeat materialization."""
    with pytest.raises(PrimitiveLimitError, match="exceeding"):
        execute_grammar(
            load_grammar(FIXTURES / "large_nested_repeats.json"),
            maximum_primitives=1000,
        )


def test_depth_limit_and_semantic_validation_fail_safely() -> None:
    """Excess depth and invalid symbolic semantics become geometry errors."""
    with pytest.raises(ExecutionDepthError, match="depth"):
        execute_grammar(
            load_grammar(FIXTURES / "deeply_nested.json"),
            maximum_depth=2,
        )
    with pytest.raises(GeometryValidationError, match="duplicate_node_id"):
        execute_grammar(load_grammar(FIXTURES / "duplicate_node_ids.json"))


def test_corrupted_in_memory_cycle_fails_before_execution() -> None:
    """The semantic validation preflight catches identity cycles iteratively."""
    grammar = load_grammar(FIXTURES / "valid_repeat.json")
    object.__setattr__(grammar.root, "element", grammar.root)
    with pytest.raises(GeometryValidationError, match="cycle_detected"):
        execute_grammar(grammar)


def test_hash_matches_canonical_grammar_and_changes_with_grammar() -> None:
    """Grammar provenance is the SHA-256 of exact canonical grammar bytes."""
    first_grammar = load_grammar(FIXTURES / "valid_terminal.json")
    second_grammar = load_grammar(FIXTURES / "valid_split.json")
    first = execute_grammar(first_grammar)
    second = execute_grammar(second_grammar)
    expected = hashlib.sha256(
        grammar_to_canonical_json(first_grammar).encode("utf-8")
    ).hexdigest()
    assert first.grammar_sha256 == first.report.grammar_sha256 == expected
    assert first.grammar_sha256 != second.grammar_sha256


def test_every_primitive_is_inside_root_and_canonical_bytes_repeat() -> None:
    """All inherited outputs stay contained and serialize byte-identically."""
    grammar = load_grammar(FIXTURES / "valid_nested_urban.json")
    first = execute_grammar(grammar)
    second = execute_grammar(grammar)
    assert all(
        bounds_contain(first.root_bounds, primitive.bounds)
        for primitive in first.primitives
    )
    assert executed_scene_to_canonical_json(first).encode(
        "utf-8"
    ) == executed_scene_to_canonical_json(second).encode("utf-8")


@pytest.mark.parametrize("name", ["maximum_depth", "maximum_primitives"])
def test_execution_configuration_requires_positive_integers(name: str) -> None:
    """Safety configuration rejects booleans and nonpositive values."""
    grammar = load_grammar(FIXTURES / "valid_terminal.json")
    arguments = {name: 0}
    with pytest.raises(ValueError, match="positive integer"):
        execute_grammar(grammar, **arguments)  # type: ignore[arg-type]
