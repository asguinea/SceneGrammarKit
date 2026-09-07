"""Canonical JSON and safe persistence for executed SceneGrammarKit geometry."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scene_grammar_kit.geometry.errors import (
    GeometryFileExistsError,
    GeometrySerializationError,
    GeometryWriteError,
)
from scene_grammar_kit.geometry.models import (
    ExecutedScene,
    ExecutionReport,
    SemanticPrimitive,
)


def executed_scene_to_canonical_json(scene: ExecutedScene) -> str:
    """Serialize an executed scene to deterministic compact JSON.

    Output uses sorted object keys, stable primitive order, direct Unicode,
    compact separators, finite numbers only, and no final newline.
    """
    if not isinstance(scene, ExecutedScene):
        raise GeometrySerializationError("scene must be an ExecutedScene")
    return _canonical_json(_scene_data(scene), "executed scene")


def execution_report_to_canonical_json(report: ExecutionReport) -> str:
    """Serialize a deterministic execution report without timestamps."""
    if not isinstance(report, ExecutionReport):
        raise GeometrySerializationError("report must be an ExecutionReport")
    return _canonical_json(_report_data(report), "execution report")


def save_executed_scene(
    scene: ExecutedScene,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Atomically save canonical ``primitives.json`` and return its path."""
    return atomic_write_text(
        executed_scene_to_canonical_json(scene),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_execution_report(
    report: ExecutionReport,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Atomically save a canonical deterministic execution report."""
    return atomic_write_text(
        execution_report_to_canonical_json(report),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def atomic_write_text(
    text: str,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Atomically write UTF-8 text without silently overwriting."""
    if not isinstance(text, str):
        raise GeometrySerializationError("text output must be a string")
    return atomic_write_bytes(
        text.encode("utf-8"),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def atomic_write_bytes(
    data: bytes,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Atomically write bytes using a same-directory temporary file."""
    if not isinstance(data, bytes):
        raise GeometrySerializationError("binary output must be bytes")
    resolved = Path(path).expanduser().resolve()
    parent = resolved.parent
    if create_parents:
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GeometryWriteError(
                f"Could not create output parent {parent}: {exc}"
            ) from exc
    if not parent.is_dir():
        raise GeometryWriteError(
            f"Output parent does not exist: {parent}; "
            "pass create_parents=True to create it"
        )
    if resolved.exists() and not overwrite:
        raise GeometryFileExistsError(
            f"Output exists; pass overwrite=True to replace it: {resolved}"
        )

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary_path, resolved)
        else:
            try:
                os.link(temporary_path, resolved)
            except FileExistsError as exc:
                raise GeometryFileExistsError(
                    f"Output appeared during save and was preserved: {resolved}"
                ) from exc
            temporary_path.unlink()
        temporary_path = None
    except GeometryFileExistsError:
        raise
    except OSError as exc:
        raise GeometryWriteError(
            f"Could not safely write output {resolved}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return resolved


def _scene_data(scene: ExecutedScene) -> dict[str, Any]:
    """Convert an executed scene to JSON-compatible deterministic values."""
    return {
        "execution_policy_version": scene.execution_policy_version,
        "grammar_schema_version": scene.grammar_schema_version,
        "grammar_sha256": scene.grammar_sha256,
        "primitives": [_primitive_data(item) for item in scene.primitives],
        "root_bounds": _bounds_data(scene.root_bounds),
        "scene_id": scene.scene_id,
        "units": scene.units,
    }


def _primitive_data(primitive: SemanticPrimitive) -> dict[str, Any]:
    """Convert one primitive while preserving its ordered provenance."""
    return {
        "attributes": dict(primitive.attributes),
        "bounds": _bounds_data(primitive.bounds),
        "geometry": primitive.geometry.value,
        "instance_path": primitive.instance_path,
        "primitive_id": primitive.primitive_id,
        "repeat_indices": list(primitive.repeat_indices),
        "semantic_class": primitive.semantic_class,
        "source_terminal_id": primitive.source_terminal_id,
    }


def _report_data(report: ExecutionReport) -> dict[str, Any]:
    """Convert an execution report to JSON-compatible values."""
    return {
        "box_count": report.box_count,
        "empty_terminal_count": report.empty_terminal_count,
        "execution_policy_version": report.execution_policy_version,
        "grammar_sha256": report.grammar_sha256,
        "maximum_execution_depth": report.maximum_execution_depth,
        "plane_count": report.plane_count,
        "primitive_count": report.primitive_count,
        "success": report.success,
        "symbolic_node_count_visited": report.symbolic_node_count_visited,
        "warnings": list(report.warnings),
    }


def _bounds_data(bounds: object) -> dict[str, list[float]]:
    """Convert shared Bounds3D values without adding derived geometry."""
    return {
        "max": list(bounds.maximum.as_tuple()),  # type: ignore[attr-defined]
        "min": list(bounds.minimum.as_tuple()),  # type: ignore[attr-defined]
    }


def _canonical_json(value: object, label: str) -> str:
    """Encode project-canonical JSON and preserve meaningful causes."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise GeometrySerializationError(
            f"Could not serialize {label} canonically: {exc}"
        ) from exc
