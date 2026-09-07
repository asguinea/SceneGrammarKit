"""Deterministic compression of supplied repeat groups into RepeatNode values."""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from pathlib import Path

from scene_grammar_kit.assisted.annotation_models import (
    RepeatGroupAnnotation,
    SceneAnnotation,
)
from scene_grammar_kit.assisted.config_models import ConstructionConfig
from scene_grammar_kit.assisted.lifting_models import (
    LIFTING_POLICY_VERSION,
    LiftedObservation,
    LiftedSceneObservations,
    ObservationSourceType,
)
from scene_grammar_kit.assisted.lifting_serialization import (
    lifted_scene_from_json,
    lifted_scene_to_canonical_json,
)
from scene_grammar_kit.assisted.repeat_induction_errors import (
    RepeatInductionValidationError,
)
from scene_grammar_kit.assisted.repeat_induction_models import (
    RepeatCompressionSummary,
    RepeatDecision,
    RepeatDiagnostic,
    RepeatDiagnosticSeverity,
    RepeatFidelitySummary,
    RepeatGroupDecision,
    RepeatInductionReport,
    RepeatInductionResult,
    RepeatMemberMapping,
    RepeatRegularityMetrics,
    RepeatRepresentationStatus,
)
from scene_grammar_kit.assisted.serialization import (
    annotation_to_canonical_json,
    construction_config_to_canonical_json,
    load_annotation,
    load_construction_config,
)
from scene_grammar_kit.assisted.split_induction import (
    induce_split_grammar,
    induce_split_grammar_from_files,
)
from scene_grammar_kit.assisted.split_induction_models import (
    SPLIT_INDUCTION_POLICY_VERSION,
    SplitInductionResult,
)
from scene_grammar_kit.assisted.split_induction_serialization import (
    split_induction_report_from_json,
)
from scene_grammar_kit.geometry import (
    EXECUTION_POLICY_VERSION,
    ExecutedScene,
    axis_interval,
    execute_grammar,
    split_bounds_by_weights,
)
from scene_grammar_kit.grammar import (
    SCHEMA_VERSION,
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
    summarize_grammar,
    validate_grammar,
)
from scene_grammar_kit.grammar.models import GrammarNodeBase

REPEAT_EPSILON = 1e-12
SUPPLIED_REPEAT_INFORMATION = (
    "repeat-group IDs and ordered membership",
    "repeat-axis hints",
    "member semantic classes, geometry, attributes, parents, and depth zones",
    "lifted member proxy bounds",
    "configured repeat tolerances and fallback permissions",
)
DERIVED_REPEAT_INFORMATION = (
    "repeat regularity metrics",
    "median proxy spacing",
    "implied equal-cell element extent",
    "consensus orthogonal proxy bounds",
    "RepeatNode compression decisions",
    "conceptual member mappings and fidelity diagnostics",
    "split-only versus repeat-grammar diagnostic comparison",
)
EXPLICITLY_NOT_INFERRED_BY_REPEAT = (
    "repeat groups from image pixels",
    "extra hidden members",
    "occluded instances",
    "physical object size",
    "stochastic repeat rules",
    "learned regularity",
    "metric depth",
    "photorealistic geometry",
)
_AXES = (Axis.X, Axis.Y, Axis.Z)


def deterministic_median(values: tuple[float, ...]) -> float:
    """Return a documented deterministic median without library ambiguity."""
    if not values:
        raise RepeatInductionValidationError("median requires at least one value")
    ordered = sorted(float(item) for item in values)
    if any(not math.isfinite(item) for item in ordered):
        raise RepeatInductionValidationError("median values must be finite")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def evaluate_repeat_group(
    group: RepeatGroupAnnotation,
    members: tuple[LiftedObservation, ...],
    config: ConstructionConfig,
    parent_bounds: Bounds3D,
) -> tuple[RepeatRegularityMetrics, tuple[str, ...]]:
    """Calculate frozen regularity metrics and ordered rejection codes."""
    if len(members) < 2:
        raise RepeatInductionValidationError(
            "repeat_invalid_fit: fewer than two members"
        )
    axis = group.axis_hint
    intervals = tuple(axis_interval(item.world_bounds, axis) for item in members)
    extents_xyz = tuple(
        tuple(
            high - low
            for low, high in zip(
                item.world_bounds.minimum.as_tuple(),
                item.world_bounds.maximum.as_tuple(),
            )
        )
        for item in members
    )
    raw_gaps = tuple(
        intervals[index + 1][0] - intervals[index][1]
        for index in range(len(intervals) - 1)
    )
    parent_axis = axis_interval(parent_bounds, axis)
    boundary_tolerance = config.boundary_merge_tolerance * (
        parent_axis[1] - parent_axis[0]
    )
    gaps = tuple(0.0 if -boundary_tolerance <= gap < 0.0 else gap for gap in raw_gaps)
    group_span = (intervals[0][0], intervals[-1][1])
    group_extent = group_span[1] - group_span[0]
    nonnegative_gaps = tuple(max(0.0, gap) for gap in gaps)
    spacing = deterministic_median(nonnegative_gaps)
    count = len(members)
    implied = (group_extent - (count - 1) * spacing) / count

    orthogonal = tuple(item for item in _AXES if item is not axis)
    centers: list[tuple[str, float]] = []
    orth_extents: list[tuple[str, float]] = []
    alignment_errors: list[float] = []
    representative_by_axis: dict[Axis, float] = {axis: implied}
    for cross_axis in orthogonal:
        intervals_cross = tuple(
            axis_interval(item.world_bounds, cross_axis) for item in members
        )
        member_centers = tuple((low + high) / 2.0 for low, high in intervals_cross)
        member_extents = tuple(high - low for low, high in intervals_cross)
        median_center = deterministic_median(member_centers)
        median_extent = deterministic_median(member_extents)
        centers.append((cross_axis.value, median_center))
        orth_extents.append((cross_axis.value, median_extent))
        representative_by_axis[cross_axis] = median_extent
        # The construction root is the stable parent coordinate frame for the
        # normalized proxy alignment metric.
        normalization_extent = (
            axis_interval(config.root_bounds, cross_axis)[1]
            - axis_interval(config.root_bounds, cross_axis)[0]
        )
        if normalization_extent <= 0:
            raise RepeatInductionValidationError(
                "repeat_invalid_fit: invalid alignment normalization extent"
            )
        alignment_errors.extend(
            abs(value - median_center) / normalization_extent
            for value in member_centers
        )
    alignment_error = max(alignment_errors, default=0.0)

    size_errors = []
    for item in members:
        for candidate_axis in _AXES:
            observed = (
                axis_interval(item.world_bounds, candidate_axis)[1]
                - axis_interval(item.world_bounds, candidate_axis)[0]
            )
            representative = representative_by_axis[candidate_axis]
            if representative <= 0:
                size_errors.append(float("inf"))
            else:
                size_errors.append(abs(observed - representative) / representative)
    size_error = max(size_errors, default=0.0)

    if spacing > REPEAT_EPSILON:
        spacing_errors = tuple(abs(gap - spacing) / spacing for gap in nonnegative_gaps)
    else:
        spacing_errors = tuple(
            abs(gap) / group_extent if group_extent > 0 else float("inf")
            for gap in nonnegative_gaps
        )
    spacing_error = max(spacing_errors, default=0.0)
    predicted = _predicted_axis_intervals(group_span, count, spacing, implied)
    positional = (
        max(
            (
                max(abs(observed[0] - expected[0]), abs(observed[1] - expected[1]))
                / group_extent
            )
            for observed, expected in zip(intervals, predicted)
        )
        if group_extent > 0
        else float("inf")
    )

    reasons: list[str] = []
    parent_ids = {item.parent_region_id for item in members}
    if len(parent_ids) != 1:
        reasons.append("repeat_member_parent_mismatch")
    if len({item.depth_zone for item in members}) != 1:
        reasons.append("repeat_member_depth_zone_mismatch")
    if len({item.semantic_class for item in members}) != 1:
        reasons.append("repeat_member_semantic_mismatch")
    if len({item.terminal_geometry for item in members}) != 1:
        reasons.append("repeat_member_geometry_mismatch")
    if len({tuple(sorted(item.attributes.items())) for item in members}) != 1:
        reasons.append("repeat_member_attribute_mismatch")
    if any(intervals[index + 1][0] < intervals[index][0] for index in range(count - 1)):
        reasons.append("repeat_member_order_nonmonotonic")
    if any(gap < -boundary_tolerance for gap in raw_gaps):
        reasons.append("repeat_member_overlap")
    if (
        implied <= 0
        or group_extent <= 0
        or any(value <= 0 for row in extents_xyz for value in row)
    ):
        reasons.append("repeat_invalid_fit")
    for cross_axis in orthogonal:
        parent_low, parent_high = axis_interval(parent_bounds, cross_axis)
        center = dict(centers)[cross_axis.value]
        extent = dict(orth_extents)[cross_axis.value]
        if (
            center - extent / 2.0 < parent_low - boundary_tolerance
            or center + extent / 2.0 > parent_high + boundary_tolerance
        ):
            reasons.append("repeat_consensus_bounds_outside_parent")
    if alignment_error > config.repeat_alignment_tolerance:
        reasons.append("repeat_alignment_tolerance_exceeded")
    if size_error > config.repeat_size_tolerance:
        reasons.append("repeat_size_tolerance_exceeded")
    if (
        spacing_error > config.repeat_spacing_tolerance
        or positional > config.repeat_spacing_tolerance
    ):
        reasons.append("repeat_spacing_tolerance_exceeded")

    metrics = RepeatRegularityMetrics(
        group_id=group.repeat_group_id,
        supplied_axis=axis,
        member_count=count,
        member_intervals=intervals,
        member_extents=extents_xyz,
        pairwise_gaps=gaps,
        group_span=group_span,
        estimated_spacing=spacing,
        implied_element_extent=implied,
        cross_axis_median_centers=tuple(centers),
        cross_axis_median_extents=tuple(orth_extents),
        alignment_error=alignment_error,
        size_error=size_error,
        spacing_error=spacing_error,
        positional_residual=positional,
        alignment_tolerance=config.repeat_alignment_tolerance,
        size_tolerance=config.repeat_size_tolerance,
        spacing_tolerance=config.repeat_spacing_tolerance,
    )
    return metrics, tuple(dict.fromkeys(reasons))


def induce_repeat_grammar(
    annotation: SceneAnnotation,
    config: ConstructionConfig,
    lifted_scene: LiftedSceneObservations,
    split_result: SplitInductionResult,
    *,
    verify_execution: bool = True,
    maximum_grammar_depth: int | None = None,
    maximum_primitives: int = 1_000_000,
) -> RepeatInductionResult:
    """Compress eligible supplied groups while preserving the split baseline."""
    _verify_inputs(annotation, config, lifted_scene, split_result)
    depth = (
        config.maximum_grammar_depth
        if maximum_grammar_depth is None
        else maximum_grammar_depth
    )
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
        raise RepeatInductionValidationError("maximum_grammar_depth must be positive")
    if (
        isinstance(maximum_primitives, bool)
        or not isinstance(maximum_primitives, int)
        or maximum_primitives < 1
    ):
        raise RepeatInductionValidationError("maximum_primitives must be positive")

    observations = {
        item.source_annotation_id: item
        for item in lifted_scene.observations
        if item.source_annotation_type is ObservationSourceType.INSTANCE
    }
    region_observations = {
        item.source_annotation_id: item
        for item in lifted_scene.observations
        if item.source_annotation_type is ObservationSourceType.REGION
    }
    fallback_ids = {
        record.repeat_group_id: record.generated_independent_terminal_ids
        for record in split_result.report.repeat_candidates
    }
    diagnostics: list[RepeatDiagnostic] = []
    decisions: list[RepeatGroupDecision] = []
    mappings: list[RepeatMemberMapping] = []
    grammar = split_result.induced_grammar

    if not annotation.repeat_groups:
        diagnostics.append(
            RepeatDiagnostic(
                "no_repeat_groups_supplied",
                RepeatDiagnosticSeverity.INFO,
                "No supplied repeat groups were evaluated.",
            )
        )

    for group_index, group in enumerate(annotation.repeat_groups):
        path = f"repeat_groups[{group_index}]"
        diagnostics.append(
            RepeatDiagnostic(
                "repeat_group_evaluated",
                RepeatDiagnosticSeverity.INFO,
                f"Evaluated {len(group.member_instance_ids)} supplied members.",
                group.repeat_group_id,
                structural_path=path,
            )
        )
        missing = [
            item for item in group.member_instance_ids if item not in observations
        ]
        if missing:
            raise RepeatInductionValidationError(
                "repeat_member_missing: " + ", ".join(missing)
            )
        members = tuple(observations[item] for item in group.member_instance_ids)
        if group.repeat_group_id not in fallback_ids:
            raise RepeatInductionValidationError(
                "repeat_member_missing: split-only repeat candidate is absent"
            )
        baseline_terminals = _terminal_ids(grammar.root)
        if any(
            terminal_id not in baseline_terminals
            for terminal_id in fallback_ids[group.repeat_group_id]
        ):
            raise RepeatInductionValidationError(
                "repeat_member_missing: split-only member terminal is absent"
            )
        member_and_parent_ids = set(group.member_instance_ids)
        if members[0].parent_region_id:
            member_and_parent_ids.add(members[0].parent_region_id)
        protected_terminal_ids = {
            node_id
            for mapping in split_result.report.node_mappings
            if mapping.source_annotation_id not in member_and_parent_ids
            for node_id in mapping.generated_grammar_node_ids
            if node_id in baseline_terminals
        }
        parent_id = members[0].parent_region_id
        parent_bounds = (
            region_observations[parent_id].world_bounds
            if parent_id is not None and parent_id in region_observations
            else config.root_bounds
        )
        metrics, reasons = evaluate_repeat_group(group, members, config, parent_bounds)
        if not _group_is_structurally_isolated(
            grammar.root,
            set(fallback_ids[group.repeat_group_id]),
            protected_terminal_ids,
            group.axis_hint,
        ):
            reasons = (
                *reasons,
                "repeat_group_interleaved_source_observation",
            )
        accepted = not reasons
        allow_fallback = (
            config.allow_repeat_fallback and group.allow_fallback_to_individuals
        )
        if not accepted and not allow_fallback:
            diagnostics.append(
                RepeatDiagnostic(
                    "repeat_group_rejected_fatal",
                    RepeatDiagnosticSeverity.ERROR,
                    "Group failed regularity and fallback is forbidden.",
                    group.repeat_group_id,
                    structural_path=path,
                )
            )
            raise RepeatInductionValidationError(
                "repeat_group_rejected_fatal: " + ",".join(reasons)
            )
        if accepted:
            repeat_id = f"induced_repeat_{_token(group.repeat_group_id)}"
            element_id = f"induced_repeat_element_{_token(group.repeat_group_id)}"
            grammar = _compress_group(
                grammar,
                group,
                members,
                metrics,
                parent_id,
                region_observations.get(parent_id) if parent_id else None,
                fallback_ids[group.repeat_group_id],
                protected_terminal_ids,
                repeat_id,
                element_id,
            )
            diagnostics.extend(
                [
                    RepeatDiagnostic(
                        "repeat_group_accepted",
                        RepeatDiagnosticSeverity.INFO,
                        "Group satisfied configured regularity tolerances.",
                        group.repeat_group_id,
                        grammar_node_id=repeat_id,
                        structural_path=path,
                    ),
                    RepeatDiagnostic(
                        "repeat_node_created",
                        RepeatDiagnosticSeverity.INFO,
                        f"Created count={len(members)} RepeatNode with spacing={metrics.estimated_spacing}.",
                        group.repeat_group_id,
                        grammar_node_id=repeat_id,
                        structural_path=path,
                    ),
                ]
            )
            decision_value = RepeatDecision.ACCEPTED
            for index, (member, predicted) in enumerate(
                zip(members, _predicted_bounds(members, metrics, config.root_bounds))
            ):
                residual = _maximum_boundary_difference(member.world_bounds, predicted)
                mappings.append(
                    RepeatMemberMapping(
                        group.repeat_group_id,
                        member.source_annotation_id,
                        index,
                        repeat_id,
                        element_id,
                        None,
                        member.world_bounds,
                        predicted,
                        residual,
                        RepeatRepresentationStatus.COMPRESSED_REPEAT_INSTANCE,
                    )
                )
        else:
            repeat_id = element_id = None
            decision_value = RepeatDecision.REJECTED_FALLBACK
            diagnostics.extend(
                [
                    RepeatDiagnostic(
                        "repeat_group_rejected_fallback",
                        RepeatDiagnosticSeverity.WARNING,
                        "Group failed regularity; permitted split-only fallback retained.",
                        group.repeat_group_id,
                        structural_path=path,
                    ),
                    RepeatDiagnostic(
                        "repeat_fallback_preserved",
                        RepeatDiagnosticSeverity.INFO,
                        "Independent member terminals remain unchanged.",
                        group.repeat_group_id,
                        structural_path=path,
                    ),
                ]
            )
            for index, (member, terminal_id) in enumerate(
                zip(members, fallback_ids[group.repeat_group_id])
            ):
                mappings.append(
                    RepeatMemberMapping(
                        group.repeat_group_id,
                        member.source_annotation_id,
                        index,
                        None,
                        None,
                        terminal_id,
                        member.world_bounds,
                        None,
                        0.0,
                        RepeatRepresentationStatus.INDEPENDENT_FALLBACK,
                    )
                )
        for reason in reasons:
            diagnostics.append(
                RepeatDiagnostic(
                    reason,
                    RepeatDiagnosticSeverity.WARNING,
                    "Configured repeat eligibility check did not pass.",
                    group.repeat_group_id,
                    structural_path=path,
                )
            )
        decisions.append(
            RepeatGroupDecision(
                group.repeat_group_id,
                decision_value,
                group.member_instance_ids,
                reasons,
                repeat_id,
                element_id,
                metrics,
                parent_id,
                members[0].semantic_class,
                members[0].terminal_geometry or GeometryType.EMPTY,
            )
        )

    validation = validate_grammar(grammar, max_depth=depth)
    if not validation.is_valid:
        raise RepeatInductionValidationError(
            "repeat_geometry_verification_failed: repeat grammar is invalid"
        )
    split_summary = summarize_grammar(split_result.induced_grammar, max_depth=depth)
    repeat_summary = summarize_grammar(grammar, max_depth=depth)
    accepted_count = sum(item.decision is RepeatDecision.ACCEPTED for item in decisions)
    if repeat_summary.repeat_node_count != accepted_count:
        raise RepeatInductionValidationError(
            "repeat_geometry_verification_failed: RepeatNode count mismatch"
        )
    split_execution: ExecutedScene | None = None
    repeat_execution: ExecutedScene | None = None
    maximum_non_repeat_change = 0.0
    max_member_error = max(
        (
            item.boundary_residual
            for item in mappings
            if item.representation_status
            is RepeatRepresentationStatus.COMPRESSED_REPEAT_INSTANCE
        ),
        default=0.0,
    )
    if verify_execution:
        split_execution = execute_grammar(
            split_result.induced_grammar,
            maximum_depth=depth,
            maximum_primitives=maximum_primitives,
        )
        repeat_execution = execute_grammar(
            grammar,
            maximum_depth=depth,
            maximum_primitives=maximum_primitives,
        )
        _verify_repeated_primitives(repeat_execution, mappings)
        accepted_source_ids = {
            source_id
            for decision in decisions
            if decision.decision is RepeatDecision.ACCEPTED
            for source_id in (
                *decision.ordered_member_ids,
                *((decision.source_parent_id,) if decision.source_parent_id else ()),
            )
        }
        baseline_terminal_ids = _terminal_ids(split_result.induced_grammar.root)
        preserved_terminal_ids = {
            node_id
            for mapping in split_result.report.node_mappings
            if mapping.source_annotation_id not in accepted_source_ids
            for node_id in mapping.generated_grammar_node_ids
            if node_id in baseline_terminal_ids
        }
        maximum_non_repeat_change = _verify_non_repeat_primitives(
            split_execution,
            repeat_execution,
            preserved_terminal_ids,
        )
        primitive_before = len(split_execution.primitives)
        primitive_after = len(repeat_execution.primitives)
    else:
        primitive_before = primitive_after = 0

    split_json = grammar_to_canonical_json(split_result.induced_grammar)
    repeat_json = grammar_to_canonical_json(grammar)
    compression = RepeatCompressionSummary(
        split_summary.total_node_count,
        repeat_summary.total_node_count,
        split_summary.split_node_count,
        repeat_summary.split_node_count,
        split_summary.terminal_node_count,
        repeat_summary.terminal_node_count,
        split_summary.repeat_node_count,
        repeat_summary.repeat_node_count,
        len(split_json.encode()),
        len(repeat_json.encode()),
        abs(len(repeat_json.encode()) - len(split_json.encode())),
        len(repeat_json.encode()) / len(split_json.encode()),
        repeat_summary.total_node_count - split_summary.total_node_count,
        primitive_before,
        primitive_after,
    )
    fidelity = RepeatFidelitySummary(
        len(lifted_scene.observations),
        len(lifted_scene.observations),
        max_member_error,
        maximum_non_repeat_change,
        grammar.root_bounds == split_result.induced_grammar.root_bounds,
        split_execution is not None,
        repeat_execution is not None,
    )
    lifted_hash = _sha256(lifted_scene_to_canonical_json(lifted_scene))
    report = RepeatInductionReport(
        True,
        annotation.annotation_schema_version,
        config.config_schema_version,
        LIFTING_POLICY_VERSION,
        SPLIT_INDUCTION_POLICY_VERSION,
        SCHEMA_VERSION,
        EXECUTION_POLICY_VERSION,
        annotation.scene_id,
        lifted_scene.annotation_sha256,
        lifted_scene.construction_config_sha256,
        lifted_hash,
        _sha256(split_json),
        _sha256(repeat_json),
        len(annotation.repeat_groups),
        accepted_count,
        sum(item.decision is RepeatDecision.REJECTED_FALLBACK for item in decisions),
        0,
        tuple(decisions),
        tuple(mappings),
        compression,
        fidelity,
        repeat_summary.repeat_node_count,
        True,
        repeat_execution is not None,
        SUPPLIED_REPEAT_INFORMATION,
        DERIVED_REPEAT_INFORMATION,
        EXPLICITLY_NOT_INFERRED_BY_REPEAT,
        tuple(diagnostics),
        tuple(
            item.message
            for item in diagnostics
            if item.severity is RepeatDiagnosticSeverity.WARNING
        ),
    )
    return RepeatInductionResult(
        annotation,
        config,
        lifted_scene,
        split_result,
        grammar,
        validation,
        split_execution,
        repeat_execution,
        report,
    )


def induce_repeat_grammar_from_files(
    annotation_path: Path,
    config_path: Path,
    output_directory: Path,
    *,
    split_induction_directory: Path | None = None,
    overwrite: bool = False,
    verify_image: bool = True,
    verify_execution: bool = True,
    maximum_grammar_depth: int | None = None,
    maximum_primitives: int = 1_000_000,
) -> RepeatInductionResult:
    """Run or load Batch 2.4, induce repeats, and persist the result."""
    if overwrite:
        from scene_grammar_kit.assisted.repeat_induction_persistence import (
            clear_repeat_induction_success_report,
        )

        clear_repeat_induction_success_report(output_directory)
    annotation = load_annotation(annotation_path)
    config = load_construction_config(config_path)
    if split_induction_directory is None:
        import tempfile

        with tempfile.TemporaryDirectory() as name:
            split_result = induce_split_grammar_from_files(
                annotation_path,
                config_path,
                Path(name),
                verify_image=verify_image,
                verify_execution=verify_execution,
                maximum_grammar_depth=maximum_grammar_depth,
                maximum_primitives=maximum_primitives,
            )
    else:
        split_result = _load_split_bundle(
            Path(split_induction_directory),
            annotation,
            config,
            verify_execution=verify_execution,
            maximum_depth=maximum_grammar_depth,
            maximum_primitives=maximum_primitives,
        )
    result = induce_repeat_grammar(
        annotation,
        config,
        split_result.lifted_observations,
        split_result,
        verify_execution=verify_execution,
        maximum_grammar_depth=maximum_grammar_depth,
        maximum_primitives=maximum_primitives,
    )
    from scene_grammar_kit.assisted.repeat_induction_persistence import (
        save_repeat_induction_result,
    )

    save_repeat_induction_result(result, output_directory, overwrite=overwrite)
    return result


def _compress_group(
    grammar: SceneGrammar,
    group: RepeatGroupAnnotation,
    members: tuple[LiftedObservation, ...],
    metrics: RepeatRegularityMetrics,
    parent_id: str | None,
    parent_observation: LiftedObservation | None,
    member_terminal_ids: tuple[str, ...],
    protected_terminal_ids: set[str],
    repeat_id: str,
    element_id: str,
) -> SceneGrammar:
    target_ids = set(member_terminal_ids)
    transformed, found = _transform_node(
        grammar.root,
        grammar.root_bounds,
        target_ids,
        group,
        members,
        metrics,
        parent_id,
        parent_observation,
        protected_terminal_ids,
        repeat_id,
        element_id,
    )
    if not found:
        raise RepeatInductionValidationError(
            "repeat_geometry_verification_failed: member baseline subtree not found"
        )
    return replace(grammar, root=transformed)


def _transform_node(
    node: GrammarNodeBase,
    bounds: Bounds3D,
    target_ids: set[str],
    group: RepeatGroupAnnotation,
    members: tuple[LiftedObservation, ...],
    metrics: RepeatRegularityMetrics,
    parent_id: str | None,
    parent_observation: LiftedObservation | None,
    protected_terminal_ids: set[str],
    repeat_id: str,
    element_id: str,
) -> tuple[GrammarNodeBase, bool]:
    if not isinstance(node, SplitNode):
        return node, False
    child_bounds = split_bounds_by_weights(
        bounds, node.axis, tuple(item.weight for item in node.children)
    )
    locations = []
    for index, child in enumerate(node.children):
        terminals = _terminal_ids(child.node)
        if terminals & target_ids:
            locations.append(index)
    if node.axis is group.axis_hint and len(locations) == len(target_ids):
        first, last = min(locations), max(locations)
        enclosed = set().union(
            *(
                _terminal_ids(node.children[index].node)
                for index in range(first, last + 1)
            )
        )
        if enclosed & protected_terminal_ids:
            return node, False
        envelope = _replace_axis(
            bounds, group.axis_hint, metrics.group_span[0], metrics.group_span[1]
        )
        replacement = _repeat_wrapper(
            envelope,
            group,
            members,
            metrics,
            parent_id,
            parent_observation,
            repeat_id,
            element_id,
        )
        new_children = (
            node.children[:first]
            + (SplitChild(metrics.group_span[1] - metrics.group_span[0], replacement),)
            + node.children[last + 1 :]
        )
        return replace(node, children=new_children), True
    children = list(node.children)
    for index, child in enumerate(children):
        updated, found = _transform_node(
            child.node,
            child_bounds[index],
            target_ids,
            group,
            members,
            metrics,
            parent_id,
            parent_observation,
            protected_terminal_ids,
            repeat_id,
            element_id,
        )
        if found:
            children[index] = replace(child, node=updated)
            return replace(node, children=tuple(children)), True
    return node, False


def _group_is_structurally_isolated(
    node: GrammarNodeBase,
    target_ids: set[str],
    protected_terminal_ids: set[str],
    axis: Axis,
) -> bool:
    """Return whether a target range can be replaced without another source."""
    if not isinstance(node, SplitNode):
        return False
    locations = [
        index
        for index, child in enumerate(node.children)
        if _terminal_ids(child.node) & target_ids
    ]
    if node.axis is axis and len(locations) == len(target_ids):
        first, last = min(locations), max(locations)
        enclosed = set().union(
            *(
                _terminal_ids(node.children[index].node)
                for index in range(first, last + 1)
            )
        )
        return not bool(enclosed & protected_terminal_ids)
    return any(
        _group_is_structurally_isolated(
            child.node,
            target_ids,
            protected_terminal_ids,
            axis,
        )
        for child in node.children
    )


def _repeat_wrapper(
    envelope: Bounds3D,
    group: RepeatGroupAnnotation,
    members: tuple[LiftedObservation, ...],
    metrics: RepeatRegularityMetrics,
    parent_id: str | None,
    parent_observation: LiftedObservation | None,
    repeat_id: str,
    element_id: str,
) -> GrammarNodeBase:
    centers = {Axis(axis): value for axis, value in metrics.cross_axis_median_centers}
    extents = {Axis(axis): value for axis, value in metrics.cross_axis_median_extents}
    target = envelope
    for axis in _AXES:
        if axis is group.axis_hint:
            continue
        center, extent = centers[axis], extents[axis]
        target = _replace_axis(target, axis, center - extent / 2, center + extent / 2)
    element = TerminalNode(
        element_id,
        members[0].semantic_class,
        members[0].terminal_geometry or GeometryType.EMPTY,
        dict(members[0].attributes),
    )
    content: GrammarNodeBase = RepeatNode(
        repeat_id, group.axis_hint, len(members), metrics.estimated_spacing, element
    )
    for axis in reversed(tuple(item for item in _AXES if item is not group.axis_hint)):
        low, high = axis_interval(envelope, axis)
        target_low, target_high = axis_interval(target, axis)
        pieces = []
        if target_low > low:
            pieces.append(
                (
                    target_low - low,
                    _repeat_filler(group, axis, len(pieces), parent_observation),
                )
            )
        pieces.append((target_high - target_low, content))
        if target_high < high:
            pieces.append(
                (
                    high - target_high,
                    _repeat_filler(group, axis, len(pieces), parent_observation),
                )
            )
        if len(pieces) > 1:
            content = SplitNode(
                f"induced_repeat_wrapper_{_token(group.repeat_group_id)}_{axis.value}",
                axis,
                tuple(SplitChild(weight, child) for weight, child in pieces),
            )
    return content


def _repeat_filler(
    group: RepeatGroupAnnotation,
    axis: Axis,
    index: int,
    parent: LiftedObservation | None,
) -> TerminalNode:
    return TerminalNode(
        f"induced_repeat_filler_{_token(group.repeat_group_id)}_{axis.value}_{index}",
        parent.semantic_class if parent else "empty_space",
        (
            parent.terminal_geometry
            if parent and parent.terminal_geometry
            else GeometryType.EMPTY
        ),
        dict(parent.attributes) if parent else {},
    )


def _predicted_axis_intervals(
    span: tuple[float, float], count: int, spacing: float, extent: float
) -> tuple[tuple[float, float], ...]:
    result = []
    for index in range(count):
        low = span[0] + index * (extent + spacing)
        high = span[1] if index == count - 1 else low + extent
        result.append((low, high))
    return tuple(result)


def _predicted_bounds(
    members: tuple[LiftedObservation, ...],
    metrics: RepeatRegularityMetrics,
    root: Bounds3D,
) -> tuple[Bounds3D, ...]:
    del root
    centers = {Axis(axis): value for axis, value in metrics.cross_axis_median_centers}
    extents = {Axis(axis): value for axis, value in metrics.cross_axis_median_extents}
    intervals = _predicted_axis_intervals(
        metrics.group_span,
        len(members),
        metrics.estimated_spacing,
        metrics.implied_element_extent,
    )
    results = []
    for repeat_interval in intervals:
        lows, highs = [], []
        for axis in _AXES:
            if axis is metrics.supplied_axis:
                low, high = repeat_interval
            else:
                low = centers[axis] - extents[axis] / 2
                high = centers[axis] + extents[axis] / 2
            lows.append(low)
            highs.append(high)
        results.append(Bounds3D(Vector3(*lows), Vector3(*highs)))
    return tuple(results)


def _verify_repeated_primitives(
    execution: ExecutedScene, mappings: list[RepeatMemberMapping]
) -> None:
    for mapping in mappings:
        if (
            mapping.representation_status
            is not RepeatRepresentationStatus.COMPRESSED_REPEAT_INSTANCE
        ):
            continue
        matches = [
            item
            for item in execution.primitives
            if item.source_terminal_id == mapping.representative_element_node_id
            and item.repeat_indices
            and item.repeat_indices[-1] == mapping.supplied_member_index
        ]
        if len(matches) != 1 or matches[0].bounds != mapping.predicted_world_bounds:
            raise RepeatInductionValidationError(
                "repeat_geometry_verification_failed: conceptual instance mismatch"
            )


def _verify_non_repeat_primitives(
    split_execution: ExecutedScene,
    repeat_execution: ExecutedScene,
    preserved_terminal_ids: set[str],
) -> float:
    """Verify that every unaffected terminal produces the same proxy bounds."""
    before: dict[str, list[Bounds3D]] = {}
    after: dict[str, list[Bounds3D]] = {}
    for primitive in split_execution.primitives:
        if primitive.source_terminal_id in preserved_terminal_ids:
            before.setdefault(primitive.source_terminal_id, []).append(primitive.bounds)
    for primitive in repeat_execution.primitives:
        if primitive.source_terminal_id in preserved_terminal_ids:
            after.setdefault(primitive.source_terminal_id, []).append(primitive.bounds)
    if set(before) != set(after):
        raise RepeatInductionValidationError(
            "repeat_geometry_verification_failed: non-repeat terminal coverage changed"
        )
    maximum = 0.0
    for terminal_id in sorted(before):
        first = sorted(before[terminal_id], key=_bounds_sort_key)
        second = sorted(after[terminal_id], key=_bounds_sort_key)
        if len(first) != len(second):
            raise RepeatInductionValidationError(
                "repeat_geometry_verification_failed: "
                f"non-repeat primitive count changed for {terminal_id}"
            )
        maximum = max(
            maximum,
            *(
                _maximum_boundary_difference(left, right)
                for left, right in zip(first, second)
            ),
        )
    if maximum > REPEAT_EPSILON:
        raise RepeatInductionValidationError(
            "repeat_geometry_verification_failed: non-repeat proxy bounds changed"
        )
    return maximum


def _bounds_sort_key(bounds: Bounds3D) -> tuple[float, ...]:
    return bounds.minimum.as_tuple() + bounds.maximum.as_tuple()


def _load_split_bundle(
    directory: Path,
    annotation: SceneAnnotation,
    config: ConstructionConfig,
    *,
    verify_execution: bool,
    maximum_depth: int | None,
    maximum_primitives: int,
) -> SplitInductionResult:
    directory = directory.expanduser().resolve()
    required = (
        "annotation.json",
        "construction_config.json",
        "lifted_observations.json",
        "induced_grammar.json",
        "split_induction_report.json",
    )
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        raise RepeatInductionValidationError(
            "incomplete_split_induction_bundle: " + ", ".join(missing)
        )
    loaded_annotation = load_annotation(directory / "annotation.json")
    loaded_config = load_construction_config(directory / "construction_config.json")
    if loaded_annotation != annotation:
        raise RepeatInductionValidationError("precomputed_annotation_mismatch")
    if loaded_config != config:
        raise RepeatInductionValidationError("precomputed_config_mismatch")
    lifted = lifted_scene_from_json(
        (directory / "lifted_observations.json").read_text(encoding="utf-8")
    )
    grammar = load_grammar(directory / "induced_grammar.json")
    split_report = split_induction_report_from_json(
        (directory / "split_induction_report.json").read_text(encoding="utf-8")
    )
    if (
        _sha256(grammar_to_canonical_json(grammar))
        != split_report.induced_grammar_sha256
    ):
        raise RepeatInductionValidationError("precomputed_split_grammar_hash_mismatch")
    rebuilt = induce_split_grammar(
        annotation,
        config,
        lifted,
        verify_execution=verify_execution,
        maximum_grammar_depth=maximum_depth,
        maximum_primitives=maximum_primitives,
    )
    if rebuilt.induced_grammar != grammar or rebuilt.report != split_report:
        raise RepeatInductionValidationError("precomputed_split_bundle_mismatch")
    return rebuilt


def _verify_inputs(annotation, config, lifted, split_result) -> None:
    if split_result.annotation != annotation:
        raise RepeatInductionValidationError("split_annotation_mismatch")
    if split_result.construction_config != config:
        raise RepeatInductionValidationError("split_config_mismatch")
    if split_result.lifted_observations != lifted:
        raise RepeatInductionValidationError("split_lifted_observations_mismatch")
    if split_result.induced_grammar.scene_id != annotation.scene_id:
        raise RepeatInductionValidationError("split_scene_id_mismatch")
    annotation_hash = _sha256(annotation_to_canonical_json(annotation))
    config_hash = _sha256(construction_config_to_canonical_json(config))
    lifted_hash = _sha256(lifted_scene_to_canonical_json(lifted))
    grammar_hash = _sha256(grammar_to_canonical_json(split_result.induced_grammar))
    if lifted.annotation_sha256 != annotation_hash:
        raise RepeatInductionValidationError("annotation_hash_mismatch")
    if lifted.construction_config_sha256 != config_hash:
        raise RepeatInductionValidationError("config_hash_mismatch")
    report = split_result.report
    if report.annotation_sha256 != annotation_hash:
        raise RepeatInductionValidationError("split_annotation_hash_mismatch")
    if report.construction_config_sha256 != config_hash:
        raise RepeatInductionValidationError("split_config_hash_mismatch")
    if report.lifted_observations_sha256 != lifted_hash:
        raise RepeatInductionValidationError("split_lifted_hash_mismatch")
    if report.induced_grammar_sha256 != grammar_hash:
        raise RepeatInductionValidationError("split_grammar_hash_mismatch")


def _terminal_ids(node: GrammarNodeBase) -> set[str]:
    result = set()
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, TerminalNode):
            result.add(current.node_id)
        elif isinstance(current, SplitNode):
            stack.extend(item.node for item in current.children)
        elif isinstance(current, RepeatNode):
            stack.append(current.element)
    return result


def _replace_axis(bounds: Bounds3D, axis: Axis, low: float, high: float) -> Bounds3D:
    lows = list(bounds.minimum.as_tuple())
    highs = list(bounds.maximum.as_tuple())
    index = _AXES.index(axis)
    lows[index] = low
    highs[index] = high
    return Bounds3D(Vector3(*lows), Vector3(*highs))


def _maximum_boundary_difference(first: Bounds3D, second: Bounds3D) -> float:
    return max(
        abs(a - b)
        for a, b in zip(
            first.minimum.as_tuple() + first.maximum.as_tuple(),
            second.minimum.as_tuple() + second.maximum.as_tuple(),
        )
    )


def _token(value: str) -> str:
    import re

    token = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    return token or "group"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
