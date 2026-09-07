"""Canonical JSON and persistence tests for assisted inputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    AnnotationValidationError,
    AssistedFileExistsError,
    AssistedJSONError,
    AssistedWriteError,
    ConstructionConfigValidationError,
    annotation_from_json,
    annotation_to_canonical_json,
    construction_config_from_json,
    construction_config_to_canonical_json,
    load_annotation,
    load_construction_config,
    save_annotation,
    save_construction_config,
)

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"
VALID = FIXTURES / "valid"
INVALID = FIXTURES / "invalid"


def test_annotation_and_config_round_trip_structural_equality() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    assert annotation_from_json(annotation_to_canonical_json(annotation)) == annotation
    assert (
        construction_config_from_json(construction_config_to_canonical_json(config))
        == config
    )


def test_canonical_bytes_are_stable_and_have_no_final_newline() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    first_annotation = annotation_to_canonical_json(annotation)
    first_config = construction_config_to_canonical_json(config)
    assert (
        annotation_to_canonical_json(annotation_from_json(first_annotation))
        == first_annotation
    )
    assert (
        construction_config_to_canonical_json(
            construction_config_from_json(first_config)
        )
        == first_config
    )
    assert not first_annotation.endswith("\n")
    assert not first_config.endswith("\n")


def test_ordered_lists_and_polygon_points_are_preserved() -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    round_trip = annotation_from_json(annotation_to_canonical_json(annotation))
    assert [item.region_id for item in round_trip.regions] == [
        item.region_id for item in annotation.regions
    ]
    assert round_trip.repeat_groups[0].member_instance_ids == (
        "car_1",
        "car_2",
        "car_3",
    )
    assert round_trip.regions[3].shape == annotation.regions[3].shape


def test_attribute_dictionary_order_does_not_change_bytes() -> None:
    text = (VALID / "urban_minimal.annotation.json").read_text(encoding="utf-8")
    data = json.loads(text)
    data["regions"][0]["attributes"] = {"z": 1, "a": 2}
    first = annotation_from_json(json.dumps(data))
    data["regions"][0]["attributes"] = {"a": 2, "z": 1}
    second = annotation_from_json(json.dumps(data))
    assert annotation_to_canonical_json(first) == annotation_to_canonical_json(second)


def test_direct_unicode_is_preserved() -> None:
    data = json.loads(
        (VALID / "facade_polygon.annotation.json").read_text(encoding="utf-8")
    )
    data["description"] = "Façade visible — supplied"
    annotation = annotation_from_json(json.dumps(data, ensure_ascii=False))
    canonical = annotation_to_canonical_json(annotation)
    assert "Façade visible — supplied" in canonical
    assert "\\u" not in canonical


def test_safe_save_load_overwrite_and_parent_control(tmp_path: Path) -> None:
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    annotation_path = tmp_path / "nested" / "annotation.json"
    config_path = tmp_path / "config.json"
    with pytest.raises(AssistedWriteError):
        save_annotation(annotation, annotation_path)
    save_annotation(annotation, annotation_path, create_parents=True)
    save_construction_config(config, config_path)
    assert load_annotation(annotation_path) == annotation
    assert load_construction_config(config_path) == config
    with pytest.raises(AssistedFileExistsError):
        save_annotation(annotation, annotation_path)
    save_annotation(annotation, annotation_path, overwrite=True)


@pytest.mark.parametrize("text", ["{", "[]", '{"x":NaN}', '{"x":Infinity}'])
def test_invalid_or_nonstandard_json_has_clear_domain_error(text: str) -> None:
    with pytest.raises(AssistedJSONError):
        annotation_from_json(text)


@pytest.mark.parametrize(
    "fixture",
    [
        "unsafe_image_path.annotation.json",
        "invalid_rectangle.annotation.json",
        "invalid_polygon.annotation.json",
        "unsupported_annotation_version.annotation.json",
    ],
)
def test_field_invalid_annotation_fixtures_fail_to_load(fixture: str) -> None:
    with pytest.raises((AnnotationValidationError, AssistedJSONError)):
        load_annotation(INVALID / fixture)


@pytest.mark.parametrize(
    "fixture",
    [
        "invalid_depth_intervals.construction.json",
        "incomplete_depth_coverage.construction.json",
        "invalid_tolerance.construction.json",
        "unsupported_config_version.construction.json",
    ],
)
def test_invalid_config_fixtures_fail_to_load(fixture: str) -> None:
    with pytest.raises(ConstructionConfigValidationError):
        load_construction_config(INVALID / fixture)


def test_unsupported_projection_model_rejected() -> None:
    data = json.loads((VALID / "default.construction.json").read_text(encoding="utf-8"))
    data["projection_model"] = "perspective"
    with pytest.raises(ConstructionConfigValidationError):
        construction_config_from_json(json.dumps(data))
