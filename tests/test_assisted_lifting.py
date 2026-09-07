"""Coordinate, observation, provenance, and diagnostic tests for Batch 2.3."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    INSTANCE_DEPTH_FRACTION,
    LIFTING_POLICY_VERSION,
    DerivedDepthPolicy,
    ObservationPurpose,
    ObservationSourceType,
    ProxyApproximation,
    construction_config_to_canonical_json,
    instance_proxy_depth_interval,
    lift_assisted_input,
    load_and_verify_source_image,
    load_annotation,
    load_construction_config,
    map_normalized_u_to_world_x,
    map_normalized_v_to_world_y,
    normalized_bounds_to_world_xy,
)
from scene_grammar_kit.assisted.serialization import annotation_to_canonical_json
from scene_grammar_kit.grammar import Axis, GeometryType

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"
VALID = FIXTURES / "valid"
LIFTING = FIXTURES / "lifting"
URBAN_ANNOTATION = VALID / "urban_minimal.annotation.json"
URBAN_CONFIG = VALID / "urban_minimal.construction.json"
FACADE_ANNOTATION = VALID / "facade_polygon.annotation.json"
DEFAULT_CONFIG = VALID / "default.construction.json"
WARNING_ANNOTATION = LIFTING / "warning_cases.annotation.json"
TRANSLATED_CONFIG = LIFTING / "translated.construction.json"


def _lift_urban(*, verified: bool = True):
    annotation = load_annotation(URBAN_ANNOTATION)
    config = load_construction_config(URBAN_CONFIG)
    image = (
        load_and_verify_source_image(annotation, URBAN_ANNOTATION) if verified else None
    )
    return lift_assisted_input(annotation, config, verified_source_image=image)


def _warning_result():
    return lift_assisted_input(
        load_annotation(WARNING_ANNOTATION),
        load_construction_config(TRANSLATED_CONFIG),
    )


@pytest.mark.parametrize(
    ("u", "expected"),
    ((0.0, -2.0), (1.0, 4.0), (0.5, 1.0)),
)
def test_u_maps_to_translated_nonunit_root_x(
    u: float,
    expected: float,
) -> None:
    root = load_construction_config(TRANSLATED_CONFIG).root_bounds
    assert map_normalized_u_to_world_x(u, root) == expected


@pytest.mark.parametrize(
    ("v", "expected"),
    ((0.0, 30.0), (1.0, 10.0), (0.5, 20.0)),
)
def test_v_inverts_to_translated_nonunit_root_y(
    v: float,
    expected: float,
) -> None:
    root = load_construction_config(TRANSLATED_CONFIG).root_bounds
    assert map_normalized_v_to_world_y(v, root) == expected


def test_rectangle_world_bounds_are_exact_and_deterministic() -> None:
    annotation = load_annotation(WARNING_ANNOTATION)
    root = load_construction_config(TRANSLATED_CONFIG).root_bounds
    bounds = annotation.regions[0].shape.bounding_rectangle
    first = normalized_bounds_to_world_xy(bounds, root)
    second = normalized_bounds_to_world_xy(bounds, root)
    assert first == second
    assert first == pytest.approx((-1.4, 16.0, 2.2, 28.0))


def test_polygon_bounding_box_world_bounds_are_exact() -> None:
    result = _warning_result()
    observation = next(
        item
        for item in result.scene.observations
        if item.source_annotation_id == "polygon_region"
    )
    assert observation.proxy_approximation is (
        ProxyApproximation.IMAGE_POLYGON_BOUNDING_BOX
    )
    assert observation.world_bounds.minimum.as_tuple() == pytest.approx(
        (-1.4, 12.0, 10.0)
    )
    assert observation.world_bounds.maximum.as_tuple() == pytest.approx(
        (3.4, 26.0, 11.0)
    )


def test_regions_use_full_configured_depth_intervals() -> None:
    result = _lift_urban()
    for observation in result.scene.observations[:6]:
        interval = next(
            item
            for item in result.scene.depth_zone_intervals
            if item.depth_zone is observation.depth_zone
        )
        assert observation.world_bounds.minimum.z == interval.z_min
        assert observation.world_bounds.maximum.z == interval.z_max
        assert observation.depth_policy is DerivedDepthPolicy.FULL_ZONE_INTERVAL


def test_region_purposes_ids_parent_hints_and_attributes() -> None:
    result = _lift_urban()
    by_id = {item.source_annotation_id: item for item in result.scene.observations}
    assert by_id["midground_layout"].purpose is ObservationPurpose.STRUCTURAL
    assert by_id["left_sidewalk"].purpose is (ObservationPurpose.TERMINAL_CANDIDATE)
    assert by_id["foreground_open"].purpose is ObservationPurpose.OPEN_SPACE
    assert by_id["midground_layout"].observation_id == ("region:midground_layout")
    assert by_id["left_sidewalk"].parent_region_id == "midground_layout"
    assert by_id["midground_layout"].supplied_split_axis_hint is Axis.X
    assert dict(by_id["left_sidewalk"].attributes) == {"side": "left"}


def test_region_terminal_geometry_and_polygon_evidence_are_preserved() -> None:
    result = _lift_urban()
    road = result.scene.observations[3]
    source_polygon = result.annotation.regions[3].shape
    assert road.terminal_geometry is GeometryType.PLANE
    assert road.normalized_source_shape == source_polygon
    assert road.normalized_source_shape.points == source_polygon.points
    assert road.normalized_source_shape.signed_area == source_polygon.signed_area
    assert road.normalized_source_shape.area == source_polygon.area
    assert road.normalized_source_shape.centroid == source_polygon.centroid
    assert road.normalized_source_signed_area == source_polygon.signed_area
    assert road.normalized_source_area == source_polygon.area
    assert road.normalized_source_centroid == source_polygon.centroid
    assert road.proxy_approximation is (ProxyApproximation.IMAGE_POLYGON_BOUNDING_BOX)


def test_instance_xy_mapping_bottom_anchor_and_stable_ids() -> None:
    result = _lift_urban()
    car = result.scene.observations[6]
    assert car.source_annotation_type is ObservationSourceType.INSTANCE
    assert car.observation_id == "instance:car_1"
    assert car.world_bounds.minimum.x == 0.36
    assert car.world_bounds.maximum.x == 0.46
    assert car.world_bounds.minimum.y == pytest.approx(0.28)
    assert car.world_bounds.maximum.y == pytest.approx(0.42)
    assert car.depth_policy is DerivedDepthPolicy.IMAGE_BOTTOM_PROXY_ANCHOR


def test_lower_instance_is_nearer_and_higher_instance_farther() -> None:
    result = _lift_urban()
    cars = result.scene.observations[6:]
    assert (
        cars[0].normalized_source_bounds.v_max > cars[2].normalized_source_bounds.v_max
    )
    assert cars[0].world_centroid.z < cars[2].world_centroid.z


def test_instance_depth_extent_is_fixed_positive_five_percent() -> None:
    result = _lift_urban()
    zone_extent = 0.8 - 0.2
    for observation in result.scene.observations[6:]:
        depth = observation.world_bounds.maximum.z - observation.world_bounds.minimum.z
        assert depth == pytest.approx(zone_extent * INSTANCE_DEPTH_FRACTION)
        assert depth > 0


@pytest.mark.parametrize(
    ("bottom_v", "expected"),
    (
        (1.0, (7.0, 7.15)),
        (0.0, (9.85, 10.0)),
    ),
)
def test_instance_depth_interval_shifts_inside_zone_boundaries(
    bottom_v: float,
    expected: tuple[float, float],
) -> None:
    interval = load_construction_config(TRANSLATED_CONFIG).depth_zone_intervals[1]
    actual = instance_proxy_depth_interval(bottom_v, interval)
    assert actual == pytest.approx(expected)
    assert actual[0] >= interval.z_min
    assert actual[1] <= interval.z_max


def test_instance_supplied_fields_and_repeat_axis_are_preserved() -> None:
    result = _lift_urban()
    car = result.scene.observations[6]
    assert car.repeat_group_id == "parked_cars"
    assert car.supplied_order_hint == 0
    assert car.terminal_geometry is GeometryType.BOX
    assert car.provenance.supplied.repeat_axis_hint is Axis.X
    assert car.provenance.supplied.repeat_group_id == "parked_cars"
    assert dict(car.attributes) == {"color_label": "red"}


def test_provenance_separates_supplied_configuration_and_derived() -> None:
    result = _lift_urban()
    observation = result.scene.observations[6]
    supplied = observation.provenance.supplied
    configuration = observation.provenance.configuration
    derived = observation.provenance.derived
    assert supplied.annotation_id == "car_1"
    assert supplied.depth_zone.value == "midground"
    assert configuration.root_bounds == result.construction_config.root_bounds
    assert configuration.depth_zone_interval.depth_zone.value == "midground"
    assert configuration.projection_model.value == ("normalized_orthographic_proxy")
    assert derived.world_bounds == observation.world_bounds
    assert derived.world_centroid == observation.world_centroid
    assert derived.lifting_policy_version == LIFTING_POLICY_VERSION


def test_scene_hashes_versions_order_and_noninference_disclosure() -> None:
    result = _lift_urban()
    assert (
        result.scene.annotation_sha256
        == hashlib.sha256(
            annotation_to_canonical_json(result.annotation).encode("utf-8")
        ).hexdigest()
    )
    assert (
        result.scene.construction_config_sha256
        == hashlib.sha256(
            construction_config_to_canonical_json(result.construction_config).encode(
                "utf-8"
            )
        ).hexdigest()
    )
    assert result.scene.lifting_policy_version == "0.1"
    assert result.scene.annotation_schema_version == "0.1"
    assert result.scene.construction_config_schema_version == "0.1"
    assert result.scene.source_pixels_used_for_geometric_inference is False
    assert tuple(item.observation_id for item in result.scene.observations) == (
        "region:foreground_open",
        "region:midground_layout",
        "region:left_sidewalk",
        "region:road",
        "region:right_sidewalk",
        "region:background_facade",
        "instance:car_1",
        "instance:car_2",
        "instance:car_3",
    )
    assert "metric depth" in result.report.explicitly_not_inferred
    assert "grammar" in result.report.explicitly_not_inferred


def test_verified_and_model_only_modes_are_explicit() -> None:
    verified = _lift_urban()
    unverified = _lift_urban(verified=False)
    assert verified.scene.image_verification_status is True
    assert verified.scene.verified_source_image_sha256 is not None
    assert unverified.scene.image_verification_status is False
    assert unverified.scene.verified_source_image_sha256 is None
    assert unverified.report.source_image_sha256 is None
    assert unverified.report.warnings[0].code == "image_verification_skipped"


def test_report_counts_and_frequencies_are_correct() -> None:
    report = _lift_urban().report
    assert report.region_observations_created == 6
    assert report.instance_observations_created == 3
    assert report.structural_observations == 1
    assert report.terminal_candidate_observations == 4
    assert report.open_space_observations == 1
    assert report.object_instance_observations == 3
    assert report.rectangle_source_count == 8
    assert report.polygon_source_count == 1
    assert dict(report.depth_zone_frequency) == {
        "background": 1,
        "foreground": 1,
        "midground": 7,
    }
    assert dict(report.geometry_type_frequency) == {
        "box": 5,
        "empty": 1,
        "plane": 2,
    }
    assert report.observations_with_split_axis_hints == 1
    assert report.observations_with_repeat_group_membership == 3


def test_warning_codes_and_order_are_stable() -> None:
    result = _warning_result()
    assert tuple(item.code for item in result.report.warnings) == (
        "image_verification_skipped",
        "polygon_bounding_box_proxy",
        "region_outside_declared_parent",
        "instance_outside_declared_parent",
        "instance_outside_declared_parent",
        "overlapping_structural_regions",
        "empty_instance_terminal_geometry",
        "missing_repeat_member_order_hint",
    )
    assert tuple(item.annotation_id for item in result.report.warnings) == (
        None,
        "polygon_region",
        "outside_child",
        "top_car",
        "bottom_car",
        "struct_a",
        "empty_marker",
        "cars_without_order",
    )
    assert _warning_result().report.warnings == result.report.warnings


def test_lifting_does_not_mutate_inputs() -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    config = load_construction_config(URBAN_CONFIG)
    annotation_before = annotation_to_canonical_json(annotation)
    config_before = construction_config_to_canonical_json(config)
    lift_assisted_input(annotation, config)
    assert annotation_to_canonical_json(annotation) == annotation_before
    assert construction_config_to_canonical_json(config) == config_before
