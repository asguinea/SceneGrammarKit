"""Deterministic orthographic camera and framing tests."""

from __future__ import annotations

import math

import pytest

from scene_grammar_kit.grammar import Bounds3D, Vector3
from scene_grammar_kit.rendering import (
    CameraPreset,
    ProjectionError,
    bounds_corners,
    camera_basis,
    fit_projection,
    fit_projection_from_points,
    project_orthographic,
)


@pytest.mark.parametrize("preset", list(CameraPreset))
def test_required_camera_presets_are_orthonormal(preset: CameraPreset) -> None:
    """Every documented camera returns a deterministic orthonormal basis."""
    basis = camera_basis(preset)
    assert basis.preset is preset
    for vector in (basis.right, basis.up, basis.forward):
        assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1)
    assert sum(a * b for a, b in zip(basis.right, basis.up)) == pytest.approx(0)


def test_front_projection_matches_coordinate_convention() -> None:
    """Canonical front maps x right and y up while depth follows positive z."""
    basis = camera_basis("front")
    assert project_orthographic((2.0, 3.0, 7.0), basis) == (2.0, 3.0)
    frame = fit_projection(
        Bounds3D(Vector3(0, 0, 0), Vector3(4, 2, 8)),
        basis,
        width=400,
        height=300,
        padding=20,
    )
    assert frame.depth((0.0, 0.0, 7.0)) == 7.0


@pytest.mark.parametrize("preset", list(CameraPreset))
def test_root_bounds_fit_inside_padding(preset: CameraPreset) -> None:
    """Projected root corners remain inside the deterministic padded frame."""
    bounds = Bounds3D(Vector3(-4, 10, 20), Vector3(6, 30, 25))
    frame = fit_projection(
        bounds,
        camera_basis(preset),
        width=640,
        height=360,
        padding=32,
    )
    points = tuple(frame.project(point) for point in bounds_corners(bounds))
    assert min(point[0] for point in points) >= 32 - 1e-9
    assert max(point[0] for point in points) <= 640 - 32 + 1e-9
    assert min(point[1] for point in points) >= 32 - 1e-9
    assert max(point[1] for point in points) <= 360 - 32 + 1e-9


def test_non_origin_scene_has_identical_relative_framing() -> None:
    """Translation does not change fitted projected shape or scale."""
    first = Bounds3D(Vector3(0, 0, 0), Vector3(1, 2, 3))
    second = Bounds3D(Vector3(10, -5, 100), Vector3(11, -3, 103))
    basis = camera_basis("isometric")
    first_frame = fit_projection(first, basis, width=800, height=600, padding=40)
    second_frame = fit_projection(second, basis, width=800, height=600, padding=40)
    first_pixels = tuple(first_frame.project(point) for point in bounds_corners(first))
    second_pixels = tuple(
        second_frame.project(point) for point in bounds_corners(second)
    )
    assert first_frame.scale == pytest.approx(second_frame.scale)
    for left, right in zip(first_pixels, second_pixels):
        assert left == pytest.approx(right)


def test_identical_inputs_produce_identical_projection() -> None:
    """Projection has no mutable or environment-dependent camera fitting state."""
    bounds = Bounds3D(Vector3(0, 0, 0), Vector3(1, 1, 1))
    basis = camera_basis("top")
    assert fit_projection(
        bounds, basis, width=500, height=400, padding=25
    ) == fit_projection(bounds, basis, width=500, height=400, padding=25)


def test_framing_uses_one_uniform_aspect_preserving_scale() -> None:
    """The same scalar transforms horizontal and vertical projection axes."""
    bounds = Bounds3D(Vector3(0, 0, 0), Vector3(4, 2, 1))
    frame = fit_projection(
        bounds,
        camera_basis("front"),
        width=800,
        height=800,
        padding=50,
    )
    origin = frame.project((0.0, 0.0, 0.0))
    x_end = frame.project((4.0, 0.0, 0.0))
    y_end = frame.project((0.0, 2.0, 0.0))
    assert abs(x_end[0] - origin[0]) / 4 == pytest.approx(abs(y_end[1] - origin[1]) / 2)


def test_degenerate_projection_fails_clearly() -> None:
    """A point set without projected width and height is rejected."""
    with pytest.raises(ProjectionError, match="degenerate"):
        fit_projection_from_points(
            ((1.0, 1.0, 1.0), (1.0, 1.0, 2.0)),
            camera_basis("front"),
            width=400,
            height=300,
            padding=20,
        )
