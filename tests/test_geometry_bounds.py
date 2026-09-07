"""Deterministic axis-aligned geometry bounds tests."""

from __future__ import annotations

import pytest

from scene_grammar_kit.geometry import (
    GeometryBoundsError,
    RepeatFitError,
    axis_extent,
    axis_interval,
    bounds_contain,
    bounds_have_positive_extent,
    repeat_bound_at,
    repeat_bounds,
    replace_axis_interval,
    split_bounds_by_weights,
)
from scene_grammar_kit.grammar import Axis, Bounds3D, Vector3


def make_bounds(
    minimum: tuple[float, float, float] = (0.0, 0.0, 0.0),
    maximum: tuple[float, float, float] = (1.0, 2.0, 3.0),
) -> Bounds3D:
    """Build shared typed bounds for focused helper tests."""
    return Bounds3D(Vector3(*minimum), Vector3(*maximum))


def test_axis_helpers_and_interval_replacement() -> None:
    """Axis access and replacement retain non-selected coordinates."""
    bounds = make_bounds()
    assert axis_interval(bounds, Axis.Y) == (0.0, 2.0)
    assert axis_extent(bounds, Axis.Z) == 3.0
    replaced = replace_axis_interval(bounds, Axis.X, 0.25, 0.75)
    assert replaced.minimum.as_tuple() == (0.25, 0.0, 0.0)
    assert replaced.maximum.as_tuple() == (0.75, 2.0, 3.0)
    assert bounds_contain(bounds, replaced)
    assert bounds_have_positive_extent(replaced)


@pytest.mark.parametrize(
    ("weights", "expected_boundaries"),
    [
        ((1.0, 1.0), (0.0, 0.5, 1.0)),
        ((1.0, 2.0), (0.0, 1.0 / 3.0, 1.0)),
        ((1.0, 2.0, 1.0), (0.0, 0.25, 0.75, 1.0)),
    ],
)
def test_weighted_splits_cover_parent_exactly_in_order(
    weights: tuple[float, ...],
    expected_boundaries: tuple[float, ...],
) -> None:
    """Split siblings are ordered, adjacent, and exactly cover the parent."""
    parent = make_bounds()
    children = split_bounds_by_weights(parent, Axis.X, weights)
    assert children[0].minimum.x == parent.minimum.x
    assert children[-1].maximum.x == parent.maximum.x
    for index, child in enumerate(children):
        assert child.minimum.x == pytest.approx(expected_boundaries[index])
        assert child.maximum.x == pytest.approx(expected_boundaries[index + 1])
        assert child.minimum.y == parent.minimum.y
        assert child.maximum.y == parent.maximum.y
        assert child.minimum.z == parent.minimum.z
        assert child.maximum.z == parent.maximum.z
        assert bounds_contain(parent, child)
        if index:
            assert children[index - 1].maximum.x == child.minimum.x


def test_repeat_count_one_receives_exact_parent_bounds() -> None:
    """A one-instance repeat has no gap and reuses the full parent."""
    parent = make_bounds()
    assert repeat_bounds(parent, Axis.Z, 1, 99.0) == (parent,)
    assert repeat_bound_at(parent, Axis.Z, 1, 99.0, 0) == parent


def test_repeat_equal_cells_use_exact_gap_and_full_parent() -> None:
    """Multiple repeat cells have equal extent and exact requested gaps."""
    parent = make_bounds(maximum=(1.0, 2.0, 1.0))
    instances = repeat_bounds(parent, Axis.Z, 4, 0.1)
    assert instances[0].minimum.z == parent.minimum.z
    assert instances[-1].maximum.z == parent.maximum.z
    extents = [axis_extent(item, Axis.Z) for item in instances]
    assert extents == pytest.approx([0.175] * 4)
    for previous, current in zip(instances, instances[1:]):
        assert current.minimum.z - previous.maximum.z == pytest.approx(0.1)
    for instance in instances:
        assert axis_interval(instance, Axis.X) == axis_interval(parent, Axis.X)
        assert axis_interval(instance, Axis.Y) == axis_interval(parent, Axis.Y)


def test_zero_spacing_produces_adjacent_equal_cells() -> None:
    """Zero spacing is valid and produces shared boundaries."""
    parent = make_bounds(maximum=(1.0, 2.0, 3.0))
    instances = repeat_bounds(parent, Axis.Z, 3, 0.0)
    assert [axis_extent(item, Axis.Z) for item in instances] == [1.0, 1.0, 1.0]
    assert instances[0].maximum.z == instances[1].minimum.z
    assert instances[1].maximum.z == instances[2].minimum.z


def test_repeat_that_cannot_fit_fails_clearly() -> None:
    """Gap consumption equal to the parent extent is rejected."""
    with pytest.raises(RepeatFitError, match="Repeat does not fit"):
        repeat_bounds(make_bounds(), Axis.X, 3, 0.5)


@pytest.mark.parametrize(
    "weights",
    [(), (1.0,), (1.0, 0.0), (1.0, float("inf"))],
)
def test_invalid_split_weights_raise_domain_error(
    weights: tuple[float, ...],
) -> None:
    """Malformed split helper input is never normalized silently."""
    with pytest.raises(GeometryBoundsError):
        split_bounds_by_weights(make_bounds(), Axis.X, weights)


def test_repeat_bound_at_validates_count_before_index_range() -> None:
    """Direct indexed access reports invalid repeat counts consistently."""
    with pytest.raises(GeometryBoundsError, match="count"):
        repeat_bound_at(make_bounds(), Axis.X, 0, 0.0, 0)
