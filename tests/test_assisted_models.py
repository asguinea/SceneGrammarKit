"""Field-level tests for Batch 2.1 immutable assisted models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from scene_grammar_kit.assisted import (
    ANNOTATION_SCHEMA_VERSION,
    CONSTRUCTION_CONFIG_SCHEMA_VERSION,
    NORMALIZED_IMAGE_COORDINATE_SYSTEM,
    AnnotationRole,
    AnnotationValidationError,
    ConstructionAxisPolicy,
    ConstructionConfig,
    ConstructionConfigValidationError,
    DepthZone,
    DepthZoneInterval,
    InstanceAnnotation,
    NormalizedPoint,
    NormalizedPolygon,
    NormalizedRectangle,
    ProjectionModel,
    RegionAnnotation,
    RepeatGroupAnnotation,
    SceneAnnotation,
    SourceImageReference,
    shape_area,
    shape_bounding_rectangle,
    shape_centroid,
)
from scene_grammar_kit.grammar import Axis, Bounds3D, GeometryType, Vector3


@pytest.mark.parametrize(("u", "v"), [(0, 0), (0.5, 0.75), (1, 1)])
def test_valid_normalized_point(u: float, v: float) -> None:
    assert NormalizedPoint(u, v) == NormalizedPoint(float(u), float(v))


@pytest.mark.parametrize(("u", "v"), [(-0.01, 0.5), (0.5, -1), (1.01, 0.5), (0.5, 2)])
def test_out_of_range_normalized_point_rejected(u: float, v: float) -> None:
    with pytest.raises(AnnotationValidationError):
        NormalizedPoint(u, v)


@pytest.mark.parametrize(("u", "v"), [(True, 0.5), (0.5, False)])
def test_boolean_normalized_point_rejected(u: object, v: object) -> None:
    with pytest.raises(AnnotationValidationError):
        NormalizedPoint(u, v)  # type: ignore[arg-type]


def test_rectangle_helpers_are_deterministic() -> None:
    rectangle = NormalizedRectangle(0.1, 0.2, 0.7, 0.8)
    assert rectangle.width == pytest.approx(0.6)
    assert rectangle.height == pytest.approx(0.6)
    assert rectangle.centroid.u == pytest.approx(0.4)
    assert rectangle.centroid.v == pytest.approx(0.5)
    assert rectangle.area == pytest.approx(0.36)
    assert shape_bounding_rectangle(rectangle) is rectangle


@pytest.mark.parametrize(
    "values",
    [(0.2, 0.1, 0.2, 0.9), (0.8, 0.1, 0.2, 0.9), (0.1, 0.6, 0.9, 0.2)],
)
def test_zero_or_reversed_rectangle_rejected(
    values: tuple[float, float, float, float],
) -> None:
    with pytest.raises(AnnotationValidationError):
        NormalizedRectangle(*values)


def test_polygon_preserves_order_and_has_deterministic_helpers() -> None:
    points = (
        NormalizedPoint(0.1, 0.1),
        NormalizedPoint(0.9, 0.1),
        NormalizedPoint(0.9, 0.9),
        NormalizedPoint(0.1, 0.9),
    )
    polygon = NormalizedPolygon(points)
    assert polygon.points == points
    assert polygon.signed_area == pytest.approx(0.64)
    assert shape_area(polygon) == pytest.approx(0.64)
    assert shape_centroid(polygon) == NormalizedPoint(0.5, 0.5)
    assert polygon.bounding_rectangle == NormalizedRectangle(0.1, 0.1, 0.9, 0.9)


@pytest.mark.parametrize(
    "points",
    [
        (NormalizedPoint(0, 0), NormalizedPoint(1, 0)),
        (
            NormalizedPoint(0, 0),
            NormalizedPoint(1, 0),
            NormalizedPoint(0, 0),
        ),
        (
            NormalizedPoint(0, 0),
            NormalizedPoint(0.5, 0.5),
            NormalizedPoint(1, 1),
        ),
    ],
)
def test_invalid_polygon_rejected(
    points: tuple[NormalizedPoint, ...],
) -> None:
    with pytest.raises(AnnotationValidationError):
        NormalizedPolygon(points)


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/image.png",
        "C:/images/input.png",
        "../images/input.png",
        "images/../input.png",
        "images\\input.png",
        "images//input.png",
        "./images/input.png",
    ],
)
def test_unsafe_source_image_paths_rejected(path: str) -> None:
    with pytest.raises(AnnotationValidationError):
        SourceImageReference("image", path, 100, 100)


def test_safe_source_image_reference_and_hash() -> None:
    digest = "a" * 64
    source = SourceImageReference(
        "image",
        "images/reference.png",
        1200,
        800,
        sha256=digest,
    )
    assert source.sha256 == digest


@pytest.mark.parametrize(("width", "height"), [(0, 10), (10, 0), (True, 10), (10, -1)])
def test_invalid_source_dimensions_rejected(width: object, height: object) -> None:
    with pytest.raises(AnnotationValidationError):
        SourceImageReference(
            "image",
            "images/reference.png",
            width,  # type: ignore[arg-type]
            height,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "g" * 64])
def test_invalid_source_hash_rejected(digest: str) -> None:
    with pytest.raises(AnnotationValidationError):
        SourceImageReference(
            "image",
            "images/reference.png",
            100,
            100,
            sha256=digest,
        )


def test_region_role_geometry_contract() -> None:
    shape = NormalizedRectangle(0, 0, 1, 1)
    structural = RegionAnnotation(
        "layout",
        "layout",
        shape,
        DepthZone.MIDGROUND,
        AnnotationRole.STRUCTURAL_REGION,
        split_axis_hint=Axis.X,
    )
    assert structural.terminal_geometry is None
    with pytest.raises(AnnotationValidationError):
        RegionAnnotation(
            "terminal",
            "road",
            shape,
            DepthZone.MIDGROUND,
            AnnotationRole.TERMINAL_REGION,
        )
    with pytest.raises(AnnotationValidationError):
        RegionAnnotation(
            "open",
            "air",
            shape,
            DepthZone.FOREGROUND,
            AnnotationRole.OPEN_SPACE,
            terminal_geometry=GeometryType.BOX,
        )


def test_instance_empty_geometry_is_only_explicit() -> None:
    instance = InstanceAnnotation(
        "gap",
        "air",
        NormalizedRectangle(0.1, 0.1, 0.2, 0.2),
        DepthZone.MIDGROUND,
        GeometryType.EMPTY,
    )
    assert instance.terminal_geometry is GeometryType.EMPTY


@pytest.mark.parametrize("hint", [-1, True, 1.5])
def test_invalid_order_hint_rejected(hint: object) -> None:
    with pytest.raises(AnnotationValidationError):
        InstanceAnnotation(
            "object",
            "car",
            NormalizedRectangle(0.1, 0.1, 0.2, 0.2),
            DepthZone.MIDGROUND,
            GeometryType.BOX,
            order_hint=hint,  # type: ignore[arg-type]
        )


def test_repeat_group_preserves_order_and_rejects_invalid_members() -> None:
    group = RepeatGroupAnnotation(
        "cars",
        ("car_2", "car_1"),
        Axis.X,
    )
    assert group.member_instance_ids == ("car_2", "car_1")
    assert group.allow_fallback_to_individuals
    with pytest.raises(AnnotationValidationError):
        RepeatGroupAnnotation("one", ("car_1",), Axis.X)
    with pytest.raises(AnnotationValidationError):
        RepeatGroupAnnotation("duplicates", ("car_1", "car_1"), Axis.X)


def test_attribute_defaults_are_immutable_and_not_shared() -> None:
    shape = NormalizedRectangle(0.1, 0.1, 0.2, 0.2)
    first = InstanceAnnotation(
        "first", "car", shape, DepthZone.MIDGROUND, GeometryType.BOX
    )
    second = InstanceAnnotation(
        "second", "car", shape, DepthZone.MIDGROUND, GeometryType.BOX
    )
    assert first.attributes is not second.attributes
    with pytest.raises(TypeError):
        first.attributes["x"] = 1  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        first.instance_id = "changed"  # type: ignore[misc]


def _bounds() -> Bounds3D:
    return Bounds3D(Vector3(0, 0, 0), Vector3(1, 1, 1))


def _intervals() -> tuple[DepthZoneInterval, ...]:
    return (
        DepthZoneInterval(DepthZone.FOREGROUND, 0, 0.2),
        DepthZoneInterval(DepthZone.MIDGROUND, 0.2, 0.8),
        DepthZoneInterval(DepthZone.BACKGROUND, 0.8, 1),
    )


def test_valid_construction_config_defaults() -> None:
    config = ConstructionConfig(
        CONSTRUCTION_CONFIG_SCHEMA_VERSION,
        ProjectionModel.NORMALIZED_ORTHOGRAPHIC_PROXY,
        _bounds(),
        _intervals(),
        ConstructionAxisPolicy.HINTS_THEN_GEOMETRY,
    )
    assert config.minimum_normalized_region_extent == 0.01
    assert config.maximum_grammar_depth == 16
    assert config.require_complete_depth_coverage


@pytest.mark.parametrize(
    "intervals",
    [
        _intervals()[:2],
        (
            DepthZoneInterval(DepthZone.FOREGROUND, 0, 0.2),
            DepthZoneInterval(DepthZone.FOREGROUND, 0.2, 0.8),
            DepthZoneInterval(DepthZone.BACKGROUND, 0.8, 1),
        ),
        (
            DepthZoneInterval(DepthZone.FOREGROUND, 0, 0.4),
            DepthZoneInterval(DepthZone.MIDGROUND, 0.3, 0.8),
            DepthZoneInterval(DepthZone.BACKGROUND, 0.8, 1),
        ),
    ],
)
def test_invalid_depth_zone_sets_or_overlap_rejected(
    intervals: tuple[DepthZoneInterval, ...],
) -> None:
    with pytest.raises(ConstructionConfigValidationError):
        ConstructionConfig(
            "0.1",
            ProjectionModel.NORMALIZED_ORTHOGRAPHIC_PROXY,
            _bounds(),
            intervals,
            ConstructionAxisPolicy.HINTS_THEN_GEOMETRY,
        )


def test_out_of_root_and_incomplete_intervals_rejected() -> None:
    with pytest.raises(ConstructionConfigValidationError):
        ConstructionConfig(
            "0.1",
            ProjectionModel.NORMALIZED_ORTHOGRAPHIC_PROXY,
            _bounds(),
            (
                DepthZoneInterval(DepthZone.FOREGROUND, -0.1, 0.2),
                DepthZoneInterval(DepthZone.MIDGROUND, 0.2, 0.8),
                DepthZoneInterval(DepthZone.BACKGROUND, 0.8, 1),
            ),
            ConstructionAxisPolicy.HINTS_THEN_GEOMETRY,
        )
    with pytest.raises(ConstructionConfigValidationError):
        ConstructionConfig(
            "0.1",
            ProjectionModel.NORMALIZED_ORTHOGRAPHIC_PROXY,
            _bounds(),
            (
                DepthZoneInterval(DepthZone.FOREGROUND, 0, 0.2),
                DepthZoneInterval(DepthZone.MIDGROUND, 0.3, 0.7),
                DepthZoneInterval(DepthZone.BACKGROUND, 0.8, 1),
            ),
            ConstructionAxisPolicy.HINTS_THEN_GEOMETRY,
        )


def test_explicit_depth_gaps_are_allowed() -> None:
    config = ConstructionConfig(
        "0.1",
        ProjectionModel.NORMALIZED_ORTHOGRAPHIC_PROXY,
        _bounds(),
        (
            DepthZoneInterval(DepthZone.FOREGROUND, 0, 0.2),
            DepthZoneInterval(DepthZone.MIDGROUND, 0.3, 0.7),
            DepthZoneInterval(DepthZone.BACKGROUND, 0.8, 1),
        ),
        ConstructionAxisPolicy.HINTS_THEN_GEOMETRY,
        require_complete_depth_coverage=False,
    )
    assert not config.require_complete_depth_coverage


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("boundary_merge_tolerance", -0.1),
        ("repeat_alignment_tolerance", float("inf")),
        ("minimum_normalized_region_extent", 0),
        ("maximum_grammar_depth", 0),
        ("maximum_grammar_depth", True),
    ],
)
def test_invalid_config_controls_rejected(field: str, value: object) -> None:
    arguments = {field: value}
    with pytest.raises(ConstructionConfigValidationError):
        ConstructionConfig(
            "0.1",
            ProjectionModel.NORMALIZED_ORTHOGRAPHIC_PROXY,
            _bounds(),
            _intervals(),
            ConstructionAxisPolicy.HINTS_THEN_GEOMETRY,
            **arguments,  # type: ignore[arg-type]
        )


def test_scene_annotation_versions_and_coordinate_identifier() -> None:
    annotation = SceneAnnotation(
        ANNOTATION_SCHEMA_VERSION,
        "scene",
        SourceImageReference("image", "images/input.png", 100, 100),
        NORMALIZED_IMAGE_COORDINATE_SYSTEM,
        (),
        (),
        (),
    )
    assert annotation.annotation_schema_version == "0.1"
    assert annotation.coordinate_system == "normalized_image_uv"
