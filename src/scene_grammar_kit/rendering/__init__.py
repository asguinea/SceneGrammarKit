"""Public deterministic headless semantic-rendering API."""

from scene_grammar_kit.rendering.camera import (
    CameraBasis,
    ProjectionFrame,
    bounds_corners,
    camera_basis,
    fit_projection,
    fit_projection_from_points,
    project_orthographic,
)
from scene_grammar_kit.rendering.errors import (
    CameraError,
    ProjectionError,
    RenderConfigError,
    RenderFileExistsError,
    RenderingError,
    RenderPersistenceError,
    RenderSerializationError,
    RenderWriteError,
)
from scene_grammar_kit.rendering.models import (
    RENDERER_POLICY_VERSION,
    CameraPreset,
    Color,
    RenderConfig,
    RenderReport,
    RenderResult,
    normalize_color,
)
from scene_grammar_kit.rendering.palette import (
    KNOWN_SEMANTIC_COLORS,
    resolve_palette,
    semantic_color,
    shade_color,
)
from scene_grammar_kit.rendering.persistence import (
    render_report_path_for,
    render_report_to_canonical_json,
    save_render,
    save_render_report,
)
from scene_grammar_kit.rendering.renderer import render_executed_scene

__all__ = [
    "RENDERER_POLICY_VERSION",
    "KNOWN_SEMANTIC_COLORS",
    "CameraBasis",
    "CameraError",
    "CameraPreset",
    "Color",
    "ProjectionError",
    "ProjectionFrame",
    "RenderConfig",
    "RenderConfigError",
    "RenderFileExistsError",
    "RenderPersistenceError",
    "RenderReport",
    "RenderResult",
    "RenderSerializationError",
    "RenderWriteError",
    "RenderingError",
    "bounds_corners",
    "camera_basis",
    "fit_projection",
    "fit_projection_from_points",
    "normalize_color",
    "project_orthographic",
    "render_executed_scene",
    "render_report_path_for",
    "render_report_to_canonical_json",
    "resolve_palette",
    "save_render",
    "save_render_report",
    "semantic_color",
    "shade_color",
]
