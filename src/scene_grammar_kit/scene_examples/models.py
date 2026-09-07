"""Strict immutable models for scene-example manifest policy version 0.1."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from scene_grammar_kit.rendering import CameraPreset, RenderConfig
from scene_grammar_kit.scene_examples.errors import ManifestValidationError

MANIFEST_POLICY_VERSION = "0.1"

ManifestScalar: TypeAlias = str | int | float

SUPPORTED_EDIT_OPERATION_TYPES = (
    "set_split_child_weight",
    "set_repeat_count",
    "set_repeat_spacing",
    "substitute_terminal_class",
)


@dataclass(frozen=True, slots=True)
class CanonicalEditSpec:
    """One existing typed edit described by stable manifest data."""

    edit_key: str
    operation_type: str
    parameters: Mapping[str, ManifestScalar]
    purpose: str
    primary_example_edit: bool
    recommended_render_camera: CameraPreset | str

    def __post_init__(self) -> None:
        _nonempty(self.edit_key, "edit_key")
        _safe_key(self.edit_key, "edit_key")
        if self.operation_type not in SUPPORTED_EDIT_OPERATION_TYPES:
            raise ManifestValidationError(
                "operation_type must be one of: "
                + ", ".join(SUPPORTED_EDIT_OPERATION_TYPES)
            )
        _nonempty(self.purpose, "purpose")
        if not isinstance(self.primary_example_edit, bool):
            raise ManifestValidationError("primary_example_edit must be a boolean")
        try:
            camera = CameraPreset(self.recommended_render_camera)
        except (TypeError, ValueError) as exc:
            raise ManifestValidationError(
                "recommended_render_camera is invalid"
            ) from exc
        object.__setattr__(self, "recommended_render_camera", camera)
        if not isinstance(self.parameters, Mapping):
            raise ManifestValidationError("parameters must be an object")
        copied: dict[str, ManifestScalar] = {}
        for key, value in self.parameters.items():
            _nonempty(key, "parameter key")
            copied[key] = _scalar(value, f"parameters.{key}")
        _validate_operation_parameters(self.operation_type, copied)
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(sorted(copied.items()))),
        )


@dataclass(frozen=True, slots=True)
class SceneManifest:
    """Strict source manifest for one canonical scene example."""

    manifest_version: str
    scene_key: str
    display_name: str
    grammar_path: str
    description: str
    supported_camera_presets: tuple[CameraPreset | str, ...]
    primary_camera: CameraPreset | str
    secondary_camera: CameraPreset | str
    primary_render_width: int
    primary_render_height: int
    canonical_edits: tuple[CanonicalEditSpec, ...]
    expected_semantic_classes: tuple[str, ...]
    expected_split_node_ids: tuple[str, ...]
    expected_repeat_node_ids: tuple[str, ...]
    known_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.manifest_version != MANIFEST_POLICY_VERSION:
            raise ManifestValidationError(
                f"manifest_version must be {MANIFEST_POLICY_VERSION!r}"
            )
        _safe_key(self.scene_key, "scene_key")
        _nonempty(self.display_name, "display_name")
        _relative_path(self.grammar_path, "grammar_path")
        _nonempty(self.description, "description")
        cameras = _cameras(
            self.supported_camera_presets,
            "supported_camera_presets",
        )
        try:
            primary = CameraPreset(self.primary_camera)
            secondary = CameraPreset(self.secondary_camera)
        except (TypeError, ValueError) as exc:
            raise ManifestValidationError(
                "primary_camera and secondary_camera must be valid presets"
            ) from exc
        if primary not in cameras or secondary not in cameras:
            raise ManifestValidationError(
                "primary and secondary cameras must be supported"
            )
        object.__setattr__(self, "supported_camera_presets", cameras)
        object.__setattr__(self, "primary_camera", primary)
        object.__setattr__(self, "secondary_camera", secondary)
        try:
            RenderConfig(
                width=self.primary_render_width,
                height=self.primary_render_height,
                camera_preset=primary,
            )
        except Exception as exc:
            raise ManifestValidationError(
                f"primary render configuration is invalid: {exc}"
            ) from exc
        if (
            not isinstance(self.canonical_edits, tuple)
            or not self.canonical_edits
            or any(
                not isinstance(item, CanonicalEditSpec) for item in self.canonical_edits
            )
        ):
            raise ManifestValidationError(
                "canonical_edits must contain at least one edit"
            )
        edit_keys = tuple(item.edit_key for item in self.canonical_edits)
        if len(set(edit_keys)) != len(edit_keys):
            raise ManifestValidationError("canonical edit keys must be unique")
        for item in self.canonical_edits:
            if item.recommended_render_camera not in cameras:
                raise ManifestValidationError(
                    f"edit {item.edit_key!r} uses an unsupported camera"
                )
        for name in (
            "expected_semantic_classes",
            "expected_split_node_ids",
            "expected_repeat_node_ids",
            "known_limitations",
        ):
            object.__setattr__(
                self,
                name,
                _sorted_unique_strings(getattr(self, name), name),
            )
        if not self.expected_semantic_classes:
            raise ManifestValidationError("expected_semantic_classes must not be empty")
        if not self.expected_split_node_ids:
            raise ManifestValidationError("expected_split_node_ids must not be empty")
        if not self.expected_repeat_node_ids:
            raise ManifestValidationError("expected_repeat_node_ids must not be empty")


@dataclass(frozen=True, slots=True)
class SceneExampleStatistics:
    """Factual symbolic and executed statistics for one original scene."""

    symbolic_node_count: int
    split_node_count: int
    repeat_node_count: int
    terminal_node_count: int
    maximum_grammar_depth: int
    canonical_grammar_byte_size: int
    original_primitive_count: int


@dataclass(frozen=True, slots=True)
class SceneExampleEditBuild:
    """Deterministic factual summary for one built canonical edit."""

    edit_key: str
    operation_type: str
    original_grammar_sha256: str
    edited_grammar_sha256: str
    primitive_count_before: int
    primitive_count_after: int
    render_camera: str
    render_width: int
    render_height: int
    parameter_before: int | float | str
    parameter_after: int | float | str
    normalized_fraction_before: float | None
    normalized_fraction_after: float | None
    conceptual_repeat_count_before: int | None
    conceptual_repeat_count_after: int | None
    artifact_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SceneExampleBuildReport:
    """Canonical environment-free report for a completed scene build."""

    success: bool
    manifest_policy_version: str
    scene_key: str
    grammar_sha256: str
    grammar_schema_version: str
    execution_policy_version: str
    renderer_policy_version: str
    editing_policy_version: str
    statistics: SceneExampleStatistics
    edit_keys: tuple[str, ...]
    edits: tuple[SceneExampleEditBuild, ...]
    artifact_paths: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SceneExampleBuildResult:
    """Resolved build output and deterministic public build report."""

    output_directory: Path
    manifest: SceneManifest
    report: SceneExampleBuildReport


def _validate_operation_parameters(
    operation_type: str,
    parameters: Mapping[str, ManifestScalar],
) -> None:
    fields = {
        "set_split_child_weight": {
            "split_node_id",
            "child_node_id",
            "new_weight",
        },
        "set_repeat_count": {"repeat_node_id", "new_count"},
        "set_repeat_spacing": {"repeat_node_id", "new_spacing"},
        "substitute_terminal_class": {
            "terminal_node_id",
            "new_semantic_class",
        },
    }[operation_type]
    if set(parameters) != fields:
        raise ManifestValidationError(
            f"{operation_type} parameters must be exactly: " + ", ".join(sorted(fields))
        )
    identifier_fields = {
        "split_node_id",
        "child_node_id",
        "repeat_node_id",
        "terminal_node_id",
    }
    for name in fields & identifier_fields:
        _nonempty(parameters[name], f"parameters.{name}")
    if operation_type == "set_split_child_weight":
        value = parameters["new_weight"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise ManifestValidationError(
                "parameters.new_weight must be a strictly positive finite number"
            )
    elif operation_type == "set_repeat_count":
        value = parameters["new_count"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ManifestValidationError(
                "parameters.new_count must be an integer of at least one"
            )
    elif operation_type == "set_repeat_spacing":
        value = parameters["new_spacing"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ManifestValidationError(
                "parameters.new_spacing must be a finite nonnegative number"
            )
    else:
        _nonempty(
            parameters["new_semantic_class"],
            "parameters.new_semantic_class",
        )


def _cameras(values: object, name: str) -> tuple[CameraPreset, ...]:
    if not isinstance(values, tuple) or not values:
        raise ManifestValidationError(f"{name} must be a nonempty array")
    try:
        cameras = tuple(CameraPreset(item) for item in values)
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(f"{name} contains an invalid camera") from exc
    if len(set(cameras)) != len(cameras):
        raise ManifestValidationError(f"{name} must not contain duplicates")
    if cameras != tuple(sorted(cameras, key=lambda item: item.value)):
        raise ManifestValidationError(f"{name} must be sorted")
    return cameras


def _sorted_unique_strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ManifestValidationError(f"{name} must be an array")
    for item in value:
        _nonempty(item, name)
    if value != tuple(sorted(set(value))):
        raise ManifestValidationError(f"{name} must be sorted and unique")
    return value


def _relative_path(value: object, name: str) -> str:
    _nonempty(value, name)
    text = str(value)
    if "\\" in text or text.startswith("/") or ":" in text:
        raise ManifestValidationError(f"{name} must be a portable relative POSIX path")
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ManifestValidationError(
            f"{name} must not contain empty, current, or parent segments"
        )
    return text


def _safe_key(value: object, name: str) -> str:
    _nonempty(value, name)
    text = str(value)
    if any(
        not (character.islower() or character.isdigit() or character == "_")
        for character in text
    ):
        raise ManifestValidationError(
            f"{name} must use lowercase letters, digits, and underscores"
        )
    return text


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{name} must be a nonempty string")
    return value


def _scalar(value: object, name: str) -> ManifestScalar:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ManifestValidationError(
            f"{name} must be a string, integer, or finite number"
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise ManifestValidationError(f"{name} must be finite")
    return value
