"""Stable semantic colors for deterministic preview rendering."""

from __future__ import annotations

import colorsys
import hashlib
from collections.abc import Iterable, Mapping

from scene_grammar_kit.rendering.models import Color, normalize_color

KNOWN_SEMANTIC_COLORS: Mapping[str, Color] = {
    "building": (76, 126, 178, 255),
    "car": (218, 78, 72, 255),
    "corridor": (63, 158, 154, 255),
    "facade": (100, 132, 184, 255),
    "ground": (171, 178, 188, 255),
    "lamp_post": (224, 165, 55, 255),
    "road": (76, 82, 94, 255),
    "sidewalk": (207, 179, 124, 255),
    "tree": (67, 142, 82, 255),
    "wall": (150, 111, 172, 255),
}


def semantic_color(semantic_class: str) -> Color:
    """Return a known or SHA-256-derived semantic RGBA color."""
    if not isinstance(semantic_class, str) or not semantic_class:
        raise ValueError("semantic_class must be a nonempty string")
    known = KNOWN_SEMANTIC_COLORS.get(semantic_class)
    if known is not None:
        return known
    digest = hashlib.sha256(semantic_class.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") / 65536.0
    saturation = 0.56 + (digest[2] / 255.0) * 0.18
    value = 0.72 + (digest[3] / 255.0) * 0.16
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    return (
        round(red * 255),
        round(green * 255),
        round(blue * 255),
        255,
    )


def resolve_palette(
    semantic_classes: Iterable[str],
    overrides: Mapping[str, Color] | None = None,
) -> dict[str, Color]:
    """Return a lexicographically ordered palette for present classes."""
    custom = overrides or {}
    result: dict[str, Color] = {}
    for semantic_class in sorted(set(semantic_classes)):
        if not isinstance(semantic_class, str) or not semantic_class:
            raise ValueError("semantic classes must be nonempty strings")
        result[semantic_class] = (
            normalize_color(
                custom[semantic_class],
                f"palette override {semantic_class!r}",
            )
            if semantic_class in custom
            else semantic_color(semantic_class)
        )
    return result


def shade_color(color: Color, factor: float) -> Color:
    """Scale RGB channels deterministically while preserving alpha."""
    if not 0.0 <= factor <= 2.0:
        raise ValueError("shade factor must be between zero and two")
    return (
        min(255, max(0, round(color[0] * factor))),
        min(255, max(0, round(color[1] * factor))),
        min(255, max(0, round(color[2] * factor))),
        color[3],
    )
