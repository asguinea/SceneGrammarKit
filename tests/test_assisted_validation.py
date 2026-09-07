"""Document and compatibility validation tests for assisted inputs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    AssistedDiagnosticDomain,
    ConstructionAxisPolicy,
    DepthZone,
    NormalizedRectangle,
    RegionAnnotation,
    RepeatGroupAnnotation,
    load_annotation,
    load_construction_config,
    validate_assisted_input,
    validate_scene_annotation,
)
from scene_grammar_kit.grammar import Axis, GeometryType

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"


def _valid():
    return load_annotation(FIXTURES / "valid" / "urban_minimal.annotation.json")


def _config():
    return load_construction_config(
        FIXTURES / "valid" / "urban_minimal.construction.json"
    )


def _codes(report) -> tuple[str, ...]:
    return tuple(item.code for item in report.diagnostics)


def test_valid_annotation_and_pair_pass() -> None:
    annotation = _valid()
    assert validate_scene_annotation(annotation).is_valid
    report = validate_assisted_input(annotation, _config())
    assert report.is_valid
    assert report.annotation_report.is_valid
    assert report.config_report.is_valid
    assert report.compatibility_diagnostics == ()


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("duplicate_ids.annotation.json", "duplicate_global_annotation_id"),
        ("missing_parent.annotation.json", "missing_parent_region"),
        ("parent_cycle.annotation.json", "region_hierarchy_cycle"),
        (
            "inconsistent_repeat_group.annotation.json",
            "repeat_membership_mismatch",
        ),
        (
            "repeat_semantic_mismatch.annotation.json",
            "repeat_semantic_class_mismatch",
        ),
    ],
)
def test_invalid_document_fixtures_have_stable_codes(
    fixture: str,
    code: str,
) -> None:
    annotation = load_annotation(FIXTURES / "invalid" / fixture)
    report = validate_scene_annotation(annotation)
    assert not report.is_valid
    assert code in _codes(report)
    diagnostic = next(item for item in report.diagnostics if item.code == code)
    assert diagnostic.path
    assert diagnostic.domain is AssistedDiagnosticDomain.ANNOTATION


def test_hierarchy_depth_limit_and_argument_validation() -> None:
    original = _valid()
    shape = NormalizedRectangle(0.1, 0.1, 0.9, 0.9)
    regions = (
        RegionAnnotation(
            "root_region",
            "layout",
            shape,
            DepthZone.MIDGROUND,
            original.regions[1].role,
        ),
        RegionAnnotation(
            "child_region",
            "layout",
            shape,
            DepthZone.MIDGROUND,
            original.regions[1].role,
            parent_region_id="root_region",
        ),
    )
    annotation = replace(original, regions=regions, instances=(), repeat_groups=())
    report = validate_scene_annotation(annotation, maximum_hierarchy_depth=1)
    assert "maximum_hierarchy_depth_exceeded" in _codes(report)
    with pytest.raises(ValueError):
        validate_scene_annotation(annotation, maximum_hierarchy_depth=True)


def test_missing_repeat_member_fails() -> None:
    annotation = _valid()
    group = replace(
        annotation.repeat_groups[0],
        member_instance_ids=("car_1", "missing"),
    )
    report = validate_scene_annotation(replace(annotation, repeat_groups=(group,)))
    assert "missing_repeat_member" in _codes(report)


def test_instance_in_multiple_groups_fails() -> None:
    annotation = _valid()
    second = RepeatGroupAnnotation(
        "second_cars",
        ("car_1", "car_2"),
        Axis.X,
        semantic_class="car",
    )
    report = validate_scene_annotation(
        replace(annotation, repeat_groups=annotation.repeat_groups + (second,))
    )
    assert "instance_in_multiple_repeat_groups" in _codes(report)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("depth_zone", DepthZone.BACKGROUND, "repeat_depth_zone_mismatch"),
        ("terminal_geometry", GeometryType.PLANE, "repeat_geometry_mismatch"),
    ],
)
def test_repeat_member_consistency_failures(
    field: str,
    value: object,
    code: str,
) -> None:
    annotation = _valid()
    changed = replace(annotation.instances[1], **{field: value})
    instances = (
        annotation.instances[0],
        changed,
        annotation.instances[2],
    )
    report = validate_scene_annotation(replace(annotation, instances=instances))
    assert code in _codes(report)


def test_diagnostic_ordering_is_deterministic() -> None:
    annotation = load_annotation(
        FIXTURES / "invalid" / "repeat_semantic_mismatch.annotation.json"
    )
    first = validate_scene_annotation(annotation)
    second = validate_scene_annotation(annotation)
    assert first == second
    assert all(item.code and item.path for item in first.diagnostics)


def test_minimum_extent_compatibility_failure() -> None:
    config = replace(_config(), minimum_normalized_region_extent=0.2)
    report = validate_assisted_input(_valid(), config)
    assert not report.is_valid
    assert "shape_below_minimum_extent" in _codes(report)
    assert all(
        item.domain is AssistedDiagnosticDomain.COMPATIBILITY
        for item in report.compatibility_diagnostics
    )


def test_hints_required_reports_missing_structural_axis() -> None:
    annotation = _valid()
    regions = list(annotation.regions)
    regions[1] = replace(regions[1], split_axis_hint=None)
    config = replace(
        _config(),
        axis_policy=ConstructionAxisPolicy.HINTS_REQUIRED,
    )
    report = validate_assisted_input(
        replace(annotation, regions=tuple(regions)),
        config,
    )
    assert "missing_required_split_axis_hint" in _codes(report)


def test_incompatible_parent_child_depth_zone_fails() -> None:
    annotation = _valid()
    regions = list(annotation.regions)
    regions[2] = replace(regions[2], depth_zone=DepthZone.FOREGROUND)
    report = validate_assisted_input(
        replace(annotation, regions=tuple(regions)),
        _config(),
    )
    assert "incompatible_parent_child_depth_zone" in _codes(report)


def test_every_annotated_zone_resolves_to_config_interval() -> None:
    annotation = _valid()
    configured = {item.depth_zone for item in _config().depth_zone_intervals}
    annotated = {item.depth_zone for item in annotation.regions + annotation.instances}
    assert annotated <= configured
    assert validate_assisted_input(annotation, _config()).is_valid


def test_reports_separate_annotation_and_compatibility_domains() -> None:
    duplicate = load_annotation(FIXTURES / "invalid" / "duplicate_ids.annotation.json")
    config = replace(_config(), minimum_normalized_region_extent=0.9)
    report = validate_assisted_input(duplicate, config)
    assert report.annotation_report.diagnostics
    assert report.compatibility_diagnostics
    assert report.config_report.diagnostics == ()
