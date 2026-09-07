"""Immutable executed-geometry models for SceneGrammarKit policy version 0.1."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeAlias

from scene_grammar_kit.geometry.errors import GeometryValidationError
from scene_grammar_kit.grammar.models import (
    AttributeValue,
    Bounds3D,
    GeometryType,
)

EXECUTION_POLICY_VERSION = "0.1"
PrimitiveBounds: TypeAlias = Bounds3D


@dataclass(frozen=True, slots=True)
class SemanticPrimitive:
    """One deterministic, renderable semantic proxy primitive."""

    primitive_id: str
    source_terminal_id: str
    semantic_class: str
    geometry: GeometryType
    bounds: PrimitiveBounds
    attributes: Mapping[str, AttributeValue] = field(default_factory=dict)
    instance_path: str = ""
    repeat_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Validate provenance and freeze a defensive attributes copy."""
        for name in (
            "primitive_id",
            "source_terminal_id",
            "semantic_class",
            "instance_path",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise GeometryValidationError(f"{name} must be a nonempty string")
        if self.geometry not in (GeometryType.BOX, GeometryType.PLANE):
            raise GeometryValidationError(
                "SemanticPrimitive geometry must be box or plane"
            )
        if not isinstance(self.bounds, Bounds3D):
            raise GeometryValidationError("bounds must be a Bounds3D")
        if not isinstance(self.repeat_indices, tuple) or any(
            isinstance(index, bool) or not isinstance(index, int) or index < 0
            for index in self.repeat_indices
        ):
            raise GeometryValidationError(
                "repeat_indices must be a tuple of nonnegative integers"
            )
        if not isinstance(self.attributes, Mapping):
            raise GeometryValidationError("attributes must be a mapping")
        copied: dict[str, AttributeValue] = {}
        for key, value in self.attributes.items():
            if not isinstance(key, str) or not key:
                raise GeometryValidationError("attribute keys must be nonempty strings")
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise GeometryValidationError(
                    "attributes must contain strings, integers, or finite numbers"
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise GeometryValidationError(
                    "numeric primitive attributes must be finite"
                )
            copied[key] = value
        object.__setattr__(self, "attributes", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """Deterministic counts and provenance for one successful execution."""

    success: bool
    symbolic_node_count_visited: int
    primitive_count: int
    box_count: int
    plane_count: int
    empty_terminal_count: int
    maximum_execution_depth: int
    grammar_sha256: str
    warnings: tuple[str, ...]
    execution_policy_version: str = EXECUTION_POLICY_VERSION

    def __post_init__(self) -> None:
        """Validate deterministic report fields."""
        for name in (
            "symbolic_node_count_visited",
            "primitive_count",
            "box_count",
            "plane_count",
            "empty_terminal_count",
            "maximum_execution_depth",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise GeometryValidationError(f"{name} must be a nonnegative integer")
        _sha256(self.grammar_sha256)
        if not isinstance(self.warnings, tuple) or any(
            not isinstance(item, str) for item in self.warnings
        ):
            raise GeometryValidationError("warnings must be a tuple of strings")
        if self.execution_policy_version != EXECUTION_POLICY_VERSION:
            raise GeometryValidationError(
                f"execution_policy_version must be {EXECUTION_POLICY_VERSION!r}"
            )


@dataclass(frozen=True, slots=True)
class ExecutedScene:
    """A flat, ordered deterministic execution of one symbolic grammar."""

    scene_id: str
    grammar_schema_version: str
    units: str
    root_bounds: PrimitiveBounds
    primitives: tuple[SemanticPrimitive, ...]
    grammar_sha256: str
    report: ExecutionReport
    execution_policy_version: str = EXECUTION_POLICY_VERSION

    def __post_init__(self) -> None:
        """Validate scene metadata and ordered primitive collection."""
        for name in ("scene_id", "grammar_schema_version", "units"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise GeometryValidationError(f"{name} must be a nonempty string")
        if not isinstance(self.root_bounds, Bounds3D):
            raise GeometryValidationError("root_bounds must be a Bounds3D")
        if not isinstance(self.primitives, tuple) or any(
            not isinstance(primitive, SemanticPrimitive)
            for primitive in self.primitives
        ):
            raise GeometryValidationError(
                "primitives must be a tuple of SemanticPrimitive values"
            )
        _sha256(self.grammar_sha256)
        if not isinstance(self.report, ExecutionReport):
            raise GeometryValidationError("report must be an ExecutionReport")
        if self.report.grammar_sha256 != self.grammar_sha256:
            raise GeometryValidationError(
                "scene and report grammar SHA-256 values must match"
            )
        if self.report.primitive_count != len(self.primitives):
            raise GeometryValidationError(
                "report primitive count must match the primitive collection"
            )
        if self.execution_policy_version != EXECUTION_POLICY_VERSION:
            raise GeometryValidationError(
                f"execution_policy_version must be {EXECUTION_POLICY_VERSION!r}"
            )


def _sha256(value: object) -> str:
    """Validate a lowercase hexadecimal SHA-256 digest."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise GeometryValidationError(
            "grammar_sha256 must be a lowercase hexadecimal SHA-256 digest"
        )
    return value
