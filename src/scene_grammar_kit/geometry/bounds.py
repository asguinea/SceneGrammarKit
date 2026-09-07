"""Axis-aligned bounds operations used by deterministic execution."""

from __future__ import annotations

import math
from collections.abc import Sequence

from scene_grammar_kit.geometry.errors import GeometryBoundsError, RepeatFitError
from scene_grammar_kit.grammar import Axis, Bounds3D, Vector3


def axis_extent(bounds: Bounds3D, axis: Axis) -> float:
    """Return the strictly positive extent of bounds on one axis."""
    lower, upper = axis_interval(bounds, axis)
    extent = upper - lower
    if not math.isfinite(extent) or extent <= 0:
        raise GeometryBoundsError(
            f"Bounds extent on axis {axis.value} must be finite and positive"
        )
    return extent


def axis_interval(bounds: Bounds3D, axis: Axis) -> tuple[float, float]:
    """Return minimum and maximum coordinates on one axis."""
    _bounds(bounds)
    _axis(axis)
    index = _axis_index(axis)
    return (
        bounds.minimum.as_tuple()[index],
        bounds.maximum.as_tuple()[index],
    )


def replace_axis_interval(
    bounds: Bounds3D,
    axis: Axis,
    lower: float,
    upper: float,
) -> Bounds3D:
    """Return bounds with one finite, strictly positive interval replaced."""
    _bounds(bounds)
    _axis(axis)
    if (
        isinstance(lower, bool)
        or isinstance(upper, bool)
        or not isinstance(lower, (int, float))
        or not isinstance(upper, (int, float))
    ):
        raise GeometryBoundsError("Axis interval endpoints must be numbers")
    lower_float = float(lower)
    upper_float = float(upper)
    if not math.isfinite(lower_float) or not math.isfinite(upper_float):
        raise GeometryBoundsError("Axis interval endpoints must be finite")
    if upper_float <= lower_float:
        raise GeometryBoundsError("Axis interval must have positive extent")

    minimum = list(bounds.minimum.as_tuple())
    maximum = list(bounds.maximum.as_tuple())
    index = _axis_index(axis)
    minimum[index] = lower_float
    maximum[index] = upper_float
    return Bounds3D(Vector3(*minimum), Vector3(*maximum))


def split_bounds_by_weights(
    bounds: Bounds3D,
    axis: Axis,
    weights: Sequence[float],
) -> tuple[Bounds3D, ...]:
    """Split bounds in order by positive relative weights.

    Internal boundaries are computed from cumulative normalized weights rather
    than incrementally accumulated child extents. The first child starts at the
    exact parent minimum and the final child ends at the exact parent maximum.
    """
    _bounds(bounds)
    _axis(axis)
    if isinstance(weights, (str, bytes)) or len(weights) < 2:
        raise GeometryBoundsError("At least two split weights are required")
    normalized_weights: list[float] = []
    for index, weight in enumerate(weights):
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(float(weight))
            or float(weight) <= 0
        ):
            raise GeometryBoundsError(
                f"Split weight {index} must be finite and strictly positive"
            )
        normalized_weights.append(float(weight))
    try:
        total = math.fsum(normalized_weights)
    except (OverflowError, ValueError) as exc:
        raise GeometryBoundsError("Split weight sum must be finite") from exc
    if not math.isfinite(total) or total <= 0:
        raise GeometryBoundsError("Split weight sum must be finite and positive")

    parent_minimum, parent_maximum = axis_interval(bounds, axis)
    extent = parent_maximum - parent_minimum
    result: list[Bounds3D] = []
    cumulative = 0.0
    child_minimum = parent_minimum
    for index, weight in enumerate(normalized_weights):
        cumulative = math.fsum((cumulative, weight))
        child_maximum = (
            parent_maximum
            if index == len(normalized_weights) - 1
            else parent_minimum + extent * (cumulative / total)
        )
        result.append(
            replace_axis_interval(
                bounds,
                axis,
                child_minimum,
                child_maximum,
            )
        )
        child_minimum = child_maximum
    return tuple(result)


def repeat_bounds(
    bounds: Bounds3D,
    axis: Axis,
    count: int,
    spacing: float,
) -> tuple[Bounds3D, ...]:
    """Return ordered equal-cell repeat bounds using the frozen policy.

    This helper materializes ``count`` bounds and is intended only after the
    executor's primitive preflight has approved the requested expansion.
    """
    parent_minimum, parent_maximum, element_extent, spacing_float = _repeat_layout(
        bounds, axis, count, spacing
    )
    if count == 1:
        return (bounds,)

    result: list[Bounds3D] = []
    for index in range(count):
        result.append(
            _repeat_bound_at_layout(
                bounds,
                axis,
                count,
                index,
                parent_minimum,
                parent_maximum,
                element_extent,
                spacing_float,
            )
        )
    return tuple(result)


def repeat_bound_at(
    bounds: Bounds3D,
    axis: Axis,
    count: int,
    spacing: float,
    index: int,
) -> Bounds3D:
    """Return one repeat instance bound without materializing its siblings."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise GeometryBoundsError("Repeat count must be an integer of at least one")
    if isinstance(index, bool) or not isinstance(index, int):
        raise GeometryBoundsError("Repeat index must be an integer")
    if index < 0 or index >= count:
        raise GeometryBoundsError(f"Repeat index {index} is outside count {count}")
    parent_minimum, parent_maximum, element_extent, spacing_float = _repeat_layout(
        bounds, axis, count, spacing
    )
    return _repeat_bound_at_layout(
        bounds,
        axis,
        count,
        index,
        parent_minimum,
        parent_maximum,
        element_extent,
        spacing_float,
    )


def bounds_contain(outer: Bounds3D, inner: Bounds3D) -> bool:
    """Return whether inner bounds lie entirely inside outer bounds."""
    _bounds(outer)
    _bounds(inner)
    return all(
        outer_low <= inner_low and inner_high <= outer_high
        for outer_low, outer_high, inner_low, inner_high in zip(
            outer.minimum.as_tuple(),
            outer.maximum.as_tuple(),
            inner.minimum.as_tuple(),
            inner.maximum.as_tuple(),
        )
    )


def bounds_have_positive_extent(bounds: Bounds3D) -> bool:
    """Return whether every bounds extent is finite and strictly positive."""
    _bounds(bounds)
    return all(
        math.isfinite(high - low) and high > low
        for low, high in zip(
            bounds.minimum.as_tuple(),
            bounds.maximum.as_tuple(),
        )
    )


def _bounds(value: object) -> Bounds3D:
    """Require the shared Phase 0 bounds type."""
    if not isinstance(value, Bounds3D):
        raise GeometryBoundsError("Expected Bounds3D")
    return value


def _axis(value: object) -> Axis:
    """Require one of the frozen spatial axes."""
    if not isinstance(value, Axis):
        raise GeometryBoundsError("Axis must be x, y, or z")
    return value


def _axis_index(axis: Axis) -> int:
    """Map an axis to its x/y/z vector index."""
    return {Axis.X: 0, Axis.Y: 1, Axis.Z: 2}[axis]


def _repeat_layout(
    bounds: Bounds3D,
    axis: Axis,
    count: int,
    spacing: float,
) -> tuple[float, float, float, float]:
    """Validate repeat parameters and return its equal-cell layout values."""
    _bounds(bounds)
    _axis(axis)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise GeometryBoundsError("Repeat count must be an integer of at least one")
    if (
        isinstance(spacing, bool)
        or not isinstance(spacing, (int, float))
        or not math.isfinite(float(spacing))
        or float(spacing) < 0
    ):
        raise GeometryBoundsError("Repeat spacing must be finite and nonnegative")
    spacing_float = float(spacing)
    parent_minimum, parent_maximum = axis_interval(bounds, axis)
    extent = parent_maximum - parent_minimum
    total_gap = (count - 1) * spacing_float
    if not math.isfinite(total_gap):
        raise RepeatFitError("Repeat total gap is not finite")
    available = extent - total_gap
    if not math.isfinite(available) or available <= 0:
        raise RepeatFitError(
            f"Repeat does not fit: extent={extent}, count={count}, "
            f"spacing={spacing_float}, available={available}"
        )
    element_extent = available / count
    if not math.isfinite(element_extent) or element_extent <= 0:
        raise RepeatFitError("Repeat element extent must be finite and positive")
    return (
        parent_minimum,
        parent_maximum,
        element_extent,
        spacing_float,
    )


def _repeat_bound_at_layout(
    bounds: Bounds3D,
    axis: Axis,
    count: int,
    index: int,
    parent_minimum: float,
    parent_maximum: float,
    element_extent: float,
    spacing: float,
) -> Bounds3D:
    """Construct one previously validated repeat instance bound."""
    if count == 1:
        return bounds
    lower = parent_minimum + index * (element_extent + spacing)
    upper = parent_maximum if index == count - 1 else lower + element_extent
    return replace_axis_interval(bounds, axis, lower, upper)
