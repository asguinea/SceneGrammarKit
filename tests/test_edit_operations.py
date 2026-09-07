"""Validation tests for Batch 1.6 immutable typed edit operations."""

from __future__ import annotations

import math

import pytest

from scene_grammar_kit.editing import (
    InvalidEditValueError,
    SetRepeatCount,
    SetRepeatSpacing,
    SetSplitChildWeight,
    SubstituteTerminalClass,
)


def test_valid_split_weight_operation_is_frozen_and_discriminated() -> None:
    operation = SetSplitChildWeight("layout", "road", 8)
    assert operation.new_weight == 8.0
    assert operation.operation_type == "set_split_child_weight"
    with pytest.raises(AttributeError):
        operation.new_weight = 3  # type: ignore[misc]


@pytest.mark.parametrize("value", [0, -1, math.inf, -math.inf, math.nan])
def test_invalid_split_weights_are_rejected(value: float) -> None:
    with pytest.raises(InvalidEditValueError):
        SetSplitChildWeight("layout", "road", value)


def test_valid_repeat_count_operation() -> None:
    operation = SetRepeatCount("cars", 6)
    assert operation.new_count == 6
    assert operation.operation_type == "set_repeat_count"


@pytest.mark.parametrize("value", [0, -1, True, 2.5])
def test_invalid_repeat_counts_are_rejected(value: object) -> None:
    with pytest.raises(InvalidEditValueError):
        SetRepeatCount("cars", value)  # type: ignore[arg-type]


def test_valid_repeat_spacing_operation() -> None:
    operation = SetRepeatSpacing("cars", 0.08)
    assert operation.new_spacing == 0.08
    assert operation.operation_type == "set_repeat_spacing"


@pytest.mark.parametrize("value", [-0.01, math.inf, -math.inf, math.nan])
def test_invalid_repeat_spacing_is_rejected(value: float) -> None:
    with pytest.raises(InvalidEditValueError):
        SetRepeatSpacing("cars", value)


def test_valid_terminal_substitution_operation() -> None:
    operation = SubstituteTerminalClass("tree", "lamp_post")
    assert operation.operation_type == "substitute_terminal_class"
    assert operation.new_semantic_class == "lamp_post"


@pytest.mark.parametrize("value", ["", "   ", 3])
def test_invalid_terminal_semantic_class_is_rejected(value: object) -> None:
    with pytest.raises(InvalidEditValueError):
        SubstituteTerminalClass("tree", value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: SetSplitChildWeight("", "road", 1),
        lambda: SetSplitChildWeight("layout", "", 1),
        lambda: SetRepeatCount("", 1),
        lambda: SetRepeatSpacing(" ", 0),
        lambda: SubstituteTerminalClass("", "tree"),
    ],
)
def test_empty_target_identifiers_are_rejected(constructor: object) -> None:
    with pytest.raises(InvalidEditValueError):
        constructor()  # type: ignore[operator]
