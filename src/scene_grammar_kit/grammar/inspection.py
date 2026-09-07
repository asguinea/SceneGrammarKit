"""Deterministic symbolic tree inspection and grammar summaries."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from scene_grammar_kit.grammar.errors import (
    GrammarExpansionLimitError,
    GrammarInspectionError,
)
from scene_grammar_kit.grammar.models import (
    GrammarNodeBase,
    RepeatNode,
    SceneGrammar,
    SplitNode,
    TerminalNode,
)
from scene_grammar_kit.grammar.serialization import grammar_to_canonical_json
from scene_grammar_kit.grammar.validation import (
    DEFAULT_MAX_GRAMMAR_DEPTH,
    validate_grammar,
)

DEFAULT_EXPANSION_LIMIT = 1_000_000_000


@dataclass(frozen=True, slots=True)
class GrammarSummary:
    """Deterministic statistics for one symbolic grammar tree.

    ``maximum_depth`` uses root depth zero. Frequency tables count symbolic
    terminal nodes, while ``expanded_terminal_instance_count`` conceptually
    multiplies terminal counts through repeats without materializing instances.
    """

    total_node_count: int
    split_node_count: int
    repeat_node_count: int
    terminal_node_count: int
    maximum_depth: int
    total_split_child_count: int
    expanded_terminal_instance_count: int
    canonical_byte_size: int
    semantic_class_frequencies: Mapping[str, int] = field(default_factory=dict)
    geometry_type_frequencies: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze defensive, deterministically ordered frequency tables."""
        object.__setattr__(
            self,
            "semantic_class_frequencies",
            MappingProxyType(dict(sorted(self.semantic_class_frequencies.items()))),
        )
        object.__setattr__(
            self,
            "geometry_type_frequencies",
            MappingProxyType(dict(sorted(self.geometry_type_frequencies.items()))),
        )


def grammar_tree_to_text(
    grammar: SceneGrammar,
    *,
    max_depth: int = DEFAULT_MAX_GRAMMAR_DEPTH,
) -> str:
    """Render a deterministic ASCII-only symbolic tree ending in one newline.

    Inspection refuses grammars with semantic errors. Iterative traversal and
    validation depth/cycle safeguards avoid uncontrolled recursion.
    """
    _require_valid(grammar, max_depth=max_depth)
    bounds = grammar.root_bounds
    lines = [
        f"Scene {grammar.scene_id} [schema={grammar.schema_version}, "
        f"units={grammar.units}]",
        f"Bounds min={_vector_text(bounds.minimum.as_tuple())} "
        f"max={_vector_text(bounds.maximum.as_tuple())}",
    ]
    stack: list[tuple[str, object, int, str]] = [("node", grammar.root, 0, "root")]
    while stack:
        kind, value, indentation, label = stack.pop()
        prefix = "  " * indentation
        if kind == "text":
            lines.append(f"{prefix}{label}")
            continue

        node = value
        if isinstance(node, SplitNode):
            lines.append(
                f"{prefix}{label}: Split id={node.node_id} axis={node.axis.value}"
            )
            for index in range(len(node.children) - 1, -1, -1):
                child = node.children[index]
                stack.append(("node", child.node, indentation + 2, "node"))
                stack.append(
                    (
                        "text",
                        child,
                        indentation + 1,
                        f"child[{index}] weight={_number_text(child.weight)}",
                    )
                )
        elif isinstance(node, RepeatNode):
            lines.append(
                f"{prefix}{label}: Repeat id={node.node_id} "
                f"axis={node.axis.value} count={node.count} "
                f"spacing={_number_text(node.spacing)}"
            )
            stack.append(("node", node.element, indentation + 1, "element"))
        elif isinstance(node, TerminalNode):
            lines.append(
                f"{prefix}{label}: Terminal id={node.node_id} "
                f"class={node.semantic_class} geometry={node.geometry.value}"
            )
    return "\n".join(lines) + "\n"


def summarize_grammar(
    grammar: SceneGrammar,
    *,
    max_depth: int = DEFAULT_MAX_GRAMMAR_DEPTH,
    expansion_limit: int = DEFAULT_EXPANSION_LIMIT,
) -> GrammarSummary:
    """Return symbolic counts and safe conceptual repeat expansion statistics."""
    _positive_integer(expansion_limit, "expansion_limit")
    _require_valid(grammar, max_depth=max_depth)

    total_nodes = 0
    split_nodes = 0
    repeat_nodes = 0
    terminal_nodes = 0
    maximum_depth = 0
    split_children = 0
    expanded_terminals = 0
    semantic_classes: Counter[str] = Counter()
    geometry_types: Counter[str] = Counter()

    stack: list[tuple[GrammarNodeBase, int, int]] = [(grammar.root, 0, 1)]
    while stack:
        node, depth, multiplier = stack.pop()
        total_nodes += 1
        maximum_depth = max(maximum_depth, depth)
        if isinstance(node, SplitNode):
            split_nodes += 1
            split_children += len(node.children)
            for child in reversed(node.children):
                stack.append((child.node, depth + 1, multiplier))
        elif isinstance(node, RepeatNode):
            repeat_nodes += 1
            repeated_multiplier = _checked_multiply(
                multiplier,
                node.count,
                expansion_limit,
                node.node_id,
            )
            stack.append((node.element, depth + 1, repeated_multiplier))
        elif isinstance(node, TerminalNode):
            terminal_nodes += 1
            if expanded_terminals > expansion_limit - multiplier:
                raise GrammarExpansionLimitError(
                    "Expanded terminal-instance count exceeds safety limit "
                    f"{expansion_limit} at terminal {node.node_id!r}."
                )
            expanded_terminals += multiplier
            semantic_classes[node.semantic_class] += 1
            geometry_types[node.geometry.value] += 1

    canonical_bytes = len(grammar_to_canonical_json(grammar).encode("utf-8"))
    return GrammarSummary(
        total_node_count=total_nodes,
        split_node_count=split_nodes,
        repeat_node_count=repeat_nodes,
        terminal_node_count=terminal_nodes,
        maximum_depth=maximum_depth,
        total_split_child_count=split_children,
        expanded_terminal_instance_count=expanded_terminals,
        canonical_byte_size=canonical_bytes,
        semantic_class_frequencies=semantic_classes,
        geometry_type_frequencies=geometry_types,
    )


def format_grammar_summary(summary: GrammarSummary) -> str:
    """Format summary statistics deterministically for the CLI."""
    semantic = _frequency_text(summary.semantic_class_frequencies)
    geometry = _frequency_text(summary.geometry_type_frequencies)
    return (
        "\n".join(
            [
                "Summary",
                f"  nodes={summary.total_node_count} "
                f"splits={summary.split_node_count} "
                f"repeats={summary.repeat_node_count} "
                f"terminals={summary.terminal_node_count}",
                f"  max_depth={summary.maximum_depth} "
                f"split_children={summary.total_split_child_count} "
                f"expanded_terminals="
                f"{summary.expanded_terminal_instance_count}",
                f"  canonical_bytes={summary.canonical_byte_size}",
                f"  semantic_classes={semantic}",
                f"  geometry_types={geometry}",
            ]
        )
        + "\n"
    )


def _require_valid(grammar: SceneGrammar, *, max_depth: int) -> None:
    """Reject invalid grammars before deterministic inspection."""
    report = validate_grammar(grammar, max_depth=max_depth)
    if not report.is_valid:
        first = report.diagnostics[0]
        raise GrammarInspectionError(
            f"Cannot inspect invalid grammar: {first.code} at "
            f"{first.path or '<unknown>'}: {first.message}"
        )


def _checked_multiply(
    value: int,
    factor: int,
    limit: int,
    node_id: str,
) -> int:
    """Multiply repeat counts without exceeding the configured limit."""
    if value > limit // factor:
        raise GrammarExpansionLimitError(
            "Expanded terminal-instance count exceeds safety limit "
            f"{limit} at repeat {node_id!r}."
        )
    return value * factor


def _positive_integer(value: object, name: str) -> int:
    """Validate a positive integer inspection configuration."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _number_text(value: float) -> str:
    """Format finite schema numbers consistently and compactly."""
    return format(value, ".15g")


def _vector_text(values: tuple[float, float, float]) -> str:
    """Format one vector using deterministic compact numbers."""
    return "(" + ",".join(_number_text(value) for value in values) + ")"


def _frequency_text(frequencies: Mapping[str, int]) -> str:
    """Format a sorted frequency mapping without environment dependence."""
    if not frequencies:
        return "-"
    return ",".join(f"{key}:{value}" for key, value in frequencies.items())
