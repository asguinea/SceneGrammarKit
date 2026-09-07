"""Source verification and overlay-policy tests for Batch 2.2."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from scene_grammar_kit.assisted import (
    AnnotationOverlayConfig,
    AnnotationOverlayConfigError,
    NormalizedPoint,
    NormalizedPolygon,
    NormalizedRectangle,
    SourceImageDimensionError,
    SourceImageFormatError,
    SourceImageHashError,
    SourceImageNotFoundError,
    SourceImagePathError,
    SourceImageReference,
    load_and_verify_source_image,
    load_annotation,
    normalized_point_to_pixel,
    overlay_dimensions,
    shape_to_pixels,
)

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"
URBAN_ANNOTATION = FIXTURES / "valid" / "urban_minimal.annotation.json"


def _annotation_for(
    directory: Path,
    image_name: str,
    width: int,
    height: int,
    *,
    sha256: str | None = None,
):
    annotation = load_annotation(URBAN_ANNOTATION)
    source = SourceImageReference(
        image_id="test_image",
        image_path=image_name,
        pixel_width=width,
        pixel_height=height,
        sha256=sha256,
    )
    return replace(annotation, source_image=source), directory / "input.json"


def test_valid_png_loads_and_converts_to_rgba() -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    verified = load_and_verify_source_image(annotation, URBAN_ANNOTATION)
    assert verified.image.mode == "RGBA"
    assert verified.image.size == (480, 320)
    assert verified.image_format == "PNG"
    assert verified.relative_path == "images/urban_minimal.png"


def test_valid_jpeg_loads(tmp_path: Path) -> None:
    image_path = tmp_path / "fixture.jpg"
    Image.new("RGB", (23, 17), (40, 80, 120)).save(
        image_path,
        format="JPEG",
        quality=90,
        optimize=False,
        progressive=False,
    )
    annotation, annotation_path = _annotation_for(tmp_path, "fixture.jpg", 23, 17)
    verified = load_and_verify_source_image(annotation, annotation_path)
    assert verified.image_format == "JPEG"
    assert verified.image.mode == "RGBA"


def test_missing_image_fails_clearly(tmp_path: Path) -> None:
    annotation, annotation_path = _annotation_for(tmp_path, "missing.png", 10, 10)
    with pytest.raises(SourceImageNotFoundError, match="does not exist"):
        load_and_verify_source_image(annotation, annotation_path)


def test_corrupt_image_fails_clearly(tmp_path: Path) -> None:
    (tmp_path / "corrupt.png").write_bytes(b"not an image")
    annotation, annotation_path = _annotation_for(tmp_path, "corrupt.png", 10, 10)
    with pytest.raises(SourceImageFormatError, match="Could not decode"):
        load_and_verify_source_image(annotation, annotation_path)


def test_unsupported_image_format_fails_clearly(tmp_path: Path) -> None:
    Image.new("RGB", (10, 8), (0, 0, 0)).save(tmp_path / "image.bmp", format="BMP")
    annotation, annotation_path = _annotation_for(tmp_path, "image.bmp", 10, 8)
    with pytest.raises(SourceImageFormatError, match="supports PNG and JPEG"):
        load_and_verify_source_image(annotation, annotation_path)


@pytest.mark.parametrize(
    ("width", "height", "message"),
    ((9, 8, "width"), (10, 7, "height")),
)
def test_declared_dimension_mismatch_fails(
    tmp_path: Path,
    width: int,
    height: int,
    message: str,
) -> None:
    Image.new("RGB", (10, 8), (0, 0, 0)).save(tmp_path / "image.png")
    annotation, annotation_path = _annotation_for(tmp_path, "image.png", width, height)
    with pytest.raises(SourceImageDimensionError, match=message):
        load_and_verify_source_image(annotation, annotation_path)


def test_valid_sha256_passes(tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    Image.new("RGB", (10, 8), (1, 2, 3)).save(image_path)
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    annotation, annotation_path = _annotation_for(
        tmp_path, "image.png", 10, 8, sha256=digest
    )
    assert (
        load_and_verify_source_image(annotation, annotation_path).byte_sha256 == digest
    )


def test_invalid_sha256_fails(tmp_path: Path) -> None:
    Image.new("RGB", (10, 8), (1, 2, 3)).save(tmp_path / "image.png")
    annotation, annotation_path = _annotation_for(
        tmp_path, "image.png", 10, 8, sha256="0" * 64
    )
    with pytest.raises(SourceImageHashError, match="does not match"):
        load_and_verify_source_image(annotation, annotation_path)


def test_resolved_path_is_confined_to_annotation_directory() -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    verified = load_and_verify_source_image(annotation, URBAN_ANNOTATION)
    resolved = (
        URBAN_ANNOTATION.parent / Path(annotation.source_image.image_path)
    ).resolve()
    assert resolved.is_relative_to(URBAN_ANNOTATION.parent.resolve())
    assert verified.relative_path == annotation.source_image.image_path


def test_post_resolution_escape_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "escape.png").write_bytes(b"unused")
    annotation, annotation_path = _annotation_for(tmp_path, "escape.png", 10, 8)
    original_resolve = Path.resolve
    outside = tmp_path.parent / "outside.png"

    def controlled_resolve(
        self: Path,
        strict: bool = False,
    ) -> Path:
        if self.name == "escape.png":
            return outside
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", controlled_resolve)
    with pytest.raises(SourceImagePathError, match="escapes"):
        load_and_verify_source_image(annotation, annotation_path)


def test_source_file_handle_is_closed_after_load(tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    Image.new("RGB", (10, 8), (1, 2, 3)).save(image_path)
    annotation, annotation_path = _annotation_for(tmp_path, "image.png", 10, 8)
    verified = load_and_verify_source_image(annotation, annotation_path)
    renamed = tmp_path / "renamed.png"
    image_path.rename(renamed)
    assert renamed.exists()
    assert verified.image.getpixel((0, 0)) == (1, 2, 3, 255)


def test_overlay_config_defaults() -> None:
    config = AnnotationOverlayConfig()
    assert config.maximum_output_dimension == 1600
    assert config.line_width == 3
    assert config.region_fill_opacity == 56
    assert config.instance_fill_opacity == 96
    assert config.draw_parent_links is False
    assert config.draw_legend is True


@pytest.mark.parametrize(
    ("keyword", "value"),
    (
        ("maximum_output_dimension", 0),
        ("line_width", 0),
        ("region_fill_opacity", 256),
        ("instance_fill_opacity", -1),
        ("label_scale", 0),
        ("label_scale", 5),
        ("maximum_output_dimension", 5000),
    ),
)
def test_invalid_overlay_config_values(
    keyword: str,
    value: int,
) -> None:
    with pytest.raises(AnnotationOverlayConfigError):
        AnnotationOverlayConfig(**{keyword: value})


@pytest.mark.parametrize(
    "keyword",
    (
        "draw_region_ids",
        "draw_instance_ids",
        "draw_semantic_labels",
        "draw_depth_zone_labels",
        "draw_repeat_group_links",
        "draw_split_axis_hints",
        "draw_parent_links",
        "draw_legend",
        "transparent_semantic_layer",
    ),
)
def test_boolean_numeric_values_are_rejected(keyword: str) -> None:
    with pytest.raises(AnnotationOverlayConfigError, match="boolean"):
        AnnotationOverlayConfig(**{keyword: 1})


@pytest.mark.parametrize(
    ("point", "size", "expected"),
    (
        (NormalizedPoint(0.0, 0.0), (101, 51), (0, 0)),
        (NormalizedPoint(1.0, 1.0), (101, 51), (100, 50)),
        (NormalizedPoint(0.5, 0.5), (101, 51), (50, 25)),
    ),
)
def test_normalized_point_conversion(
    point: NormalizedPoint,
    size: tuple[int, int],
    expected: tuple[int, int],
) -> None:
    assert normalized_point_to_pixel(point, *size) == expected


def test_rectangle_conversion() -> None:
    rectangle = NormalizedRectangle(0.1, 0.2, 0.8, 0.9)
    assert shape_to_pixels(rectangle, 101, 51) == ((10, 10), (80, 45))


def test_polygon_conversion_preserves_supplied_order() -> None:
    polygon = NormalizedPolygon(
        (
            NormalizedPoint(0.1, 0.2),
            NormalizedPoint(0.8, 0.3),
            NormalizedPoint(0.4, 0.9),
        )
    )
    assert shape_to_pixels(polygon, 101, 51) == (
        (10, 10),
        (80, 15),
        (40, 45),
    )


def test_output_resizing_preserves_aspect_ratio_and_alignment() -> None:
    config = AnnotationOverlayConfig(maximum_output_dimension=300)
    assert overlay_dimensions(1200, 800, config) == (300, 200)
    center = normalized_point_to_pixel(NormalizedPoint(0.5, 0.5), 300, 200)
    assert center == (150, 100)
