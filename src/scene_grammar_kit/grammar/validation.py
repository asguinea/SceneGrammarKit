"""Deterministic semantic validation for symbolic SceneGrammarKit grammars."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from scene_grammar_kit.grammar.models import (
    SCHEMA_VERSION,
    Axis,
    Bounds3D,
    GeometryType,
    GrammarNodeBase,
    RepeatNode,
    SceneGrammar,
    SplitChild,
    SplitNode,
    TerminalNode,
    Vector3,
)

DEFAULT_MAX_GRAMMAR_DEPTH = 128


class ValidationSeverity(str, Enum):
    """Severity of one semantic validation diagnostic."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ValidationDiagnostic:
    """One deterministic, structured grammar validation finding."""

    code: str
    severity: ValidationSeverity
    message: str
    node_id: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Ordered semantic validation results for one grammar."""

    diagnostics: tuple[ValidationDiagnostic, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether the report contains no error diagnostics."""
        return self.error_count == 0

    @property
    def error_count(self) -> int:
        """Return the number of error diagnostics."""
        return sum(
            diagnostic.severity is ValidationSeverity.ERROR
            for diagnostic in self.diagnostics
        )

    @property
    def warning_count(self) -> int:
        """Return the number of warning diagnostics."""
        return sum(
            diagnostic.severity is ValidationSeverity.WARNING
            for diagnostic in self.diagnostics
        )


def validate_grammar(
    grammar: SceneGrammar,
    *,
    max_depth: int = DEFAULT_MAX_GRAMMAR_DEPTH,
) -> ValidationReport:
    """Validate field-independent invariants using deterministic preorder.

    The root node has depth zero. Traversal is iterative, stops descending when
    ``max_depth`` is exceeded, and detects object-identity cycles in malformed
    in-memory graphs. JSON-loaded grammars cannot contain such cycles.
    """
    _positive_integer(max_depth, "max_depth")
    if not isinstance(grammar, SceneGrammar):
        raise TypeError("grammar must be a SceneGrammar")

    diagnostics: list[ValidationDiagnostic] = []
    _validate_scene(grammar, diagnostics)
    root = getattr(grammar, "root", None)
    if not isinstance(root, (SplitNode, RepeatNode, TerminalNode)):
        if root is not None:
            _add(
                diagnostics,
                "invalid_root_node",
                "Root must be a SplitNode, RepeatNode, or TerminalNode.",
                path="root",
            )
        return ValidationReport(tuple(diagnostics))

    seen_node_ids: dict[str, str] = {}
    stack: list[tuple[GrammarNodeBase, str, int, tuple[int, ...]]] = [
        (root, "root", 0, ())
    ]
    while stack:
        node, path, depth, ancestors = stack.pop()
        node_id = _display_node_id(node)

        if depth > max_depth:
            _add(
                diagnostics,
                "maximum_depth_exceeded",
                f"Grammar depth {depth} exceeds configured maximum {max_depth}.",
                node_id=node_id,
                path=path,
            )
            continue

        identity = id(node)
        if identity in ancestors:
            _add(
                diagnostics,
                "cycle_detected",
                "Object-identity cycle detected in in-memory grammar.",
                node_id=node_id,
                path=path,
            )
            continue

        raw_node_id = getattr(node, "node_id", None)
        if not isinstance(raw_node_id, str) or not raw_node_id.strip():
            _add(
                diagnostics,
                "empty_node_id",
                "Node identifier must be a nonempty string.",
                node_id=node_id,
                path=path,
            )
        else:
            first_path = seen_node_ids.get(raw_node_id)
            if first_path is not None:
                _add(
                    diagnostics,
                    "duplicate_node_id",
                    f"Node identifier {raw_node_id!r} was first used at {first_path}.",
                    node_id=raw_node_id,
                    path=path,
                )
            else:
                seen_node_ids[raw_node_id] = path

        next_ancestors = ancestors + (identity,)
        if isinstance(node, SplitNode):
            descendants = _validate_split(node, path, diagnostics)
        elif isinstance(node, RepeatNode):
            descendants = _validate_repeat(node, path, diagnostics)
        elif isinstance(node, TerminalNode):
            descendants = _validate_terminal(node, path, diagnostics)
        else:
            _add(
                diagnostics,
                "unsupported_node_type",
                f"Unsupported in-memory node class {type(node).__name__}.",
                node_id=node_id,
                path=path,
            )
            descendants = []

        for child, child_path in reversed(descendants):
            stack.append((child, child_path, depth + 1, next_ancestors))

    return ValidationReport(tuple(diagnostics))


def _validate_scene(
    grammar: SceneGrammar,
    diagnostics: list[ValidationDiagnostic],
) -> None:
    """Validate defensive scene-level invariants."""
    if getattr(grammar, "schema_version", None) != SCHEMA_VERSION:
        _add(
            diagnostics,
            "unsupported_schema_version",
            f"Supported schema version is {SCHEMA_VERSION!r}.",
            path="schema_version",
        )
    if not _nonempty_string(getattr(grammar, "scene_id", None)):
        _add(
            diagnostics,
            "empty_scene_id",
            "Scene identifier must be a nonempty string.",
            path="scene_id",
        )
    if not _nonempty_string(getattr(grammar, "units", None)):
        _add(
            diagnostics,
            "empty_units",
            "Units must be a nonempty string.",
            path="units",
        )
    _validate_bounds(getattr(grammar, "root_bounds", None), diagnostics)
    if getattr(grammar, "root", None) is None:
        _add(
            diagnostics,
            "missing_root",
            "Scene grammar must contain a root node.",
            path="root",
        )


def _validate_bounds(
    bounds: object,
    diagnostics: list[ValidationDiagnostic],
) -> None:
    """Validate finite root bounds and positive extent defensively."""
    if not isinstance(bounds, Bounds3D):
        _add(
            diagnostics,
            "invalid_root_bounds",
            "Root bounds must be a Bounds3D value.",
            path="root_bounds",
        )
        return
    minimum = getattr(bounds, "minimum", None)
    maximum = getattr(bounds, "maximum", None)
    if not isinstance(minimum, Vector3) or not isinstance(maximum, Vector3):
        _add(
            diagnostics,
            "invalid_root_bounds",
            "Root bounds must contain minimum and maximum Vector3 values.",
            path="root_bounds",
        )
        return
    lows = (
        getattr(minimum, "x", None),
        getattr(minimum, "y", None),
        getattr(minimum, "z", None),
    )
    highs = (
        getattr(maximum, "x", None),
        getattr(maximum, "y", None),
        getattr(maximum, "z", None),
    )
    for index, axis_name in enumerate(("x", "y", "z")):
        low = lows[index]
        high = highs[index]
        if not _finite_number(low) or not _finite_number(high):
            _add(
                diagnostics,
                "nonfinite_root_bounds",
                f"Root bounds on axis {axis_name} must be finite.",
                path=f"root_bounds.{axis_name}",
            )
        elif float(high) <= float(low):
            _add(
                diagnostics,
                "nonpositive_root_extent",
                f"Root bounds on axis {axis_name} must have positive extent.",
                path=f"root_bounds.{axis_name}",
            )


def _validate_split(
    node: SplitNode,
    path: str,
    diagnostics: list[ValidationDiagnostic],
) -> list[tuple[GrammarNodeBase, str]]:
    """Validate one split and return ordered traversable descendants."""
    node_id = _display_node_id(node)
    if getattr(node, "type", None) != "split":
        _add(
            diagnostics,
            "invalid_node_discriminator",
            "SplitNode discriminator must be 'split'.",
            node_id=node_id,
            path=f"{path}.type",
        )
    if not isinstance(getattr(node, "axis", None), Axis):
        _add(
            diagnostics,
            "invalid_split_axis",
            "Split axis must be one of x, y, or z.",
            node_id=node_id,
            path=f"{path}.axis",
        )

    children = getattr(node, "children", None)
    if not isinstance(children, tuple):
        _add(
            diagnostics,
            "invalid_split_children",
            "Split children must be an ordered tuple.",
            node_id=node_id,
            path=f"{path}.children",
        )
        return []
    if len(children) < 2:
        _add(
            diagnostics,
            "split_too_few_children",
            "Split must contain at least two children.",
            node_id=node_id,
            path=f"{path}.children",
        )

    valid_weights: list[float] = []
    descendants: list[tuple[GrammarNodeBase, str]] = []
    for index, child in enumerate(children):
        child_path = f"{path}.children[{index}]"
        if not isinstance(child, SplitChild):
            _add(
                diagnostics,
                "invalid_split_child",
                "Split entry must be a SplitChild.",
                node_id=node_id,
                path=child_path,
            )
            continue
        weight = getattr(child, "weight", None)
        if not _finite_number(weight) or float(weight) <= 0:
            _add(
                diagnostics,
                "invalid_split_weight",
                "Split child weight must be finite and strictly positive.",
                node_id=node_id,
                path=f"{child_path}.weight",
            )
        else:
            valid_weights.append(float(weight))
        child_node = getattr(child, "node", None)
        if isinstance(child_node, (SplitNode, RepeatNode, TerminalNode)):
            descendants.append((child_node, f"{child_path}.node"))
        else:
            _add(
                diagnostics,
                "missing_split_child_node",
                "Split child must contain a grammar node.",
                node_id=node_id,
                path=f"{child_path}.node",
            )

    if len(valid_weights) == len(children):
        try:
            weight_sum = math.fsum(valid_weights)
        except (OverflowError, ValueError):
            weight_sum = float("inf")
        if not math.isfinite(weight_sum) or weight_sum <= 0:
            _add(
                diagnostics,
                "invalid_split_weight_sum",
                "Sum of split weights must be finite and greater than zero.",
                node_id=node_id,
                path=f"{path}.children",
            )
    return descendants


def _validate_repeat(
    node: RepeatNode,
    path: str,
    diagnostics: list[ValidationDiagnostic],
) -> list[tuple[GrammarNodeBase, str]]:
    """Validate one repeat without inventing a physical fit calculation."""
    node_id = _display_node_id(node)
    if getattr(node, "type", None) != "repeat":
        _add(
            diagnostics,
            "invalid_node_discriminator",
            "RepeatNode discriminator must be 'repeat'.",
            node_id=node_id,
            path=f"{path}.type",
        )
    if not isinstance(getattr(node, "axis", None), Axis):
        _add(
            diagnostics,
            "invalid_repeat_axis",
            "Repeat axis must be one of x, y, or z.",
            node_id=node_id,
            path=f"{path}.axis",
        )
    count = getattr(node, "count", None)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        _add(
            diagnostics,
            "invalid_repeat_count",
            "Repeat count must be an integer of at least one.",
            node_id=node_id,
            path=f"{path}.count",
        )
    spacing = getattr(node, "spacing", None)
    if not _finite_number(spacing) or float(spacing) < 0:
        _add(
            diagnostics,
            "invalid_repeat_spacing",
            "Repeat spacing must be finite and nonnegative.",
            node_id=node_id,
            path=f"{path}.spacing",
        )
    element = getattr(node, "element", None)
    if not isinstance(element, (SplitNode, RepeatNode, TerminalNode)):
        _add(
            diagnostics,
            "missing_repeat_element",
            "Repeat must contain one grammar element.",
            node_id=node_id,
            path=f"{path}.element",
        )
        return []
    return [(element, f"{path}.element")]


def _validate_terminal(
    node: TerminalNode,
    path: str,
    diagnostics: list[ValidationDiagnostic],
) -> list[tuple[GrammarNodeBase, str]]:
    """Validate terminal semantics and scalar/string attributes."""
    node_id = _display_node_id(node)
    if getattr(node, "type", None) != "terminal":
        _add(
            diagnostics,
            "invalid_node_discriminator",
            "TerminalNode discriminator must be 'terminal'.",
            node_id=node_id,
            path=f"{path}.type",
        )
    if not _nonempty_string(getattr(node, "semantic_class", None)):
        _add(
            diagnostics,
            "empty_semantic_class",
            "Terminal semantic class must be nonempty after trimming.",
            node_id=node_id,
            path=f"{path}.semantic_class",
        )
    if not isinstance(getattr(node, "geometry", None), GeometryType):
        _add(
            diagnostics,
            "invalid_geometry_type",
            "Terminal geometry must be box, plane, or empty.",
            node_id=node_id,
            path=f"{path}.geometry",
        )
    attributes = getattr(node, "attributes", None)
    if not isinstance(attributes, Mapping):
        _add(
            diagnostics,
            "invalid_attributes",
            "Terminal attributes must be a mapping.",
            node_id=node_id,
            path=f"{path}.attributes",
        )
        return []
    for key, value in attributes.items():
        attribute_path = f"{path}.attributes"
        if not isinstance(key, str) or not key:
            _add(
                diagnostics,
                "invalid_attribute_key",
                "Terminal attribute keys must be nonempty strings.",
                node_id=node_id,
                path=attribute_path,
            )
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            _add(
                diagnostics,
                "invalid_attribute_value",
                "Terminal attributes must be strings, integers, or finite numbers.",
                node_id=node_id,
                path=f"{attribute_path}.{key}",
            )
        elif isinstance(value, float) and not math.isfinite(value):
            _add(
                diagnostics,
                "nonfinite_attribute_value",
                "Numeric terminal attributes must be finite.",
                node_id=node_id,
                path=f"{attribute_path}.{key}",
            )
    return []


def _add(
    diagnostics: list[ValidationDiagnostic],
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    path: str | None = None,
) -> None:
    """Append one error diagnostic in traversal order."""
    diagnostics.append(
        ValidationDiagnostic(
            code=code,
            severity=ValidationSeverity.ERROR,
            message=message,
            node_id=node_id,
            path=path,
        )
    )


def _positive_integer(value: object, name: str) -> int:
    """Validate a positive integer traversal configuration."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _display_node_id(node: object) -> str | None:
    """Return a usable diagnostic identifier without trusting the model."""
    node_id = getattr(node, "node_id", None)
    return node_id if isinstance(node_id, str) else None


def _nonempty_string(value: object) -> bool:
    """Return whether a value is a nonempty string after trimming."""
    return isinstance(value, str) and bool(value.strip())


def _finite_number(value: object) -> bool:
    """Return whether a value is a finite non-boolean number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False
