"""Deterministic symbolic-grammar execution into flat semantic primitives."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from scene_grammar_kit.geometry.bounds import (
    bounds_contain,
    bounds_have_positive_extent,
    repeat_bound_at,
    repeat_bounds,
    split_bounds_by_weights,
)
from scene_grammar_kit.geometry.errors import (
    ExecutionDepthError,
    GeometryBoundsError,
    GeometryValidationError,
    PrimitiveLimitError,
)
from scene_grammar_kit.geometry.models import (
    EXECUTION_POLICY_VERSION,
    ExecutedScene,
    ExecutionReport,
    SemanticPrimitive,
)
from scene_grammar_kit.grammar import (
    GeometryType,
    RepeatNode,
    SceneGrammar,
    SplitNode,
    TerminalNode,
    grammar_to_canonical_json,
    validate_grammar,
)
from scene_grammar_kit.grammar.models import GrammarNodeBase

DEFAULT_MAXIMUM_EXECUTION_DEPTH = 128
DEFAULT_MAXIMUM_PRIMITIVES = 1_000_000


@dataclass(frozen=True, slots=True)
class _SubtreeCounts:
    renderable: int
    empty: int


@dataclass(frozen=True, slots=True)
class _ExecutionAnalysis:
    subtree_counts: dict[int, _SubtreeCounts]
    symbolic_node_count: int
    maximum_depth: int


@dataclass(frozen=True, slots=True)
class _Frame:
    node: GrammarNodeBase
    bounds: object
    path: str
    repeat_indices: tuple[int, ...]
    depth: int


def execute_grammar(
    grammar: SceneGrammar,
    *,
    maximum_depth: int = DEFAULT_MAXIMUM_EXECUTION_DEPTH,
    maximum_primitives: int = DEFAULT_MAXIMUM_PRIMITIVES,
) -> ExecutedScene:
    """Execute a valid grammar deterministically into ordered flat primitives.

    Execution performs semantic validation first, preflights conceptual
    renderable counts before materializing repeat instances, and uses iterative
    traversal to avoid uncontrolled Python recursion.
    """
    _positive_integer(maximum_depth, "maximum_depth")
    _positive_integer(maximum_primitives, "maximum_primitives")
    if not isinstance(grammar, SceneGrammar):
        raise TypeError("grammar must be a SceneGrammar")

    validation = validate_grammar(grammar, max_depth=maximum_depth)
    if not validation.is_valid:
        first = validation.diagnostics[0]
        if first.code == "maximum_depth_exceeded":
            raise ExecutionDepthError(
                f"Execution depth limit exceeded at {first.path}: {first.message}"
            )
        raise GeometryValidationError(
            f"Grammar is not executable: {first.code} at "
            f"{first.path or '<unknown>'}: {first.message}"
        )

    analysis = _analyze_execution(grammar.root)
    root_counts = analysis.subtree_counts[id(grammar.root)]
    if root_counts.renderable > maximum_primitives:
        raise PrimitiveLimitError(
            f"Execution would create {root_counts.renderable} primitives, "
            f"exceeding maximum_primitives={maximum_primitives}"
        )

    grammar_bytes = grammar_to_canonical_json(grammar).encode("utf-8")
    grammar_sha256 = hashlib.sha256(grammar_bytes).hexdigest()
    primitives: list[SemanticPrimitive] = []
    stack: list[_Frame] = [
        _Frame(
            node=grammar.root,
            bounds=grammar.root_bounds,
            path="root",
            repeat_indices=(),
            depth=0,
        )
    ]

    while stack:
        frame = stack.pop()
        if frame.depth > maximum_depth:
            raise ExecutionDepthError(
                f"Execution depth {frame.depth} exceeds {maximum_depth} at {frame.path}"
            )
        bounds = frame.bounds
        if not bounds_have_positive_extent(bounds):  # type: ignore[arg-type]
            raise GeometryBoundsError(
                f"Inherited bounds must have positive extent at {frame.path}"
            )
        if not bounds_contain(grammar.root_bounds, bounds):  # type: ignore[arg-type]
            raise GeometryBoundsError(
                f"Inherited bounds escape root bounds at {frame.path}"
            )

        node = frame.node
        if isinstance(node, SplitNode):
            child_bounds = split_bounds_by_weights(
                bounds,  # type: ignore[arg-type]
                node.axis,
                tuple(child.weight for child in node.children),
            )
            for index in range(len(node.children) - 1, -1, -1):
                child = node.children[index]
                stack.append(
                    _Frame(
                        node=child.node,
                        bounds=child_bounds[index],
                        path=f"{frame.path}.children[{index}].node",
                        repeat_indices=frame.repeat_indices,
                        depth=frame.depth + 1,
                    )
                )
        elif isinstance(node, RepeatNode):
            element_counts = analysis.subtree_counts[id(node.element)]
            if element_counts.renderable == 0:
                instance_bounds = (
                    repeat_bound_at(
                        bounds,  # type: ignore[arg-type]
                        node.axis,
                        node.count,
                        node.spacing,
                        0,
                    ),
                )
                instance_indices = (0,)
            else:
                instance_bounds = repeat_bounds(
                    bounds,  # type: ignore[arg-type]
                    node.axis,
                    node.count,
                    node.spacing,
                )
                instance_indices = tuple(range(node.count))
            for offset in range(len(instance_indices) - 1, -1, -1):
                repeat_index = instance_indices[offset]
                stack.append(
                    _Frame(
                        node=node.element,
                        bounds=instance_bounds[offset],
                        path=(f"{frame.path}.instances[{repeat_index}].element"),
                        repeat_indices=frame.repeat_indices + (repeat_index,),
                        depth=frame.depth + 1,
                    )
                )
        elif isinstance(node, TerminalNode):
            if node.geometry is GeometryType.EMPTY:
                continue
            if len(primitives) >= maximum_primitives:
                raise PrimitiveLimitError(
                    f"Execution reached maximum_primitives={maximum_primitives}"
                )
            primitive = _terminal_primitive(
                node,
                bounds,  # type: ignore[arg-type]
                frame.path,
                frame.repeat_indices,
                grammar.root_bounds,
            )
            primitives.append(primitive)

    primitive_tuple = tuple(primitives)
    box_count = sum(
        primitive.geometry is GeometryType.BOX for primitive in primitive_tuple
    )
    plane_count = sum(
        primitive.geometry is GeometryType.PLANE for primitive in primitive_tuple
    )
    report = ExecutionReport(
        success=True,
        symbolic_node_count_visited=analysis.symbolic_node_count,
        primitive_count=len(primitive_tuple),
        box_count=box_count,
        plane_count=plane_count,
        empty_terminal_count=root_counts.empty,
        maximum_execution_depth=analysis.maximum_depth,
        grammar_sha256=grammar_sha256,
        warnings=(),
        execution_policy_version=EXECUTION_POLICY_VERSION,
    )
    return ExecutedScene(
        scene_id=grammar.scene_id,
        grammar_schema_version=grammar.schema_version,
        units=grammar.units,
        root_bounds=grammar.root_bounds,
        primitives=primitive_tuple,
        grammar_sha256=grammar_sha256,
        report=report,
        execution_policy_version=EXECUTION_POLICY_VERSION,
    )


def _terminal_primitive(
    node: TerminalNode,
    bounds: object,
    instance_path: str,
    repeat_indices: tuple[int, ...],
    root_bounds: object,
) -> SemanticPrimitive:
    """Create one box or proxy-plane primitive with provenance."""
    if not bounds_have_positive_extent(bounds):  # type: ignore[arg-type]
        raise GeometryBoundsError(f"Terminal {node.node_id!r} has non-positive bounds")
    if not bounds_contain(root_bounds, bounds):  # type: ignore[arg-type]
        raise GeometryBoundsError(f"Terminal {node.node_id!r} lies outside root bounds")
    primitive_id = (
        "primitive-" + hashlib.sha256(instance_path.encode("utf-8")).hexdigest()
    )
    return SemanticPrimitive(
        primitive_id=primitive_id,
        source_terminal_id=node.node_id,
        semantic_class=node.semantic_class,
        geometry=node.geometry,
        bounds=bounds,  # type: ignore[arg-type]
        attributes=dict(node.attributes),
        instance_path=instance_path,
        repeat_indices=repeat_indices,
    )


def _analyze_execution(root: GrammarNodeBase) -> _ExecutionAnalysis:
    """Count symbolic nodes and conceptual outputs by iterative postorder."""
    subtree_counts: dict[int, _SubtreeCounts] = {}
    symbolic_node_count = 0
    maximum_depth = 0
    stack: list[tuple[GrammarNodeBase, int, bool]] = [(root, 0, False)]
    while stack:
        node, depth, exiting = stack.pop()
        maximum_depth = max(maximum_depth, depth)
        if not exiting:
            symbolic_node_count += 1
            stack.append((node, depth, True))
            if isinstance(node, SplitNode):
                for child in reversed(node.children):
                    stack.append((child.node, depth + 1, False))
            elif isinstance(node, RepeatNode):
                stack.append((node.element, depth + 1, False))
            continue

        if isinstance(node, TerminalNode):
            subtree_counts[id(node)] = _SubtreeCounts(
                renderable=0 if node.geometry is GeometryType.EMPTY else 1,
                empty=1 if node.geometry is GeometryType.EMPTY else 0,
            )
        elif isinstance(node, SplitNode):
            subtree_counts[id(node)] = _SubtreeCounts(
                renderable=sum(
                    subtree_counts[id(child.node)].renderable for child in node.children
                ),
                empty=sum(
                    subtree_counts[id(child.node)].empty for child in node.children
                ),
            )
        elif isinstance(node, RepeatNode):
            element = subtree_counts[id(node.element)]
            subtree_counts[id(node)] = _SubtreeCounts(
                renderable=element.renderable * node.count,
                empty=element.empty * node.count,
            )
    return _ExecutionAnalysis(
        subtree_counts=subtree_counts,
        symbolic_node_count=symbolic_node_count,
        maximum_depth=maximum_depth,
    )


def _positive_integer(value: object, name: str) -> int:
    """Require a positive integer execution configuration."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value
