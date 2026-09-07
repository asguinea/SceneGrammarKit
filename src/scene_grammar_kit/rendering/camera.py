"""Deterministic orthographic camera presets and projection framing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeAlias

from scene_grammar_kit.grammar import Bounds3D
from scene_grammar_kit.rendering.errors import CameraError, ProjectionError
from scene_grammar_kit.rendering.models import CameraPreset

Point3: TypeAlias = tuple[float, float, float]
Point2: TypeAlias = tuple[float, float]


@dataclass(frozen=True, slots=True)
class CameraBasis:
    """Orthonormal screen-right, screen-up, and viewing-forward vectors."""

    preset: CameraPreset
    right: Point3
    up: Point3
    forward: Point3

    def __post_init__(self) -> None:
        """Require finite unit-length mutually orthogonal basis vectors."""
        try:
            preset = CameraPreset(self.preset)
        except (TypeError, ValueError) as exc:
            raise CameraError("camera basis preset is invalid") from exc
        object.__setattr__(self, "preset", preset)
        for name in ("right", "up", "forward"):
            vector = getattr(self, name)
            if (
                not isinstance(vector, tuple)
                or len(vector) != 3
                or any(not math.isfinite(value) for value in vector)
            ):
                raise CameraError(f"{name} must be a finite three-vector")
            if not math.isclose(_dot(vector, vector), 1.0, abs_tol=1e-12):
                raise CameraError(f"{name} must have unit length")
        if any(
            not math.isclose(_dot(first, second), 0.0, abs_tol=1e-12)
            for first, second in (
                (self.right, self.up),
                (self.right, self.forward),
                (self.up, self.forward),
            )
        ):
            raise CameraError("camera basis vectors must be orthogonal")


@dataclass(frozen=True, slots=True)
class ProjectionFrame:
    """One deterministic orthographic world-to-pixel fitting transform."""

    basis: CameraBasis
    minimum_u: float
    minimum_v: float
    scale: float
    offset_x: float
    offset_y: float
    width: int
    height: int
    padding: int

    def project(self, point: Point3) -> Point2:
        """Project one 3D world point into top-left-origin image coordinates."""
        u, v = project_orthographic(point, self.basis)
        return (
            self.offset_x + (u - self.minimum_u) * self.scale,
            self.height - (self.offset_y + (v - self.minimum_v) * self.scale),
        )

    def depth(self, point: Point3) -> float:
        """Return camera-space depth increasing from near to far."""
        return _dot(point, self.basis.forward)


def camera_basis(preset: CameraPreset | str) -> CameraBasis:
    """Return the fixed orthographic basis for a named camera preset."""
    try:
        normalized = CameraPreset(preset)
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in CameraPreset)
        raise CameraError(f"camera preset must be one of: {choices}") from exc
    if normalized is CameraPreset.FRONT:
        return CameraBasis(
            preset=normalized,
            right=(1.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            forward=(0.0, 0.0, 1.0),
        )
    if normalized is CameraPreset.TOP:
        return CameraBasis(
            preset=normalized,
            right=(1.0, 0.0, 0.0),
            up=(0.0, 0.0, 1.0),
            forward=(0.0, -1.0, 0.0),
        )
    forward = _normalize((1.0, -0.75, 1.0))
    right = _normalize((1.0, 0.0, -1.0))
    up = _normalize(_cross(forward, right))
    return CameraBasis(
        preset=normalized,
        right=right,
        up=up,
        forward=forward,
    )


def fit_projection(
    bounds: Bounds3D,
    basis: CameraBasis,
    *,
    width: int,
    height: int,
    padding: int,
) -> ProjectionFrame:
    """Fit projected root bounds inside an image with deterministic padding."""
    if not isinstance(bounds, Bounds3D):
        raise ProjectionError("bounds must be a Bounds3D")
    return fit_projection_from_points(
        bounds_corners(bounds),
        basis,
        width=width,
        height=height,
        padding=padding,
    )


def fit_projection_from_points(
    points: tuple[Point3, ...],
    basis: CameraBasis,
    *,
    width: int,
    height: int,
    padding: int,
) -> ProjectionFrame:
    """Fit projected points, rejecting zero-area orthographic projections."""
    if not points:
        raise ProjectionError("at least one point is required for framing")
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or width < 1
        or isinstance(height, bool)
        or not isinstance(height, int)
        or height < 1
    ):
        raise ProjectionError("projection dimensions must be positive integers")
    if (
        isinstance(padding, bool)
        or not isinstance(padding, int)
        or padding < 0
        or padding * 2 >= min(width, height)
    ):
        raise ProjectionError("projection padding leaves no drawable area")
    projected = tuple(project_orthographic(point, basis) for point in points)
    minimum_u = min(point[0] for point in projected)
    maximum_u = max(point[0] for point in projected)
    minimum_v = min(point[1] for point in projected)
    maximum_v = max(point[1] for point in projected)
    span_u = maximum_u - minimum_u
    span_v = maximum_v - minimum_v
    if (
        not math.isfinite(span_u)
        or not math.isfinite(span_v)
        or span_u <= 1e-15
        or span_v <= 1e-15
    ):
        raise ProjectionError("root projection is degenerate for the selected camera")
    drawable_width = width - 2 * padding
    drawable_height = height - 2 * padding
    scale = min(drawable_width / span_u, drawable_height / span_v)
    if not math.isfinite(scale) or scale <= 0:
        raise ProjectionError("projection scale must be finite and positive")
    used_width = span_u * scale
    used_height = span_v * scale
    return ProjectionFrame(
        basis=basis,
        minimum_u=minimum_u,
        minimum_v=minimum_v,
        scale=scale,
        offset_x=(width - used_width) / 2.0,
        offset_y=(height - used_height) / 2.0,
        width=width,
        height=height,
        padding=padding,
    )


def project_orthographic(point: Point3, basis: CameraBasis) -> Point2:
    """Project one world point onto the camera's right/up plane."""
    if (
        not isinstance(point, tuple)
        or len(point) != 3
        or any(not math.isfinite(value) for value in point)
    ):
        raise ProjectionError("point must be a finite three-vector")
    return (_dot(point, basis.right), _dot(point, basis.up))


def bounds_corners(bounds: Bounds3D) -> tuple[Point3, ...]:
    """Return eight bounds corners in stable binary x/y/z order."""
    x0, y0, z0 = bounds.minimum.as_tuple()
    x1, y1, z1 = bounds.maximum.as_tuple()
    return (
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    )


def _dot(first: Point3, second: Point3) -> float:
    """Return a three-vector dot product."""
    return sum(left * right for left, right in zip(first, second))


def _cross(first: Point3, second: Point3) -> Point3:
    """Return a three-vector cross product."""
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _normalize(vector: Point3) -> Point3:
    """Return a finite unit vector."""
    length = math.sqrt(_dot(vector, vector))
    if not math.isfinite(length) or length <= 0:
        raise CameraError("camera vector must have positive finite length")
    return tuple(value / length for value in vector)  # type: ignore[return-value]
