"""Immutable value types for semantic preview rendering policy version 0.1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TypeAlias

from PIL import Image

from scene_grammar_kit.rendering.errors import RenderConfigError

RENDERER_POLICY_VERSION = "0.1"
MAX_RENDER_DIMENSION = 8192
MAX_SUPERSAMPLING = 8
MAX_SUPERSAMPLED_PIXELS = 64_000_000

Color: TypeAlias = tuple[int, int, int, int]


class CameraPreset(str, Enum):
    """Supported deterministic orthographic camera presets."""

    ISOMETRIC = "isometric"
    FRONT = "front"
    TOP = "top"


@dataclass(frozen=True, slots=True)
class RenderConfig:
    """Validated deterministic renderer configuration."""

    width: int = 1024
    height: int = 683
    camera_preset: CameraPreset | str = CameraPreset.ISOMETRIC
    image_padding: int = 64
    background_color: Color | Sequence[int] = (246, 248, 251, 255)
    show_ground: bool = True
    show_edges: bool = True
    edge_width: int = 2
    show_bounds: bool = False
    semantic_palette: Mapping[str, Color | Sequence[int]] = field(default_factory=dict)
    transparent_background: bool = False
    supersampling: int = 2

    def __post_init__(self) -> None:
        """Normalize enum/color fields and reject unsafe dimensions."""
        _positive_integer(self.width, "width")
        _positive_integer(self.height, "height")
        if self.width > MAX_RENDER_DIMENSION or self.height > MAX_RENDER_DIMENSION:
            raise RenderConfigError(
                f"width and height must not exceed {MAX_RENDER_DIMENSION}"
            )
        try:
            preset = CameraPreset(self.camera_preset)
        except (TypeError, ValueError) as exc:
            choices = ", ".join(item.value for item in CameraPreset)
            raise RenderConfigError(f"camera_preset must be one of: {choices}") from exc
        object.__setattr__(self, "camera_preset", preset)

        if (
            isinstance(self.image_padding, bool)
            or not isinstance(self.image_padding, int)
            or self.image_padding < 0
        ):
            raise RenderConfigError("image_padding must be a nonnegative integer")
        if self.image_padding * 2 >= min(self.width, self.height):
            raise RenderConfigError(
                "image_padding must leave positive drawable width and height"
            )
        _positive_integer(self.edge_width, "edge_width")
        _positive_integer(self.supersampling, "supersampling")
        if self.supersampling > MAX_SUPERSAMPLING:
            raise RenderConfigError(
                f"supersampling must not exceed {MAX_SUPERSAMPLING}"
            )
        supersampled_pixels = (
            self.width * self.height * self.supersampling * self.supersampling
        )
        if supersampled_pixels > MAX_SUPERSAMPLED_PIXELS:
            raise RenderConfigError(
                "requested dimensions and supersampling exceed the "
                f"{MAX_SUPERSAMPLED_PIXELS} pixel safety limit"
            )
        for name in (
            "show_ground",
            "show_edges",
            "show_bounds",
            "transparent_background",
        ):
            if not isinstance(getattr(self, name), bool):
                raise RenderConfigError(f"{name} must be a boolean")

        object.__setattr__(
            self,
            "background_color",
            normalize_color(self.background_color, "background_color"),
        )
        if not isinstance(self.semantic_palette, Mapping):
            raise RenderConfigError("semantic_palette must be a mapping")
        palette: dict[str, Color] = {}
        for semantic_class, color in self.semantic_palette.items():
            if not isinstance(semantic_class, str) or not semantic_class:
                raise RenderConfigError(
                    "semantic_palette keys must be nonempty strings"
                )
            palette[semantic_class] = normalize_color(
                color,
                f"semantic_palette[{semantic_class!r}]",
            )
        object.__setattr__(
            self,
            "semantic_palette",
            MappingProxyType(dict(sorted(palette.items()))),
        )


@dataclass(frozen=True, slots=True)
class RenderReport:
    """Canonical deterministic facts about one completed render."""

    success: bool
    width: int
    height: int
    camera_preset: CameraPreset | str
    primitive_count_considered: int
    box_count_rendered: int
    plane_count_rendered: int
    empty_count_skipped: int
    visible_face_count: int
    semantic_classes_present: tuple[str, ...]
    palette_mapping: Mapping[str, Color]
    executed_scene_grammar_sha256: str
    renderer_policy_version: str = RENDERER_POLICY_VERSION

    def __post_init__(self) -> None:
        """Validate and freeze deterministic report collections."""
        if not isinstance(self.success, bool):
            raise RenderConfigError("success must be a boolean")
        _positive_integer(self.width, "width")
        _positive_integer(self.height, "height")
        try:
            preset = CameraPreset(self.camera_preset)
        except (TypeError, ValueError) as exc:
            raise RenderConfigError("report camera_preset is invalid") from exc
        object.__setattr__(self, "camera_preset", preset)
        for name in (
            "primitive_count_considered",
            "box_count_rendered",
            "plane_count_rendered",
            "empty_count_skipped",
            "visible_face_count",
        ):
            _nonnegative_integer(getattr(self, name), name)
        if (
            not isinstance(self.semantic_classes_present, tuple)
            or any(
                not isinstance(item, str) or not item
                for item in self.semantic_classes_present
            )
            or self.semantic_classes_present
            != tuple(sorted(set(self.semantic_classes_present)))
        ):
            raise RenderConfigError(
                "semantic_classes_present must be a sorted unique string tuple"
            )
        if not isinstance(self.palette_mapping, Mapping):
            raise RenderConfigError("palette_mapping must be a mapping")
        palette: dict[str, Color] = {}
        for semantic_class, color in self.palette_mapping.items():
            if not isinstance(semantic_class, str) or not semantic_class:
                raise RenderConfigError("palette_mapping keys must be nonempty strings")
            palette[semantic_class] = normalize_color(
                color,
                f"palette_mapping[{semantic_class!r}]",
            )
        object.__setattr__(
            self,
            "palette_mapping",
            MappingProxyType(dict(sorted(palette.items()))),
        )
        _sha256(self.executed_scene_grammar_sha256)
        if self.renderer_policy_version != RENDERER_POLICY_VERSION:
            raise RenderConfigError(
                f"renderer_policy_version must be {RENDERER_POLICY_VERSION!r}"
            )


@dataclass(frozen=True, slots=True)
class RenderResult:
    """A final RGBA Pillow image paired with its deterministic report."""

    image: Image.Image
    report: RenderReport
    palette_mapping: Mapping[str, Color]

    def __post_init__(self) -> None:
        """Validate image dimensions and freeze a palette copy."""
        if not isinstance(self.image, Image.Image):
            raise RenderConfigError("image must be a Pillow Image")
        if self.image.mode != "RGBA":
            raise RenderConfigError("render image must use RGBA mode")
        if self.image.size != (self.report.width, self.report.height):
            raise RenderConfigError(
                "render image dimensions must match the render report"
            )
        palette = dict(sorted(self.palette_mapping.items()))
        if palette != dict(self.report.palette_mapping):
            raise RenderConfigError(
                "result palette_mapping must match the render report"
            )
        object.__setattr__(self, "palette_mapping", MappingProxyType(palette))


def normalize_color(value: object, name: str = "color") -> Color:
    """Return a validated RGBA color from an RGB or RGBA integer sequence."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RenderConfigError(f"{name} must be an RGB or RGBA sequence")
    channels = tuple(value)
    if len(channels) not in (3, 4):
        raise RenderConfigError(f"{name} must contain three or four channels")
    if any(
        isinstance(channel, bool)
        or not isinstance(channel, int)
        or channel < 0
        or channel > 255
        for channel in channels
    ):
        raise RenderConfigError(f"{name} channels must be integers between 0 and 255")
    if len(channels) == 3:
        channels = channels + (255,)
    return channels  # type: ignore[return-value]


def _positive_integer(value: object, name: str) -> int:
    """Require a positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RenderConfigError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    """Require a nonnegative integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RenderConfigError(f"{name} must be a nonnegative integer")
    return value


def _sha256(value: object) -> str:
    """Validate a lowercase SHA-256 hexadecimal digest."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RenderConfigError(
            "executed_scene_grammar_sha256 must be a lowercase SHA-256 digest"
        )
    return value
