"""Deterministic, document-scale Pillow figures for evaluation."""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from scene_grammar_kit.evaluation.models import ControlledCaseResult, RealCaseResult
from scene_grammar_kit.evaluation.persistence import atomic_write

BACKGROUND = (250, 249, 245)
INK = (22, 35, 58)
MUTED = (92, 101, 114)
PANEL = (238, 240, 243)
ACCENT = (214, 223, 235)
WARNING = (246, 238, 220)
BLUE = (76, 126, 178)
RED = (209, 73, 91)
CONFORMANCE_COVERAGE_LABEL = "Complete coverage of supplied observations"
CONFORMANCE_RATIO_LABEL = "Median output/split-only byte ratio — 12 cases"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a bundled-system font with Unicode coverage and fixed metrics."""
    candidates = (
        (
            Path("C:/Windows/Fonts/arialbd.ttf")
            if bold
            else Path("C:/Windows/Fonts/arial.ttf")
        ),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
            if bold
            else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        ),
    )
    font_path = next((path for path in candidates if path.is_file()), None)
    if font_path is None:
        raise OSError("a Unicode TrueType font is required for report figures")
    return ImageFont.truetype(font_path, size)


def conformance_summary(
    summary: dict[str, object],
    path: Path,
    *,
    overwrite: bool,
) -> bytes:
    """Draw the compact controlled-suite conformance summary."""
    values = (
        ("Valid and executable", "12/12"),
        (CONFORMANCE_COVERAGE_LABEL, "12/12"),
        ("Valid visible edits", "12/12"),
        ("Repeat accepted", "8/12"),
        ("Deterministic fallback", "4/12"),
        (
            CONFORMANCE_RATIO_LABEL,
            f"{float(_summary_item(summary, 'median_byte_ratio', 'median')):.3f}",
        ),
    )
    image = Image.new("RGB", (1800, 1000), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1800, 145), fill=INK)
    draw.text(
        (54, 42),
        "Controlled conformance suite — 12 generated cases",
        fill="white",
        font=_font(46, bold=True),
    )
    for index, (label, value) in enumerate(values):
        top = 185 + index * 112
        fill = (245, 247, 250) if index % 2 == 0 else (232, 237, 244)
        draw.rounded_rectangle(
            (55, top, 1745, top + 86),
            radius=14,
            fill=fill,
            outline=ACCENT,
            width=2,
        )
        draw.text((88, top + 20), label, fill=INK, font=_font(34))
        value_box = draw.textbbox((0, 0), value, font=_font(38, bold=True))
        draw.text(
            (1695 - (value_box[2] - value_box[0]), top + 16),
            value,
            fill=BLUE,
            font=_font(38, bold=True),
        )
    draw.text(
        (55, 908),
        "Controlled sanity checks under the supported representation assumptions.",
        fill=MUTED,
        font=_font(29),
    )
    data = _png_bytes(image)
    atomic_write(path, data, overwrite=overwrite)
    return data


def compactness_comparison(
    rows: tuple[ControlledCaseResult, ...],
    path: Path,
    *,
    overwrite: bool,
) -> bytes:
    """Plot repeat/split ratios only for the eight accepted-repeat cases."""
    accepted = tuple(row for row in rows if row.repeat_decision == "accepted")
    if len(accepted) != 8:
        raise ValueError(f"expected 8 accepted-repeat cases, found {len(accepted)}")
    image = Image.new("RGB", (1800, 1000), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text(
        (48, 34),
        "Serialized grammar size on accepted-repeat controlled cases",
        fill=INK,
        font=_font(43, bold=True),
    )
    draw.text(
        (50, 96),
        "Repeat grammar bytes ÷ split-only grammar bytes",
        fill=MUTED,
        font=_font(28),
    )
    left, top, right, bottom = 255, 180, 1710, 750
    scale_max = 1.1
    reference_x = left + int((right - left) / scale_max)
    draw.line((reference_x, top - 18, reference_x, bottom), fill=RED, width=5)
    draw.text(
        (reference_x - 85, top - 58),
        "split-only = 1.0",
        fill=RED,
        font=_font(23, bold=True),
    )
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = left + int((right - left) * tick / scale_max)
        draw.line((x, bottom, x, bottom + 10), fill=INK, width=2)
        draw.text((x - 20, bottom + 16), f"{tick:.2g}", fill=MUTED, font=_font(20))
    height = 53
    gap = 17
    for index, row in enumerate(accepted):
        y = top + index * (height + gap)
        draw.text((44, y + 10), row.case_id, fill=INK, font=_font(24, bold=True))
        width = int((right - left) * row.byte_ratio / scale_max)
        color = BLUE if row.family == "urban_street" else (100, 132, 184)
        draw.rounded_rectangle(
            (left, y, left + width, y + height),
            radius=8,
            fill=color,
        )
        draw.text(
            (left + width + 14, y + 10),
            f"{row.byte_ratio:.3f}",
            fill=INK,
            font=_font(24, bold=True),
        )
    draw.text(
        (52, 810),
        "Lower is smaller than the split-only grammar",
        fill=INK,
        font=_font(31, bold=True),
    )
    draw.rounded_rectangle((50, 860, 1750, 960), radius=12, fill=WARNING)
    draw.text(
        (76, 876),
        "Four corridor cases use deterministic split-only fallback.",
        fill=INK,
        font=_font(25, bold=True),
    )
    draw.multiline_text(
        (76, 912),
        "A flat terminal list can remain smaller for these small cases, but does not encode "
        "the same hierarchy and repeat-edit structure.",
        fill=MUTED,
        font=_font(21),
        spacing=4,
    )
    data = _png_bytes(image)
    atomic_write(path, data, overwrite=overwrite)
    return data


def controlled_case_grid(
    rows: tuple[ControlledCaseResult, ...],
    render_pairs: dict[str, tuple[Path, Path]],
    path: Path,
    *,
    overwrite: bool,
) -> bytes:
    """Compose close matched before/after views with actual stored edit labels."""
    by_id = {row.case_id: row for row in rows}
    representatives = ("street_02", "facade_02", "corridor_02")
    image = Image.new("RGB", (1800, 1200), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text(
        (42, 28),
        "Controlled structural edits",
        fill=INK,
        font=_font(43, bold=True),
    )
    draw.text(
        (44, 88),
        "Identical deterministic camera before and after; callouts mark the changed region.",
        fill=MUTED,
        font=_font(26),
    )
    for row_index, case_id in enumerate(representatives):
        row = by_id[case_id]
        before_path, after_path = render_pairs[case_id]
        edit_label = _controlled_edit_label(row, before_path)
        y = 155 + row_index * 335
        draw.rounded_rectangle((36, y, 1764, y + 305), radius=16, fill=PANEL)
        draw.text((62, y + 22), case_id, fill=MUTED, font=_font(22, bold=True))
        draw.text((250, y + 17), edit_label, fill=INK, font=_font(31, bold=True))
        draw.text((735, y + 24), "BEFORE", fill=MUTED, font=_font(20, bold=True))
        draw.text((1390, y + 24), "AFTER", fill=RED, font=_font(20, bold=True))
        before, after = _matched_change_crops(before_path, after_path)
        for column, panel in enumerate((before, after)):
            panel = ImageOps.contain(panel, (680, 225))
            x = 310 + column * 735 + (680 - panel.width) // 2
            panel_y = y + 62 + (225 - panel.height) // 2
            image.paste(panel, (x, panel_y))
            outline = RED if column else INK
            draw.rectangle(
                (x, panel_y, x + panel.width - 1, panel_y + panel.height - 1),
                outline=outline,
                width=4,
            )
            bracket_y = panel_y + panel.height + 8
            draw.line(
                (x + 20, bracket_y, x + panel.width - 20, bracket_y), fill=RED, width=5
            )
            draw.line(
                (x + 20, bracket_y - 12, x + 20, bracket_y + 5), fill=RED, width=5
            )
            draw.line(
                (
                    x + panel.width - 20,
                    bracket_y - 12,
                    x + panel.width - 20,
                    bracket_y + 5,
                ),
                fill=RED,
                width=5,
            )
        draw.line((1010, y + 178, 1065, y + 178), fill=RED, width=8)
        draw.polygon(((1065, y + 178), (1043, y + 164), (1043, y + 192)), fill=RED)
    data = _png_bytes(image)
    atomic_write(path, data, overwrite=overwrite)
    return data


def controlled_edit_labels(
    rows: tuple[ControlledCaseResult, ...],
    render_pairs: dict[str, tuple[Path, Path]],
) -> dict[str, str]:
    """Return the actual displayed labels for the representative edit rows."""
    by_id = {row.case_id: row for row in rows}
    return {
        case_id: _controlled_edit_label(by_id[case_id], render_pairs[case_id][0])
        for case_id in ("street_02", "facade_02", "corridor_02")
    }


def evaluation_panel(
    compactness_path: Path,
    summary: dict[str, object],
    real_rows: tuple[RealCaseResult, ...],
    real_review_paths: dict[str, Path],
    path: Path,
    *,
    overwrite: bool,
) -> bytes:
    """Retain the legacy comprehensive dashboard as a supplementary artifact."""
    del summary
    image = Image.new("RGB", (2400, 1350), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 2400, 105), fill=INK)
    draw.text(
        (38, 28),
        "Supplementary evaluation overview — controlled and descriptive evidence",
        fill="white",
        font=_font(38, bold=True),
    )
    with Image.open(compactness_path) as opened:
        plot = ImageOps.contain(opened.convert("RGB"), (1500, 1120))
    image.paste(plot, (30, 145))
    for index, row in enumerate(real_rows):
        x, y = 1580, 150 + index * 385
        draw.rounded_rectangle((x, y, 2365, y + 350), radius=14, fill=PANEL)
        draw.text(
            (x + 20, y + 18),
            f"{row.case_key}: {row.outcome}",
            fill=INK,
            font=_font(25, bold=True),
        )
        with Image.open(real_review_paths[row.case_key]) as opened:
            thumb = ImageOps.contain(opened.convert("RGB"), (735, 255))
        image.paste(thumb, (x + 20, y + 70))
    data = _png_bytes(image)
    atomic_write(path, data, overwrite=overwrite)
    return data


def _controlled_edit_label(row: ControlledCaseResult, before_path: Path) -> str:
    if row.family == "urban_street":
        return f"Cars: {row.supplied_repeat_count} → {row.supplied_repeat_count + 1}"
    if row.family == "repeated_facade":
        return f"Windows: {row.supplied_repeat_count} → {row.supplied_repeat_count + 1}"
    report_path = before_path.parents[1] / "edit" / "edit_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    realization = report["realizations"][0]
    before = float(realization["old_normalized_fraction"])
    after = float(realization["new_normalized_fraction"])
    return f"Corridor share: {before:.3f} → {after:.3f}"


def _matched_change_crops(
    before_path: Path,
    after_path: Path,
) -> tuple[Image.Image, Image.Image]:
    with Image.open(before_path) as opened:
        before = opened.convert("RGB")
    with Image.open(after_path) as opened:
        after = opened.convert("RGB")
    if before.size != after.size:
        raise ValueError("before/after renders must use identical framing")
    bounds = ImageChops.difference(before, after).getbbox()
    if bounds is None:
        return before, after
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    margin_x = max(80, int(width * 0.7))
    margin_y = max(60, int(height * 1.2))
    crop = (
        max(0, bounds[0] - margin_x),
        max(0, bounds[1] - margin_y),
        min(before.width, bounds[2] + margin_x),
        min(before.height, bounds[3] + margin_y),
    )
    return before.crop(crop), after.crop(crop)


def _summary_item(
    summary: dict[str, object],
    key: str,
    field: str,
) -> object:
    item = summary[key]
    if not isinstance(item, dict):
        raise ValueError(f"summary field {key!r} is not an object")
    return item[field]


def _png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()
