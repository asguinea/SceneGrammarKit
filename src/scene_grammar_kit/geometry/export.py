"""Headless deterministic GLB export for executed semantic primitives."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scene_grammar_kit.geometry.errors import (
    GeometryExportError,
    GeometryFileExistsError,
)
from scene_grammar_kit.geometry.models import ExecutedScene, SemanticPrimitive
from scene_grammar_kit.geometry.serialization import (
    atomic_write_bytes,
    atomic_write_text,
)
from scene_grammar_kit.grammar import GeometryType


@dataclass(frozen=True, slots=True)
class GeometryExportResult:
    """Resolved deterministic paths and digest for one GLB export."""

    glb_path: Path
    semantic_index_path: Path
    glb_sha256: str


def export_scene(
    scene: ExecutedScene,
    path: Path,
    *,
    semantic_index_path: Path | None = None,
    overwrite: bool = False,
    create_parents: bool = False,
) -> GeometryExportResult:
    """Export boxes and proxy planes to a headless GLB plus semantic index.

    Box primitives export as closed cuboids. Plane primitives retain full
    inherited bounds in canonical JSON; for GLB preview geometry only, their
    deterministic proxy surface is the bounds' positive-y face. Empty terminals
    are absent from ``ExecutedScene.primitives`` and therefore from the export.
    """
    if not isinstance(scene, ExecutedScene):
        raise TypeError("scene must be an ExecutedScene")
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.lower() != ".glb":
        raise GeometryExportError("GLB export path must use the .glb suffix")
    semantic_resolved = (
        Path(semantic_index_path).expanduser().resolve()
        if semantic_index_path is not None
        else resolved.with_name("semantic_index.json")
    )
    if not overwrite:
        for target in (resolved, semantic_resolved):
            if target.exists():
                raise GeometryFileExistsError(
                    f"Export target exists; pass overwrite=True: {target}"
                )

    try:
        import trimesh
    except ImportError as exc:
        raise GeometryExportError(
            "GLB export requires the declared trimesh runtime dependency"
        ) from exc

    try:
        exported = trimesh.Scene()
        for primitive in scene.primitives:
            mesh = _primitive_mesh(primitive, trimesh)
            mesh.metadata.update(
                {
                    "primitive_id": primitive.primitive_id,
                    "semantic_class": primitive.semantic_class,
                    "source_terminal_id": primitive.source_terminal_id,
                    "geometry": primitive.geometry.value,
                    "instance_path": primitive.instance_path,
                }
            )
            exported.add_geometry(
                mesh,
                node_name=primitive.primitive_id,
                geom_name=primitive.primitive_id,
            )
        glb_data = (
            _empty_scene_glb()
            if not scene.primitives
            else exported.export(file_type="glb")
        )
    except Exception as exc:
        raise GeometryExportError(f"Could not build GLB geometry: {exc}") from exc
    if not isinstance(glb_data, bytes) or not glb_data:
        raise GeometryExportError("trimesh returned an empty or invalid GLB payload")

    semantic_json = json.dumps(
        {
            "execution_policy_version": scene.execution_policy_version,
            "grammar_sha256": scene.grammar_sha256,
            "primitives": [
                {
                    "geometry": primitive.geometry.value,
                    "instance_path": primitive.instance_path,
                    "primitive_id": primitive.primitive_id,
                    "repeat_indices": list(primitive.repeat_indices),
                    "semantic_class": primitive.semantic_class,
                    "source_terminal_id": primitive.source_terminal_id,
                }
                for primitive in scene.primitives
            ],
            "scene_id": scene.scene_id,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    glb_path = atomic_write_bytes(
        glb_data,
        resolved,
        overwrite=overwrite,
        create_parents=create_parents,
    )
    try:
        index_path = atomic_write_text(
            semantic_json,
            semantic_resolved,
            overwrite=overwrite,
            create_parents=create_parents,
        )
    except Exception:
        if not overwrite:
            try:
                glb_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return GeometryExportResult(
        glb_path=glb_path,
        semantic_index_path=index_path,
        glb_sha256=hashlib.sha256(glb_data).hexdigest(),
    )


def _primitive_mesh(primitive: SemanticPrimitive, trimesh: Any) -> Any:
    """Build one deterministic trimesh object from primitive bounds."""
    minimum = primitive.bounds.minimum.as_tuple()
    maximum = primitive.bounds.maximum.as_tuple()
    extents = tuple(high - low for low, high in zip(minimum, maximum))
    center = tuple((low + high) / 2.0 for low, high in zip(minimum, maximum))
    if primitive.geometry is GeometryType.BOX:
        mesh = trimesh.creation.box(extents=extents)
        mesh.apply_translation(center)
        return mesh
    if primitive.geometry is GeometryType.PLANE:
        x0, _, z0 = minimum
        x1, y1, z1 = maximum
        vertices = [
            [x0, y1, z0],
            [x1, y1, z0],
            [x1, y1, z1],
            [x0, y1, z1],
        ]
        faces = [[0, 1, 2], [0, 2, 3]]
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    raise GeometryExportError(
        f"Unsupported export geometry {primitive.geometry.value!r}"
    )


def _empty_scene_glb() -> bytes:
    """Return a valid deterministic GLB containing an empty glTF scene."""
    document = json.dumps(
        {
            "asset": {
                "generator": "SceneGrammarKit geometry policy 0.1",
                "version": "2.0",
            },
            "scene": 0,
            "scenes": [{}],
        },
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    document += b" " * (-len(document) % 4)
    total_length = 12 + 8 + len(document)
    return (
        struct.pack("<4sII", b"glTF", 2, total_length)
        + struct.pack("<I4s", len(document), b"JSON")
        + document
    )
