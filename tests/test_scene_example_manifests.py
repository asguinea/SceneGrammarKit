"""Strict manifest-policy-v0.1 model and persistence tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scene_grammar_kit.scene_examples import (
    MANIFEST_POLICY_VERSION,
    ManifestValidationError,
    load_scene_manifest,
    scene_manifest_from_json,
    scene_manifest_to_canonical_json,
)

SCENES = Path(__file__).resolve().parents[1] / "examples" / "scene_examples"
MANIFESTS = tuple(sorted(SCENES.glob("*/scene_manifest.json")))


@pytest.mark.parametrize("path", MANIFESTS)
def test_valid_source_manifest_loads_and_round_trips(path: Path) -> None:
    manifest = load_scene_manifest(path)
    assert manifest.manifest_version == MANIFEST_POLICY_VERSION
    canonical = scene_manifest_to_canonical_json(manifest)
    assert scene_manifest_from_json(canonical) == manifest
    assert not canonical.endswith("\n")
    assert str(Path.cwd()) not in canonical


def manifest_data() -> dict[str, object]:
    return json.loads(MANIFESTS[0].read_text(encoding="utf-8"))


def parse(data: dict[str, object]):
    return scene_manifest_from_json(json.dumps(data))


def test_invalid_manifest_version_is_rejected() -> None:
    data = manifest_data()
    data["manifest_version"] = "1.0"
    with pytest.raises(ManifestValidationError, match="manifest_version"):
        parse(data)


def test_missing_grammar_path_is_rejected() -> None:
    data = manifest_data()
    del data["grammar_path"]
    with pytest.raises(ManifestValidationError, match="grammar_path"):
        parse(data)


def test_unknown_edit_operation_is_rejected() -> None:
    data = manifest_data()
    data["canonical_edits"][0]["operation_type"] = "move_geometry"  # type: ignore[index]
    with pytest.raises(ManifestValidationError, match="operation_type"):
        parse(data)


@pytest.mark.parametrize(
    "grammar_path",
    [
        "C:/outside/grammar.json",
        "/outside/grammar.json",
        "../outside.json",
        "nested\\grammar.json",
    ],
)
def test_unsafe_or_nonportable_grammar_path_is_rejected(
    grammar_path: str,
) -> None:
    data = manifest_data()
    data["grammar_path"] = grammar_path
    with pytest.raises(ManifestValidationError, match="grammar_path"):
        parse(data)


def test_duplicate_edit_keys_are_rejected() -> None:
    data = json.loads(
        (SCENES / "urban_street" / "scene_manifest.json").read_text("utf-8")
    )
    data["canonical_edits"][1]["edit_key"] = data["canonical_edits"][0]["edit_key"]
    with pytest.raises(ManifestValidationError, match="keys must be unique"):
        parse(data)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("primary_render_width", 0, "render configuration"),
        ("primary_render_height", -1, "render configuration"),
        ("primary_camera", "perspective", "camera"),
        (
            "supported_camera_presets",
            ["isometric", "front"],
            "sorted",
        ),
    ],
)
def test_invalid_dimensions_or_cameras_are_rejected(
    field: str,
    value: object,
    message: str,
) -> None:
    data = manifest_data()
    data[field] = value
    with pytest.raises(ManifestValidationError, match=message):
        parse(data)


@pytest.mark.parametrize(
    "field",
    [
        "expected_semantic_classes",
        "expected_split_node_ids",
        "expected_repeat_node_ids",
    ],
)
def test_expected_lists_must_be_sorted_unique(field: str) -> None:
    data = manifest_data()
    original = data[field]
    assert isinstance(original, list)
    data[field] = list(reversed(original)) + [original[0]]
    with pytest.raises(ManifestValidationError, match="sorted and unique"):
        parse(data)


def test_operation_parameters_are_exact_and_typed() -> None:
    data = manifest_data()
    parameters = data["canonical_edits"][0]["parameters"]  # type: ignore[index]
    parameters["extra"] = 1
    with pytest.raises(ManifestValidationError, match="parameters must be exactly"):
        parse(data)


@pytest.mark.parametrize("value", [0, -1, True, "wide"])
def test_split_weight_parameter_value_is_strict(value: object) -> None:
    data = manifest_data()
    data["canonical_edits"][0]["parameters"]["new_weight"] = value  # type: ignore[index]
    with pytest.raises(ManifestValidationError, match="new_weight"):
        parse(data)
