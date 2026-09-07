"""Deterministic orchestration for the three frozen Open Images cases."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from scene_grammar_kit.assisted import construct_assisted_scene
from scene_grammar_kit.demo.runner import compare_scene_builds
from scene_grammar_kit.geometry.serialization import (
    atomic_write_bytes,
    atomic_write_text,
)
from scene_grammar_kit.grammar import grammar_to_canonical_json, load_grammar
from scene_grammar_kit.paths import OutputDirectoryError, create_output_directory
from scene_grammar_kit.real_cases.open_images import (
    ALLOWED_IMAGE_LICENSES,
    OPEN_IMAGES_ANNOTATION_LICENSE,
    sha256_file,
)
from scene_grammar_kit.rendering.palette import resolve_palette

CASE_KEYS = ("canonical_success", "moderate_case", "limitation_case")
REAL_CASE_POLICY_VERSION = "0.1"


class RealCaseBuildError(RuntimeError):
    """A frozen-case input, provenance, or deterministic-build failure."""


def refresh_review_figures(
    input_directory: Path,
    results_directory: Path,
) -> None:
    """Recompose review-only figures without rebuilding constructor artifacts."""
    inputs = Path(input_directory).resolve()
    results = Path(results_directory).resolve()
    for case_key in CASE_KEYS:
        case_input = inputs / case_key
        case_output = results / case_key
        if case_key != "limitation_case":
            _build_presentation_overlay(
                case_input / "annotation.json",
                case_output / "review" / "presentation_overlay.png",
            )
        _build_panel(
            case_key,
            case_input,
            case_output,
            results / "review" / f"{case_key}.png",
        )
    _build_overview(results, CASE_KEYS)


def build_open_images_cases(
    output_directory: Path,
    *,
    input_directory: Path | None = None,
    cases: tuple[str, ...] = CASE_KEYS,
    overwrite: bool = False,
    verify_determinism: bool = False,
) -> dict[str, Any]:
    """Build selected frozen cases through the unmodified Batch 2.6 constructor."""
    repository = Path(__file__).resolve().parents[3]
    source_root = (
        repository / "inputs" / "real_cases"
        if input_directory is None
        else Path(input_directory).expanduser().resolve()
    )
    _validate_selection(cases)
    try:
        root = create_output_directory(
            Path(output_directory).expanduser().resolve(),
            allow_nonempty=overwrite,
        )
    except OutputDirectoryError as exc:
        raise RealCaseBuildError(str(exc)) from exc
    (root / "review").mkdir(exist_ok=True)
    reports: list[dict[str, Any]] = []
    determinism: dict[str, dict[str, Any]] = {}
    for case_key in cases:
        case_input = source_root / case_key
        case_output = root / case_key
        report = _build_case(case_key, case_input, case_output, overwrite=overwrite)
        panel = root / "review" / f"{case_key}.png"
        _build_panel(case_key, case_input, case_output, panel)
        reports.append(report)
        determinism[case_key] = _determinism_result(False)
        if verify_determinism:
            determinism[case_key] = _verify_case_determinism(
                case_key, case_input, case_output, panel, root
            )
    _build_overview(root, cases)
    summary = _write_summaries(root, reports, determinism)
    return summary


def _build_case(
    case_key: str,
    input_root: Path,
    output_root: Path,
    *,
    overwrite: bool,
) -> dict[str, Any]:
    manifest = _load_manifest(input_root / "case_manifest.json", case_key)
    source = input_root / manifest["source_image_path"]
    annotation = input_root / manifest["annotation_path"]
    config = input_root / manifest["construction_config_path"]
    _verify_source(source, manifest)
    result = construct_assisted_scene(
        annotation,
        config,
        output_root,
        overwrite=overwrite,
        verify_image=True,
        verify_execution=True,
        render_width=1200,
        render_height=800,
        camera=manifest["primary_camera"],
        apply_default_edit=True,
    )
    audit_overlay = output_root / "review" / "audit_overlay.png"
    atomic_write_bytes(
        (output_root / "review" / "annotation_overlay.png").read_bytes(),
        audit_overlay,
        overwrite=True,
        create_parents=True,
    )
    if case_key != "limitation_case":
        _build_presentation_overlay(
            annotation,
            output_root / "review" / "presentation_overlay.png",
        )
    atomic_write_bytes(
        (input_root / "case_manifest.json").read_bytes(),
        output_root / "input" / "case_manifest.json",
        overwrite=True,
        create_parents=True,
    )
    constructor = json.loads((output_root / "construction_report.json").read_text())
    _verify_constructor_provenance(output_root, result, constructor, source)
    report = {
        "real_case_policy_version": REAL_CASE_POLICY_VERSION,
        "case_key": case_key,
        "case_role": manifest["case_role"],
        "expected_outcome": manifest["expected_outcome"],
        "outcome": _outcome(case_key, constructor),
        "image_id": manifest["image_id"],
        "source_image_sha256": sha256_file(source),
        "license_url": manifest["license_url"],
        "annotation_license_url": manifest["annotation_license_url"],
        "attribution": {
            "author": manifest["author"],
            "title": manifest["title"],
            "original_landing_page": manifest["original_landing_page"],
        },
        "annotation_sha256": constructor["annotation_sha256"],
        "construction_config_sha256": constructor["construction_config_sha256"],
        "constructor_policy_version": constructor["constructor_policy_version"],
        "constructor_success": constructor["success"],
        "primary_grammar_type": constructor["primary_grammar_type"],
        "primary_grammar_sha256": constructor["primary_grammar_sha256"],
        "primary_primitive_count": len(result.primary_execution.primitives),
        "supplied_repeat_group_count": constructor["supplied_repeat_group_count"],
        "accepted_repeat_group_count": constructor["accepted_repeat_group_count"],
        "fallback_repeat_group_count": constructor["fallback_repeat_group_count"],
        "edit_decision": constructor["edit_decision"],
        "construction_warnings": constructor["construction_warnings"],
        "known_representation_challenges": manifest["known_representation_challenges"],
        "limitation": (
            "Curved and receding facade geometry is reduced to axis-aligned "
            "bounding-box proxies; the semantic result is deterministic but "
            "does not preserve curvature or perspective."
            if case_key == "limitation_case"
            else None
        ),
        "provenance": {
            "dataset_supplied": manifest["dataset_supplied_information"],
            "project_supplied": manifest["researcher_supplied_information"],
            "scene_grammar_kit_derived": manifest[
                "scene_grammar_kit_derived_information"
            ],
            "not_inferred": constructor["explicitly_not_inferred"],
        },
        "artifact_paths": [
            *constructor["artifact_relative_paths"],
            "review/audit_overlay.png",
            *(
                ["review/presentation_overlay.png"]
                if case_key != "limitation_case"
                else []
            ),
        ],
        "provenance_checks": {
            "source_bytes_preserved": True,
            "grammar_hash_from_constructor": True,
            "render_from_saved_constructor_grammar": True,
            "edit_from_constructor_primary_grammar": True,
        },
    }
    _write_json(output_root / "real_case_report.json", report)
    atomic_write_text(
        _case_readme(report),
        output_root / "REAL_CASE_README.md",
        overwrite=True,
    )
    return report


def _load_manifest(path: Path, case_key: str) -> dict[str, Any]:
    if not path.is_file():
        raise RealCaseBuildError(f"missing frozen-case manifest: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "dataset_name",
        "dataset_version",
        "split",
        "image_id",
        "source_image_sha256",
        "original_landing_page",
        "author",
        "license_url",
        "annotation_license_url",
        "case_role",
        "privacy_review",
        "dataset_supplied_information",
        "researcher_supplied_information",
        "scene_grammar_kit_derived_information",
    )
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise RealCaseBuildError(
            f"{case_key} attribution/provenance fields missing: {', '.join(missing)}"
        )
    if data["case_role"] != case_key:
        raise RealCaseBuildError(f"{case_key} case_role mismatch")
    if data["license_url"] not in ALLOWED_IMAGE_LICENSES:
        raise RealCaseBuildError(f"{case_key} image license is not permitted")
    if data["annotation_license_url"] != OPEN_IMAGES_ANNOTATION_LICENSE:
        raise RealCaseBuildError(f"{case_key} annotation license mismatch")
    return data


def _verify_source(path: Path, manifest: dict[str, Any]) -> None:
    if not path.is_file():
        raise RealCaseBuildError(f"frozen source image is missing: {path}")
    actual = sha256_file(path)
    if actual != manifest["source_image_sha256"]:
        raise RealCaseBuildError(
            f"frozen source SHA-256 mismatch: expected "
            f"{manifest['source_image_sha256']}, got {actual}"
        )


def _verify_constructor_provenance(
    root: Path,
    result: Any,
    report: dict[str, Any],
    source: Path,
) -> None:
    primary = root / "primary" / "grammar.json"
    canonical = grammar_to_canonical_json(result.primary_grammar).encode()
    if primary.read_bytes() != canonical:
        raise RealCaseBuildError(
            "saved primary grammar differs from constructor result"
        )
    grammar_hash = hashlib.sha256(canonical).hexdigest()
    if grammar_hash != report["primary_grammar_sha256"]:
        raise RealCaseBuildError("primary grammar hash was not constructor-derived")
    render_report = json.loads((root / "primary" / "render.json").read_text())
    if render_report["executed_scene_grammar_sha256"] != grammar_hash:
        raise RealCaseBuildError("primary render does not come from saved grammar")
    if (root / "input" / "source_image.jpg").read_bytes() != source.read_bytes():
        raise RealCaseBuildError("constructor input source bytes changed")
    if report["edit_decision"]["applied"]:
        before = root / "edit" / "grammar_before.json"
        after = root / "edit" / "grammar_after.json"
        edit_report = json.loads((root / "edit" / "edit_report.json").read_text())
        if before.read_bytes() != primary.read_bytes():
            raise RealCaseBuildError("edit does not start from primary grammar")
        edited = grammar_to_canonical_json(load_grammar(after)).encode()
        if after.read_bytes() != edited:
            raise RealCaseBuildError("saved edited grammar is not canonical")
        if hashlib.sha256(edited).hexdigest() != edit_report["edited_grammar_sha256"]:
            raise RealCaseBuildError("edited grammar hash mismatch")


def _outcome(case_key: str, report: dict[str, Any]) -> str:
    if case_key == "limitation_case":
        return "degraded_success"
    if report["fallback_repeat_group_count"]:
        return "success_with_repeat_fallback"
    return "success"


def _build_panel(
    case_key: str, input_root: Path, output_root: Path, target: Path
) -> None:
    manifest = json.loads((input_root / "case_manifest.json").read_text())
    items = [
        ("Single input image", input_root / manifest["source_image_path"]),
        (
            (
                "Supplied structure"
                if case_key != "limitation_case"
                else "Audit annotation overlay"
            ),
            (
                output_root / "review" / "presentation_overlay.png"
                if case_key != "limitation_case"
                else output_root / "review" / "audit_overlay.png"
            ),
        ),
        ("Structured-scene proxy", output_root / "primary" / "render.png"),
    ]
    canvas = Image.new("RGB", (2400, 700), "#f4f1ea")
    draw = ImageDraw.Draw(canvas)
    title_font = _font(23, bold=True)
    body_font = _font(19)
    attribution_font = _font(17)
    for index, (label, path) in enumerate(items):
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            if index == 2:
                image = _tight_proxy_crop(image)
            fitted = ImageOps.contain(image, (570, 540))
        x = index * 600 + 15 + (570 - fitted.width) // 2
        y = 72 + (540 - fitted.height) // 2
        canvas.paste(fitted, (x, y))
        draw.text(
            (index * 600 + 16, 42),
            label,
            fill="#17233d",
            font=title_font,
        )
    if case_key == "limitation_case":
        x = 1818
        draw.rectangle((x, 72, 2385, 612), fill="#fff8e8", outline="#d17a22", width=3)
        limitation = (
            "Axis-aligned proxy limitation\n\n"
            "The curved, receding facade is approximated by\n"
            "rectangular regions.\n\n"
            "Curvature and projective foreshortening are\n"
            "not preserved."
        )
        draw.multiline_text(
            (x + 24, 110),
            limitation,
            fill="#5a3415",
            font=body_font,
            spacing=12,
        )
        draw.text(
            (1816, 42),
            "Representation limitation",
            fill="#17233d",
            font=title_font,
        )
    else:
        constructor = json.loads(
            (output_root / "construction_report.json").read_text(encoding="utf-8")
        )
        annotation = json.loads(
            (input_root / manifest["annotation_path"]).read_text(encoding="utf-8")
        )
        before_count = len(annotation["repeat_groups"][0]["member_instance_ids"])
        noun = "Windows" if case_key == "canonical_success" else "Cars"
        edit_label = (
            f"{noun}: {before_count} → "
            f"{constructor['edit_decision']['requested_value']}"
        )
        edit_path = output_root / "edit" / "after.png"
        with Image.open(edit_path) as opened:
            original = opened.convert("RGB")
            image = _tight_proxy_crop(original)
            fitted = ImageOps.contain(image, (570, 540))
        x = 1815 + (570 - fitted.width) // 2
        y = 72 + (540 - fitted.height) // 2
        canvas.paste(fitted, (x, y))
        draw.text(
            (1816, 42),
            f"Explicit edit | {edit_label}",
            fill="#17233d",
            font=title_font,
        )
        semantic = "window" if case_key == "canonical_success" else "car"
        inset = _semantic_inset(original, semantic)
        if inset is not None:
            inset = ImageOps.contain(inset, (280, 118))
            panel_left, panel_top = 2072, 80
            draw.rounded_rectangle(
                (panel_left - 12, panel_top - 10, 2372, 224),
                radius=10,
                fill="#fff4f5",
                outline="#d1495b",
                width=4,
            )
            canvas.paste(
                inset,
                (
                    panel_left + (280 - inset.width) // 2,
                    panel_top + (118 - inset.height) // 2,
                ),
            )
            draw.text(
                (2072, 202),
                f"{semantic.title()} count detail",
                fill="#8c2638",
                font=attribution_font,
            )
        draw.line((1850, 570, 2320, 570), fill="#d1495b", width=10)
        draw.polygon(((2320, 570), (2288, 548), (2288, 592)), fill="#d1495b")
        draw.text((1900, 582), edit_label, fill="#8c2638", font=body_font)
        if case_key == "canonical_success":
            draw.rounded_rectangle(
                (1215, 548, 1780, 612),
                radius=8,
                fill="#fff4f5",
                outline="#d1495b",
                width=3,
            )
            draw.text(
                (1235, 566),
                "Supplied repeat band: 5 windows",
                fill="#8c2638",
                font=_font(19, bold=True),
            )
        _draw_semantic_legend(draw, case_key, (1230, 428))
    attribution = f"Open Images {manifest['image_id']}"
    source_line = f"{manifest['author']} · CC BY 2.0"
    draw.rectangle((0, 626, 2400, 700), fill="#17233d")
    draw.text((18, 635), attribution, fill="white", font=attribution_font)
    draw.text((18, 669), source_line, fill="#d7e1f2", font=attribution_font)
    _save_png(canvas, target)


def _build_overview(root: Path, cases: tuple[str, ...]) -> None:
    panels = []
    for key in cases:
        with Image.open(root / "review" / f"{key}.png") as image:
            panels.append(image.convert("RGB").copy())
    overview = Image.new("RGB", (2400, 700 * len(panels)), "white")
    for index, panel in enumerate(panels):
        overview.paste(panel, ((2400 - panel.width) // 2, index * 700))
    _save_png(overview, root / "review" / "three_case_overview.png")


def _build_presentation_overlay(annotation_path: Path, target: Path) -> None:
    annotation = json.loads(Path(annotation_path).read_text(encoding="utf-8"))
    source = Path(annotation_path).parent / annotation["source_image"]["image_path"]
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    scale = min(1.0, 1200 / max(image.size))
    if scale < 1.0:
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    palette = resolve_palette(
        tuple(
            item["semantic_class"]
            for item in annotation["regions"] + annotation["instances"]
        )
    )
    fill = Image.new("RGBA", image.size, (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(fill, "RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    font = _font(22, bold=True)
    labeled: set[str] = set()
    for region in annotation["regions"]:
        shape = region["shape"]
        if shape["type"] != "rectangle":
            continue
        box = _normalized_box(shape, image.size)
        color = palette[region["semantic_class"]]
        fill_draw.rectangle(box, fill=(*color[:3], 34))
        draw.rectangle(box, outline=(*color[:3], 255), width=7)
        semantic = region["semantic_class"]
        if semantic not in labeled and region["role"] != "open_space":
            draw.rounded_rectangle(
                (box[0] + 4, box[1] + 4, box[0] + 150, box[1] + 34),
                radius=5,
                fill=(*color[:3], 225),
            )
            draw.text(
                (box[0] + 9, box[1] + 7),
                semantic,
                fill="white",
                font=font,
            )
            labeled.add(semantic)
    image = Image.alpha_composite(image, fill)
    draw = ImageDraw.Draw(image, "RGBA")
    instances = {item["instance_id"]: item for item in annotation["instances"]}
    for instance in annotation["instances"]:
        box = _normalized_box(instance["shape"], image.size)
        color = palette[instance["semantic_class"]]
        draw.rectangle(box, fill=(*color[:3], 62), outline=(*color[:3], 255), width=7)
    for group in annotation["repeat_groups"]:
        centers = []
        for member in group["member_instance_ids"]:
            box = _normalized_box(instances[member]["shape"], image.size)
            centers.append(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
        draw.line(centers, fill=(190, 45, 196, 255), width=7)
        for center in centers:
            draw.ellipse(
                (center[0] - 7, center[1] - 7, center[0] + 7, center[1] + 7),
                fill=(190, 45, 196, 255),
            )
    entries = _legend_entries_from_annotation(annotation)
    columns = 2 if len(entries) > 3 else 1
    rows = (len(entries) + columns - 1) // columns
    legend_width = 520 if columns == 2 else 330
    legend_height = 42 + rows * 34
    left, top = image.width - legend_width - 14, image.height - legend_height - 14
    draw.rounded_rectangle(
        (left, top, image.width - 14, image.height - 14),
        radius=10,
        fill=(23, 35, 61, 225),
    )
    draw.text((left + 18, top + 10), "Semantic regions", fill="white", font=font)
    for index, (label, semantic) in enumerate(entries):
        column = index // rows
        row = index % rows
        x = left + 18 + column * 250
        y = top + 45 + row * 34
        color = palette[semantic]
        draw.rectangle((x, y, x + 28, y + 20), fill=(*color[:3], 255))
        draw.text((x + 38, y - 3), label, fill="white", font=_font(17))
    draw.line(
        (left + legend_width - 92, top + 25, left + legend_width - 32, top + 25),
        fill=(190, 45, 196),
        width=7,
    )
    _save_png(image.convert("RGB"), target)


def semantic_legend_entries(case_key: str) -> tuple[tuple[str, str], ...]:
    """Return display labels paired with the renderer semantic palette key."""
    if case_key == "canonical_success":
        return (
            ("Upper facade", "facade"),
            ("Repeated windows", "window"),
            ("Lower facade", "facade"),
        )
    if case_key == "moderate_case":
        return (
            ("Building", "building"),
            ("Parking", "parking"),
            ("Road", "road"),
            ("Sidewalk", "sidewalk"),
            ("Curb", "curb"),
            ("Cars", "car"),
        )
    return ()


def _legend_entries_from_annotation(
    annotation: dict[str, Any],
) -> tuple[tuple[str, str], ...]:
    semantics = {
        item["semantic_class"]
        for item in annotation["regions"] + annotation["instances"]
    }
    if "car" in semantics:
        return semantic_legend_entries("moderate_case")
    return semantic_legend_entries("canonical_success")


def _draw_semantic_legend(
    draw: ImageDraw.ImageDraw,
    case_key: str,
    origin: tuple[int, int],
) -> None:
    entries = semantic_legend_entries(case_key)
    if not entries:
        return
    palette = resolve_palette(tuple(semantic for _, semantic in entries))
    x, y = origin
    columns = 2 if len(entries) > 3 else 1
    rows = (len(entries) + columns - 1) // columns
    width = 540 if columns == 2 else 310
    height = 40 + rows * 34
    draw.rounded_rectangle(
        (x, y, x + width, y + height),
        radius=9,
        fill="#17233d",
        outline="#d7e1f2",
        width=2,
    )
    draw.text(
        (x + 14, y + 10), "Semantic proxy", fill="white", font=_font(16, bold=True)
    )
    for index, (label, semantic) in enumerate(entries):
        column = index // rows
        row = index % rows
        item_x = x + 14 + column * 260
        item_y = y + 42 + row * 34
        color = palette[semantic]
        draw.rectangle(
            (item_x, item_y, item_x + 24, item_y + 20),
            fill=color[:3],
            outline="white",
        )
        draw.text((item_x + 34, item_y - 2), label, fill="white", font=_font(15))


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
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


def _normalized_box(
    shape: dict[str, Any], size: tuple[int, int]
) -> tuple[int, int, int, int]:
    return (
        round(float(shape["u_min"]) * (size[0] - 1)),
        round(float(shape["v_min"]) * (size[1] - 1)),
        round(float(shape["u_max"]) * (size[0] - 1)),
        round(float(shape["v_max"]) * (size[1] - 1)),
    )


def _tight_proxy_crop(image: Image.Image) -> Image.Image:
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    difference = ImageChops.difference(image, background).convert("L")
    difference = difference.point(lambda value: 255 if value > 12 else 0)
    bounds = difference.getbbox()
    if bounds is None:
        return image
    margin_x = max(12, round((bounds[2] - bounds[0]) * 0.08))
    margin_y = max(12, round((bounds[3] - bounds[1]) * 0.08))
    return image.crop(
        (
            max(0, bounds[0] - margin_x),
            max(0, bounds[1] - margin_y),
            min(image.width, bounds[2] + margin_x),
            min(image.height, bounds[3] + margin_y),
        )
    )


def _semantic_inset(image: Image.Image, semantic: str) -> Image.Image | None:
    target = resolve_palette((semantic,))[semantic][:3]
    pixels = image.load()
    selected = [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if sum(abs(int(pixels[x, y][index]) - int(target[index])) for index in range(3))
        < 75
    ]
    if not selected:
        return None
    left = min(item[0] for item in selected)
    top = min(item[1] for item in selected)
    right = max(item[0] for item in selected) + 1
    bottom = max(item[1] for item in selected) + 1
    margin_x = max(14, round((right - left) * 0.15))
    margin_y = max(14, round((bottom - top) * 0.5))
    crop = image.crop(
        (
            max(0, left - margin_x),
            max(0, top - margin_y),
            min(image.width, right + margin_x),
            min(image.height, bottom + margin_y),
        )
    )
    return crop.resize(
        (max(1, crop.width * 3), max(1, crop.height * 3)),
        Image.Resampling.NEAREST,
    )


def _verify_case_determinism(
    case_key: str,
    input_root: Path,
    first: Path,
    first_panel: Path,
    output_root: Path,
) -> dict[str, Any]:
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{case_key}.verify-", dir=output_root.parent)
    ).resolve()
    removed = False
    try:
        second = temporary / case_key
        _build_case(case_key, input_root, second, overwrite=False)
        second_panel = temporary / f"{case_key}.png"
        _build_panel(case_key, input_root, second, second_panel)
        evidence = compare_scene_builds(first, second)
        unstable_json = {"runtime_report.json", "artifact_index.json"}
        json_mismatches = tuple(
            item
            for item in evidence.canonical_json_mismatches
            if item not in unstable_json
        )
        report_equal = (first / "real_case_report.json").read_bytes() == (
            second / "real_case_report.json"
        ).read_bytes()
        panel_bytes_equal = first_panel.read_bytes() == second_panel.read_bytes()
        with Image.open(first_panel) as left, Image.open(second_panel) as right:
            panel_pixels_equal = (
                left.size == right.size
                and left.convert("RGBA").tobytes() == right.convert("RGBA").tobytes()
            )
        result = {
            "requested": True,
            "performed": True,
            "canonical_json_equal": not json_mismatches,
            "png_pixels_equal": not evidence.png_pixel_mismatches
            and panel_pixels_equal,
            "png_bytes_equal": not evidence.png_byte_mismatches and panel_bytes_equal,
            "glb_bytes_equal": not evidence.glb_byte_mismatches,
            "glb_structures_equal": not evidence.glb_structure_mismatches,
            "case_reports_equal": report_equal,
            "review_panels_equal": panel_bytes_equal and panel_pixels_equal,
            "source_bytes_equal": (
                (first / "input" / "source_image.jpg").read_bytes()
                == (second / "input" / "source_image.jpg").read_bytes()
            ),
            "temporary_directory_removed": False,
            "mismatches": sorted(
                {
                    *json_mismatches,
                    *evidence.png_pixel_mismatches,
                    *evidence.png_byte_mismatches,
                    *evidence.glb_byte_mismatches,
                    *evidence.glb_structure_mismatches,
                }
            ),
        }
    finally:
        if (
            temporary.parent == output_root.parent.resolve()
            and temporary.name.startswith(f".{case_key}.verify-")
        ):
            shutil.rmtree(temporary)
            removed = not temporary.exists()
    result["temporary_directory_removed"] = removed
    if not all(
        value
        for key, value in result.items()
        if key.endswith("_equal") or key == "temporary_directory_removed"
    ):
        raise RealCaseBuildError(f"{case_key} determinism verification failed")
    return result


def _write_summaries(
    root: Path,
    reports: list[dict[str, Any]],
    determinism: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    summary = {
        "real_case_policy_version": REAL_CASE_POLICY_VERSION,
        "success": True,
        "case_order": [item["case_key"] for item in reports],
        "cases": reports,
        "determinism": determinism,
        "annotation_assistance_disclosure": (
            "All semantic regions, hierarchy, depth zones, split hints, and "
            "repeat memberships are project-supplied; no automatic pixel "
            "segmentation or monocular reconstruction is claimed."
        ),
    }
    _write_json(root / "real_case_summary.json", summary)
    fields = (
        "case_key",
        "image_id",
        "outcome",
        "primary_grammar_type",
        "accepted_repeat_group_count",
        "fallback_repeat_group_count",
        "primary_primitive_count",
        "license_url",
    )
    rows = [[str(item[field]) for field in fields] for item in reports]
    csv_path = root / "real_case_summary.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)
    lines = [
        "# Open Images real-case summary",
        "",
        "All three demonstrations are **Annotation-assisted**.",
        "",
        "| Case | Image ID | Outcome | Primary grammar | Accepted / fallback repeats |",
        "|---|---|---|---|---|",
    ]
    for item in reports:
        lines.append(
            f"| {item['case_key']} | `{item['image_id']}` | {item['outcome']} | "
            f"{item['primary_grammar_type']} | "
            f"{item['accepted_repeat_group_count']} / "
            f"{item['fallback_repeat_group_count']} |"
        )
    atomic_write_text(
        "\n".join(lines) + "\n",
        root / "real_case_summary.md",
        overwrite=True,
    )
    return summary


def _case_readme(report: dict[str, Any]) -> str:
    return (
        f"# {report['case_key']}\n\n"
        "Annotation-assisted Open Images demonstration built by the unchanged "
        "Batch 2.6 constructor.\n\n"
        f"- Image ID: `{report['image_id']}`\n"
        f"- Outcome: `{report['outcome']}`\n"
        f"- Primary grammar: `{report['primary_grammar_type']}`\n"
        f"- License: {report['license_url']}\n"
    )


def _save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    image.save(temporary, format="PNG", optimize=False, compress_level=9)
    atomic_write_bytes(
        temporary.read_bytes(), path, overwrite=True, create_parents=True
    )
    temporary.unlink()


def _write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        path,
        overwrite=True,
        create_parents=True,
    )


def _validate_selection(cases: tuple[str, ...]) -> None:
    if not cases:
        raise RealCaseBuildError("at least one case must be selected")
    invalid = [item for item in cases if item not in CASE_KEYS]
    if invalid or len(set(cases)) != len(cases):
        raise RealCaseBuildError("invalid or duplicate real-case selection")


def _determinism_result(requested: bool) -> dict[str, Any]:
    return {"requested": requested, "performed": False}
