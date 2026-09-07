"""Deterministic constrained construction of split-only SceneGrammarKit grammars."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from scene_grammar_kit.assisted.annotation_models import (
    DepthZone,
    SceneAnnotation,
)
from scene_grammar_kit.assisted.config_models import (
    ConstructionAxisPolicy,
    ConstructionConfig,
)
from scene_grammar_kit.assisted.lifting import lift_assisted_input
from scene_grammar_kit.assisted.lifting_models import (
    LIFTING_POLICY_VERSION,
    LiftedObservation,
    LiftedSceneObservations,
    ObservationPurpose,
    ObservationSourceType,
)
from scene_grammar_kit.assisted.lifting_serialization import (
    lifted_scene_from_json,
    lifted_scene_to_canonical_json,
)
from scene_grammar_kit.assisted.overlay import load_and_verify_source_image
from scene_grammar_kit.assisted.serialization import (
    annotation_to_canonical_json,
    construction_config_to_canonical_json,
    load_annotation,
    load_construction_config,
)
from scene_grammar_kit.assisted.split_induction_errors import (
    SplitInductionValidationError,
)
from scene_grammar_kit.assisted.split_induction_models import (
    AxisCandidateScore,
    AxisDecision,
    AxisSelectionSource,
    BoundaryDecision,
    GapDecision,
    GapReason,
    InductionDiagnostic,
    InductionDiagnosticSeverity,
    IntervalDecision,
    NodeMapping,
    RepeatCandidateRecord,
    RootConstructionDecision,
    SplitInductionReport,
    SplitInductionResult,
)
from scene_grammar_kit.assisted.validation import validate_assisted_input
from scene_grammar_kit.geometry import (
    ExecutedScene,
    axis_interval,
    bounds_contain,
    execute_grammar,
)
from scene_grammar_kit.grammar import (
    SCHEMA_VERSION,
    Axis,
    Bounds3D,
    GeometryType,
    SceneGrammar,
    SplitChild,
    SplitNode,
    TerminalNode,
    Vector3,
    grammar_to_canonical_json,
    summarize_grammar,
    validate_grammar,
)

SPLIT_INDUCTION_ASSUMPTIONS = (
    "Construction is constrained by supplied annotation hierarchy and hints.",
    "Lifted proxy bounds are non-metric and axis aligned.",
    "Configured depth zones define the three root z partitions.",
    "Boundary tolerance is a fraction of the current parent axis extent.",
    "Large uncovered intervals remain explicit semantic empty terminals.",
    "Repeat members remain independent terminals in Batch 2.4.",
)

SUPPLIED_INDUCTION_INFORMATION = (
    "region hierarchy",
    "annotation order and optional order hints",
    "semantic classes and terminal geometry",
    "structural split-axis hints",
    "repeat-group membership and axis hints",
    "lifted proxy bounds",
    "construction tolerances and limits",
)

DERIVED_INDUCTION_INFORMATION = (
    "three-zone root split",
    "geometry-selected partition axes",
    "snapped partition boundaries",
    "explicit gap and margin terminals",
    "split weights from final proxy intervals",
    "wrapper splits isolating observation bounds",
    "stable source-to-node mappings",
)

EXPLICITLY_NOT_INFERRED_BY_INDUCTION = (
    "image segmentation",
    "metric depth",
    "camera calibration",
    "semantic labels beyond supplied annotations",
    "parent hierarchy beyond supplied annotation hierarchy",
    "repeat spacing",
    "RepeatNode structure",
    "stochastic grammar",
    "photorealistic geometry",
)

_AXES = (Axis.X, Axis.Y, Axis.Z)
_ZONE_ORDER = (
    DepthZone.FOREGROUND,
    DepthZone.MIDGROUND,
    DepthZone.BACKGROUND,
)


@dataclass(frozen=True, slots=True)
class _Item:
    observation: LiftedObservation
    annotation_index: int


@dataclass(frozen=True, slots=True)
class _Segment:
    minimum: float
    maximum: float
    item: _Item | None
    reason: GapReason | None


class _Context:
    """Mutable construction ledger isolated to one API invocation."""

    def __init__(
        self,
        annotation: SceneAnnotation,
        config: ConstructionConfig,
        lifted: LiftedSceneObservations,
        *,
        maximum_depth: int,
    ) -> None:
        self.annotation = annotation
        self.config = config
        self.lifted = lifted
        self.maximum_depth = maximum_depth
        self.axis_decisions: list[AxisDecision] = []
        self.boundary_decisions: list[BoundaryDecision] = []
        self.gap_decisions: list[GapDecision] = []
        self.diagnostics: list[InductionDiagnostic] = []
        self.mapping_ids: dict[str, list[str]] = {}
        self.mapping_primary: dict[str, str] = {}
        self.terminal_ids: dict[str, list[str]] = {}
        self.used_node_ids: set[str] = {"induced_scene_depth_zones"}
        self.gap_counter = 0
        self.wrapper_counter = 0
        self.split_counter = 0
        self.fragment_counter = 0
        self._sanitized_sources: dict[str, str] = {}

        self.observations = {
            self.key(observation): observation for observation in lifted.observations
        }
        self.region_by_id = {region.region_id: region for region in annotation.regions}
        self.instance_by_id = {
            instance.instance_id: instance for instance in annotation.instances
        }
        self.repeat_by_id = {
            group.repeat_group_id: group for group in annotation.repeat_groups
        }
        self.annotation_order: dict[str, int] = {}
        for index, region in enumerate(annotation.regions):
            self.annotation_order[f"region:{region.region_id}"] = index
        offset = len(annotation.regions)
        for index, instance in enumerate(annotation.instances):
            self.annotation_order[f"instance:{instance.instance_id}"] = offset + index

    @staticmethod
    def key(observation: LiftedObservation) -> str:
        return (
            f"{observation.source_annotation_type.value}:"
            f"{observation.source_annotation_id}"
        )

    def source_token(self, source_id: str) -> str:
        token = re.sub(r"[^A-Za-z0-9_]+", "_", source_id).strip("_").lower()
        if not token:
            token = "source"
        previous = self._sanitized_sources.get(token)
        if previous is not None and previous != source_id:
            raise SplitInductionValidationError(
                "sanitized_source_id_collision: "
                f"{previous!r} and {source_id!r} both map to {token!r}"
            )
        self._sanitized_sources[token] = source_id
        return token

    def new_node_id(self, base: str) -> str:
        if base in self.used_node_ids:
            raise SplitInductionValidationError(f"duplicate_generated_node_id: {base}")
        self.used_node_ids.add(base)
        return base

    def map_node(
        self,
        observation: LiftedObservation,
        node_id: str,
        *,
        terminal: bool = False,
    ) -> None:
        key = self.key(observation)
        values = self.mapping_ids.setdefault(key, [])
        if node_id not in values:
            values.append(node_id)
        self.mapping_primary.setdefault(key, node_id)
        if terminal:
            terminals = self.terminal_ids.setdefault(key, [])
            if node_id not in terminals:
                terminals.append(node_id)

    def diagnostic(
        self,
        code: str,
        message: str,
        *,
        severity: InductionDiagnosticSeverity = (InductionDiagnosticSeverity.INFO),
        source_id: str | None = None,
        node_id: str | None = None,
        path: str | None = None,
    ) -> None:
        self.diagnostics.append(
            InductionDiagnostic(
                code=code,
                severity=severity,
                message=message,
                source_annotation_id=source_id,
                grammar_node_id=node_id,
                structural_path=path,
            )
        )

    def fail(
        self,
        code: str,
        message: str,
        *,
        source_id: str | None = None,
        path: str | None = None,
    ) -> None:
        self.diagnostic(
            code,
            message,
            severity=InductionDiagnosticSeverity.ERROR,
            source_id=source_id,
            path=path,
        )
        raise SplitInductionValidationError(f"{code}: {message}")


def induce_split_grammar(
    annotation: SceneAnnotation,
    config: ConstructionConfig,
    lifted_scene: LiftedSceneObservations,
    *,
    verify_execution: bool = True,
    maximum_grammar_depth: int | None = None,
    maximum_primitives: int = 1_000_000,
) -> SplitInductionResult:
    """Induce and verify one deterministic split-only grammar.

    The function consumes only supplied annotations, lifted proxy bounds,
    configuration values, and deterministic geometric rules. Inputs are never
    mutated and no ``RepeatNode`` is constructed.
    """
    validation = validate_assisted_input(annotation, config)
    if not validation.is_valid:
        codes = tuple(
            item.code
            for item in validation.diagnostics
            if item.severity.value == "error"
        )
        if "missing_required_split_axis_hint" in codes:
            raise SplitInductionValidationError(
                "no_partition_axis: axis policy hints_required has a "
                "structural region without a supplied split-axis hint"
            )
        raise SplitInductionValidationError(
            "assisted_input_invalid: " + ", ".join(codes)
        )
    _positive_integer(maximum_primitives, "maximum_primitives")
    depth_limit = (
        config.maximum_grammar_depth
        if maximum_grammar_depth is None
        else _positive_integer(maximum_grammar_depth, "maximum_grammar_depth")
    )
    _verify_lifted_identity(annotation, config, lifted_scene)
    context = _Context(
        annotation,
        config,
        lifted_scene,
        maximum_depth=depth_limit,
    )
    _verify_expected_observations(context)
    _require_complete_root_depth_coverage(config)

    zone_nodes = []
    for interval in config.depth_zone_intervals:
        zone_bounds = Bounds3D(
            Vector3(
                config.root_bounds.minimum.x,
                config.root_bounds.minimum.y,
                interval.z_min,
            ),
            Vector3(
                config.root_bounds.maximum.x,
                config.root_bounds.maximum.y,
                interval.z_max,
            ),
        )
        items = _top_level_items(context, interval.depth_zone)
        zone_id = f"induced_zone_{interval.depth_zone.value}"
        context.used_node_ids.add(zone_id)
        if not items:
            node = TerminalNode(
                node_id=zone_id,
                semantic_class=f"{interval.depth_zone.value}_empty",
                geometry=GeometryType.EMPTY,
            )
        else:
            raw = _build_container(
                context,
                parent_bounds=zone_bounds,
                items=items,
                parent_source_id=f"zone:{interval.depth_zone.value}",
                parent_hint=None,
                background_observation=None,
                path=f"root.{interval.depth_zone.value}",
                depth=1,
            )
            node = _rename_root_node(context, raw, zone_id)
        zone_nodes.append(node)

    weights = tuple(
        interval.z_max - interval.z_min for interval in config.depth_zone_intervals
    )
    root = SplitNode(
        node_id="induced_scene_depth_zones",
        axis=Axis.Z,
        children=tuple(
            SplitChild(weight=weight, node=node)
            for weight, node in zip(weights, zone_nodes)
        ),
    )
    grammar = SceneGrammar(
        schema_version=SCHEMA_VERSION,
        scene_id=annotation.scene_id,
        units="normalized",
        root_bounds=config.root_bounds,
        root=root,
    )
    grammar_validation = validate_grammar(grammar, max_depth=depth_limit)
    if not grammar_validation.is_valid:
        first = grammar_validation.diagnostics[0]
        context.fail(
            "execution_verification_failed",
            "Induced grammar validation failed: "
            f"{first.code} at {first.path}: {first.message}",
        )
    summary = summarize_grammar(grammar, max_depth=depth_limit)
    if summary.repeat_node_count != 0:
        context.fail(
            "execution_verification_failed",
            "Induced Batch 2.4 grammar unexpectedly contains Repeat nodes.",
        )
    mappings = _node_mappings(context)
    if len(mappings) != len(lifted_scene.observations):
        represented = {item.source_annotation_id for item in mappings}
        missing = [
            observation.source_annotation_id
            for observation in lifted_scene.observations
            if observation.source_annotation_id not in represented
        ]
        context.fail(
            "source_observation_omitted",
            f"Missing source mappings: {', '.join(missing)}",
        )
    _verify_mapping_uniqueness(context, mappings)

    executed: ExecutedScene | None = None
    if verify_execution:
        try:
            executed = execute_grammar(
                grammar,
                maximum_depth=depth_limit,
                maximum_primitives=maximum_primitives,
            )
            _verify_execution_geometry(context, executed, mappings)
        except SplitInductionValidationError:
            raise
        except Exception as exc:
            raise SplitInductionValidationError(
                f"execution_verification_failed: {exc}"
            ) from exc

    repeat_candidates = _repeat_candidates(context)
    root_decision = RootConstructionDecision(
        root_node_id=root.node_id,
        axis=Axis.Z,
        ordered_zones=tuple(zone.value for zone in _ZONE_ORDER),
        configured_intervals=tuple(
            (item.z_min, item.z_max) for item in config.depth_zone_intervals
        ),
        weights=weights,
    )
    grammar_json = grammar_to_canonical_json(grammar)
    grammar_hash = _sha256_text(grammar_json)
    lifted_json = lifted_scene_to_canonical_json(lifted_scene)
    warnings = tuple(
        item.message
        for item in context.diagnostics
        if item.severity is InductionDiagnosticSeverity.WARNING
    )
    report = SplitInductionReport(
        success=True,
        grammar_schema_version=SCHEMA_VERSION,
        lifting_policy_version=LIFTING_POLICY_VERSION,
        scene_id=annotation.scene_id,
        annotation_sha256=lifted_scene.annotation_sha256,
        construction_config_sha256=lifted_scene.construction_config_sha256,
        lifted_observations_sha256=_sha256_text(lifted_json),
        induced_grammar_sha256=grammar_hash,
        root_construction_decision=root_decision,
        axis_decisions=tuple(context.axis_decisions),
        boundary_decisions=tuple(context.boundary_decisions),
        gap_decisions=tuple(context.gap_decisions),
        node_mappings=mappings,
        repeat_candidates=repeat_candidates,
        source_observation_count=len(lifted_scene.observations),
        represented_observation_count=len(mappings),
        omitted_observation_count=0,
        split_node_count=summary.split_node_count,
        terminal_node_count=summary.terminal_node_count,
        empty_terminal_count=summary.geometry_type_frequencies.get("empty", 0),
        repeat_node_count=summary.repeat_node_count,
        maximum_grammar_depth=summary.maximum_depth,
        canonical_grammar_byte_size=len(grammar_json.encode("utf-8")),
        validation_status=True,
        execution_verification_status=executed is not None,
        supplied_information=SUPPLIED_INDUCTION_INFORMATION,
        derived_information=DERIVED_INDUCTION_INFORMATION,
        explicitly_not_inferred=EXPLICITLY_NOT_INFERRED_BY_INDUCTION,
        diagnostics=tuple(context.diagnostics),
        warnings=warnings,
    )
    return SplitInductionResult(
        annotation=annotation,
        construction_config=config,
        lifted_observations=lifted_scene,
        induced_grammar=grammar,
        grammar_validation_report=grammar_validation,
        execution_verification_result=executed,
        report=report,
    )


def induce_split_grammar_from_files(
    annotation_path: Path,
    config_path: Path,
    output_directory: Path,
    *,
    lifted_scene_path: Path | None = None,
    overwrite: bool = False,
    verify_image: bool = True,
    verify_execution: bool = True,
    maximum_grammar_depth: int | None = None,
    maximum_primitives: int = 1_000_000,
) -> SplitInductionResult:
    """Run loading, optional verified lifting, induction, and persistence."""
    annotation = load_annotation(annotation_path)
    config = load_construction_config(config_path)
    if lifted_scene_path is None:
        verified = (
            load_and_verify_source_image(annotation, annotation_path)
            if verify_image
            else None
        )
        lifted = lift_assisted_input(
            annotation,
            config,
            verified_source_image=verified,
        ).scene
    else:
        path = Path(lifted_scene_path).expanduser().resolve()
        if not path.is_file():
            raise SplitInductionValidationError(f"lifted_observations_missing: {path}")
        try:
            lifted = lifted_scene_from_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise SplitInductionValidationError(
                f"lifted_observations_read_failed: {exc}"
            ) from exc
    result = induce_split_grammar(
        annotation,
        config,
        lifted,
        verify_execution=verify_execution,
        maximum_grammar_depth=maximum_grammar_depth,
        maximum_primitives=maximum_primitives,
    )
    from scene_grammar_kit.assisted.split_induction_persistence import (
        save_split_induction_result,
    )

    save_split_induction_result(result, output_directory, overwrite=overwrite)
    return result


def _verify_lifted_identity(
    annotation: SceneAnnotation,
    config: ConstructionConfig,
    lifted: LiftedSceneObservations,
) -> None:
    annotation_hash = _sha256_text(annotation_to_canonical_json(annotation))
    config_hash = _sha256_text(construction_config_to_canonical_json(config))
    checks = (
        (
            lifted.scene_id == annotation.scene_id,
            "lifted_scene_id_mismatch",
        ),
        (
            lifted.annotation_sha256 == annotation_hash,
            "lifted_annotation_hash_mismatch",
        ),
        (
            lifted.construction_config_sha256 == config_hash,
            "lifted_config_hash_mismatch",
        ),
        (
            lifted.root_bounds == config.root_bounds,
            "lifted_root_bounds_mismatch",
        ),
        (
            lifted.depth_zone_intervals == config.depth_zone_intervals,
            "lifted_depth_intervals_mismatch",
        ),
    )
    for valid, code in checks:
        if not valid:
            raise SplitInductionValidationError(code)


def _verify_expected_observations(context: _Context) -> None:
    expected = [
        *(f"region:{item.region_id}" for item in context.annotation.regions),
        *(f"instance:{item.instance_id}" for item in context.annotation.instances),
    ]
    actual = [context.key(item) for item in context.lifted.observations]
    if actual != expected:
        missing = [item for item in expected if item not in actual]
        duplicates = sorted({item for item in actual if actual.count(item) > 1})
        if missing:
            raise SplitInductionValidationError(
                "missing_lifted_observation: " + ", ".join(missing)
            )
        if duplicates:
            raise SplitInductionValidationError(
                "duplicate_lifted_observation: " + ", ".join(duplicates)
            )
        raise SplitInductionValidationError("lifted_observation_order_mismatch")


def _require_complete_root_depth_coverage(config: ConstructionConfig) -> None:
    intervals = config.depth_zone_intervals
    if (
        intervals[0].z_min != config.root_bounds.minimum.z
        or intervals[0].z_max != intervals[1].z_min
        or intervals[1].z_max != intervals[2].z_min
        or intervals[2].z_max != config.root_bounds.maximum.z
    ):
        raise SplitInductionValidationError(
            "incomplete_depth_coverage: split-only root requires contiguous "
            "configured foreground/midground/background intervals"
        )


def _top_level_items(context: _Context, zone: DepthZone) -> tuple[_Item, ...]:
    observations = [
        item
        for item in context.lifted.observations
        if item.depth_zone is zone and item.parent_region_id is None
    ]
    return _ordered_items(context, observations)


def _direct_children(
    context: _Context,
    parent_id: str,
) -> tuple[_Item, ...]:
    observations = [
        item
        for item in context.lifted.observations
        if item.parent_region_id == parent_id
    ]
    return _ordered_items(context, observations)


def _ordered_items(
    context: _Context,
    observations: list[LiftedObservation],
) -> tuple[_Item, ...]:
    items = [
        _Item(item, context.annotation_order[context.key(item)])
        for item in observations
    ]
    hints = [item.observation.supplied_order_hint for item in items]
    if (
        items
        and all(hint is not None for hint in hints)
        and len(set(hints)) == len(hints)
    ):
        items.sort(
            key=lambda item: (
                item.observation.supplied_order_hint,
                item.annotation_index,
            )
        )
    else:
        items.sort(key=lambda item: item.annotation_index)
    return tuple(items)


def _build_container(
    context: _Context,
    *,
    parent_bounds: Bounds3D,
    items: tuple[_Item, ...],
    parent_source_id: str,
    parent_hint: Axis | None,
    background_observation: LiftedObservation | None,
    path: str,
    depth: int,
) -> SplitNode | TerminalNode:
    _check_depth(context, depth, path)
    if not items:
        if background_observation is not None:
            return _source_terminal(
                context,
                background_observation,
                path=path,
                fragment=True,
            )
        return _empty_terminal(context, parent_source_id, Axis.X, path)
    if len(items) == 1:
        return _build_observation(
            context,
            items[0].observation,
            allocated_bounds=parent_bounds,
            background_observation=background_observation,
            path=f"{path}.{items[0].observation.source_annotation_id}",
            depth=depth,
        )

    axis, source, candidates, tolerance = _select_axis(
        context,
        parent_bounds,
        items,
        parent_source_id,
        parent_hint,
        path,
    )
    context.axis_decisions.append(
        AxisDecision(
            parent_source_id=parent_source_id,
            candidate_scores=candidates,
            selected_axis=axis,
            selection_source=source,
            world_tolerance=tolerance,
            structural_path=path,
        )
    )
    segments, interval_decisions = _partition_segments(
        context,
        parent_bounds,
        items,
        axis,
        parent_source_id,
        tolerance,
        path,
    )
    children: list[SplitChild] = []
    boundaries = [segments[0].minimum]
    affected: list[str] = []
    for index, segment in enumerate(segments):
        segment_bounds = _replace_interval(
            parent_bounds,
            axis,
            segment.minimum,
            segment.maximum,
        )
        if segment.item is None:
            node = _filler_terminal(
                context,
                background_observation,
                parent_source_id,
                axis,
                path=f"{path}.gap[{index}]",
            )
            assert segment.reason is not None
            if background_observation is None:
                context.gap_decisions.append(
                    GapDecision(
                        parent_source_id=parent_source_id,
                        axis=axis,
                        gap_interval=(segment.minimum, segment.maximum),
                        reason=segment.reason,
                        generated_empty_node_id=node.node_id,
                        structural_path=f"{path}.gap[{index}]",
                    )
                )
                code = {
                    GapReason.LEADING_MARGIN: "leading_margin_created",
                    GapReason.INTERNAL_GAP: "explicit_gap_created",
                    GapReason.TRAILING_MARGIN: "trailing_margin_created",
                }[segment.reason]
                context.diagnostic(
                    code,
                    f"Created explicit {segment.reason.value} interval "
                    f"[{segment.minimum}, {segment.maximum}].",
                    node_id=node.node_id,
                    path=path,
                )
        else:
            observation = segment.item.observation
            affected.append(observation.source_annotation_id)
            node = _build_observation(
                context,
                observation,
                allocated_bounds=segment_bounds,
                background_observation=background_observation,
                path=f"{path}.{observation.source_annotation_id}",
                depth=depth + 1,
            )
        weight = segment.maximum - segment.minimum
        children.append(SplitChild(weight=weight, node=node))
        boundaries.append(segment.maximum)
    if len(children) < 2:
        context.fail(
            "no_partition_axis",
            "Partition did not produce at least two positive children.",
            source_id=parent_source_id,
            path=path,
        )
    context.split_counter += 1
    node_id = context.new_node_id(
        f"induced_split_{context.source_token(parent_source_id)}_"
        f"{axis.value}_{context.split_counter}"
    )
    node = SplitNode(node_id=node_id, axis=axis, children=tuple(children))
    context.boundary_decisions.append(
        BoundaryDecision(
            parent_source_id=parent_source_id,
            axis=axis,
            parent_interval=axis_interval(parent_bounds, axis),
            intervals=interval_decisions,
            final_boundaries=tuple(boundaries),
            final_weights=tuple(child.weight for child in children),
            world_tolerance=tolerance,
            affected_source_ids=tuple(affected),
            structural_path=path,
        )
    )
    return node


def _build_observation(
    context: _Context,
    observation: LiftedObservation,
    *,
    allocated_bounds: Bounds3D,
    background_observation: LiftedObservation | None,
    path: str,
    depth: int,
) -> SplitNode | TerminalNode:
    _check_depth(context, depth, path)
    target = _contained_target(
        context,
        observation,
        allocated_bounds,
        path,
    )
    children = _direct_children(context, observation.source_annotation_id)

    def build_content(
        content_bounds: Bounds3D,
        content_path: str,
        content_depth: int,
    ) -> SplitNode | TerminalNode:
        if observation.purpose is ObservationPurpose.STRUCTURAL:
            if not children:
                context.fail(
                    "structural_region_without_children",
                    "Structural region has no usable direct children.",
                    source_id=observation.source_annotation_id,
                    path=content_path,
                )
            node = _build_container(
                context,
                parent_bounds=content_bounds,
                items=children,
                parent_source_id=observation.source_annotation_id,
                parent_hint=observation.supplied_split_axis_hint,
                background_observation=None,
                path=content_path,
                depth=content_depth,
            )
            context.map_node(observation, node.node_id)
            return node
        if children:
            node = _build_container(
                context,
                parent_bounds=content_bounds,
                items=children,
                parent_source_id=observation.source_annotation_id,
                parent_hint=observation.supplied_split_axis_hint,
                background_observation=observation,
                path=content_path,
                depth=content_depth,
            )
            context.map_node(observation, node.node_id)
            return node
        return _source_terminal(context, observation, path=content_path)

    return _wrap_to_target(
        context,
        allocated_bounds=allocated_bounds,
        target_bounds=target,
        axes=_AXES,
        build_content=build_content,
        background_observation=background_observation,
        source_observation=observation,
        path=path,
        depth=depth,
    )


def _wrap_to_target(
    context: _Context,
    *,
    allocated_bounds: Bounds3D,
    target_bounds: Bounds3D,
    axes: tuple[Axis, ...],
    build_content: Callable[[Bounds3D, str, int], SplitNode | TerminalNode],
    background_observation: LiftedObservation | None,
    source_observation: LiftedObservation,
    path: str,
    depth: int,
) -> SplitNode | TerminalNode:
    if not axes:
        return build_content(allocated_bounds, path, depth)
    axis = axes[0]
    parent_min, parent_max = axis_interval(allocated_bounds, axis)
    target_min, target_max = axis_interval(target_bounds, axis)
    tolerance = context.config.boundary_merge_tolerance * (parent_max - parent_min)
    leading = target_min - parent_min
    trailing = parent_max - target_max
    adjusted_min = parent_min if leading <= tolerance else target_min
    adjusted_max = parent_max if trailing <= tolerance else target_max
    if 0.0 < leading <= tolerance:
        context.diagnostic(
            "small_gap_absorbed",
            f"Absorbed leading wrapper margin {leading} within tolerance.",
            source_id=source_observation.source_annotation_id,
            path=path,
        )
        context.diagnostic(
            "boundary_snapped",
            f"Snapped leading wrapper boundary to parent minimum {parent_min}.",
            source_id=source_observation.source_annotation_id,
            path=path,
        )
    if 0.0 < trailing <= tolerance:
        context.diagnostic(
            "small_gap_absorbed",
            f"Absorbed trailing wrapper margin {trailing} within tolerance.",
            source_id=source_observation.source_annotation_id,
            path=path,
        )
        context.diagnostic(
            "boundary_snapped",
            f"Snapped trailing wrapper boundary to parent maximum {parent_max}.",
            source_id=source_observation.source_annotation_id,
            path=path,
        )
    adjusted_target = _replace_interval(
        target_bounds,
        axis,
        adjusted_min,
        adjusted_max,
    )
    if adjusted_min == parent_min and adjusted_max == parent_max:
        return _wrap_to_target(
            context,
            allocated_bounds=allocated_bounds,
            target_bounds=adjusted_target,
            axes=axes[1:],
            build_content=build_content,
            background_observation=background_observation,
            source_observation=source_observation,
            path=path,
            depth=depth,
        )

    _check_depth(context, depth + 1, path)
    pieces: list[tuple[float, float, bool, GapReason | None]] = []
    if adjusted_min > parent_min:
        pieces.append((parent_min, adjusted_min, False, GapReason.LEADING_MARGIN))
    pieces.append((adjusted_min, adjusted_max, True, None))
    if adjusted_max < parent_max:
        pieces.append((adjusted_max, parent_max, False, GapReason.TRAILING_MARGIN))
    children = []
    for index, (low, high, is_content, reason) in enumerate(pieces):
        child_bounds = _replace_interval(allocated_bounds, axis, low, high)
        if is_content:
            node = _wrap_to_target(
                context,
                allocated_bounds=child_bounds,
                target_bounds=adjusted_target,
                axes=axes[1:],
                build_content=build_content,
                background_observation=background_observation,
                source_observation=source_observation,
                path=f"{path}.content",
                depth=depth + 1,
            )
        else:
            node = _filler_terminal(
                context,
                background_observation,
                source_observation.source_annotation_id,
                axis,
                path=f"{path}.wrapper[{index}]",
            )
            assert reason is not None
            if background_observation is None:
                context.gap_decisions.append(
                    GapDecision(
                        parent_source_id=(source_observation.source_annotation_id),
                        axis=axis,
                        gap_interval=(low, high),
                        reason=reason,
                        generated_empty_node_id=node.node_id,
                        structural_path=f"{path}.wrapper[{index}]",
                    )
                )
                code = (
                    "leading_margin_created"
                    if reason is GapReason.LEADING_MARGIN
                    else "trailing_margin_created"
                )
                context.diagnostic(
                    code,
                    f"Created explicit wrapper {reason.value} interval "
                    f"[{low}, {high}].",
                    node_id=node.node_id,
                    path=path,
                )
        children.append(SplitChild(weight=high - low, node=node))
    context.wrapper_counter += 1
    node_id = context.new_node_id(
        f"induced_wrapper_{context.source_token(source_observation.source_annotation_id)}_"
        f"{axis.value}_{context.wrapper_counter}"
    )
    node = SplitNode(node_id=node_id, axis=axis, children=tuple(children))
    context.map_node(source_observation, node_id)
    context.diagnostic(
        "wrapper_split_created",
        f"Created {axis.value}-axis wrapper split for limited source bounds.",
        source_id=source_observation.source_annotation_id,
        node_id=node_id,
        path=path,
    )
    return node


def _select_axis(
    context: _Context,
    parent_bounds: Bounds3D,
    items: tuple[_Item, ...],
    parent_source_id: str,
    parent_hint: Axis | None,
    path: str,
) -> tuple[
    Axis,
    AxisSelectionSource,
    tuple[AxisCandidateScore, ...],
    float,
]:
    candidates = tuple(
        _candidate_score(context, parent_bounds, items, axis) for axis in _AXES
    )
    score_by_axis = {item.axis: item for item in candidates}
    selected: Axis | None = None
    source: AxisSelectionSource | None = None
    if parent_hint is not None:
        selected = parent_hint
        source = AxisSelectionSource.SUPPLIED_REGION_HINT
        context.diagnostic(
            "supplied_split_axis_used",
            f"Used supplied {selected.value}-axis structural hint.",
            source_id=parent_source_id,
            path=path,
        )
    else:
        group_ids = {item.observation.repeat_group_id for item in items}
        if (
            len(group_ids) == 1
            and None not in group_ids
            and all(
                item.observation.source_annotation_type
                is ObservationSourceType.INSTANCE
                for item in items
            )
        ):
            group_id = next(iter(group_ids))
            assert group_id is not None
            selected = context.repeat_by_id[group_id].axis_hint
            source = AxisSelectionSource.SUPPLIED_REPEAT_HINT
            context.diagnostic(
                "supplied_repeat_axis_used",
                f"Used supplied repeat-group {selected.value}-axis hint.",
                source_id=parent_source_id,
                path=path,
            )
            context.diagnostic(
                "repeat_candidate_deferred",
                f"Repeat group {group_id} remains independent terminals.",
                source_id=group_id,
                path=path,
            )
        elif context.config.axis_policy is ConstructionAxisPolicy.HINTS_REQUIRED:
            context.fail(
                "no_partition_axis",
                "Axis policy hints_required has no applicable supplied hint.",
                source_id=parent_source_id,
                path=path,
            )
        else:
            valid = [item for item in candidates if item.valid]
            if valid:
                selected = min(
                    valid,
                    key=lambda item: (
                        item.overlap_violations,
                        -item.normalized_centroid_spread,
                        -item.normalized_coverage,
                        item.explicit_gap_count,
                        _AXES.index(item.axis),
                    ),
                ).axis
                source = AxisSelectionSource.DERIVED_GEOMETRY
                context.diagnostic(
                    "geometry_axis_selected",
                    f"Selected {selected.value}-axis by deterministic geometry score.",
                    source_id=parent_source_id,
                    path=path,
                )
            else:
                context.fail(
                    "no_partition_axis",
                    "No axis forms a contained non-overlapping partition.",
                    source_id=parent_source_id,
                    path=path,
                )
    assert selected is not None and source is not None
    if not score_by_axis[selected].valid:
        intervals = [
            axis_interval(item.observation.world_bounds, selected) for item in items
        ]
        parent_interval = axis_interval(parent_bounds, selected)
        tolerance = context.config.boundary_merge_tolerance * (
            parent_interval[1] - parent_interval[0]
        )
        if any(
            low < parent_interval[0] - tolerance
            or high > parent_interval[1] + tolerance
            for low, high in intervals
        ):
            context.fail(
                "child_outside_parent",
                f"Child interval lies outside parent on axis {selected.value}.",
                source_id=parent_source_id,
                path=path,
            )
        context.fail(
            "child_interval_overlap",
            f"Selected axis {selected.value} contains excessive overlap.",
            source_id=parent_source_id,
            path=path,
        )
    parent_low, parent_high = axis_interval(parent_bounds, selected)
    return (
        selected,
        source,
        candidates,
        context.config.boundary_merge_tolerance * (parent_high - parent_low),
    )


def _candidate_score(
    context: _Context,
    parent_bounds: Bounds3D,
    items: tuple[_Item, ...],
    axis: Axis,
) -> AxisCandidateScore:
    parent_low, parent_high = axis_interval(parent_bounds, axis)
    extent = parent_high - parent_low
    tolerance = context.config.boundary_merge_tolerance * extent
    intervals = [axis_interval(item.observation.world_bounds, axis) for item in items]
    positive = all(high > low for low, high in intervals)
    contained = all(
        low >= parent_low - tolerance and high <= parent_high + tolerance
        for low, high in intervals
    )
    ordered = sorted(intervals)
    overlaps = sum(
        max(0.0, first[1] - second[0]) > tolerance
        for first, second in zip(ordered, ordered[1:])
    )
    gaps = sum(
        second[0] - first[1] > tolerance for first, second in zip(ordered, ordered[1:])
    )
    gaps += int(ordered[0][0] - parent_low > tolerance)
    gaps += int(parent_high - ordered[-1][1] > tolerance)
    centroids = [(low + high) / 2.0 for low, high in intervals]
    spread = (max(centroids) - min(centroids)) / extent
    coverage = min(
        1.0,
        math.fsum(high - low for low, high in intervals) / extent,
    )
    return AxisCandidateScore(
        axis=axis,
        valid=positive and contained and overlaps == 0,
        overlap_violations=overlaps,
        normalized_centroid_spread=spread,
        normalized_coverage=coverage,
        explicit_gap_count=gaps,
    )


def _partition_segments(
    context: _Context,
    parent_bounds: Bounds3D,
    items: tuple[_Item, ...],
    axis: Axis,
    parent_source_id: str,
    tolerance: float,
    path: str,
) -> tuple[tuple[_Segment, ...], tuple[IntervalDecision, ...]]:
    parent_low, parent_high = axis_interval(parent_bounds, axis)
    work = [
        [
            axis_interval(item.observation.world_bounds, axis)[0],
            axis_interval(item.observation.world_bounds, axis)[1],
            item,
        ]
        for item in items
    ]
    if any(
        float(work[index][0]) > float(work[index + 1][0])
        for index in range(len(work) - 1)
    ):
        context.fail(
            "no_partition_axis",
            "Supplied sibling order conflicts with spatial interval order.",
            source_id=parent_source_id,
            path=path,
        )
    for low, high, item in work:
        if float(low) < parent_low - tolerance or float(high) > parent_high + tolerance:
            context.fail(
                "child_outside_parent",
                f"Child {item.observation.source_annotation_id} lies outside parent.",
                source_id=item.observation.source_annotation_id,
                path=path,
            )
        if float(high) - float(low) < (
            context.config.minimum_normalized_region_extent * (parent_high - parent_low)
        ):
            context.fail(
                "observation_below_minimum_extent",
                f"Observation {item.observation.source_annotation_id} is below "
                "the configured minimum extent on the selected axis.",
                source_id=item.observation.source_annotation_id,
                path=path,
            )
    original = [(float(low), float(high), item) for low, high, item in work]
    work[0][0] = (
        parent_low if abs(float(work[0][0]) - parent_low) <= tolerance else work[0][0]
    )
    work[-1][1] = (
        parent_high
        if abs(parent_high - float(work[-1][1])) <= tolerance
        else work[-1][1]
    )
    for index in range(len(work) - 1):
        first_high = float(work[index][1])
        second_low = float(work[index + 1][0])
        delta = second_low - first_high
        if delta < -tolerance:
            context.fail(
                "child_interval_overlap",
                f"Adjacent child intervals overlap by {-delta}, exceeding "
                f"tolerance {tolerance}.",
                source_id=parent_source_id,
                path=path,
            )
        if abs(delta) <= tolerance:
            midpoint = (first_high + second_low) / 2.0
            work[index][1] = midpoint
            work[index + 1][0] = midpoint
            context.diagnostic(
                "boundary_snapped",
                f"Snapped adjacent boundary to midpoint {midpoint}.",
                source_id=parent_source_id,
                path=path,
            )
            if delta > 0:
                context.diagnostic(
                    "small_gap_absorbed",
                    f"Absorbed gap {delta} within tolerance {tolerance}.",
                    source_id=parent_source_id,
                    path=path,
                )
    segments: list[_Segment] = []
    if float(work[0][0]) > parent_low:
        segments.append(
            _Segment(
                parent_low,
                float(work[0][0]),
                None,
                GapReason.LEADING_MARGIN,
            )
        )
    for index, (low, high, item) in enumerate(work):
        segments.append(_Segment(float(low), float(high), item, None))
        if index < len(work) - 1 and float(work[index + 1][0]) > float(high):
            segments.append(
                _Segment(
                    float(high),
                    float(work[index + 1][0]),
                    None,
                    GapReason.INTERNAL_GAP,
                )
            )
    if float(work[-1][1]) < parent_high:
        segments.append(
            _Segment(
                float(work[-1][1]),
                parent_high,
                None,
                GapReason.TRAILING_MARGIN,
            )
        )
    if any(segment.maximum <= segment.minimum for segment in segments):
        context.fail(
            "no_partition_axis",
            "Boundary construction produced a non-positive segment.",
            source_id=parent_source_id,
            path=path,
        )
    decisions = tuple(
        IntervalDecision(
            source_annotation_id=item.observation.source_annotation_id,
            source_minimum=source_low,
            source_maximum=source_high,
            final_minimum=float(final[0]),
            final_maximum=float(final[1]),
        )
        for (source_low, source_high, item), final in zip(original, work)
    )
    return tuple(segments), decisions


def _contained_target(
    context: _Context,
    observation: LiftedObservation,
    allocated: Bounds3D,
    path: str,
) -> Bounds3D:
    lows = list(observation.world_bounds.minimum.as_tuple())
    highs = list(observation.world_bounds.maximum.as_tuple())
    parent_lows = allocated.minimum.as_tuple()
    parent_highs = allocated.maximum.as_tuple()
    for index, axis in enumerate(_AXES):
        tolerance = context.config.boundary_merge_tolerance * (
            parent_highs[index] - parent_lows[index]
        )
        if (
            lows[index] < parent_lows[index] - tolerance
            or highs[index] > parent_highs[index] + tolerance
        ):
            context.fail(
                "child_outside_parent",
                f"Observation lies outside parent on axis {axis.value}.",
                source_id=observation.source_annotation_id,
                path=path,
            )
        lows[index] = max(lows[index], parent_lows[index])
        highs[index] = min(highs[index], parent_highs[index])
        if highs[index] <= lows[index]:
            context.fail(
                "observation_below_minimum_extent",
                f"Observation has no positive {axis.value} extent in parent.",
                source_id=observation.source_annotation_id,
                path=path,
            )
    return Bounds3D(Vector3(*lows), Vector3(*highs))


def _source_terminal(
    context: _Context,
    observation: LiftedObservation,
    *,
    path: str,
    fragment: bool = False,
) -> TerminalNode:
    source_token = context.source_token(observation.source_annotation_id)
    if fragment:
        context.fragment_counter += 1
        base = f"induced_region_{source_token}_fragment_{context.fragment_counter}"
    elif observation.source_annotation_type is ObservationSourceType.REGION:
        base = f"induced_region_{source_token}"
    else:
        base = f"induced_instance_{source_token}"
    node_id = context.new_node_id(base)
    geometry = (
        GeometryType.EMPTY
        if observation.purpose is ObservationPurpose.OPEN_SPACE
        else observation.terminal_geometry
    )
    if geometry is None:
        context.fail(
            "structural_region_without_children",
            "A non-structural terminal lacks supplied terminal geometry.",
            source_id=observation.source_annotation_id,
            path=path,
        )
    node = TerminalNode(
        node_id=node_id,
        semantic_class=observation.semantic_class,
        geometry=geometry,
        attributes=dict(observation.attributes),
    )
    context.map_node(observation, node_id, terminal=True)
    return node


def _filler_terminal(
    context: _Context,
    background: LiftedObservation | None,
    parent_source_id: str,
    axis: Axis,
    *,
    path: str,
) -> TerminalNode:
    if background is not None:
        return _source_terminal(context, background, path=path, fragment=True)
    return _empty_terminal(context, parent_source_id, axis, path)


def _empty_terminal(
    context: _Context,
    parent_source_id: str,
    axis: Axis,
    path: str,
) -> TerminalNode:
    context.gap_counter += 1
    node_id = context.new_node_id(
        f"induced_gap_{context.source_token(parent_source_id)}_"
        f"{axis.value}_{context.gap_counter}"
    )
    return TerminalNode(
        node_id=node_id,
        semantic_class="empty_space",
        geometry=GeometryType.EMPTY,
        attributes={"generated_reason": "explicit_partition_filler"},
    )


def _rename_root_node(
    context: _Context,
    node: SplitNode | TerminalNode,
    new_id: str,
) -> SplitNode | TerminalNode:
    old_id = node.node_id
    renamed = replace(node, node_id=new_id)
    context.used_node_ids.discard(old_id)
    for values in context.mapping_ids.values():
        for index, value in enumerate(values):
            if value == old_id:
                values[index] = new_id
    for key, value in tuple(context.mapping_primary.items()):
        if value == old_id:
            context.mapping_primary[key] = new_id
    for diagnostic_index, diagnostic in enumerate(context.diagnostics):
        if diagnostic.grammar_node_id == old_id:
            context.diagnostics[diagnostic_index] = replace(
                diagnostic,
                grammar_node_id=new_id,
            )
    return renamed


def _node_mappings(context: _Context) -> tuple[NodeMapping, ...]:
    results = []
    for observation in context.lifted.observations:
        key = context.key(observation)
        node_ids = tuple(context.mapping_ids.get(key, ()))
        if not node_ids:
            continue
        results.append(
            NodeMapping(
                source_annotation_type=observation.source_annotation_type.value,
                source_annotation_id=observation.source_annotation_id,
                generated_grammar_node_ids=node_ids,
                primary_generated_node_id=context.mapping_primary[key],
                represented_purpose=observation.purpose.value,
            )
        )
    return tuple(results)


def _verify_mapping_uniqueness(
    context: _Context,
    mappings: tuple[NodeMapping, ...],
) -> None:
    owners: dict[str, str] = {}
    for mapping in mappings:
        for node_id in mapping.generated_grammar_node_ids:
            previous = owners.get(node_id)
            if previous is not None and previous != mapping.source_annotation_id:
                context.fail(
                    "duplicate_source_representation",
                    f"Grammar node {node_id} maps to both {previous} and "
                    f"{mapping.source_annotation_id}.",
                )
            owners[node_id] = mapping.source_annotation_id


def _repeat_candidates(
    context: _Context,
) -> tuple[RepeatCandidateRecord, ...]:
    records = []
    for group in context.annotation.repeat_groups:
        terminal_ids = []
        for member_id in group.member_instance_ids:
            values = context.terminal_ids.get(f"instance:{member_id}", [])
            if not values:
                context.fail(
                    "source_observation_omitted",
                    f"Repeat member {member_id} has no independent terminal.",
                    source_id=member_id,
                )
            terminal_ids.append(values[0])
        records.append(
            RepeatCandidateRecord(
                repeat_group_id=group.repeat_group_id,
                supplied_axis=group.axis_hint,
                ordered_source_member_ids=group.member_instance_ids,
                generated_independent_terminal_ids=tuple(terminal_ids),
            )
        )
    return tuple(records)


def _verify_execution_geometry(
    context: _Context,
    executed: ExecutedScene,
    mappings: tuple[NodeMapping, ...],
) -> None:
    if executed.root_bounds != context.config.root_bounds:
        context.fail(
            "execution_verification_failed",
            "Executed root bounds differ from construction configuration.",
        )
    mapping_by_id = {item.source_annotation_id: item for item in mappings}
    for observation in context.lifted.observations:
        mapping = mapping_by_id[observation.source_annotation_id]
        terminal_ids = set(context.terminal_ids.get(context.key(observation), ()))
        if observation.purpose is ObservationPurpose.STRUCTURAL:
            continue
        if observation.terminal_geometry is GeometryType.EMPTY:
            if not terminal_ids:
                context.fail(
                    "source_observation_omitted",
                    f"Empty source {observation.source_annotation_id} has no "
                    "mapped empty occurrence.",
                )
            continue
        primitives = [
            primitive
            for primitive in executed.primitives
            if primitive.source_terminal_id in terminal_ids
        ]
        if not primitives:
            context.fail(
                "execution_verification_failed",
                f"No primitive represents {observation.source_annotation_id}.",
            )
        union = Bounds3D(
            Vector3(
                min(item.bounds.minimum.x for item in primitives),
                min(item.bounds.minimum.y for item in primitives),
                min(item.bounds.minimum.z for item in primitives),
            ),
            Vector3(
                max(item.bounds.maximum.x for item in primitives),
                max(item.bounds.maximum.y for item in primitives),
                max(item.bounds.maximum.z for item in primitives),
            ),
        )
        if not _bounds_close(
            union,
            observation.world_bounds,
            context.config.boundary_merge_tolerance,
            context.config.root_bounds,
        ):
            context.fail(
                "execution_verification_failed",
                f"Executed proxy bounds differ for {observation.source_annotation_id}.",
            )
        del mapping
    if any(
        not bounds_contain(context.config.root_bounds, item.bounds)
        for item in executed.primitives
    ):
        context.fail(
            "execution_verification_failed",
            "An executed primitive lies outside root bounds.",
        )


def _bounds_close(
    first: Bounds3D,
    second: Bounds3D,
    tolerance_fraction: float,
    root: Bounds3D,
) -> bool:
    tolerances = tuple(
        tolerance_fraction * (high - low)
        for low, high in zip(
            root.minimum.as_tuple(),
            root.maximum.as_tuple(),
        )
    )
    return all(
        abs(left - right) <= tolerance
        for left, right, tolerance in zip(
            first.minimum.as_tuple() + first.maximum.as_tuple(),
            second.minimum.as_tuple() + second.maximum.as_tuple(),
            tolerances + tolerances,
        )
    )


def _replace_interval(
    bounds: Bounds3D,
    axis: Axis,
    low: float,
    high: float,
) -> Bounds3D:
    minimum = list(bounds.minimum.as_tuple())
    maximum = list(bounds.maximum.as_tuple())
    index = _AXES.index(axis)
    minimum[index] = low
    maximum[index] = high
    return Bounds3D(Vector3(*minimum), Vector3(*maximum))


def _check_depth(context: _Context, depth: int, path: str) -> None:
    if depth > context.maximum_depth:
        context.fail(
            "execution_verification_failed",
            f"Induced depth {depth} exceeds configured maximum "
            f"{context.maximum_depth}.",
            path=path,
        )


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SplitInductionValidationError(f"{name} must be a positive integer")
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
