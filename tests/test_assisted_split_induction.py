"""Policy and integration tests for Batch 2.4 split-only induction."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    SPLIT_INDUCTION_POLICY_VERSION,
    AxisSelectionSource,
    ConstructionAxisPolicy,
    DepthZone,
    GapReason,
    InstanceAnnotation,
    NormalizedRectangle,
    RepeatCompressionStatus,
    SplitInductionValidationError,
    induce_split_grammar,
    lift_assisted_input,
    load_annotation,
    load_construction_config,
)
from scene_grammar_kit.geometry import execute_grammar
from scene_grammar_kit.grammar import (
    Axis,
    GeometryType,
    RepeatNode,
    SplitNode,
    TerminalNode,
    summarize_grammar,
    validate_grammar,
)

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"
VALID = FIXTURES / "valid"
INDUCTION = FIXTURES / "induction"


def _load_and_induce(name: str, *, config_name: str = "default.construction.json"):
    annotation = load_annotation(INDUCTION / name)
    config = load_construction_config(VALID / config_name)
    lifted = lift_assisted_input(annotation, config).scene
    return annotation, config, lifted, induce_split_grammar(annotation, config, lifted)


def _walk(node):
    yield node
    if isinstance(node, SplitNode):
        for child in node.children:
            yield from _walk(child.node)
    elif isinstance(node, RepeatNode):
        yield from _walk(node.element)


def test_policy_version_is_independent_and_frozen() -> None:
    assert SPLIT_INDUCTION_POLICY_VERSION == "0.1"


def test_root_has_exact_ordered_three_zone_split_and_physical_weights() -> None:
    _, config, _, result = _load_and_induce("two_way_x.annotation.json")
    root = result.induced_grammar.root
    assert isinstance(root, SplitNode)
    assert root.node_id == "induced_scene_depth_zones"
    assert root.axis is Axis.Z
    assert len(root.children) == 3
    assert tuple(child.weight for child in root.children) == tuple(
        item.z_max - item.z_min for item in config.depth_zone_intervals
    )
    assert result.report.root_construction_decision.ordered_zones == (
        "foreground",
        "midground",
        "background",
    )


def test_missing_zones_are_explicit_empty_terminals() -> None:
    _, _, _, result = _load_and_induce("two_way_x.annotation.json")
    root = result.induced_grammar.root
    assert isinstance(root.children[0].node, TerminalNode)
    assert root.children[0].node.geometry is GeometryType.EMPTY
    assert isinstance(root.children[2].node, TerminalNode)
    assert root.children[2].node.geometry is GeometryType.EMPTY


def test_root_execution_reproduces_configured_bounds_and_intervals() -> None:
    _, config, _, result = _load_and_induce("two_way_x.annotation.json")
    executed = execute_grammar(result.induced_grammar)
    assert executed.root_bounds == config.root_bounds
    assert result.report.execution_verification_status is True


def test_supplied_x_hint_and_hierarchy_are_preserved() -> None:
    _, _, _, result = _load_and_induce("two_way_x.annotation.json")
    decision = next(
        item
        for item in result.report.axis_decisions
        if item.parent_source_id == "layout"
    )
    assert decision.selected_axis is Axis.X
    assert decision.selection_source is AxisSelectionSource.SUPPLIED_REGION_HINT
    mapping = {item.source_annotation_id: item for item in result.report.node_mappings}
    assert tuple(mapping) == ("layout", "left", "right")
    assert mapping["left"].represented_purpose == "terminal_candidate"
    assert mapping["right"].represented_purpose == "terminal_candidate"


def test_geometry_axis_selection_and_fixed_tie_break_are_deterministic() -> None:
    _, _, _, first = _load_and_induce("geometry_gap.annotation.json")
    _, _, _, second = _load_and_induce("geometry_gap.annotation.json")
    decision = next(
        item
        for item in first.report.axis_decisions
        if item.parent_source_id == "layout"
    )
    assert decision.selected_axis is Axis.X
    assert decision.selection_source is AxisSelectionSource.DERIVED_GEOMETRY
    assert decision == second.report.axis_decisions[0]


def test_supplied_y_hint_is_selected() -> None:
    annotation = load_annotation(INDUCTION / "two_way_x.annotation.json")
    config = load_construction_config(VALID / "default.construction.json")
    regions = list(annotation.regions)
    regions[0] = replace(regions[0], split_axis_hint=Axis.Y)
    regions[1] = replace(
        regions[1],
        shape=NormalizedRectangle(0.0, 0.5, 1.0, 1.0),
    )
    regions[2] = replace(
        regions[2],
        shape=NormalizedRectangle(0.0, 0.0, 1.0, 0.5),
    )
    annotation = replace(annotation, regions=tuple(regions))
    lifted = lift_assisted_input(annotation, config).scene
    result = induce_split_grammar(annotation, config, lifted)
    decision = next(
        item
        for item in result.report.axis_decisions
        if item.parent_source_id == "layout"
    )
    assert decision.selected_axis is Axis.Y
    assert decision.selection_source is AxisSelectionSource.SUPPLIED_REGION_HINT


def test_supplied_z_hint_is_selected_for_separated_instances() -> None:
    base = load_annotation(INDUCTION / "two_way_x.annotation.json")
    config = load_construction_config(VALID / "default.construction.json")
    parent = replace(base.regions[0], split_axis_hint=Axis.Z)
    instances = (
        InstanceAnnotation(
            instance_id="near",
            semantic_class="object",
            shape=NormalizedRectangle(0.2, 0.7, 0.4, 0.9),
            depth_zone=DepthZone.MIDGROUND,
            terminal_geometry=GeometryType.BOX,
            parent_region_id="layout",
        ),
        InstanceAnnotation(
            instance_id="far",
            semantic_class="object",
            shape=NormalizedRectangle(0.6, 0.0, 0.8, 0.1),
            depth_zone=DepthZone.MIDGROUND,
            terminal_geometry=GeometryType.BOX,
            parent_region_id="layout",
        ),
    )
    annotation = replace(
        base,
        regions=(parent,),
        instances=instances,
        scene_id="supplied_z",
    )
    lifted = lift_assisted_input(annotation, config).scene
    result = induce_split_grammar(annotation, config, lifted)
    decision = next(
        item
        for item in result.report.axis_decisions
        if item.parent_source_id == "layout"
    )
    assert decision.selected_axis is Axis.Z


def test_fixed_axis_tie_break_prefers_x() -> None:
    annotation = load_annotation(INDUCTION / "geometry_gap.annotation.json")
    config = load_construction_config(VALID / "default.construction.json")
    regions = list(annotation.regions)
    regions[1] = replace(
        regions[1],
        shape=NormalizedRectangle(0.0, 0.6, 0.4, 1.0),
    )
    regions[2] = replace(
        regions[2],
        shape=NormalizedRectangle(0.6, 0.0, 1.0, 0.4),
    )
    annotation = replace(annotation, regions=tuple(regions))
    lifted = lift_assisted_input(annotation, config).scene
    result = induce_split_grammar(annotation, config, lifted)
    decision = next(
        item
        for item in result.report.axis_decisions
        if item.parent_source_id == "layout"
    )
    assert decision.candidate_scores[0].valid
    assert decision.candidate_scores[1].valid
    assert decision.selected_axis is Axis.X


def test_large_gap_and_margins_create_explicit_empty_terminals() -> None:
    _, _, _, result = _load_and_induce("geometry_gap.annotation.json")
    reasons = {item.reason for item in result.report.gap_decisions}
    assert GapReason.LEADING_MARGIN in reasons
    assert GapReason.INTERNAL_GAP in reasons
    assert GapReason.TRAILING_MARGIN in reasons
    nodes = {node.node_id: node for node in _walk(result.induced_grammar.root)}
    for decision in result.report.gap_decisions:
        node = nodes[decision.generated_empty_node_id]
        assert isinstance(node, TerminalNode)
        assert node.geometry is GeometryType.EMPTY


@pytest.mark.parametrize(
    ("left_max", "right_min", "expected_code"),
    [
        (0.495, 0.505, "small_gap_absorbed"),
        (0.505, 0.495, "boundary_snapped"),
    ],
)
def test_small_gap_and_tolerated_overlap_snap_at_midpoint(
    left_max: float,
    right_min: float,
    expected_code: str,
) -> None:
    annotation = load_annotation(INDUCTION / "two_way_x.annotation.json")
    config = load_construction_config(VALID / "default.construction.json")
    regions = list(annotation.regions)
    regions[1] = replace(
        regions[1],
        shape=NormalizedRectangle(0.0, 0.0, left_max, 1.0),
    )
    regions[2] = replace(
        regions[2],
        shape=NormalizedRectangle(right_min, 0.0, 1.0, 1.0),
    )
    annotation = replace(annotation, regions=tuple(regions))
    lifted = lift_assisted_input(annotation, config).scene
    result = induce_split_grammar(annotation, config, lifted)
    codes = tuple(item.code for item in result.report.diagnostics)
    assert expected_code in codes
    boundary = next(
        item
        for item in result.report.boundary_decisions
        if item.parent_source_id == "layout"
    )
    assert boundary.intervals[0].final_maximum == 0.5
    assert boundary.intervals[1].final_minimum == 0.5


def test_excessive_overlap_fails_clearly() -> None:
    annotation = load_annotation(INDUCTION / "two_way_x.annotation.json")
    config = load_construction_config(VALID / "default.construction.json")
    regions = list(annotation.regions)
    regions[1] = replace(
        regions[1],
        shape=NormalizedRectangle(0.0, 0.0, 0.6, 1.0),
    )
    regions[2] = replace(
        regions[2],
        shape=NormalizedRectangle(0.4, 0.0, 1.0, 1.0),
    )
    annotation = replace(annotation, regions=tuple(regions))
    lifted = lift_assisted_input(annotation, config).scene
    with pytest.raises(
        SplitInductionValidationError,
        match="child_interval_overlap",
    ):
        induce_split_grammar(annotation, config, lifted)


def test_unpartitionable_overlapping_children_fail_without_assertion() -> None:
    annotation = load_annotation(INDUCTION / "geometry_gap.annotation.json")
    config = load_construction_config(VALID / "default.construction.json")
    regions = list(annotation.regions)
    identical = NormalizedRectangle(0.2, 0.2, 0.8, 0.8)
    regions[1] = replace(regions[1], shape=identical)
    regions[2] = replace(regions[2], shape=identical)
    annotation = replace(annotation, regions=tuple(regions))
    lifted = lift_assisted_input(annotation, config).scene
    with pytest.raises(
        SplitInductionValidationError,
        match="no_partition_axis",
    ):
        induce_split_grammar(annotation, config, lifted)


def test_structural_region_without_children_fails_clearly() -> None:
    annotation = load_annotation(
        INDUCTION / "structural_without_children.annotation.json"
    )
    config = load_construction_config(VALID / "default.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    with pytest.raises(
        SplitInductionValidationError,
        match="structural_region_without_children",
    ):
        induce_split_grammar(annotation, config, lifted)


def test_hints_required_fails_without_applicable_hint() -> None:
    annotation = load_annotation(INDUCTION / "geometry_gap.annotation.json")
    base = load_construction_config(VALID / "default.construction.json")
    config = replace(base, axis_policy=ConstructionAxisPolicy.HINTS_REQUIRED)
    validation_lifted = lift_assisted_input(annotation, base).scene
    with pytest.raises(
        SplitInductionValidationError,
        match="no_partition_axis",
    ):
        induce_split_grammar(annotation, config, validation_lifted)


def test_wrapper_splits_isolate_limited_bounds_and_have_stable_ids() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    first = induce_split_grammar(annotation, config, lifted)
    second = induce_split_grammar(annotation, config, lifted)
    wrapper_codes = [
        item
        for item in first.report.diagnostics
        if item.code == "wrapper_split_created"
    ]
    assert wrapper_codes
    assert first.induced_grammar == second.induced_grammar
    assert first.report.node_mappings == second.report.node_mappings
    car_mapping = next(
        item
        for item in first.report.node_mappings
        if item.source_annotation_id == "car_1"
    )
    assert any(
        "wrapper_car_1" in item for item in car_mapping.generated_grammar_node_ids
    )
    assert any(
        "instance_car_1" in item for item in car_mapping.generated_grammar_node_ids
    )


def test_urban_repeat_members_are_independent_and_repeat_is_deferred() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    result = induce_split_grammar(annotation, config, lifted)
    assert not any(
        isinstance(node, RepeatNode) for node in _walk(result.induced_grammar.root)
    )
    assert result.report.repeat_node_count == 0
    candidate = result.report.repeat_candidates[0]
    assert candidate.ordered_source_member_ids == ("car_1", "car_2", "car_3")
    assert candidate.supplied_axis is Axis.X
    assert candidate.compression_status is RepeatCompressionStatus.DEFERRED_TO_BATCH_2_5
    assert all(
        node_id.startswith("induced_instance_car_")
        for node_id in candidate.generated_independent_terminal_ids
    )
    assert any(
        item.code == "supplied_repeat_axis_used" for item in result.report.diagnostics
    )


def test_every_urban_observation_is_mapped_exactly_once() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    result = induce_split_grammar(annotation, config, lifted)
    assert result.report.source_observation_count == 9
    assert result.report.represented_observation_count == 9
    assert result.report.omitted_observation_count == 0
    assert len(result.report.node_mappings) == 9
    assert (
        len({mapping.source_annotation_id for mapping in result.report.node_mappings})
        == 9
    )


def test_semantics_geometry_attributes_and_open_space_are_preserved() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    result = induce_split_grammar(annotation, config, lifted)
    terminals = [
        node
        for node in _walk(result.induced_grammar.root)
        if isinstance(node, TerminalNode)
    ]
    car = next(item for item in terminals if item.node_id == "induced_instance_car_1")
    assert car.semantic_class == "car"
    assert car.geometry is GeometryType.BOX
    assert dict(car.attributes) == {"color_label": "red"}
    foreground = [item for item in terminals if item.semantic_class == "foreground"]
    assert foreground
    assert all(item.geometry is GeometryType.EMPTY for item in foreground)


def test_induced_grammar_validates_executes_and_respects_depth_limit() -> None:
    _, config, _, result = _load_and_induce("two_way_x.annotation.json")
    assert validate_grammar(
        result.induced_grammar,
        max_depth=config.maximum_grammar_depth,
    ).is_valid
    assert execute_grammar(result.induced_grammar).report.success
    with pytest.raises(
        SplitInductionValidationError,
        match="exceeds configured maximum",
    ):
        _, _, lifted, _ = _load_and_induce("two_way_x.annotation.json")
        induce_split_grammar(
            load_annotation(INDUCTION / "two_way_x.annotation.json"),
            config,
            lifted,
            maximum_grammar_depth=1,
        )


def test_input_identity_mismatches_and_missing_observation_fail() -> None:
    annotation, config, lifted, _ = _load_and_induce("two_way_x.annotation.json")
    with pytest.raises(
        SplitInductionValidationError,
        match="lifted_scene_id_mismatch",
    ):
        induce_split_grammar(
            annotation,
            config,
            replace(lifted, scene_id="different"),
        )
    with pytest.raises(
        SplitInductionValidationError,
        match="lifted_annotation_hash_mismatch",
    ):
        induce_split_grammar(
            annotation,
            config,
            replace(lifted, annotation_sha256="0" * 64),
        )
    with pytest.raises(
        SplitInductionValidationError,
        match="missing_lifted_observation",
    ):
        induce_split_grammar(
            annotation,
            config,
            replace(lifted, observations=lifted.observations[:-1]),
        )


def test_inputs_remain_immutable_and_no_repeat_spacing_is_reported() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    snapshots = (annotation, config, lifted)
    result = induce_split_grammar(annotation, config, lifted)
    assert snapshots == (annotation, config, lifted)
    report_text = repr(result.report)
    assert "repeat_spacing" not in report_text
    assert "repeat spacing" in result.report.explicitly_not_inferred


def test_report_counts_match_grammar_summary() -> None:
    _, _, _, result = _load_and_induce("geometry_gap.annotation.json")
    summary = summarize_grammar(result.induced_grammar)
    assert result.report.split_node_count == summary.split_node_count
    assert result.report.terminal_node_count == summary.terminal_node_count
    assert result.report.repeat_node_count == summary.repeat_node_count == 0
    assert result.report.canonical_grammar_byte_size == summary.canonical_byte_size
