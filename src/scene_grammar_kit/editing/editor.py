"""Transactional immutable application of typed grammar edit operations."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from scene_grammar_kit.editing.diff import (
    NodeRecord,
    build_node_index,
    geometry_diff,
    symbolic_diff,
)
from scene_grammar_kit.editing.errors import (
    EditChildNotFoundError,
    EditExecutionError,
    EditTargetNotFoundError,
    EditTargetTypeError,
    EditValidationError,
    InvalidEditValueError,
)
from scene_grammar_kit.editing.operations import (
    EditOperation,
    SetRepeatCount,
    SetRepeatSpacing,
    SetSplitChildWeight,
    SubstituteTerminalClass,
)
from scene_grammar_kit.editing.reports import (
    EditRealization,
    EditReport,
    EditResult,
    RepeatCountRealization,
    RepeatSpacingRealization,
    SplitWeightRealization,
    TerminalSubstitutionRealization,
)
from scene_grammar_kit.geometry import (
    DEFAULT_MAXIMUM_EXECUTION_DEPTH,
    DEFAULT_MAXIMUM_PRIMITIVES,
    GeometryError,
    execute_grammar,
)
from scene_grammar_kit.grammar import (
    RepeatNode,
    SceneGrammar,
    SplitChild,
    SplitNode,
    TerminalNode,
    grammar_to_canonical_json,
    validate_grammar,
)
from scene_grammar_kit.grammar.models import GrammarNodeBase


def apply_edit(
    grammar: SceneGrammar,
    operation: EditOperation,
    *,
    verify_execution: bool = True,
    maximum_depth: int = DEFAULT_MAXIMUM_EXECUTION_DEPTH,
    maximum_primitives: int = DEFAULT_MAXIMUM_PRIMITIVES,
) -> EditResult:
    """Apply one immutable operation as an atomic editing transaction."""
    return apply_edits(
        grammar,
        (operation,),
        verify_execution=verify_execution,
        maximum_depth=maximum_depth,
        maximum_primitives=maximum_primitives,
    )


def apply_edits(
    grammar: SceneGrammar,
    operations: Sequence[EditOperation],
    *,
    verify_execution: bool = True,
    maximum_depth: int = DEFAULT_MAXIMUM_EXECUTION_DEPTH,
    maximum_primitives: int = DEFAULT_MAXIMUM_PRIMITIVES,
) -> EditResult:
    """Apply ordered operations atomically without mutating the input grammar."""
    if not isinstance(grammar, SceneGrammar):
        raise TypeError("grammar must be a SceneGrammar")
    if isinstance(operations, (str, bytes)) or not isinstance(operations, Sequence):
        raise TypeError("operations must be a sequence of edit operations")
    operation_tuple = tuple(operations)
    if not operation_tuple:
        raise InvalidEditValueError("operations must not be empty")
    if any(not _is_operation(operation) for operation in operation_tuple):
        raise TypeError("operations contains an unsupported edit operation")
    if not isinstance(verify_execution, bool):
        raise ValueError("verify_execution must be a boolean")

    _require_valid(grammar, maximum_depth, "input grammar")
    original_execution = None
    if verify_execution:
        original_execution = _execute_verified(
            grammar,
            maximum_depth,
            maximum_primitives,
            "original grammar",
        )

    current = grammar
    realizations: list[EditRealization] = []
    for operation in operation_tuple:
        current, realization = _apply_one(
            current,
            operation,
            execution_verified=verify_execution,
        )
        realizations.append(realization)

    _require_valid(current, maximum_depth, "edited grammar")
    edited_execution = None
    geometry = None
    if verify_execution:
        edited_execution = _execute_verified(
            current,
            maximum_depth,
            maximum_primitives,
            "edited grammar",
        )
        geometry = geometry_diff(original_execution, edited_execution)

    original_hash = _grammar_hash(grammar)
    edited_hash = _grammar_hash(current)
    symbolic = symbolic_diff(grammar, current, operation_tuple)
    report = EditReport(
        success=True,
        grammar_schema_version=grammar.schema_version,
        original_grammar_sha256=original_hash,
        edited_grammar_sha256=edited_hash,
        operations=operation_tuple,
        symbolic_diff=symbolic,
        realizations=tuple(realizations),
        geometry_diff=geometry,
        validation_succeeded=True,
        execution_verification_succeeded=verify_execution,
        warnings=(
            ()
            if verify_execution
            else ("execution verification was explicitly disabled",)
        ),
    )
    return EditResult(
        original_grammar=grammar,
        edited_grammar=current,
        operations=operation_tuple,
        report=report,
        original_execution=original_execution,
        edited_execution=edited_execution,
    )


def _apply_one(
    grammar: SceneGrammar,
    operation: EditOperation,
    *,
    execution_verified: bool,
) -> tuple[SceneGrammar, EditRealization]:
    index = build_node_index(grammar)
    if isinstance(operation, SetSplitChildWeight):
        record = _target(index, operation.split_node_id)
        if not isinstance(record.node, SplitNode):
            raise EditTargetTypeError(
                f"Target {operation.split_node_id!r} is not a SplitNode"
            )
        split = record.node
        child_index = next(
            (
                index
                for index, child in enumerate(split.children)
                if child.node.node_id == operation.child_node_id
            ),
            None,
        )
        if child_index is None:
            raise EditChildNotFoundError(
                f"Node {operation.child_node_id!r} is not a direct child of "
                f"split {operation.split_node_id!r}"
            )
        old_weight = split.children[child_index].weight
        if operation.new_weight == old_weight:
            raise InvalidEditValueError("new split weight must change the value")
        before_sum = math.fsum(child.weight for child in split.children)
        children = list(split.children)
        children[child_index] = SplitChild(
            weight=operation.new_weight,
            node=children[child_index].node,
        )
        replacement = SplitNode(
            node_id=split.node_id,
            axis=split.axis,
            children=tuple(children),
        )
        after_sum = math.fsum(child.weight for child in replacement.children)
        sibling_sum = math.fsum(
            child.weight
            for index, child in enumerate(split.children)
            if index != child_index
        )
        realization: EditRealization = SplitWeightRealization(
            operation_type=operation.operation_type,
            split_node_id=split.node_id,
            child_node_id=operation.child_node_id,
            old_stored_weight=old_weight,
            requested_new_stored_weight=operation.new_weight,
            realized_new_stored_weight=replacement.children[child_index].weight,
            old_normalized_fraction=old_weight / before_sum,
            new_normalized_fraction=operation.new_weight / after_sum,
            normalized_fraction_delta=(
                operation.new_weight / after_sum - old_weight / before_sum
            ),
            sibling_count=len(split.children) - 1,
            sibling_weight_sum_before=sibling_sum,
            sibling_weight_sum_after=sibling_sum,
            direct_child_weight_sum_before=before_sum,
            direct_child_weight_sum_after=after_sum,
        )
    elif isinstance(operation, SetRepeatCount):
        record = _target(index, operation.repeat_node_id)
        if not isinstance(record.node, RepeatNode):
            raise EditTargetTypeError(
                f"Target {operation.repeat_node_id!r} is not a RepeatNode"
            )
        repeat = record.node
        if operation.new_count == repeat.count:
            raise InvalidEditValueError("new repeat count must change the value")
        replacement = RepeatNode(
            node_id=repeat.node_id,
            axis=repeat.axis,
            count=operation.new_count,
            spacing=repeat.spacing,
            element=repeat.element,
        )
        symbolic_count, conceptual_count = _terminal_counts(repeat.element)
        realization = RepeatCountRealization(
            operation_type=operation.operation_type,
            repeat_node_id=repeat.node_id,
            old_count=repeat.count,
            requested_count=operation.new_count,
            realized_count=replacement.count,
            symbolic_terminal_count_in_element=symbolic_count,
            conceptual_terminal_count_in_element=conceptual_count,
            conceptual_expanded_terminal_count_before=(conceptual_count * repeat.count),
            conceptual_expanded_terminal_count_after=(
                conceptual_count * replacement.count
            ),
            count_delta=replacement.count - repeat.count,
        )
    elif isinstance(operation, SetRepeatSpacing):
        record = _target(index, operation.repeat_node_id)
        if not isinstance(record.node, RepeatNode):
            raise EditTargetTypeError(
                f"Target {operation.repeat_node_id!r} is not a RepeatNode"
            )
        repeat = record.node
        if operation.new_spacing == repeat.spacing:
            raise InvalidEditValueError("new repeat spacing must change the value")
        replacement = RepeatNode(
            node_id=repeat.node_id,
            axis=repeat.axis,
            count=repeat.count,
            spacing=operation.new_spacing,
            element=repeat.element,
        )
        realization = RepeatSpacingRealization(
            operation_type=operation.operation_type,
            repeat_node_id=repeat.node_id,
            old_spacing=repeat.spacing,
            requested_spacing=operation.new_spacing,
            realized_spacing=replacement.spacing,
            repeat_count=repeat.count,
            parent_axis_occurrence_count=_occurrence_count(record, index),
            execution_verified=execution_verified,
        )
    elif isinstance(operation, SubstituteTerminalClass):
        record = _target(index, operation.terminal_node_id)
        if not isinstance(record.node, TerminalNode):
            raise EditTargetTypeError(
                f"Target {operation.terminal_node_id!r} is not a TerminalNode"
            )
        terminal = record.node
        if operation.new_semantic_class == terminal.semantic_class:
            raise InvalidEditValueError("new semantic class must change the value")
        replacement = TerminalNode(
            node_id=terminal.node_id,
            semantic_class=operation.new_semantic_class,
            geometry=terminal.geometry,
            attributes=terminal.attributes,
        )
        realization = TerminalSubstitutionRealization(
            operation_type=operation.operation_type,
            terminal_node_id=terminal.node_id,
            old_semantic_class=terminal.semantic_class,
            requested_semantic_class=operation.new_semantic_class,
            realized_semantic_class=replacement.semantic_class,
            geometry_type_preserved=replacement.geometry is terminal.geometry,
            attributes_preserved=(
                dict(replacement.attributes) == dict(terminal.attributes)
            ),
        )
    else:
        raise TypeError("Unsupported edit operation")

    new_root = _rebuild_path(record, replacement, index)
    return (
        SceneGrammar(
            schema_version=grammar.schema_version,
            scene_id=grammar.scene_id,
            units=grammar.units,
            root_bounds=grammar.root_bounds,
            root=new_root,  # type: ignore[arg-type]
        ),
        realization,
    )


def _rebuild_path(
    target: NodeRecord,
    replacement: GrammarNodeBase,
    index: dict[str, NodeRecord],
) -> GrammarNodeBase:
    current_record = target
    current_node = replacement
    while current_record.parent_id is not None:
        parent_record = index[current_record.parent_id]
        parent = parent_record.node
        if isinstance(parent, SplitNode):
            relation_index = current_record.relation_index
            if relation_index is None:
                raise EditValidationError("split child relation is missing")
            children = list(parent.children)
            child = children[relation_index]
            children[relation_index] = SplitChild(
                weight=child.weight,
                node=current_node,
            )
            current_node = SplitNode(
                node_id=parent.node_id,
                axis=parent.axis,
                children=tuple(children),
            )
        elif isinstance(parent, RepeatNode):
            current_node = RepeatNode(
                node_id=parent.node_id,
                axis=parent.axis,
                count=parent.count,
                spacing=parent.spacing,
                element=current_node,
            )
        else:
            raise EditValidationError(
                f"Terminal node {parent.node_id!r} cannot contain a child"
            )
        current_record = parent_record
    return current_node


def _target(index: dict[str, NodeRecord], node_id: str) -> NodeRecord:
    try:
        return index[node_id]
    except KeyError as exc:
        raise EditTargetNotFoundError(
            f"Edit target node ID was not found: {node_id!r}"
        ) from exc


def _terminal_counts(root: GrammarNodeBase) -> tuple[int, int]:
    symbolic = 0
    expanded: dict[int, int] = {}
    stack: list[tuple[GrammarNodeBase, bool]] = [(root, False)]
    while stack:
        node, exiting = stack.pop()
        if not exiting:
            stack.append((node, True))
            if isinstance(node, SplitNode):
                for child in reversed(node.children):
                    stack.append((child.node, False))
            elif isinstance(node, RepeatNode):
                stack.append((node.element, False))
            continue
        if isinstance(node, TerminalNode):
            symbolic += 1
            expanded[id(node)] = 1
        elif isinstance(node, SplitNode):
            expanded[id(node)] = sum(
                expanded[id(child.node)] for child in node.children
            )
        elif isinstance(node, RepeatNode):
            expanded[id(node)] = expanded[id(node.element)] * node.count
    return symbolic, expanded[id(root)]


def _occurrence_count(
    record: NodeRecord,
    index: dict[str, NodeRecord],
) -> int:
    count = 1
    for ancestor_id in record.ancestor_ids:
        ancestor = index[ancestor_id].node
        if isinstance(ancestor, RepeatNode):
            count *= ancestor.count
    return count


def _require_valid(grammar: SceneGrammar, maximum_depth: int, label: str) -> None:
    report = validate_grammar(grammar, max_depth=maximum_depth)
    if not report.is_valid:
        diagnostic = report.diagnostics[0]
        raise EditValidationError(
            f"{label} is invalid: {diagnostic.code} at "
            f"{diagnostic.path or '<unknown>'}: {diagnostic.message}"
        )


def _execute_verified(
    grammar: SceneGrammar,
    maximum_depth: int,
    maximum_primitives: int,
    label: str,
):
    try:
        return execute_grammar(
            grammar,
            maximum_depth=maximum_depth,
            maximum_primitives=maximum_primitives,
        )
    except (GeometryError, ValueError) as exc:
        raise EditExecutionError(f"{label} failed execution: {exc}") from exc


def _grammar_hash(grammar: SceneGrammar) -> str:
    return hashlib.sha256(
        grammar_to_canonical_json(grammar).encode("utf-8")
    ).hexdigest()


def _is_operation(value: object) -> bool:
    return isinstance(
        value,
        (
            SetSplitChildWeight,
            SetRepeatCount,
            SetRepeatSpacing,
            SubstituteTerminalClass,
        ),
    )
