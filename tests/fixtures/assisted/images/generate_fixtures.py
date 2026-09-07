"""Regenerate original deterministic source-image fixtures for Batch 2.2."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def _urban() -> Image.Image:
    image = Image.new("RGB", (480, 320), (164, 205, 231))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 70, 479, 165), fill=(151, 157, 166))
    for x in range(28, 456, 58):
        draw.rectangle((x, 88, x + 26, 121), fill=(226, 226, 210))
        draw.rectangle((x + 4, 93, x + 22, 117), fill=(78, 116, 146))
    draw.polygon(((120, 319), (164, 78), (326, 78), (360, 319)), fill=(63, 67, 74))
    draw.polygon(((0, 319), (0, 80), (164, 78), (120, 319)), fill=(193, 171, 127))
    draw.polygon(((360, 319), (326, 78), (479, 80), (479, 319)), fill=(193, 171, 127))
    for x, y in ((178, 190), (240, 182), (302, 174)):
        draw.rectangle((x, y, x + 48, y + 30), fill=(189, 53, 47))
        draw.rectangle((x + 9, y - 9, x + 36, y + 2), fill=(205, 64, 56))
        draw.ellipse((x + 5, y + 23, x + 16, y + 34), fill=(25, 27, 31))
        draw.ellipse((x + 34, y + 23, x + 45, y + 34), fill=(25, 27, 31))
    draw.rectangle((0, 263, 479, 319), fill=(88, 105, 82))
    return image


def _facade() -> Image.Image:
    image = Image.new("RGB", (480, 360), (188, 215, 232))
    draw = ImageDraw.Draw(image)
    draw.polygon(((58, 316), (86, 43), (403, 36), (432, 316)), fill=(108, 129, 165))
    draw.polygon(((58, 316), (432, 316), (468, 359), (17, 359)), fill=(137, 139, 142))
    for row in range(3):
        for column in range(5):
            left = 110 + column * 56 + row * 2
            top = 76 + row * 70
            draw.rectangle((left, top, left + 30, top + 42), fill=(225, 221, 194))
            draw.rectangle((left + 4, top + 4, left + 26, top + 38), fill=(58, 89, 119))
    draw.line(((58, 316), (86, 43), (403, 36), (432, 316)), fill=(58, 69, 91), width=4)
    return image


def main() -> None:
    """Write fixed metadata-free PNGs and confined byte-identical copies."""
    root = Path(__file__).resolve().parent
    valid_images = root.parent / "valid" / "images"
    valid_images.mkdir(parents=True, exist_ok=True)
    for name, image in (
        ("urban_minimal.png", _urban()),
        ("facade_polygon.png", _facade()),
    ):
        canonical = root / name
        image.save(
            canonical,
            format="PNG",
            compress_level=9,
            optimize=False,
        )
        valid_images.joinpath(name).write_bytes(canonical.read_bytes())


if __name__ == "__main__":
    main()
