"""CPU-only semantic painter-renderer behavior tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scene_grammar_kit.geometry import ExecutedScene, execute_grammar
from scene_grammar_kit.grammar import load_grammar
from scene_grammar_kit.rendering import (
    CameraPreset,
    RenderConfig,
    render_executed_scene,
)

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"


def execute_fixture(name: str) -> ExecutedScene:
    """Load and execute one shared grammar fixture."""
    return execute_grammar(load_grammar(FIXTURES / name))


@pytest.mark.parametrize("preset", list(CameraPreset))
def test_all_camera_presets_render_exact_requested_dimensions(
    preset: CameraPreset,
) -> None:
    """Every camera produces a final-size RGBA image with visible boxes."""
    result = render_executed_scene(
        execute_fixture("valid_nested_urban.json"),
        RenderConfig(
            width=480,
            height=320,
            camera_preset=preset,
            supersampling=2,
        ),
    )
    assert result.image.size == (480, 320)
    assert result.image.mode == "RGBA"
    assert result.report.camera_preset is preset
    assert result.report.box_count_rendered == 6
    assert result.report.visible_face_count >= 6


def test_box_rendering_has_visible_faces_and_semantic_color() -> None:
    """One box yields three isometric faces retaining its semantic hue."""
    result = render_executed_scene(
        execute_fixture("valid_terminal.json"),
        RenderConfig(
            width=400,
            height=300,
            semantic_palette={"road": (240, 40, 50, 255)},
            supersampling=1,
            show_ground=False,
        ),
    )
    assert result.report.box_count_rendered == 1
    assert result.report.visible_face_count == 3
    colors = result.image.getcolors(maxcolors=result.image.width * result.image.height)
    assert colors is not None
    non_background = [pixel for _, pixel in colors if pixel != (246, 248, 251, 255)]
    assert non_background
    assert max(pixel[0] for pixel in non_background) >= 170
    assert max(pixel[1] for pixel in non_background) < 100


def test_edges_toggle_changes_output_deterministically() -> None:
    """Edges can be disabled without changing geometry/report face counts."""
    scene = execute_fixture("valid_terminal.json")
    with_edges = render_executed_scene(
        scene,
        RenderConfig(width=400, height=300, show_edges=True, supersampling=1),
    )
    without_edges = render_executed_scene(
        scene,
        RenderConfig(width=400, height=300, show_edges=False, supersampling=1),
    )
    assert with_edges.image.tobytes() != without_edges.image.tobytes()
    assert (
        with_edges.report.visible_face_count == without_edges.report.visible_face_count
    )


def test_plane_uses_only_positive_y_proxy_face() -> None:
    """Top view renders one plane polygon without adding box side faces."""
    result = render_executed_scene(
        execute_fixture("terminal_types.json"),
        RenderConfig(
            width=480,
            height=320,
            camera_preset="top",
            show_ground=False,
            supersampling=1,
        ),
    )
    assert result.report.box_count_rendered == 1
    assert result.report.plane_count_rendered == 1
    assert result.report.visible_face_count == 2
    assert "ground" in result.report.palette_mapping


def test_front_view_reports_edge_on_proxy_plane_as_not_drawn() -> None:
    """The positive-y proxy has zero projected area in the canonical front view."""
    result = render_executed_scene(
        execute_fixture("terminal_types.json"),
        RenderConfig(
            width=480,
            height=320,
            camera_preset="front",
            show_ground=False,
            supersampling=1,
        ),
    )
    assert result.report.box_count_rendered == 1
    assert result.report.plane_count_rendered == 0
    assert result.report.visible_face_count == 1


def test_empty_scene_produces_valid_background_image_and_report() -> None:
    """A fully empty grammar draws no geometry but remains a valid PNG source."""
    result = render_executed_scene(
        execute_fixture("valid_empty_scene.json"),
        RenderConfig(
            width=320,
            height=240,
            show_ground=False,
            supersampling=1,
        ),
    )
    assert result.report.primitive_count_considered == 0
    assert result.report.empty_count_skipped == 1
    assert result.report.visible_face_count == 0
    assert result.image.getcolors(maxcolors=1) == [(320 * 240, (246, 248, 251, 255))]


def test_ground_and_bounds_toggles_change_pixels_stably() -> None:
    """Debug guides are optional deterministic overlays outside scene data."""
    scene = execute_fixture("valid_empty_scene.json")
    plain = render_executed_scene(
        scene,
        RenderConfig(
            width=360,
            height=280,
            show_ground=False,
            show_bounds=False,
            supersampling=1,
        ),
    )
    ground = render_executed_scene(
        scene,
        RenderConfig(
            width=360,
            height=280,
            show_ground=True,
            show_bounds=False,
            supersampling=1,
        ),
    )
    bounds = render_executed_scene(
        scene,
        RenderConfig(
            width=360,
            height=280,
            show_ground=False,
            show_bounds=True,
            supersampling=1,
        ),
    )
    assert plain.image.tobytes() != ground.image.tobytes()
    assert plain.image.tobytes() != bounds.image.tobytes()
    assert (
        ground.image.tobytes()
        == render_executed_scene(
            scene,
            RenderConfig(
                width=360,
                height=280,
                show_ground=True,
                show_bounds=False,
                supersampling=1,
            ),
        ).image.tobytes()
    )


def test_transparent_background_has_zero_alpha_outside_scene() -> None:
    """Transparent mode affects only the backdrop, not semantic geometry."""
    result = render_executed_scene(
        execute_fixture("valid_terminal.json"),
        RenderConfig(
            width=400,
            height=300,
            transparent_background=True,
            show_ground=False,
            supersampling=1,
        ),
    )
    assert result.image.getpixel((0, 0))[3] == 0
    assert result.image.getextrema()[3][1] == 255


def test_repeated_rendering_and_primitive_reordering_are_stable() -> None:
    """Painter tie-breaks depend on stable IDs rather than tuple insertion order."""
    scene = execute_fixture("valid_nested_urban.json")
    config = RenderConfig(width=500, height=340, supersampling=1)
    first = render_executed_scene(scene, config)
    second = render_executed_scene(scene, config)
    reordered_scene = replace(
        scene,
        primitives=tuple(reversed(scene.primitives)),
    )
    reordered = render_executed_scene(reordered_scene, config)
    assert first.image.tobytes() == second.image.tobytes()
    assert first.image.tobytes() == reordered.image.tobytes()
    assert first.report == second.report == reordered.report


def test_scene_content_stays_inside_root_projection_margin() -> None:
    """The isometric render leaves untouched pixels around every image boundary."""
    result = render_executed_scene(
        execute_fixture("valid_nested_urban.json"),
        RenderConfig(width=600, height=400, image_padding=50, supersampling=1),
    )
    background = (246, 248, 251, 255)
    assert all(result.image.getpixel((x, 0)) == background for x in range(600))
    assert all(result.image.getpixel((x, 399)) == background for x in range(600))
    assert all(result.image.getpixel((0, y)) == background for y in range(400))
    assert all(result.image.getpixel((599, y)) == background for y in range(400))
