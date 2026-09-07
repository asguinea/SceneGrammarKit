"""Strict typed data models for the SceneGrammarKit grammar schema v0.1."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Literal, Mapping, TypeAlias

from scene_grammar_kit.grammar.errors import GrammarValidationError

SCHEMA_VERSION = "0.1"

AttributeValue: TypeAlias = str | int | float


class Axis(str, Enum):
    """A supported axis in the right-handed SceneGrammarKit coordinate system."""

    X = "x"
    Y = "y"
    Z = "z"


class GeometryType(str, Enum):
    """A terminal proxy-geometry type frozen by Phase 0."""

    BOX = "box"
    PLANE = "plane"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class Vector3:
    """A finite three-dimensional coordinate."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        """Validate and normalize all coordinates as finite floats."""
        for field_name in ("x", "y", "z"):
            value = getattr(self, field_name)
            normalized = _finite_number(value, field_name)
            object.__setattr__(self, field_name, normalized)

    def as_tuple(self) -> tuple[float, float, float]:
        """Return the coordinate components in x, y, z order."""
        return (self.x, self.y, self.z)


@dataclass(frozen=True, slots=True)
class Bounds3D:
    """Finite axis-aligned bounds with strictly positive extent."""

    minimum: Vector3
    maximum: Vector3

    def __post_init__(self) -> None:
        """Require typed endpoints and positive extent on every axis."""
        if not isinstance(self.minimum, Vector3):
            raise GrammarValidationError("root_bounds.min must be a Vector3")
        if not isinstance(self.maximum, Vector3):
            raise GrammarValidationError("root_bounds.max must be a Vector3")
        for axis_name, low, high in zip(
            ("x", "y", "z"),
            self.minimum.as_tuple(),
            self.maximum.as_tuple(),
        ):
            if high <= low:
                raise GrammarValidationError(
                    f"root_bounds has non-positive {axis_name} dimension: "
                    f"min={low}, max={high}"
                )


@dataclass(frozen=True, slots=True)
class GrammarNodeBase:
    """Common nominal base for recursive grammar nodes."""

    node_id: str

    def __post_init__(self) -> None:
        """Validate the stable, explicitly supplied node identifier."""
        _nonempty_string(self.node_id, "node_id")


@dataclass(frozen=True, slots=True)
class TerminalNode(GrammarNodeBase):
    """A semantic terminal with a Phase 0 proxy-geometry type."""

    semantic_class: str
    geometry: GeometryType
    attributes: Mapping[str, AttributeValue] = field(default_factory=dict)
    type: Literal["terminal"] = field(default="terminal", init=False)

    def __post_init__(self) -> None:
        """Validate terminal fields and freeze a defensive attributes copy."""
        super(TerminalNode, self).__post_init__()
        _nonempty_string(self.semantic_class, "semantic_class")
        if not isinstance(self.geometry, GeometryType):
            raise GrammarValidationError(
                "geometry must be a GeometryType: box, plane, or empty"
            )
        if not isinstance(self.attributes, Mapping):
            raise GrammarValidationError("attributes must be an object")

        copied: dict[str, AttributeValue] = {}
        for key, value in self.attributes.items():
            if not isinstance(key, str) or not key:
                raise GrammarValidationError("attributes keys must be nonempty strings")
            copied[key] = _attribute_value(value, f"attributes.{key}")
        object.__setattr__(self, "attributes", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class RepeatNode(GrammarNodeBase):
    """A repeat operator retaining one unexpanded child element."""

    axis: Axis
    count: int
    spacing: float
    element: GrammarNodeBase
    type: Literal["repeat"] = field(default="repeat", init=False)

    def __post_init__(self) -> None:
        """Validate repeat fields without performing parent-fit checks."""
        super(RepeatNode, self).__post_init__()
        _axis(self.axis)
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise GrammarValidationError("count must be an integer")
        if self.count < 1:
            raise GrammarValidationError("count must be at least 1")
        normalized_spacing = _finite_number(self.spacing, "spacing")
        if normalized_spacing < 0:
            raise GrammarValidationError("spacing must be nonnegative")
        object.__setattr__(self, "spacing", normalized_spacing)
        _grammar_node(self.element, "element")


@dataclass(frozen=True, slots=True)
class SplitChild:
    """One weighted, ordered child of a split operator."""

    weight: float
    node: GrammarNodeBase

    def __post_init__(self) -> None:
        """Validate a strictly positive finite weight and typed child node."""
        normalized_weight = _finite_number(self.weight, "weight")
        if normalized_weight <= 0:
            raise GrammarValidationError("weight must be strictly positive")
        object.__setattr__(self, "weight", normalized_weight)
        _grammar_node(self.node, "node")


@dataclass(frozen=True, slots=True)
class SplitNode(GrammarNodeBase):
    """An ordered axis-aligned split with at least two children."""

    axis: Axis
    children: tuple[SplitChild, ...]
    type: Literal["split"] = field(default="split", init=False)

    def __post_init__(self) -> None:
        """Validate the axis and field-level child constraints."""
        super(SplitNode, self).__post_init__()
        _axis(self.axis)
        if not isinstance(self.children, tuple):
            raise GrammarValidationError(
                "children must be a tuple of SplitChild values"
            )
        if len(self.children) < 2:
            raise GrammarValidationError("children must contain at least two entries")
        for index, child in enumerate(self.children):
            if not isinstance(child, SplitChild):
                raise GrammarValidationError(f"children[{index}] must be a SplitChild")


GrammarNode: TypeAlias = SplitNode | RepeatNode | TerminalNode


@dataclass(frozen=True, slots=True)
class SceneGrammar:
    """The root document for SceneGrammarKit grammar schema version 0.1."""

    schema_version: str
    scene_id: str
    units: str
    root_bounds: Bounds3D
    root: GrammarNode

    def __post_init__(self) -> None:
        """Validate root-document fields without deep semantic checks."""
        if self.schema_version != SCHEMA_VERSION:
            raise GrammarValidationError(
                f"schema_version must be {SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )
        _nonempty_string(self.scene_id, "scene_id")
        _nonempty_string(self.units, "units")
        if not isinstance(self.root_bounds, Bounds3D):
            raise GrammarValidationError("root_bounds must be a Bounds3D")
        _grammar_node(self.root, "root")


def _axis(value: object) -> Axis:
    """Return a valid Axis or raise a field-focused domain error."""
    if not isinstance(value, Axis):
        raise GrammarValidationError("axis must be one of: x, y, z")
    return value


def _finite_number(value: object, field_name: str) -> float:
    """Return a normalized finite float while rejecting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GrammarValidationError(f"{field_name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise GrammarValidationError(f"{field_name} must be finite")
    return normalized


def _nonempty_string(value: object, field_name: str) -> str:
    """Return a string that contains at least one non-whitespace character."""
    if not isinstance(value, str) or not value.strip():
        raise GrammarValidationError(f"{field_name} must be a nonempty string")
    return value


def _attribute_value(value: object, field_name: str) -> AttributeValue:
    """Validate a Phase 0 scalar/string terminal attribute."""
    if isinstance(value, bool):
        raise GrammarValidationError(
            f"{field_name} must be a string, integer, or finite number"
        )
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise GrammarValidationError(
        f"{field_name} must be a string, integer, or finite number"
    )


def _grammar_node(value: object, field_name: str) -> GrammarNodeBase:
    """Require one of the three tagged SceneGrammarKit node classes."""
    if not isinstance(value, (SplitNode, RepeatNode, TerminalNode)):
        raise GrammarValidationError(
            f"{field_name} must be a SplitNode, RepeatNode, or TerminalNode"
        )
    return value
