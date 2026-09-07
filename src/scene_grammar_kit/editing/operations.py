"""Immutable typed edit operations for editing policy version 0.1."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from scene_grammar_kit.editing.errors import InvalidEditValueError

EDITING_POLICY_VERSION = "0.1"


@dataclass(frozen=True, slots=True)
class SetSplitChildWeight:
    """Replace one direct split-child stored weight."""

    split_node_id: str
    child_node_id: str
    new_weight: float
    operation_type: Literal["set_split_child_weight"] = field(
        default="set_split_child_weight",
        init=False,
    )

    def __post_init__(self) -> None:
        _node_id(self.split_node_id, "split_node_id")
        _node_id(self.child_node_id, "child_node_id")
        object.__setattr__(
            self,
            "new_weight",
            _finite_number(self.new_weight, "new_weight", minimum=0.0, strict=True),
        )


@dataclass(frozen=True, slots=True)
class SetRepeatCount:
    """Replace a repeat node's integer count."""

    repeat_node_id: str
    new_count: int
    operation_type: Literal["set_repeat_count"] = field(
        default="set_repeat_count",
        init=False,
    )

    def __post_init__(self) -> None:
        _node_id(self.repeat_node_id, "repeat_node_id")
        if (
            isinstance(self.new_count, bool)
            or not isinstance(self.new_count, int)
            or self.new_count < 1
        ):
            raise InvalidEditValueError("new_count must be an integer of at least one")


@dataclass(frozen=True, slots=True)
class SetRepeatSpacing:
    """Replace a repeat node's nonnegative spacing."""

    repeat_node_id: str
    new_spacing: float
    operation_type: Literal["set_repeat_spacing"] = field(
        default="set_repeat_spacing",
        init=False,
    )

    def __post_init__(self) -> None:
        _node_id(self.repeat_node_id, "repeat_node_id")
        object.__setattr__(
            self,
            "new_spacing",
            _finite_number(
                self.new_spacing,
                "new_spacing",
                minimum=0.0,
                strict=False,
            ),
        )


@dataclass(frozen=True, slots=True)
class SubstituteTerminalClass:
    """Replace only a terminal node's semantic class."""

    terminal_node_id: str
    new_semantic_class: str
    operation_type: Literal["substitute_terminal_class"] = field(
        default="substitute_terminal_class",
        init=False,
    )

    def __post_init__(self) -> None:
        _node_id(self.terminal_node_id, "terminal_node_id")
        if (
            not isinstance(self.new_semantic_class, str)
            or not self.new_semantic_class.strip()
        ):
            raise InvalidEditValueError("new_semantic_class must be a nonempty string")


EditOperation: TypeAlias = (
    SetSplitChildWeight | SetRepeatCount | SetRepeatSpacing | SubstituteTerminalClass
)


def operation_target_id(operation: EditOperation) -> str:
    """Return the symbolic target node ID of an operation."""
    if isinstance(operation, SetSplitChildWeight):
        return operation.split_node_id
    if isinstance(operation, (SetRepeatCount, SetRepeatSpacing)):
        return operation.repeat_node_id
    if isinstance(operation, SubstituteTerminalClass):
        return operation.terminal_node_id
    raise TypeError("operation must be a supported EditOperation")


def _node_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEditValueError(f"{name} must be a nonempty string")
    return value


def _finite_number(
    value: object,
    name: str,
    *,
    minimum: float,
    strict: bool,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidEditValueError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise InvalidEditValueError(f"{name} must be finite")
    if normalized < minimum or (strict and normalized == minimum):
        comparator = "strictly positive" if strict else "nonnegative"
        raise InvalidEditValueError(f"{name} must be {comparator}")
    return normalized
