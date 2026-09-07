"""Deterministic symbolic and executed-geometry comparison helpers."""

from __future__ import annotations

from dataclasses import dataclass

from scene_grammar_kit.editing.operations import EditOperation, operation_target_id
from scene_grammar_kit.editing.reports import GeometryDiff, SymbolicDiff
from scene_grammar_kit.geometry import ExecutedScene, SemanticPrimitive
from scene_grammar_kit.grammar import RepeatNode, SceneGrammar, SplitNode, TerminalNode
from scene_grammar_kit.grammar.models import GrammarNodeBase

DEFAULT_GEOMETRY_DETAIL_LIMIT = 1_000


@dataclass(frozen=True, slots=True)
class NodeRecord:
    """One immutable internal node-index entry."""

    node: GrammarNodeBase
    parent_id: str | None
    path: str
    ancestor_ids: tuple[str, ...]
    relation_index: int | None


def build_node_index(grammar: SceneGrammar) -> dict[str, NodeRecord]:
    """Build a deterministic node-ID index by iterative preorder traversal."""
    records: dict[str, NodeRecord] = {}
    stack: list[
        tuple[GrammarNodeBase, str | None, str, tuple[str, ...], int | None]
    ] = [(grammar.root, None, "root", (), None)]
    while stack:
        node, parent_id, path, ancestors, relation_index = stack.pop()
        records[node.node_id] = NodeRecord(
            node=node,
            parent_id=parent_id,
            path=path,
            ancestor_ids=ancestors,
            relation_index=relation_index,
        )
        child_ancestors = ancestors + (node.node_id,)
        if isinstance(node, SplitNode):
            for index in range(len(node.children) - 1, -1, -1):
                child = node.children[index]
                stack.append(
                    (
                        child.node,
                        node.node_id,
                        f"{path}.children[{index}].node",
                        child_ancestors,
                        index,
                    )
                )
        elif isinstance(node, RepeatNode):
            stack.append(
                (
                    node.element,
                    node.node_id,
                    f"{path}.element",
                    child_ancestors,
                    0,
                )
            )
    return records


def symbolic_diff(
    before: SceneGrammar,
    after: SceneGrammar,
    operations: tuple[EditOperation, ...],
) -> SymbolicDiff:
    """Compare local node signatures and report reconstruction ancestors."""
    before_index = build_node_index(before)
    after_index = build_node_index(after)
    before_ids = tuple(sorted(before_index))
    after_ids = tuple(sorted(after_index))
    common = set(before_index) & set(after_index)
    directly_modified = tuple(
        sorted(
            node_id
            for node_id in common
            if _local_signature(before_index[node_id].node)
            != _local_signature(after_index[node_id].node)
        )
    )
    targets = tuple(operation_target_id(operation) for operation in operations)
    affected_ancestors = tuple(
        sorted(
            {
                ancestor
                for target in targets
                if target in before_index
                for ancestor in before_index[target].ancestor_ids
            }
            - set(directly_modified)
        )
    )
    return SymbolicDiff(
        node_ids_before=before_ids,
        node_ids_after=after_ids,
        added_node_ids=tuple(sorted(set(after_ids) - set(before_ids))),
        removed_node_ids=tuple(sorted(set(before_ids) - set(after_ids))),
        directly_modified_node_ids=directly_modified,
        affected_ancestor_node_ids=affected_ancestors,
        unchanged_node_ids=tuple(sorted(common - set(directly_modified))),
        target_node_ids=targets,
        target_paths_before=tuple(before_index[target].path for target in targets),
        target_paths_after=tuple(after_index[target].path for target in targets),
    )


def geometry_diff(
    before: ExecutedScene,
    after: ExecutedScene,
    *,
    detail_limit: int = DEFAULT_GEOMETRY_DETAIL_LIMIT,
) -> GeometryDiff:
    """Match complete primitive values by deterministic primitive ID."""
    before_map = {item.primitive_id: item for item in before.primitives}
    after_map = {item.primitive_id: item for item in after.primitives}
    added = tuple(sorted(set(after_map) - set(before_map)))
    removed = tuple(sorted(set(before_map) - set(after_map)))
    common = set(before_map) & set(after_map)
    modified = tuple(
        sorted(
            primitive_id
            for primitive_id in common
            if _primitive_signature(before_map[primitive_id])
            != _primitive_signature(after_map[primitive_id])
        )
    )
    unchanged = tuple(sorted(common - set(modified)))
    details_truncated = any(
        len(values) > detail_limit for values in (added, removed, modified, unchanged)
    )
    return GeometryDiff(
        primitive_count_before=len(before.primitives),
        primitive_count_after=len(after.primitives),
        added_primitive_count=len(added),
        removed_primitive_count=len(removed),
        modified_primitive_count=len(modified),
        unchanged_primitive_count=len(unchanged),
        box_count_before=before.report.box_count,
        box_count_after=after.report.box_count,
        plane_count_before=before.report.plane_count,
        plane_count_after=after.report.plane_count,
        empty_terminal_count_before=before.report.empty_terminal_count,
        empty_terminal_count_after=after.report.empty_terminal_count,
        grammar_sha256_before=before.grammar_sha256,
        grammar_sha256_after=after.grammar_sha256,
        added_primitive_ids=added[:detail_limit],
        removed_primitive_ids=removed[:detail_limit],
        modified_primitive_ids=modified[:detail_limit],
        unchanged_primitive_ids=unchanged[:detail_limit],
        detail_list_limit=detail_limit,
        details_truncated=details_truncated,
    )


def _local_signature(node: GrammarNodeBase) -> tuple[object, ...]:
    if isinstance(node, SplitNode):
        return (
            node.node_id,
            node.type,
            node.axis.value,
            tuple(child.weight for child in node.children),
            tuple(child.node.node_id for child in node.children),
        )
    if isinstance(node, RepeatNode):
        return (
            node.node_id,
            node.type,
            node.axis.value,
            node.count,
            node.spacing,
            node.element.node_id,
        )
    if isinstance(node, TerminalNode):
        return (
            node.node_id,
            node.type,
            node.semantic_class,
            node.geometry.value,
            tuple(sorted(node.attributes.items())),
        )
    raise TypeError(f"Unsupported grammar node: {type(node).__name__}")


def _primitive_signature(primitive: SemanticPrimitive) -> tuple[object, ...]:
    return (
        primitive.primitive_id,
        primitive.source_terminal_id,
        primitive.semantic_class,
        primitive.geometry.value,
        primitive.bounds.minimum.as_tuple(),
        primitive.bounds.maximum.as_tuple(),
        tuple(sorted(primitive.attributes.items())),
        primitive.instance_path,
        primitive.repeat_indices,
    )
