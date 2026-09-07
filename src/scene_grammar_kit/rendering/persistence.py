"""Deterministic PNG and canonical render-report persistence."""

from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scene_grammar_kit.rendering.errors import (
    RenderFileExistsError,
    RenderSerializationError,
    RenderWriteError,
)
from scene_grammar_kit.rendering.models import RenderReport, RenderResult


def render_report_to_canonical_json(report: RenderReport) -> str:
    """Serialize a render report as compact deterministic JSON."""
    if not isinstance(report, RenderReport):
        raise RenderSerializationError("report must be a RenderReport")
    try:
        return json.dumps(
            _report_data(report),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise RenderSerializationError(
            f"Could not serialize render report canonically: {exc}"
        ) from exc


def save_render(
    result: RenderResult,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save a deterministic metadata-free PNG without silent overwrite."""
    if not isinstance(result, RenderResult):
        raise RenderSerializationError("result must be a RenderResult")
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.lower() != ".png":
        raise RenderWriteError("render output path must use the .png suffix")
    stream = io.BytesIO()
    try:
        result.image.save(
            stream,
            format="PNG",
            compress_level=9,
            optimize=False,
        )
    except (OSError, ValueError) as exc:
        raise RenderWriteError(f"Could not encode PNG: {exc}") from exc
    return _atomic_write_bytes(
        stream.getvalue(),
        resolved,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_render_report(
    report: RenderReport,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save canonical render-report JSON without silent overwrite."""
    return _atomic_write_bytes(
        render_report_to_canonical_json(report).encode("utf-8"),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def render_report_path_for(image_path: Path) -> Path:
    """Return the default companion ``.render.json`` path for a PNG."""
    return Path(image_path).with_suffix(".render.json")


def _report_data(report: RenderReport) -> dict[str, Any]:
    """Convert a report to deterministic JSON-compatible values."""
    return {
        "box_count_rendered": report.box_count_rendered,
        "camera_preset": report.camera_preset.value,
        "empty_count_skipped": report.empty_count_skipped,
        "executed_scene_grammar_sha256": (report.executed_scene_grammar_sha256),
        "height": report.height,
        "palette_mapping": {
            semantic_class: list(color)
            for semantic_class, color in report.palette_mapping.items()
        },
        "plane_count_rendered": report.plane_count_rendered,
        "primitive_count_considered": report.primitive_count_considered,
        "renderer_policy_version": report.renderer_policy_version,
        "semantic_classes_present": list(report.semantic_classes_present),
        "success": report.success,
        "visible_face_count": report.visible_face_count,
        "width": report.width,
    }


def _atomic_write_bytes(
    data: bytes,
    path: Path,
    *,
    overwrite: bool,
    create_parents: bool,
) -> Path:
    """Atomically write bytes using a temporary file beside the target."""
    resolved = Path(path).expanduser().resolve()
    parent = resolved.parent
    if create_parents:
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RenderWriteError(
                f"Could not create render parent directory {parent}: {exc}"
            ) from exc
    if not parent.is_dir():
        raise RenderWriteError(
            f"Render parent directory does not exist: {parent}; "
            "pass create_parents=True to create it"
        )
    if resolved.exists() and not overwrite:
        raise RenderFileExistsError(
            f"Render output exists; pass overwrite=True to replace it: {resolved}"
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
                raise RenderFileExistsError(
                    f"Render output appeared during save and was preserved: {resolved}"
                ) from exc
            temporary_path.unlink()
        temporary_path = None
    except RenderFileExistsError:
        raise
    except OSError as exc:
        raise RenderWriteError(
            f"Could not safely write render output {resolved}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return resolved
