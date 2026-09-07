"""Render configuration and deterministic semantic palette tests."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from scene_grammar_kit.rendering import (
    KNOWN_SEMANTIC_COLORS,
    CameraPreset,
    RenderConfig,
    RenderConfigError,
    resolve_palette,
    semantic_color,
)


def test_default_render_configuration_is_valid_and_frozen() -> None:
    """Recommended render defaults are normalized deterministically."""
    config = RenderConfig()
    assert config.width == 1024
    assert config.height == 683
    assert config.camera_preset is CameraPreset.ISOMETRIC
    assert config.show_ground
    assert config.show_edges
    assert not config.show_bounds
    assert config.supersampling == 2
    with pytest.raises(AttributeError):
        config.width = 10  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", 0),
        ("height", -1),
        ("width", True),
        ("height", 9000),
    ],
)
def test_invalid_dimensions_are_rejected(field: str, value: object) -> None:
    """Dimensions must be bounded positive integers."""
    with pytest.raises(RenderConfigError):
        RenderConfig(**{field: value})  # type: ignore[arg-type]


def test_invalid_camera_preset_is_rejected() -> None:
    """Only the documented fixed cameras are accepted."""
    with pytest.raises(RenderConfigError, match="camera_preset"):
        RenderConfig(camera_preset="orbit")


@pytest.mark.parametrize(
    "color",
    [
        (0, 0),
        (0, 0, 0, 0, 0),
        (-1, 0, 0),
        (256, 0, 0),
        (1.5, 0, 0),
        "black",
    ],
)
def test_invalid_colors_are_rejected(color: object) -> None:
    """RGB/RGBA channels require bounded integers."""
    with pytest.raises(RenderConfigError, match="background_color"):
        RenderConfig(background_color=color)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0, -1, True, 9])
def test_invalid_supersampling_is_rejected(value: object) -> None:
    """Supersampling is a conservative bounded positive integer."""
    with pytest.raises(RenderConfigError, match="supersampling"):
        RenderConfig(supersampling=value)  # type: ignore[arg-type]


def test_unsafe_supersampled_pixel_count_is_rejected() -> None:
    """Large otherwise-valid dimensions cannot allocate uncontrolled images."""
    with pytest.raises(RenderConfigError, match="pixel safety limit"):
        RenderConfig(width=8000, height=8000, supersampling=2)


def test_known_semantic_classes_have_explicit_colors() -> None:
    """The complete required common vocabulary has stable preferred colors."""
    expected = {
        "road",
        "sidewalk",
        "building",
        "facade",
        "car",
        "tree",
        "lamp_post",
        "wall",
        "corridor",
        "ground",
    }
    assert set(KNOWN_SEMANTIC_COLORS) == expected
    assert semantic_color("road") == (76, 82, 94, 255)
    assert semantic_color("car") == (218, 78, 72, 255)


def test_unknown_color_is_stable_and_not_python_hash_based() -> None:
    """SHA-256 fallback is stable across distinct hash-randomized processes."""
    semantic_class = "unknown_über_class"
    local = semantic_color(semantic_class)
    script = (
        "from scene_grammar_kit.rendering import semantic_color;"
        f"print(','.join(map(str,semantic_color({semantic_class!r}))))"
    )
    outputs: list[str] = []
    for seed in ("1", "8675309"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.append(result.stdout.strip())
    assert outputs == [",".join(map(str, local))] * 2
    assert semantic_color(semantic_class) == local


def test_palette_order_and_overrides_are_deterministic() -> None:
    """Palette resolution sorts class keys and honors validated overrides."""
    palette = resolve_palette(
        ["tree", "car", "tree", "custom"],
        {"custom": (1, 2, 3, 4)},
    )
    assert tuple(palette) == ("car", "custom", "tree")
    assert palette["custom"] == (1, 2, 3, 4)
    assert palette == resolve_palette(
        reversed(["tree", "car", "tree", "custom"]),
        {"custom": (1, 2, 3, 4)},
    )
