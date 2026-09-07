"""Policy, construction, mapping, and fidelity tests for Batch 2.5."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    REPEAT_INDUCTION_POLICY_VERSION,
    DepthZone,
    RepeatDecision,
    RepeatInductionValidationError,
    RepeatRepresentationStatus,
    deterministic_median,
    evaluate_repeat_group,
    induce_repeat_grammar,
    induce_split_grammar,
    lift_assisted_input,
    load_annotation,
    load_construction_config,
)
from scene_grammar_kit.grammar import (
    Bounds3D,
    GeometryType,
    RepeatNode,
    SplitNode,
    TerminalNode,
    Vector3,
    grammar_to_canonical_json,
    summarize_grammar,
    validate_grammar,
)

VALID = Path(__file__).parent / "fixtures" / "assisted" / "valid"


@pytest.fixture(scope="module")
def urban_bundle():
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    split = induce_split_grammar(annotation, config, lifted)
    repeat = induce_repeat_grammar(annotation, config, lifted, split)
    return annotation, config, lifted, split, repeat


def _members(bundle):
    annotation, _, lifted, _, _ = bundle
    ids = annotation.repeat_groups[0].member_instance_ids
    by_id = {item.source_annotation_id: item for item in lifted.observations}
    return tuple(by_id[item] for item in ids)


def _parent_bounds(bundle):
    _, _, lifted, _, _ = bundle
    return next(
        item.world_bounds
        for item in lifted.observations
        if item.source_annotation_id == "road"
    )


def _with_bounds(observation, bounds: Bounds3D):
    centroid = Vector3(
        (bounds.minimum.x + bounds.maximum.x) / 2,
        (bounds.minimum.y + bounds.maximum.y) / 2,
        (bounds.minimum.z + bounds.maximum.z) / 2,
    )
    derived = replace(
        observation.provenance.derived,
        world_bounds=bounds,
        world_centroid=centroid,
    )
    return replace(
        observation,
        world_bounds=bounds,
        world_centroid=centroid,
        provenance=replace(observation.provenance, derived=derived),
    )


def _bounds(x0, x1, y0=0.30, y1=0.44, z0=0.365, z1=0.395):
    return Bounds3D(Vector3(x0, y0, z0), Vector3(x1, y1, z1))


def _metrics(bundle, members=None, group=None, config=None):
    annotation, original_config, _, _, _ = bundle
    return evaluate_repeat_group(
        group or annotation.repeat_groups[0],
        members or _members(bundle),
        config or original_config,
        _parent_bounds(bundle),
    )


def _walk(node):
    yield node
    if isinstance(node, SplitNode):
        for child in node.children:
            yield from _walk(child.node)
    elif isinstance(node, RepeatNode):
        yield from _walk(node.element)


def test_repeat_policy_version_is_independent_and_frozen() -> None:
    assert REPEAT_INDUCTION_POLICY_VERSION == "0.1"


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((3.0, 1.0, 2.0), 2.0),
        ((4.0, 1.0, 3.0, 2.0), 2.5),
    ],
)
def test_deterministic_median(values, expected) -> None:
    assert deterministic_median(values) == expected


def test_deterministic_median_rejects_empty_and_nonfinite() -> None:
    with pytest.raises(RepeatInductionValidationError):
        deterministic_median(())
    with pytest.raises(RepeatInductionValidationError):
        deterministic_median((float("inf"),))


def test_canonical_metrics_use_frozen_equations(urban_bundle) -> None:
    metrics, reasons = _metrics(urban_bundle)
    assert reasons == ()
    assert metrics.member_intervals == (
        (0.36, 0.46),
        (0.49, 0.59),
        (0.62, 0.72),
    )
    assert metrics.pairwise_gaps == pytest.approx((0.03, 0.03))
    assert metrics.group_span == (0.36, 0.72)
    assert metrics.estimated_spacing == pytest.approx(0.03)
    assert metrics.implied_element_extent == pytest.approx(0.10)
    assert metrics.positional_residual < 1e-12
    assert dict(metrics.cross_axis_median_centers) == pytest.approx(
        {"y": 0.37, "z": 0.38}
    )


def test_zero_spacing_is_finite_and_safe(urban_bundle) -> None:
    members = _members(urban_bundle)
    modified = (
        _with_bounds(members[0], _bounds(0.36, 0.46)),
        _with_bounds(members[1], _bounds(0.46, 0.56)),
        _with_bounds(members[2], _bounds(0.56, 0.66)),
    )
    metrics, reasons = _metrics(urban_bundle, modified)
    assert metrics.estimated_spacing == 0.0
    assert metrics.spacing_error == 0.0
    assert metrics.positional_residual < 1e-12
    assert reasons == ()


def test_small_negative_gap_is_clamped_to_zero(urban_bundle) -> None:
    members = _members(urban_bundle)
    modified = (
        members[0],
        _with_bounds(members[1], _bounds(0.459, 0.559)),
        _with_bounds(members[2], _bounds(0.589, 0.689)),
    )
    metrics, reasons = _metrics(urban_bundle, modified)
    assert metrics.pairwise_gaps[0] == 0.0
    assert "repeat_member_overlap" not in reasons


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("alignment", "repeat_alignment_tolerance_exceeded"),
        ("size", "repeat_size_tolerance_exceeded"),
        ("spacing", "repeat_spacing_tolerance_exceeded"),
        ("order", "repeat_member_order_nonmonotonic"),
        ("overlap", "repeat_member_overlap"),
        ("semantic", "repeat_member_semantic_mismatch"),
        ("geometry", "repeat_member_geometry_mismatch"),
        ("parent", "repeat_member_parent_mismatch"),
        ("zone", "repeat_member_depth_zone_mismatch"),
    ],
)
def test_eligibility_rejection_codes(urban_bundle, mutation, reason) -> None:
    annotation, _, _, _, _ = urban_bundle
    members = list(_members(urban_bundle))
    group = annotation.repeat_groups[0]
    if mutation == "alignment":
        members[2] = _with_bounds(members[2], _bounds(0.62, 0.72, 0.50, 0.64))
    elif mutation == "size":
        members[2] = _with_bounds(members[2], _bounds(0.62, 0.72, 0.30, 0.60))
    elif mutation == "spacing":
        members[2] = _with_bounds(members[2], _bounds(0.72, 0.82))
    elif mutation == "order":
        members = list(reversed(members))
        group = replace(
            group, member_instance_ids=tuple(reversed(group.member_instance_ids))
        )
    elif mutation == "overlap":
        members[1] = _with_bounds(members[1], _bounds(0.44, 0.54))
    elif mutation == "semantic":
        members[2] = replace(members[2], semantic_class="truck")
    elif mutation == "geometry":
        members[2] = replace(members[2], terminal_geometry=GeometryType.PLANE)
    elif mutation == "parent":
        members[2] = replace(members[2], parent_region_id="left_sidewalk")
    elif mutation == "zone":
        members[2] = replace(members[2], depth_zone=DepthZone.BACKGROUND)
    _, reasons = _metrics(urban_bundle, tuple(members), group)
    assert reason in reasons


def test_attribute_mismatch_is_canonical(urban_bundle) -> None:
    members = list(_members(urban_bundle))
    supplied = replace(
        members[2].provenance.supplied,
        attributes={"color_label": "blue"},
    )
    members[2] = replace(
        members[2],
        attributes={"color_label": "blue"},
        provenance=replace(members[2].provenance, supplied=supplied),
    )
    _, reasons = _metrics(urban_bundle, tuple(members))
    assert "repeat_member_attribute_mismatch" in reasons


def test_consensus_bounds_must_remain_in_parent(urban_bundle) -> None:
    members = tuple(
        _with_bounds(
            item,
            _bounds(
                item.world_bounds.minimum.x,
                item.world_bounds.maximum.x,
                0.75,
                0.89,
            ),
        )
        for item in _members(urban_bundle)
    )
    _, reasons = _metrics(urban_bundle, members)
    assert "repeat_consensus_bounds_outside_parent" in reasons


def test_invalid_equal_cell_fit_is_rejected(urban_bundle) -> None:
    annotation, _, _, _, _ = urban_bundle
    original = _members(urban_bundle)
    members = (
        _with_bounds(original[0], _bounds(0.0, 0.01)),
        _with_bounds(original[1], _bounds(0.01, 0.02)),
        _with_bounds(original[2], _bounds(10.02, 10.03)),
        _with_bounds(original[0], _bounds(20.03, 20.04)),
    )
    group = replace(
        annotation.repeat_groups[0],
        member_instance_ids=("a", "b", "c", "d"),
    )
    metrics, reasons = _metrics(urban_bundle, members, group)
    assert metrics.implied_element_extent < 0
    assert "repeat_invalid_fit" in reasons


def test_canonical_group_creates_one_stable_repeat(urban_bundle) -> None:
    annotation, config, _, split, result = urban_bundle
    summary = summarize_grammar(result.repeat_grammar)
    nodes = tuple(_walk(result.repeat_grammar.root))
    repeats = [item for item in nodes if isinstance(item, RepeatNode)]
    assert len(repeats) == 1
    assert repeats[0].node_id == "induced_repeat_parked_cars"
    assert repeats[0].element.node_id == "induced_repeat_element_parked_cars"
    assert repeats[0].count == len(annotation.repeat_groups[0].member_instance_ids)
    assert repeats[0].spacing == pytest.approx(0.03)
    assert result.repeat_grammar.root_bounds == config.root_bounds
    assert validate_grammar(result.repeat_grammar).is_valid
    assert summary.repeat_node_count == 1
    assert split.report.induced_grammar_sha256 == (
        "043032701e04d2e7e0765e493500751e1deccec70ff68fc865ae7762af1d2761"
    )


def test_accepted_members_are_not_independent_or_hallucinated(urban_bundle) -> None:
    annotation, _, _, _, result = urban_bundle
    terminals = {
        item.node_id
        for item in _walk(result.repeat_grammar.root)
        if isinstance(item, TerminalNode)
    }
    assert not terminals.intersection(
        {"induced_instance_car_1", "induced_instance_car_2", "induced_instance_car_3"}
    )
    assert len(result.report.member_mappings) == 3
    assert (
        tuple(item.source_instance_id for item in result.report.member_mappings)
        == annotation.repeat_groups[0].member_instance_ids
    )
    assert tuple(
        item.supplied_member_index for item in result.report.member_mappings
    ) == (0, 1, 2)
    assert all(
        item.representation_status
        is RepeatRepresentationStatus.COMPRESSED_REPEAT_INSTANCE
        for item in result.report.member_mappings
    )


def test_execution_fidelity_and_compactness_are_factual(urban_bundle) -> None:
    *_, result = urban_bundle
    fidelity = result.report.fidelity_summary
    compact = result.report.compression_summary
    assert fidelity.root_bounds_equal
    assert fidelity.maximum_non_repeat_observation_change == 0.0
    assert fidelity.maximum_accepted_member_boundary_error == pytest.approx(0.02)
    assert compact.split_only_symbolic_node_count == 43
    assert compact.repeat_symbolic_node_count == 28
    assert compact.split_only_repeat_count == 0
    assert compact.repeat_repeat_count == 1
    assert compact.primitive_count_before == 22
    assert compact.primitive_count_after == 12
    assert compact.absolute_byte_difference == 2044
    assert compact.byte_ratio == pytest.approx(
        compact.repeat_canonical_bytes / compact.split_only_canonical_bytes
    )
    assert "orders of magnitude" not in str(result.report).lower()


def test_repeat_construction_is_deterministic_and_inputs_are_immutable(
    urban_bundle,
) -> None:
    annotation, config, lifted, split, first = urban_bundle
    before = grammar_to_canonical_json(split.induced_grammar)
    second = induce_repeat_grammar(annotation, config, lifted, split)
    assert first == second
    assert grammar_to_canonical_json(first.repeat_grammar) == (
        grammar_to_canonical_json(second.repeat_grammar)
    )
    assert grammar_to_canonical_json(split.induced_grammar) == before


def test_nonmonotonic_group_uses_permitted_fallback() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    group = annotation.repeat_groups[0]
    annotation = replace(
        annotation,
        repeat_groups=(
            replace(
                group,
                member_instance_ids=tuple(reversed(group.member_instance_ids)),
            ),
        ),
    )
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    split = induce_split_grammar(annotation, config, lifted)
    result = induce_repeat_grammar(annotation, config, lifted, split)
    assert result.report.accepted_group_count == 0
    assert result.report.fallback_group_count == 1
    assert result.report.group_decisions[0].decision is RepeatDecision.REJECTED_FALLBACK
    assert "repeat_group_rejected_fallback" in {
        item.code for item in result.report.diagnostics
    }
    assert all(
        item.representation_status is RepeatRepresentationStatus.INDEPENDENT_FALLBACK
        for item in result.report.member_mappings
    )


def test_forbidden_fallback_fails_without_result() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    group = annotation.repeat_groups[0]
    annotation = replace(
        annotation,
        repeat_groups=(
            replace(
                group,
                member_instance_ids=tuple(reversed(group.member_instance_ids)),
                allow_fallback_to_individuals=False,
            ),
        ),
    )
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    split = induce_split_grammar(annotation, config, lifted)
    with pytest.raises(
        RepeatInductionValidationError,
        match="repeat_group_rejected_fatal",
    ):
        induce_repeat_grammar(annotation, config, lifted, split)


def test_no_supplied_repeat_groups_is_explicit() -> None:
    source = load_annotation(VALID / "urban_minimal.annotation.json")
    annotation = replace(
        source,
        instances=tuple(
            replace(item, repeat_group_id=None) for item in source.instances
        ),
        repeat_groups=(),
    )
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    split = induce_split_grammar(annotation, config, lifted)
    result = induce_repeat_grammar(annotation, config, lifted, split)
    assert result.report.supplied_repeat_group_count == 0
    assert result.report.repeat_node_count == 0
    assert result.repeat_grammar == split.induced_grammar
    assert result.report.diagnostics[0].code == "no_repeat_groups_supplied"


def test_execution_can_be_explicitly_disabled(urban_bundle) -> None:
    annotation, config, lifted, split, _ = urban_bundle
    result = induce_repeat_grammar(
        annotation, config, lifted, split, verify_execution=False
    )
    assert result.split_only_execution is None
    assert result.repeat_execution is None
    assert not result.report.execution_status
    assert result.report.compression_summary.primitive_count_before == 0


def test_limits_are_validated(urban_bundle) -> None:
    annotation, config, lifted, split, _ = urban_bundle
    with pytest.raises(RepeatInductionValidationError):
        induce_repeat_grammar(
            annotation, config, lifted, split, maximum_primitives=True
        )
    with pytest.raises(RepeatInductionValidationError):
        induce_repeat_grammar(
            annotation, config, lifted, split, maximum_grammar_depth=0
        )
