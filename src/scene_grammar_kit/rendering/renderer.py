"""Deterministic CPU-only painter renderer for executed semantic scenes."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

from scene_grammar_kit.geometry import ExecutedScene, SemanticPrimitive
from scene_grammar_kit.grammar import GeometryType
from scene_grammar_kit.rendering.camera import (
    Point2,
    Point3,
    ProjectionFrame,
    bounds_corners,
    camera_basis,
    fit_projection,
)
from scene_grammar_kit.rendering.models import RenderConfig, RenderReport, RenderResult
from scene_grammar_kit.rendering.palette import resolve_palette, shade_color

_GROUND_COLOR = (222, 226, 232, 255)
_GROUND_EDGE_COLOR = (165, 172, 182, 255)
_BOUNDS_COLOR = (30, 34, 42, 255)
_LIGHT_DIRECTION = (-0.3007679386, 0.9023038158, -0.3107935366)


@dataclass(frozen=True, slots=True)
class _WorldFace:
    normal: Point3
    vertices: tuple[Point3, ...]
    face_index: int


@dataclass(frozen=True, slots=True)
class _DrawFace:
    primitive_id: str
    face_index: int
    depth: float
    points: tuple[Point2, ...]
    fill: tuple[int, int, int, int]
    edge: tuple[int, int, int, int]
    geometry: GeometryType


def render_executed_scene(
    scene: ExecutedScene,
    config: RenderConfig | None = None,
) -> RenderResult:
    """Render an executed scene into a deterministic final-size RGBA image."""
    if not isinstance(scene, ExecutedScene):
        raise TypeError("scene must be an ExecutedScene")
    resolved_config = config or RenderConfig()
    if not isinstance(resolved_config, RenderConfig):
        raise TypeError("config must be a RenderConfig or None")

    scale_factor = resolved_config.supersampling
    render_width = resolved_config.width * scale_factor
    render_height = resolved_config.height * scale_factor
    basis = camera_basis(resolved_config.camera_preset)
    frame = fit_projection(
        scene.root_bounds,
        basis,
        width=render_width,
        height=render_height,
        padding=resolved_config.image_padding * scale_factor,
    )
    semantic_classes = tuple(
        sorted({primitive.semantic_class for primitive in scene.primitives})
    )
    palette = resolve_palette(
        semantic_classes,
        resolved_config.semantic_palette,
    )
    background = resolved_config.background_color
    if resolved_config.transparent_background:
        background = (background[0], background[1], background[2], 0)
    image = Image.new("RGBA", (render_width, render_height), background)
    draw = ImageDraw.Draw(image, "RGBA")

    if resolved_config.show_ground:
        _draw_ground(
            draw,
            scene,
            frame,
            show_edges=resolved_config.show_edges,
            edge_width=resolved_config.edge_width * scale_factor,
        )

    draw_faces: list[_DrawFace] = []
    boxes_rendered: set[str] = set()
    planes_rendered: set[str] = set()
    for primitive in scene.primitives:
        faces = (
            _box_faces(primitive)
            if primitive.geometry is GeometryType.BOX
            else (_plane_face(primitive),)
        )
        for face in faces:
            if _dot(face.normal, basis.forward) >= -1e-12:
                continue
            points = tuple(frame.project(vertex) for vertex in face.vertices)
            if abs(_polygon_area(points)) <= 1e-8:
                continue
            base = palette[primitive.semantic_class]
            shade = 0.72 + 0.28 * max(
                0.0,
                _dot(face.normal, _LIGHT_DIRECTION),
            )
            draw_faces.append(
                _DrawFace(
                    primitive_id=primitive.primitive_id,
                    face_index=face.face_index,
                    depth=sum(frame.depth(point) for point in face.vertices)
                    / len(face.vertices),
                    points=points,
                    fill=shade_color(base, shade),
                    edge=shade_color(base, 0.42),
                    geometry=primitive.geometry,
                )
            )
            if primitive.geometry is GeometryType.BOX:
                boxes_rendered.add(primitive.primitive_id)
            else:
                planes_rendered.add(primitive.primitive_id)

    draw_faces.sort(key=lambda face: (-face.depth, face.primitive_id, face.face_index))
    for face in draw_faces:
        draw.polygon(
            face.points,
            fill=face.fill,
            outline=face.edge if resolved_config.show_edges else None,
            width=(
                resolved_config.edge_width * scale_factor
                if resolved_config.show_edges
                else 1
            ),
        )

    if resolved_config.show_bounds:
        _draw_bounds_overlay(
            draw,
            scene,
            frame,
            width=max(1, resolved_config.edge_width * scale_factor),
        )

    final_image = (
        image
        if scale_factor == 1
        else image.resize(
            (resolved_config.width, resolved_config.height),
            resample=Image.Resampling.LANCZOS,
        )
    )
    report = RenderReport(
        success=True,
        width=resolved_config.width,
        height=resolved_config.height,
        camera_preset=resolved_config.camera_preset,
        primitive_count_considered=len(scene.primitives),
        box_count_rendered=len(boxes_rendered),
        plane_count_rendered=len(planes_rendered),
        empty_count_skipped=scene.report.empty_terminal_count,
        visible_face_count=len(draw_faces),
        semantic_classes_present=semantic_classes,
        palette_mapping=palette,
        executed_scene_grammar_sha256=scene.grammar_sha256,
    )
    return RenderResult(
        image=final_image,
        report=report,
        palette_mapping=palette,
    )


def _box_faces(primitive: SemanticPrimitive) -> tuple[_WorldFace, ...]:
    """Return six outward-facing box faces in stable orientation order."""
    corners = bounds_corners(primitive.bounds)
    specifications = (
        ((0.0, 0.0, -1.0), (0, 3, 2, 1)),
        ((0.0, 0.0, 1.0), (4, 5, 6, 7)),
        ((-1.0, 0.0, 0.0), (0, 4, 7, 3)),
        ((1.0, 0.0, 0.0), (1, 2, 6, 5)),
        ((0.0, -1.0, 0.0), (0, 1, 5, 4)),
        ((0.0, 1.0, 0.0), (3, 7, 6, 2)),
    )
    return tuple(
        _WorldFace(
            normal=normal,
            vertices=tuple(corners[index] for index in indices),
            face_index=face_index,
        )
        for face_index, (normal, indices) in enumerate(specifications)
    )


def _plane_face(primitive: SemanticPrimitive) -> _WorldFace:
    """Return the Batch 1.4 positive-y proxy face for a plane primitive."""
    corners = bounds_corners(primitive.bounds)
    return _WorldFace(
        normal=(0.0, 1.0, 0.0),
        vertices=(corners[3], corners[7], corners[6], corners[2]),
        face_index=6,
    )


def _draw_ground(
    draw: ImageDraw.ImageDraw,
    scene: ExecutedScene,
    frame: ProjectionFrame,
    *,
    show_edges: bool,
    edge_width: int,
) -> None:
    """Draw the root minimum-y rectangle behind semantic geometry."""
    x0, y0, z0 = scene.root_bounds.minimum.as_tuple()
    x1, _, z1 = scene.root_bounds.maximum.as_tuple()
    points = tuple(
        frame.project(point)
        for point in (
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y0, z1),
            (x0, y0, z1),
        )
    )
    if abs(_polygon_area(points)) <= 1e-8:
        return
    draw.polygon(
        points,
        fill=_GROUND_COLOR,
        outline=_GROUND_EDGE_COLOR if show_edges else None,
        width=edge_width if show_edges else 1,
    )


def _draw_bounds_overlay(
    draw: ImageDraw.ImageDraw,
    scene: ExecutedScene,
    frame: ProjectionFrame,
    *,
    width: int,
) -> None:
    """Draw the projected root-bounds wireframe after scene geometry."""
    corners = bounds_corners(scene.root_bounds)
    projected = tuple(frame.project(point) for point in corners)
    edges = (
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    )
    for start, end in edges:
        draw.line(
            (projected[start], projected[end]),
            fill=_BOUNDS_COLOR,
            width=width,
        )


def _polygon_area(points: tuple[Point2, ...]) -> float:
    """Return the signed shoelace area of a projected polygon."""
    return 0.5 * sum(
        x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1])
    )


def _dot(first: Point3, second: Point3) -> float:
    """Return a stable three-vector dot product."""
    result = sum(left * right for left, right in zip(first, second))
    return 0.0 if math.isclose(result, 0.0, abs_tol=1e-15) else result
