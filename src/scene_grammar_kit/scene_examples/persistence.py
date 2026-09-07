"""Strict JSON loading and canonical persistence for scene examples."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scene_grammar_kit.geometry import GeometryFileExistsError
from scene_grammar_kit.geometry.serialization import atomic_write_text
from scene_grammar_kit.scene_examples.errors import (
    ManifestFileNotFoundError,
    ManifestJSONError,
    ManifestReadError,
    ManifestSerializationError,
    ManifestValidationError,
    SceneExampleFileExistsError,
    SceneExamplePersistenceError,
)
from scene_grammar_kit.scene_examples.models import (
    CanonicalEditSpec,
    SceneExampleBuildReport,
    SceneManifest,
)


def load_scene_manifest(path: Path) -> SceneManifest:
    """Load one strict UTF-8 scene manifest from disk."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ManifestFileNotFoundError(f"Scene manifest does not exist: {resolved}")
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ManifestReadError(
            f"Could not read scene manifest as UTF-8: {resolved}: {exc}"
        ) from exc
    return scene_manifest_from_json(text)


def scene_manifest_from_json(text: str) -> SceneManifest:
    """Parse strict standard JSON into an immutable scene manifest."""
    if not isinstance(text, str):
        raise ManifestJSONError("scene manifest input must be text")
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ManifestJSONError(f"Invalid scene manifest JSON: {exc}") from exc
    return _manifest_from_data(value)


def scene_manifest_to_canonical_json(manifest: SceneManifest) -> str:
    """Serialize a scene manifest deterministically without environment data."""
    if not isinstance(manifest, SceneManifest):
        raise ManifestSerializationError("manifest must be a SceneManifest")
    return _canonical_json(_manifest_data(manifest), "scene manifest")


def build_report_to_canonical_json(report: SceneExampleBuildReport) -> str:
    """Serialize a deterministic scene-example build report."""
    if not isinstance(report, SceneExampleBuildReport):
        raise ManifestSerializationError("report must be a SceneExampleBuildReport")
    return _canonical_json(_json_value(asdict(report)), "build report")


def save_scene_manifest(
    manifest: SceneManifest,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save canonical scene-manifest JSON using an atomic file write."""
    return _write(
        scene_manifest_to_canonical_json(manifest),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_build_report(
    report: SceneExampleBuildReport,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save canonical build-report JSON using an atomic file write."""
    return _write(
        build_report_to_canonical_json(report),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def _manifest_from_data(value: object) -> SceneManifest:
    data = _object(value, "$")
    required = {
        "manifest_version",
        "scene_key",
        "display_name",
        "grammar_path",
        "description",
        "supported_camera_presets",
        "primary_camera",
        "secondary_camera",
        "primary_render_width",
        "primary_render_height",
        "canonical_edits",
        "expected_semantic_classes",
        "expected_split_node_ids",
        "expected_repeat_node_ids",
        "known_limitations",
    }
    _exact_fields(data, required, "$")
    edits_data = _array(data["canonical_edits"], "$.canonical_edits")
    edits = tuple(
        _edit_from_data(item, f"$.canonical_edits[{index}]")
        for index, item in enumerate(edits_data)
    )
    try:
        return SceneManifest(
            manifest_version=_string(
                data["manifest_version"],
                "$.manifest_version",
            ),
            scene_key=_string(data["scene_key"], "$.scene_key"),
            display_name=_string(data["display_name"], "$.display_name"),
            grammar_path=_string(data["grammar_path"], "$.grammar_path"),
            description=_string(data["description"], "$.description"),
            supported_camera_presets=_string_tuple(
                data["supported_camera_presets"],
                "$.supported_camera_presets",
            ),
            primary_camera=_string(
                data["primary_camera"],
                "$.primary_camera",
            ),
            secondary_camera=_string(
                data["secondary_camera"],
                "$.secondary_camera",
            ),
            primary_render_width=_integer(
                data["primary_render_width"],
                "$.primary_render_width",
            ),
            primary_render_height=_integer(
                data["primary_render_height"],
                "$.primary_render_height",
            ),
            canonical_edits=edits,
            expected_semantic_classes=_string_tuple(
                data["expected_semantic_classes"],
                "$.expected_semantic_classes",
            ),
            expected_split_node_ids=_string_tuple(
                data["expected_split_node_ids"],
                "$.expected_split_node_ids",
            ),
            expected_repeat_node_ids=_string_tuple(
                data["expected_repeat_node_ids"],
                "$.expected_repeat_node_ids",
            ),
            known_limitations=_string_tuple(
                data["known_limitations"],
                "$.known_limitations",
            ),
        )
    except ManifestValidationError:
        raise
    except Exception as exc:
        raise ManifestValidationError(
            f"Scene manifest validation failed: {exc}"
        ) from exc


def _edit_from_data(value: object, path: str) -> CanonicalEditSpec:
    data = _object(value, path)
    _exact_fields(
        data,
        {
            "edit_key",
            "operation_type",
            "parameters",
            "purpose",
            "primary_example_edit",
            "recommended_render_camera",
        },
        path,
    )
    parameters = _object(data["parameters"], f"{path}.parameters")
    return CanonicalEditSpec(
        edit_key=_string(data["edit_key"], f"{path}.edit_key"),
        operation_type=_string(
            data["operation_type"],
            f"{path}.operation_type",
        ),
        parameters=dict(parameters),
        purpose=_string(data["purpose"], f"{path}.purpose"),
        primary_example_edit=_boolean(
            data["primary_example_edit"],
            f"{path}.primary_example_edit",
        ),
        recommended_render_camera=_string(
            data["recommended_render_camera"],
            f"{path}.recommended_render_camera",
        ),
    )


def _manifest_data(manifest: SceneManifest) -> dict[str, Any]:
    return {
        "canonical_edits": [
            {
                "edit_key": item.edit_key,
                "operation_type": item.operation_type,
                "parameters": dict(item.parameters),
                "primary_example_edit": item.primary_example_edit,
                "purpose": item.purpose,
                "recommended_render_camera": (item.recommended_render_camera.value),
            }
            for item in manifest.canonical_edits
        ],
        "description": manifest.description,
        "display_name": manifest.display_name,
        "expected_repeat_node_ids": list(manifest.expected_repeat_node_ids),
        "expected_semantic_classes": list(manifest.expected_semantic_classes),
        "expected_split_node_ids": list(manifest.expected_split_node_ids),
        "grammar_path": manifest.grammar_path,
        "known_limitations": list(manifest.known_limitations),
        "manifest_version": manifest.manifest_version,
        "primary_camera": manifest.primary_camera.value,
        "primary_render_height": manifest.primary_render_height,
        "primary_render_width": manifest.primary_render_width,
        "scene_key": manifest.scene_key,
        "secondary_camera": manifest.secondary_camera.value,
        "supported_camera_presets": [
            item.value for item in manifest.supported_camera_presets
        ],
    }


def _write(
    text: str,
    path: Path,
    *,
    overwrite: bool,
    create_parents: bool,
) -> Path:
    try:
        return atomic_write_text(
            text,
            path,
            overwrite=overwrite,
            create_parents=create_parents,
        )
    except GeometryFileExistsError as exc:
        raise SceneExampleFileExistsError(str(exc)) from exc
    except Exception as exc:
        raise SceneExamplePersistenceError(
            f"Could not save scene-example JSON: {exc}"
        ) from exc


def _canonical_json(value: object, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ManifestSerializationError(
            f"Could not serialize {label} canonically: {exc}"
        ) from exc


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ManifestValidationError(f"{path} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ManifestValidationError(f"{path} keys must be strings")
    return value


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ManifestValidationError(f"{path} must be an array")
    return value


def _string_tuple(value: object, path: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ManifestValidationError(f"{path} must be a string")
    return value


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestValidationError(f"{path} must be an integer")
    return value


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ManifestValidationError(f"{path} must be a boolean")
    return value


def _exact_fields(
    data: dict[str, object],
    required: set[str],
    path: str,
) -> None:
    missing = sorted(required - data.keys())
    unexpected = sorted(data.keys() - required)
    if missing:
        raise ManifestValidationError(
            f"{path} missing required field(s): {', '.join(missing)}"
        )
    if unexpected:
        raise ManifestValidationError(
            f"{path} has unexpected field(s): {', '.join(unexpected)}"
        )


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite constant {value!r} is not permitted")
