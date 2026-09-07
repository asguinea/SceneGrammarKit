"""Canonical lifted-scene, report, and text serialization tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    LiftingSerializationError,
    lift_assisted_input,
    lifted_scene_from_json,
    lifted_scene_to_canonical_json,
    lifted_scene_to_text,
    lifting_report_from_json,
    lifting_report_to_canonical_json,
    load_and_verify_source_image,
    load_annotation,
    load_construction_config,
)

FIXTURES = Path(__file__).parent / "fixtures" / "assisted" / "valid"
URBAN_ANNOTATION = FIXTURES / "urban_minimal.annotation.json"
URBAN_CONFIG = FIXTURES / "urban_minimal.construction.json"
FACADE_ANNOTATION = FIXTURES / "facade_polygon.annotation.json"
FACADE_CONFIG = FIXTURES / "default.construction.json"


def _result(annotation_path: Path = URBAN_ANNOTATION, config_path: Path = URBAN_CONFIG):
    annotation = load_annotation(annotation_path)
    config = load_construction_config(config_path)
    verified = load_and_verify_source_image(annotation, annotation_path)
    return lift_assisted_input(annotation, config, verified_source_image=verified)


def test_scene_round_trip_equality_and_canonical_bytes() -> None:
    result = _result()
    canonical = lifted_scene_to_canonical_json(result.scene)
    parsed = lifted_scene_from_json(canonical)
    assert parsed == result.scene
    assert lifted_scene_to_canonical_json(parsed) == canonical
    assert canonical == canonical.strip()


def test_report_round_trip_equality_and_canonical_bytes() -> None:
    result = _result()
    canonical = lifting_report_to_canonical_json(result.report)
    parsed = lifting_report_from_json(canonical)
    assert parsed == result.report
    assert lifting_report_to_canonical_json(parsed) == canonical
    assert canonical == canonical.strip()


def test_observation_and_polygon_point_order_are_preserved() -> None:
    result = _result()
    parsed = lifted_scene_from_json(lifted_scene_to_canonical_json(result.scene))
    assert tuple(item.observation_id for item in parsed.observations) == tuple(
        item.observation_id for item in result.scene.observations
    )
    original = result.scene.observations[3].normalized_source_shape
    round_tripped = parsed.observations[3].normalized_source_shape
    assert round_tripped.points == original.points


def test_depth_zone_interval_order_is_preserved() -> None:
    result = _result()
    parsed = lifted_scene_from_json(lifted_scene_to_canonical_json(result.scene))
    assert tuple(item.depth_zone.value for item in parsed.depth_zone_intervals) == (
        "foreground",
        "midground",
        "background",
    )


def test_dictionary_insertion_order_does_not_change_output() -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    config = load_construction_config(URBAN_CONFIG)
    first_instance = replace(
        annotation.instances[0], attributes={"zeta": 1, "alpha": 2}
    )
    second_instance = replace(
        annotation.instances[0], attributes={"alpha": 2, "zeta": 1}
    )
    first = lift_assisted_input(
        replace(
            annotation,
            instances=(first_instance,) + annotation.instances[1:],
        ),
        config,
    )
    second = lift_assisted_input(
        replace(
            annotation,
            instances=(second_instance,) + annotation.instances[1:],
        ),
        config,
    )
    assert lifted_scene_to_canonical_json(first.scene) == (
        lifted_scene_to_canonical_json(second.scene)
    )


def test_direct_unicode_is_preserved() -> None:
    annotation = load_annotation(FACADE_ANNOTATION)
    region = replace(
        annotation.regions[0],
        semantic_class="façade_東京",
    )
    result = lift_assisted_input(
        replace(annotation, regions=(region,)),
        load_construction_config(FACADE_CONFIG),
    )
    canonical = lifted_scene_to_canonical_json(result.scene)
    assert "façade_東京" in canonical
    assert "\\u6771" not in canonical


@pytest.mark.parametrize("constant", ("NaN", "Infinity", "-Infinity"))
def test_nonfinite_json_is_rejected(constant: str) -> None:
    scene = lifted_scene_to_canonical_json(_result().scene)
    modified = scene.replace('"annotation_sha256"', f'{constant},"unused"', 1)
    with pytest.raises(LiftingSerializationError):
        lifted_scene_from_json(modified)


def test_unknown_or_malformed_enums_are_rejected() -> None:
    data = json.loads(lifted_scene_to_canonical_json(_result().scene))
    data["observations"][0]["purpose"] = "ground_truth_mesh"
    with pytest.raises(LiftingSerializationError):
        lifted_scene_from_json(json.dumps(data))


def test_text_is_deterministic_and_has_one_final_newline() -> None:
    result = _result()
    first = lifted_scene_to_text(result.scene, result.report)
    second = lifted_scene_to_text(result.scene, result.report)
    assert first == second
    assert first.endswith("\n")
    assert not first.endswith("\n\n")
    assert "Source pixels used for geometric inference: false" in first
    assert "Not inferred" in first
    assert "region:road" in first
    assert "instance:car_1" in first


def test_serialized_artifacts_have_no_absolute_paths_or_timestamps(
    tmp_path: Path,
) -> None:
    result = _result()
    scene = lifted_scene_to_canonical_json(result.scene)
    report = lifting_report_to_canonical_json(result.report)
    combined = scene + report
    assert str(tmp_path.resolve()) not in combined
    assert "C:\\\\" not in combined
    assert "timestamp" not in combined.lower()
    assert result.scene.source_image_relative_path == "images/urban_minimal.png"


def test_report_lists_supplied_derived_and_not_inferred_information() -> None:
    report = _result().report
    assert "annotation geometry" in report.supplied_information
    assert any("world x/y" in item for item in report.derived_information)
    assert report.explicitly_not_inferred == (
        "metric depth",
        "camera intrinsics",
        "camera extrinsics",
        "physical object dimensions",
        "split hierarchy",
        "split boundaries",
        "repeat count beyond supplied membership",
        "repeat spacing",
        "grammar",
        "reconstructed mesh",
    )


def test_report_and_scene_warning_order_match() -> None:
    result = _result()
    assert result.scene.warnings == result.report.warnings
    assert result.report.warnings[0].code == "polygon_bounding_box_proxy"
