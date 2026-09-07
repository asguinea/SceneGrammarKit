"""Deterministic, official-resource candidate acquisition and review records."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from scene_grammar_kit.assisted import construct_assisted_scene
from scene_grammar_kit.geometry.serialization import (
    atomic_write_bytes,
    atomic_write_text,
)
from scene_grammar_kit.paths import OutputDirectoryError, create_output_directory
from scene_grammar_kit.real_cases import build_open_images_cases
from scene_grammar_kit.real_cases.open_images import (
    OFFICIAL_URLS,
    OpenImagesBoundingBox,
    OpenImagesImage,
    download_cached,
    load_bounding_boxes,
    load_class_names,
    load_human_labels,
    load_image_metadata,
    sha256_file,
)
from scene_grammar_kit.rendering.palette import resolve_palette

RESELECTION_POLICY_VERSION = "0.1"
FAMILIES = ("facade", "street")
GATE_NAMES = (
    "three_second_correspondence",
    "supported_terminal_organization",
    "no_identity_defining_unsupported_feature",
    "two_visible_semantic_partitions",
    "visible_repeats_when_used",
    "unmistakable_edit_at_quarter_scale",
    "no_dominant_proxy_slab",
    "scene_matched_camera",
    "deliberately_abstract_correspondence",
    "story_survives_label_removal",
)
METADATA_FILENAMES = {
    "image_metadata": "validation-images-with-rotation.csv",
    "class_descriptions": "class-descriptions.csv",
    "human_labels": "validation-human-labels.csv",
    "bounding_boxes": "validation-bboxes.csv",
}
PROBLEM_LABELS = frozenset(
    {
        "Castle",
        "Church",
        "Skyscraper",
        "Tower",
    }
)
FACADE_LABELS = frozenset({"Building", "House", "Window"})
STREET_LABELS = frozenset(
    {
        "Building",
        "Car",
        "Land vehicle",
        "Parking meter",
        "Road",
        "Street light",
        "Traffic light",
        "Vehicle",
    }
)


class ReselectionError(RuntimeError):
    """Candidate acquisition or curation failed without changing frozen cases."""


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    """One attribution-complete, decoded Open Images candidate."""

    image_id: str
    title: str
    author: str
    license: str
    original_landing_page: str
    official_mirror_url: str
    width: int
    height: int
    sha256: str
    relevant_labels: tuple[str, ...]
    family: str
    preliminary_suitability_score: float
    rejection_flags: tuple[str, ...]
    rationale: str
    box_counts: dict[str, int]
    occluded_relevant_box_count: int


@dataclass(frozen=True, slots=True)
class VisualGateRecord:
    """Complete ten-question visual acceptance record for one preview."""

    image_id: str
    family: str
    camera: str
    gates: dict[str, bool]
    notes: dict[str, str]

    @property
    def passed(self) -> bool:
        return all(self.gates.get(name) is True for name in GATE_NAMES)


@dataclass(frozen=True, slots=True)
class ReselectionResult:
    """Paths and counts produced by one deterministic selection pass."""

    output_directory: Path
    candidate_count: int
    facade_count: int
    street_count: int
    shortlisted_count: int
    frozen_roles: tuple[str, ...]


def run_case_reselection(
    output_directory: Path,
    *,
    cache_directory: Path | None = None,
    candidate_count: int = 120,
    freeze_best: bool = False,
    verify_determinism: bool = False,
    overwrite: bool = True,
) -> ReselectionResult:
    """Acquire, rank, and record an official Open Images validation subset."""
    if candidate_count < 10:
        raise ReselectionError("candidate_count must be at least 10")
    repository = Path(__file__).resolve().parents[3]
    cache = (
        repository / ".local-temp" / "open-images-metadata"
        if cache_directory is None
        else Path(cache_directory).expanduser().resolve()
    )
    image_cache = (
        repository / ".local-temp" / "open-images-candidates"
        if cache_directory is None
        else cache / "images"
    )
    try:
        output = create_output_directory(
            Path(output_directory).expanduser().resolve(),
            allow_nonempty=overwrite,
        )
    except OutputDirectoryError as exc:
        raise ReselectionError(str(exc)) from exc
    metadata_paths = _acquire_metadata(cache)
    class_names = load_class_names(metadata_paths["class_descriptions"])
    metadata = load_image_metadata(metadata_paths["image_metadata"])
    labels = load_human_labels(metadata_paths["human_labels"], class_names)
    boxes = load_bounding_boxes(metadata_paths["bounding_boxes"])
    ranked = _rank_candidates(metadata, labels, boxes, class_names, candidate_count)
    records = _download_and_describe(
        ranked, metadata, labels, boxes, class_names, image_cache
    )
    if len(records) != candidate_count:
        raise ReselectionError(
            f"expected {candidate_count} decoded candidates, got {len(records)}"
        )
    manifest = {
        "candidate_count": len(records),
        "dataset": "Open Images",
        "dataset_version": "V7",
        "preferred_split": "validation",
        "reselection_policy_version": RESELECTION_POLICY_VERSION,
        "official_resources": dict(sorted(OFFICIAL_URLS.items())),
        "records": [asdict(item) for item in records],
    }
    _write_json(output / "candidate_manifest.json", manifest)
    build_contact_sheets(records, image_cache, output)
    _write_selection_report(output, records)
    curated_path = Path(__file__).with_name("curated_shortlist.json")
    shortlist_count = 0
    frozen_roles: tuple[str, ...] = ()
    if curated_path.is_file():
        shortlist_count, frozen_roles = _build_curated_previews(
            curated_path,
            records,
            image_cache,
            output,
            repository,
            freeze_best=freeze_best,
            verify_determinism=verify_determinism,
        )
    elif freeze_best:
        raise ReselectionError(
            "freeze requested before a reviewed curated_shortlist.json exists"
        )
    return ReselectionResult(
        output_directory=output,
        candidate_count=len(records),
        facade_count=sum(item.family == "facade" for item in records),
        street_count=sum(item.family == "street" for item in records),
        shortlisted_count=shortlist_count,
        frozen_roles=frozen_roles,
    )


def load_candidate_manifest(path: Path) -> tuple[CandidateRecord, ...]:
    """Parse and validate a deterministic candidate manifest."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = []
    for raw in data.get("records", []):
        normalized = dict(raw)
        normalized["relevant_labels"] = tuple(normalized["relevant_labels"])
        normalized["rejection_flags"] = tuple(normalized["rejection_flags"])
        records.append(CandidateRecord(**normalized))
    if data.get("candidate_count") != len(records):
        raise ReselectionError("candidate manifest count does not match its records")
    if any(item.family not in FAMILIES for item in records):
        raise ReselectionError("candidate manifest contains an unknown family")
    if len({item.image_id for item in records}) != len(records):
        raise ReselectionError("candidate manifest contains duplicate image IDs")
    return tuple(records)


def validate_visual_gate(record: VisualGateRecord) -> None:
    """Reject incomplete, undocumented, or camera-incompatible gate records."""
    missing_gates = [name for name in GATE_NAMES if name not in record.gates]
    missing_notes = [
        name for name in GATE_NAMES if not record.notes.get(name, "").strip()
    ]
    extra = sorted(set(record.gates).difference(GATE_NAMES))
    if missing_gates or missing_notes or extra:
        raise ReselectionError(
            "incomplete visual gate record: "
            f"missing_gates={missing_gates}, missing_notes={missing_notes}, extra={extra}"
        )
    if record.family == "facade" and record.camera != "front":
        raise ReselectionError("facade visual gate requires the front camera")
    if record.family == "street" and record.camera not in {
        "isometric",
        "top",
    }:
        raise ReselectionError("street visual gate requires top or isometric camera")


def build_contact_sheets(
    records: Sequence[CandidateRecord],
    image_directory: Path,
    output_directory: Path,
) -> tuple[Path, ...]:
    """Create two stable, large-thumbnail sheets per candidate family."""
    output = Path(output_directory)
    paths: list[Path] = []
    for family in FAMILIES:
        family_records = [item for item in records if item.family == family]
        chunks = _balanced_chunks(family_records, 2)
        for index, chunk in enumerate(chunks, start=1):
            target = output / f"{family}_candidates_{index:02d}.png"
            image = _contact_sheet_image(family, chunk, Path(image_directory))
            _save_png(image, target)
            paths.append(target)
    return tuple(paths)


def _acquire_metadata(cache: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for key, filename in METADATA_FILENAMES.items():
        target = cache / filename
        paths[key] = download_cached(OFFICIAL_URLS[key], target)
    return paths


def _rank_candidates(
    metadata: Mapping[str, OpenImagesImage],
    labels: Mapping[str, Iterable[str]],
    boxes: Mapping[str, Sequence[OpenImagesBoundingBox]],
    class_names: Mapping[str, str],
    candidate_count: int,
) -> tuple[tuple[str, str], ...]:
    per_family = candidate_count // 2
    remainder = candidate_count - (per_family * 2)
    desired = {"facade": per_family + remainder, "street": per_family}
    ranked: dict[str, list[tuple[float, str]]] = {family: [] for family in FAMILIES}
    for image_id, item in metadata.items():
        if item.split != "validation" or not item.attribution_complete:
            continue
        display_labels = set(labels.get(image_id, ()))
        counts = Counter(
            class_names.get(box.label_name, box.label_name)
            for box in boxes.get(image_id, ())
        )
        if (
            "Building" in display_labels
            and counts["Window"] >= 6
            and not display_labels.intersection(PROBLEM_LABELS)
        ):
            relevant = sum(
                1
                for box in boxes.get(image_id, ())
                if class_names.get(box.label_name) in FACADE_LABELS
            )
            occluded = sum(
                1
                for box in boxes.get(image_id, ())
                if box.is_occluded and class_names.get(box.label_name) in FACADE_LABELS
            )
            score = (
                min(counts["Window"], 80) * 1.5
                + min(counts["Building"], 4) * 4
                - 35 * (occluded / max(relevant, 1))
                - min(counts["Tree"], 20) * 0.6
            )
            ranked["facade"].append((round(score, 6), image_id))
        vehicle_count = counts["Car"] + counts["Land vehicle"] + counts["Vehicle"]
        repeated_count = (
            vehicle_count + counts["Street light"] + counts["Parking meter"]
        )
        if (
            "Building" in display_labels
            and repeated_count >= 3
            and (
                "Car" in display_labels
                or "Street light" in display_labels
                or "Road" in display_labels
            )
            and not display_labels.intersection(PROBLEM_LABELS)
        ):
            relevant = sum(
                1
                for box in boxes.get(image_id, ())
                if class_names.get(box.label_name) in STREET_LABELS
            )
            occluded = sum(
                1
                for box in boxes.get(image_id, ())
                if box.is_occluded and class_names.get(box.label_name) in STREET_LABELS
            )
            score = (
                min(vehicle_count, 15) * 5
                + min(counts["Street light"], 10) * 4
                + min(counts["Building"], 5) * 3
                + (8 if "Road" in display_labels else 0)
                - 30 * (occluded / max(relevant, 1))
                - min(counts["Person"], 20) * 0.5
            )
            ranked["street"].append((round(score, 6), image_id))
    selected: list[tuple[str, str]] = []
    used: set[str] = set()
    for family in FAMILIES:
        ordered = sorted(ranked[family], key=lambda pair: (-pair[0], pair[1]))
        for _, image_id in ordered:
            if image_id in used:
                continue
            selected.append((family, image_id))
            used.add(image_id)
            if sum(item[0] == family for item in selected) == desired[family]:
                break
        if sum(item[0] == family for item in selected) != desired[family]:
            raise ReselectionError(
                f"official metadata yielded too few {family} candidates"
            )
    return tuple(selected)


def _download_and_describe(
    ranked: Sequence[tuple[str, str]],
    metadata: Mapping[str, OpenImagesImage],
    labels: Mapping[str, Iterable[str]],
    boxes: Mapping[str, Sequence[OpenImagesBoundingBox]],
    class_names: Mapping[str, str],
    image_cache: Path,
) -> tuple[CandidateRecord, ...]:
    image_cache.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                download_cached,
                metadata[image_id].official_mirror_url,
                image_cache / f"{image_id}.jpg",
            ): (family, image_id)
            for family, image_id in ranked
        }
        for future in as_completed(futures):
            family, image_id = futures[future]
            try:
                future.result()
            except Exception as exc:
                failures.append(f"{family}:{image_id}:{exc}")
    if failures:
        raise ReselectionError(
            "official candidate download failures: " + "; ".join(sorted(failures))
        )
    records: list[CandidateRecord] = []
    for family, image_id in ranked:
        item = metadata[image_id]
        path = image_cache / f"{image_id}.jpg"
        with Image.open(path) as opened:
            opened.verify()
        with Image.open(path) as opened:
            width, height = ImageOps.exif_transpose(opened).size
        display_counts = Counter(
            class_names.get(box.label_name, box.label_name)
            for box in boxes.get(image_id, ())
        )
        relevant_set = FACADE_LABELS if family == "facade" else STREET_LABELS
        relevant_labels = tuple(
            sorted(set(labels.get(image_id, ())).intersection(relevant_set))
        )
        relevant_boxes = [
            box
            for box in boxes.get(image_id, ())
            if class_names.get(box.label_name, box.label_name) in relevant_set
        ]
        occluded = sum(box.is_occluded for box in relevant_boxes)
        flags = _preliminary_flags(
            family,
            width,
            height,
            set(labels.get(image_id, ())),
            display_counts,
            occluded,
            len(relevant_boxes),
        )
        score = _record_score(
            family,
            width,
            height,
            display_counts,
            occluded,
            len(relevant_boxes),
            flags,
        )
        rationale = _rationale(
            family, display_counts, occluded, len(relevant_boxes), flags
        )
        records.append(
            CandidateRecord(
                image_id=image_id,
                title=item.title,
                author=item.author,
                license=item.license_url,
                original_landing_page=item.landing_page,
                official_mirror_url=item.official_mirror_url,
                width=width,
                height=height,
                sha256=sha256_file(path),
                relevant_labels=relevant_labels,
                family=family,
                preliminary_suitability_score=score,
                rejection_flags=flags,
                rationale=rationale,
                box_counts={
                    key: display_counts[key]
                    for key in sorted(display_counts)
                    if display_counts[key]
                    and key in relevant_set.union({"Tree", "Person"})
                },
                occluded_relevant_box_count=occluded,
            )
        )
    return tuple(records)


def _preliminary_flags(
    family: str,
    width: int,
    height: int,
    labels: set[str],
    counts: Counter[str],
    occluded: int,
    relevant_count: int,
) -> tuple[str, ...]:
    flags: list[str] = []
    if width < 640 or height < 400:
        flags.append("low_resolution")
    if labels.intersection(PROBLEM_LABELS):
        flags.append("unsupported_architectural_identity_label")
    if occluded / max(relevant_count, 1) > 0.25:
        flags.append("metadata_occlusion_over_25_percent")
    if family == "facade" and counts["Window"] < 6:
        flags.append("too_few_visible_window_boxes")
    if (
        family == "street"
        and (
            counts["Car"]
            + counts["Land vehicle"]
            + counts["Vehicle"]
            + counts["Street light"]
        )
        < 3
    ):
        flags.append("too_few_repeated_layout_elements")
    return tuple(sorted(flags))


def _record_score(
    family: str,
    width: int,
    height: int,
    counts: Counter[str],
    occluded: int,
    relevant_count: int,
    flags: Sequence[str],
) -> float:
    resolution = min(width * height / (1024 * 768), 2.0) * 10
    repetition = (
        min(counts["Window"], 40) * 1.2
        if family == "facade"
        else min(
            counts["Car"]
            + counts["Land vehicle"]
            + counts["Vehicle"]
            + counts["Street light"],
            20,
        )
        * 3
    )
    occlusion_penalty = 30 * occluded / max(relevant_count, 1)
    return round(resolution + repetition - occlusion_penalty - 20 * len(flags), 3)


def _rationale(
    family: str,
    counts: Counter[str],
    occluded: int,
    relevant_count: int,
    flags: Sequence[str],
) -> str:
    if family == "facade":
        evidence = f"{counts['Window']} window and {counts['Building']} building boxes"
    else:
        vehicles = counts["Car"] + counts["Land vehicle"] + counts["Vehicle"]
        evidence = f"{vehicles} vehicle and {counts['Street light']} street-light boxes"
    status = (
        "retained for visual review"
        if not flags
        else "retained in the evaluated pool with preliminary rejection flags"
    )
    return (
        f"Official annotations provide {evidence}; "
        f"{occluded}/{relevant_count} relevant boxes are marked occluded; {status}."
    )


def _contact_sheet_image(
    family: str,
    records: Sequence[CandidateRecord],
    image_directory: Path,
) -> Image.Image:
    columns = 5
    rows = max(1, (len(records) + columns - 1) // columns)
    cell_width = 440
    cell_height = 350
    header_height = 90
    canvas = Image.new(
        "RGB",
        (columns * cell_width, header_height + rows * cell_height),
        "#f4f1ea",
    )
    draw = ImageDraw.Draw(canvas)
    title_font = ImageFont.load_default(size=27)
    text_font = ImageFont.load_default(size=16)
    small_font = ImageFont.load_default(size=14)
    draw.rectangle((0, 0, canvas.width, header_height), fill="#17233d")
    draw.text(
        (24, 17),
        f"Open Images V7 validation - {family} candidates",
        fill="white",
        font=title_font,
    )
    draw.text(
        (24, 55),
        "Preliminary metadata ranking only; visual gates are recorded in shortlisted previews.",
        fill="#d7e1f2",
        font=small_font,
    )
    for index, record in enumerate(records):
        column = index % columns
        row = index // columns
        x0 = column * cell_width
        y0 = header_height + row * cell_height
        path = image_directory / f"{record.image_id}.jpg"
        with Image.open(path) as opened:
            fitted = ImageOps.contain(
                ImageOps.exif_transpose(opened).convert("RGB"),
                (400, 230),
            )
        canvas.paste(
            fitted,
            (x0 + 20 + (400 - fitted.width) // 2, y0 + 12 + (230 - fitted.height) // 2),
        )
        flag = (
            " | flags=" + ",".join(record.rejection_flags)
            if record.rejection_flags
            else ""
        )
        lines = (
            f"{record.image_id} | score={record.preliminary_suitability_score:.3f}",
            f"{record.width}x{record.height} | {', '.join(record.relevant_labels)}",
            f"{record.title[:48]}",
            f"CC BY | {record.author[:40]}{flag}",
        )
        for line_index, line in enumerate(lines):
            draw.text(
                (x0 + 20, y0 + 250 + line_index * 22),
                line,
                fill="#17233d",
                font=text_font if line_index == 0 else small_font,
            )
    return canvas


def _balanced_chunks(
    records: Sequence[CandidateRecord], count: int
) -> tuple[tuple[CandidateRecord, ...], ...]:
    base, remainder = divmod(len(records), count)
    chunks = []
    start = 0
    for index in range(count):
        size = base + (1 if index < remainder else 0)
        chunks.append(tuple(records[start : start + size]))
        start += size
    return tuple(chunks)


def _write_selection_report(output: Path, records: Sequence[CandidateRecord]) -> None:
    lines = [
        "# Representation-aligned Open Images selection",
        "",
        "This deterministic pool uses only official Open Images V7 validation metadata,",
        "official CVDF image storage, and attribution-complete Creative Commons images.",
        "Preliminary scores rank annotation evidence; they are not visual-acceptance",
        "decisions and are not model accuracy measurements.",
        "",
    ]
    for family in FAMILIES:
        family_records = [item for item in records if item.family == family]
        lines.extend(
            [
                f"## {family.title()} family",
                "",
                f"- Evaluated: {len(family_records)}",
                f"- Without preliminary metadata flags: {sum(not item.rejection_flags for item in family_records)}",
                f"- Contact sheets: `{family}_candidates_01.png`, `{family}_candidates_02.png`",
                "",
            ]
        )
    lines.extend(
        [
            "## Hard visual gate",
            "",
            "Only separately shortlisted previews receive the ten-question visual gate.",
            "No candidate is frozen unless every gate passes.",
            "",
        ]
    )
    atomic_write_text(
        "\n".join(lines),
        output / "selection_report.md",
        overwrite=True,
        create_parents=True,
    )


def _build_curated_previews(
    curated_path: Path,
    records: Sequence[CandidateRecord],
    image_cache: Path,
    output: Path,
    repository: Path,
    *,
    freeze_best: bool,
    verify_determinism: bool,
) -> tuple[int, tuple[str, ...]]:
    data = json.loads(curated_path.read_text(encoding="utf-8"))
    curated = data.get("records", [])
    by_id = {item.image_id: item for item in records}
    if len(curated) < 10:
        raise ReselectionError("curated shortlist must contain at least ten records")
    family_counts = Counter(item.get("family") for item in curated)
    if any(family_counts[family] < 5 for family in FAMILIES):
        raise ReselectionError(
            "curated shortlist requires five facade and five street records"
        )
    if len({item.get("image_id") for item in curated}) != len(curated):
        raise ReselectionError("curated shortlist contains duplicate image IDs")
    selected: list[
        tuple[dict[str, Any], CandidateRecord, dict[str, Any], dict[str, Any]]
    ] = []
    preview_records: list[dict[str, Any]] = []
    for item in curated:
        image_id = item.get("image_id")
        record = by_id.get(image_id)
        if record is None:
            raise ReselectionError(
                f"curated image {image_id!r} is absent from the evaluated pool"
            )
        if record.family != item.get("family"):
            raise ReselectionError(f"curated family mismatch for {image_id}")
        gate = _gate_from_curation(item)
        validate_visual_gate(gate)
        annotation = _annotation_from_curation(record, item)
        config = _construction_config()
        preview = output / "previews" / image_id
        input_root = preview / "input"
        source_bytes = (image_cache / f"{image_id}.jpg").read_bytes()
        atomic_write_bytes(
            source_bytes,
            input_root / "source.jpg",
            overwrite=True,
            create_parents=True,
        )
        _write_json(input_root / "annotation.json", annotation)
        _write_json(input_root / "construction.json", config)
        constructor_root = preview / "constructor"
        result = construct_assisted_scene(
            input_root / "annotation.json",
            input_root / "construction.json",
            constructor_root,
            overwrite=True,
            verify_image=True,
            verify_execution=True,
            render_width=800,
            render_height=533,
            camera=item["camera"],
            apply_default_edit=True,
        )
        del result
        build_presentation_overlay(
            input_root / "annotation.json",
            preview / "presentation_overlay.png",
        )
        constructor_report = json.loads(
            (constructor_root / "construction_report.json").read_text(encoding="utf-8")
        )
        if not constructor_report["success"]:
            raise ReselectionError(f"shortlisted constructor failed for {image_id}")
        edit = constructor_report["edit_decision"]
        edit_label = _edit_label(item["family"], item["layout"]["repeat_count"], edit)
        _build_preview_panel(
            record,
            item,
            gate,
            preview,
            edit_label,
        )
        gate_data = {
            "camera": gate.camera,
            "family": gate.family,
            "gates": gate.gates,
            "image_id": gate.image_id,
            "notes": gate.notes,
            "overall": "PASS" if gate.passed else "FAIL",
            "visual_gate_policy_version": RESELECTION_POLICY_VERSION,
        }
        _write_json(preview / "visual_gate.json", gate_data)
        preview_report = {
            "annotation_sha256": constructor_report["annotation_sha256"],
            "camera": item["camera"],
            "construction_config_sha256": constructor_report[
                "construction_config_sha256"
            ],
            "constructor_policy_version": constructor_report[
                "constructor_policy_version"
            ],
            "edit_label": edit_label,
            "family": item["family"],
            "image_id": image_id,
            "manual_grammar_substitution": False,
            "primary_grammar_sha256": constructor_report["primary_grammar_sha256"],
            "preview_constructed_once": True,
            "selected_role": item.get("selected_role"),
            "visual_gate": gate_data["overall"],
        }
        _write_json(preview / "preview_report.json", preview_report)
        preview_records.append(preview_report)
        if item.get("selected_role") is not None:
            selected.append((item, record, annotation, config))
    _write_json(
        output / "shortlist_manifest.json",
        {
            "count": len(preview_records),
            "records": preview_records,
            "shortlist_policy_version": data.get("shortlist_policy_version"),
        },
    )
    frozen_roles: tuple[str, ...] = ()
    if freeze_best:
        frozen_roles = _freeze_selected(
            selected,
            repository,
            image_cache,
            verify_determinism=verify_determinism,
            candidate_count=len(records),
        )
    return len(preview_records), frozen_roles


def _gate_from_curation(item: Mapping[str, Any]) -> VisualGateRecord:
    failed = set(item.get("failed_gates", []))
    unknown = sorted(failed.difference(GATE_NAMES))
    if unknown:
        raise ReselectionError(f"unknown visual gates: {unknown}")
    note = str(item.get("visual_note", "")).strip()
    gates = {name: name not in failed for name in GATE_NAMES}
    notes = {
        name: f"{'PASS' if gates[name] else 'FAIL'} — {note}" for name in GATE_NAMES
    }
    return VisualGateRecord(
        image_id=str(item["image_id"]),
        family=str(item["family"]),
        camera=str(item["camera"]),
        gates=gates,
        notes=notes,
    )


def _annotation_from_curation(
    record: CandidateRecord,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    if item["family"] == "facade":
        return _facade_annotation(record, item["layout"])
    return _street_annotation(record, item["layout"])


def _facade_annotation(
    record: CandidateRecord,
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    u_min, u_max, v_min, v_max = layout["facade_bounds"]
    _, _, band_v_min, band_v_max = layout["window_band"]
    count = int(layout["repeat_count"])
    start = float(layout["repeat_start"])
    width = float(layout["repeat_width"])
    gap = float(layout["repeat_gap"])
    repeat_v_min, repeat_v_max = layout["repeat_v"]
    instances = []
    members = []
    for index in range(count):
        instance_id = f"window_{index + 1}"
        member_u_min = start + index * (width + gap)
        instances.append(
            {
                "attributes": {
                    "annotation_source": "manually_authored_regularized_visible_window"
                },
                "depth_zone": "midground",
                "instance_id": instance_id,
                "order_hint": index,
                "parent_region_id": "window_band",
                "repeat_group_id": "facade_windows",
                "semantic_class": "window",
                "shape": {
                    "type": "rectangle",
                    "u_max": round(member_u_min + width, 6),
                    "u_min": round(member_u_min, 6),
                    "v_max": repeat_v_max,
                    "v_min": repeat_v_min,
                },
                "terminal_geometry": "box",
            }
        )
        members.append(instance_id)
    regions = [
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "foreground",
            "region_id": "foreground_ground",
            "role": "open_space",
            "semantic_class": "foreground",
            "shape": {
                "type": "rectangle",
                "u_max": 1.0,
                "u_min": 0.0,
                "v_max": 1.0,
                "v_min": max(v_max, 0.88),
            },
            "terminal_geometry": "empty",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "midground",
            "region_id": "facade_layout",
            "role": "structural_region",
            "semantic_class": "facade",
            "shape": {
                "type": "rectangle",
                "u_max": u_max,
                "u_min": u_min,
                "v_max": v_max,
                "v_min": v_min,
            },
            "split_axis_hint": "y",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "midground",
            "order_hint": 2,
            "parent_region_id": "facade_layout",
            "region_id": "parapet",
            "role": "terminal_region",
            "semantic_class": "facade",
            "shape": {
                "type": "rectangle",
                "u_max": u_max,
                "u_min": u_min,
                "v_max": band_v_min,
                "v_min": v_min,
            },
            "terminal_geometry": "box",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "midground",
            "order_hint": 1,
            "parent_region_id": "facade_layout",
            "region_id": "window_band",
            "role": "terminal_region",
            "semantic_class": "facade",
            "shape": {
                "type": "rectangle",
                "u_max": u_max,
                "u_min": u_min,
                "v_max": band_v_max,
                "v_min": band_v_min,
            },
            "terminal_geometry": "empty",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "midground",
            "order_hint": 0,
            "parent_region_id": "facade_layout",
            "region_id": "facade_base",
            "role": "terminal_region",
            "semantic_class": "facade",
            "shape": {
                "type": "rectangle",
                "u_max": u_max,
                "u_min": u_min,
                "v_max": v_max,
                "v_min": band_v_max,
            },
            "terminal_geometry": "box",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "background",
            "region_id": "sky",
            "role": "terminal_region",
            "semantic_class": "sky",
            "shape": {
                "type": "rectangle",
                "u_max": 1.0,
                "u_min": 0.0,
                "v_max": max(v_min, 0.22),
                "v_min": 0.0,
            },
            "terminal_geometry": "plane",
        },
    ]
    return _annotation_document(
        record,
        f"Representation-aligned regular facade shortlist {record.image_id}.",
        regions,
        instances,
        [
            {
                "allow_fallback_to_individuals": True,
                "axis_hint": "x",
                "member_instance_ids": members,
                "note": (
                    "Membership and regularized visible boxes are manually supplied; "
                    "SceneGrammarKit derives repeat acceptance, count, and spacing."
                ),
                "repeat_group_id": "facade_windows",
                "semantic_class": "window",
            }
        ],
    )


def _street_annotation(
    record: CandidateRecord,
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    road_u_min, road_u_max, road_v_min, road_v_max = layout["road_bounds"]
    parking_u_min, parking_u_max, parking_v_min, parking_v_max = layout[
        "parking_bounds"
    ]
    building_u_min, building_u_max, building_v_min, building_v_max = layout[
        "building_bounds"
    ]
    count = int(layout["repeat_count"])
    start = float(layout["repeat_start"])
    width = float(layout["repeat_width"])
    gap = float(layout["repeat_gap"])
    repeat_v_min, repeat_v_max = layout["repeat_v"]
    members = []
    instances = []
    for index in range(count):
        instance_id = f"car_{index + 1}"
        member_u_min = start + index * (width + gap)
        members.append(instance_id)
        instances.append(
            {
                "attributes": {
                    "annotation_source": "manually_authored_regularized_visible_car"
                },
                "depth_zone": "midground",
                "instance_id": instance_id,
                "order_hint": index,
                "parent_region_id": "parking_lane",
                "repeat_group_id": "parked_cars",
                "semantic_class": "car",
                "shape": {
                    "type": "rectangle",
                    "u_max": round(member_u_min + width, 6),
                    "u_min": round(member_u_min, 6),
                    "v_max": repeat_v_max,
                    "v_min": repeat_v_min,
                },
                "terminal_geometry": "box",
            }
        )
    left_boundary = road_u_min + (road_u_max - road_u_min) * 0.18
    right_boundary = road_u_min + (road_u_max - road_u_min) * 0.82
    regions = [
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "foreground",
            "region_id": "street_layout",
            "role": "structural_region",
            "semantic_class": "road",
            "shape": {
                "type": "rectangle",
                "u_max": road_u_max,
                "u_min": road_u_min,
                "v_max": road_v_max,
                "v_min": road_v_min,
            },
            "split_axis_hint": "x",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "foreground",
            "order_hint": 0,
            "parent_region_id": "street_layout",
            "region_id": "left_sidewalk",
            "role": "terminal_region",
            "semantic_class": "sidewalk",
            "shape": {
                "type": "rectangle",
                "u_max": left_boundary,
                "u_min": road_u_min,
                "v_max": road_v_max,
                "v_min": road_v_min,
            },
            "terminal_geometry": "plane",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "foreground",
            "order_hint": 1,
            "parent_region_id": "street_layout",
            "region_id": "road",
            "role": "terminal_region",
            "semantic_class": "road",
            "shape": {
                "type": "rectangle",
                "u_max": right_boundary,
                "u_min": left_boundary,
                "v_max": road_v_max,
                "v_min": road_v_min,
            },
            "terminal_geometry": "plane",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "foreground",
            "order_hint": 2,
            "parent_region_id": "street_layout",
            "region_id": "right_curb",
            "role": "terminal_region",
            "semantic_class": "curb",
            "shape": {
                "type": "rectangle",
                "u_max": road_u_max,
                "u_min": right_boundary,
                "v_max": road_v_max,
                "v_min": road_v_min,
            },
            "terminal_geometry": "plane",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "midground",
            "region_id": "parking_lane",
            "role": "terminal_region",
            "semantic_class": "parking",
            "shape": {
                "type": "rectangle",
                "u_max": parking_u_max,
                "u_min": parking_u_min,
                "v_max": parking_v_max,
                "v_min": parking_v_min,
            },
            "terminal_geometry": "plane",
        },
        {
            "attributes": {"annotation_source": "manually_authored"},
            "depth_zone": "background",
            "region_id": "building_mass",
            "role": "terminal_region",
            "semantic_class": "building",
            "shape": {
                "type": "rectangle",
                "u_max": building_u_max,
                "u_min": building_u_min,
                "v_max": building_v_max,
                "v_min": building_v_min,
            },
            "terminal_geometry": "box",
        },
    ]
    return _annotation_document(
        record,
        f"Representation-aligned structured street shortlist {record.image_id}.",
        regions,
        instances,
        [
            {
                "allow_fallback_to_individuals": True,
                "axis_hint": "x",
                "member_instance_ids": members,
                "note": (
                    "Five representative visible parked-car boxes and ordering "
                    "are manually supplied; repeat acceptance remains constructor-derived."
                ),
                "repeat_group_id": "parked_cars",
                "semantic_class": "car",
            }
        ],
    )


def _annotation_document(
    record: CandidateRecord,
    description: str,
    regions: list[dict[str, Any]],
    instances: list[dict[str, Any]],
    repeat_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "annotation_notes": [
            "Project-authored simplified regions and repeat membership were supplied before constructor review.",
            "This is annotation assistance, not automatic pixel inference or true 3D recovery.",
        ],
        "annotation_schema_version": "0.1",
        "coordinate_system": "normalized_image_uv",
        "description": description,
        "instances": instances,
        "regions": regions,
        "repeat_groups": repeat_groups,
        "scene_id": f"open_images_reselection_{record.image_id}",
        "source_image": {
            "description": (
                "Open Images V7 validation image frozen from the official CVDF mirror."
            ),
            "image_id": record.image_id,
            "image_path": "source.jpg",
            "pixel_height": record.height,
            "pixel_width": record.width,
            "sha256": record.sha256,
        },
    }


def _construction_config() -> dict[str, Any]:
    return {
        "allow_repeat_fallback": True,
        "axis_policy": "hints_then_geometry",
        "boundary_merge_tolerance": 0.02,
        "config_schema_version": "0.1",
        "depth_zone_intervals": [
            {"depth_zone": "foreground", "z_max": 0.2, "z_min": 0.0},
            {"depth_zone": "midground", "z_max": 0.8, "z_min": 0.2},
            {"depth_zone": "background", "z_max": 1.0, "z_min": 0.8},
        ],
        "maximum_grammar_depth": 16,
        "minimum_normalized_region_extent": 0.01,
        "projection_model": "normalized_orthographic_proxy",
        "repeat_alignment_tolerance": 0.03,
        "repeat_size_tolerance": 0.2,
        "repeat_spacing_tolerance": 0.25,
        "require_complete_depth_coverage": True,
        "root_bounds": {
            "max": [1.0, 1.0, 1.0],
            "min": [0.0, 0.0, 0.0],
        },
    }


def build_presentation_overlay(annotation_path: Path, target: Path) -> Path:
    """Render a simplified presentation overlay without diagnostic identifiers."""
    annotation = json.loads(Path(annotation_path).read_text(encoding="utf-8"))
    source = Path(annotation_path).parent / annotation["source_image"]["image_path"]
    with Image.open(source) as opened:
        base = ImageOps.exif_transpose(opened).convert("RGBA")
    scale = min(1.0, 1200 / max(base.size))
    if scale < 1.0:
        base = base.resize(
            (round(base.width * scale), round(base.height * scale)),
            Image.Resampling.LANCZOS,
        )
    semantics = [
        item["semantic_class"]
        for item in annotation["regions"] + annotation["instances"]
    ]
    palette = resolve_palette(semantics)
    fill = Image.new("RGBA", base.size, (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(fill, "RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    font = ImageFont.load_default(size=22)
    labeled: set[str] = set()
    for region in annotation["regions"]:
        shape = region["shape"]
        if shape["type"] != "rectangle":
            continue
        box = _normalized_box(shape, base.size)
        color = palette[region["semantic_class"]]
        fill_draw.rectangle(box, fill=(*color[:3], 34))
        draw.rectangle(box, outline=(*color[:3], 255), width=7)
        semantic = region["semantic_class"]
        if semantic not in labeled and region["role"] != "open_space":
            label_box = draw.textbbox((box[0] + 8, box[1] + 7), semantic, font=font)
            draw.rounded_rectangle(
                (
                    label_box[0] - 5,
                    label_box[1] - 3,
                    label_box[2] + 5,
                    label_box[3] + 3,
                ),
                radius=5,
                fill=(*color[:3], 225),
            )
            draw.text(
                (box[0] + 8, box[1] + 7),
                semantic,
                fill="white",
                font=font,
            )
            labeled.add(semantic)
    base = Image.alpha_composite(base, fill)
    draw = ImageDraw.Draw(base, "RGBA")
    instance_by_id = {item["instance_id"]: item for item in annotation["instances"]}
    for instance in annotation["instances"]:
        box = _normalized_box(instance["shape"], base.size)
        color = palette[instance["semantic_class"]]
        draw.rectangle(box, fill=(*color[:3], 62), outline=(*color[:3], 255), width=7)
    for group in annotation["repeat_groups"]:
        centers = []
        for member in group["member_instance_ids"]:
            box = _normalized_box(instance_by_id[member]["shape"], base.size)
            centers.append(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
        if len(centers) > 1:
            draw.line(centers, fill=(190, 45, 196, 255), width=7)
            for center in centers:
                draw.ellipse(
                    (
                        center[0] - 7,
                        center[1] - 7,
                        center[0] + 7,
                        center[1] + 7,
                    ),
                    fill=(190, 45, 196, 255),
                )
    legend_width, legend_height = 310, 72
    left = base.width - legend_width - 14
    top = base.height - legend_height - 14
    draw.rounded_rectangle(
        (left, top, left + legend_width, top + legend_height),
        radius=10,
        fill=(23, 35, 61, 225),
    )
    draw.line((left + 18, top + 24, left + 58, top + 24), fill=(244, 174, 0), width=7)
    draw.text((left + 72, top + 13), "Supplied regions", fill="white", font=font)
    draw.line((left + 18, top + 54, left + 58, top + 54), fill=(190, 45, 196), width=7)
    draw.text((left + 72, top + 43), "Repeat group", fill="white", font=font)
    _save_png(base.convert("RGB"), target)
    return target


def _normalized_box(
    shape: Mapping[str, Any],
    size: tuple[int, int],
) -> tuple[int, int, int, int]:
    return (
        round(float(shape["u_min"]) * (size[0] - 1)),
        round(float(shape["v_min"]) * (size[1] - 1)),
        round(float(shape["u_max"]) * (size[0] - 1)),
        round(float(shape["v_max"]) * (size[1] - 1)),
    )


def _edit_label(
    family: str,
    before_count: int,
    edit: Mapping[str, Any],
) -> str:
    if edit.get("operation_type") != "set_repeat_count" or not edit.get("applied"):
        raise ReselectionError("shortlisted repeat preview lacks a repeat-count edit")
    noun = "Windows" if family == "facade" else "Cars"
    return f"{noun}: {before_count} -> {edit['requested_value']}"


def _build_preview_panel(
    record: CandidateRecord,
    item: Mapping[str, Any],
    gate: VisualGateRecord,
    preview: Path,
    edit_label: str,
) -> None:
    canvas = Image.new("RGB", (2000, 1200), "#f4f1ea")
    draw = ImageDraw.Draw(canvas)
    title_font = ImageFont.load_default(size=28)
    label_font = ImageFont.load_default(size=22)
    small_font = ImageFont.load_default(size=17)
    draw.rectangle((0, 0, 2000, 86), fill="#17233d")
    draw.text(
        (24, 17),
        f"Annotation-assisted {item['family']} preview | {edit_label}",
        fill="white",
        font=title_font,
    )
    assets = (
        ("Single input image", preview / "input" / "source.jpg"),
        (
            "Supplied structure (presentation overlay)",
            preview / "presentation_overlay.png",
        ),
        (
            f"Structured-scene proxy | {item['camera']}",
            preview / "constructor" / "primary" / "render.png",
        ),
        (
            f"Explicit edit | {edit_label}",
            preview / "constructor" / "edit" / "after.png",
        ),
    )
    for index, (label, path) in enumerate(assets):
        column = index % 2
        row = index // 2
        x0 = column * 1000
        y0 = 92 + row * 500
        draw.text((x0 + 24, y0 + 8), label, fill="#17233d", font=label_font)
        with Image.open(path) as opened:
            original_image = ImageOps.exif_transpose(opened).convert("RGB")
            source_image = original_image
            if index >= 2:
                source_image = _tight_proxy_crop(source_image)
            fitted = ImageOps.contain(source_image, (940, 410))
        canvas.paste(
            fitted,
            (
                x0 + 30 + (940 - fitted.width) // 2,
                y0 + 56 + (410 - fitted.height) // 2,
            ),
        )
        if index >= 2:
            semantic = "window" if item["family"] == "facade" else "car"
            inset = _semantic_inset(original_image, semantic)
            if inset is not None:
                inset = ImageOps.contain(inset, (300, 122))
                inset_x = x0 + 650 + (300 - inset.width) // 2
                inset_y = y0 + 72 + (122 - inset.height) // 2
                draw.rounded_rectangle(
                    (x0 + 638, y0 + 60, x0 + 962, y0 + 206),
                    radius=10,
                    fill="#fff4f5",
                    outline="#d1495b",
                    width=4,
                )
                canvas.paste(inset, (inset_x, inset_y))
                draw.text(
                    (x0 + 650, y0 + 174),
                    f"{semantic.title()} count detail",
                    fill="#8c2638",
                    font=small_font,
                )
    arrow_y = 823
    draw.line((900, arrow_y, 1090, arrow_y), fill="#d1495b", width=12)
    draw.polygon(
        ((1090, arrow_y), (1058, arrow_y - 24), (1058, arrow_y + 24)),
        fill="#d1495b",
    )
    draw.rounded_rectangle(
        (820, 844, 1180, 902),
        radius=14,
        fill="#fff4f5",
        outline="#d1495b",
        width=3,
    )
    draw.text((846, 858), edit_label, fill="#8c2638", font=label_font)
    gate_color = "#26734d" if gate.passed else "#a14520"
    draw.rectangle((0, 1092, 2000, 1200), fill=gate_color)
    draw.text(
        (22, 1105),
        f"Visual gate: {'PASS 10/10' if gate.passed else 'FAIL'} | {item['visual_note']}",
        fill="white",
        font=small_font,
    )
    draw.text(
        (22, 1150),
        (
            f"Open Images {record.image_id} | {record.title} | by {record.author} | "
            f"{record.license}"
        ),
        fill="#eef5f2",
        font=small_font,
    )
    _save_png(canvas, preview / "preview_panel.png")


def _tight_proxy_crop(image: Image.Image) -> Image.Image:
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    difference = ImageChops.difference(image, background).convert("L")
    difference = difference.point(lambda value: 255 if value > 12 else 0)
    bounds = difference.getbbox()
    if bounds is None:
        return image
    margin_x = max(12, round((bounds[2] - bounds[0]) * 0.08))
    margin_y = max(12, round((bounds[3] - bounds[1]) * 0.08))
    expanded = (
        max(0, bounds[0] - margin_x),
        max(0, bounds[1] - margin_y),
        min(image.width, bounds[2] + margin_x),
        min(image.height, bounds[3] + margin_y),
    )
    return image.crop(expanded)


def _semantic_inset(image: Image.Image, semantic: str) -> Image.Image | None:
    target = resolve_palette((semantic,))[semantic][:3]
    pixels = image.load()
    selected = []
    for y in range(image.height):
        for x in range(image.width):
            color = pixels[x, y]
            if (
                sum(abs(int(color[index]) - int(target[index])) for index in range(3))
                < 75
            ):
                selected.append((x, y))
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


def _freeze_selected(
    selected: Sequence[
        tuple[dict[str, Any], CandidateRecord, dict[str, Any], dict[str, Any]]
    ],
    repository: Path,
    image_cache: Path,
    *,
    verify_determinism: bool,
    candidate_count: int,
) -> tuple[str, ...]:
    roles = [item[0].get("selected_role") for item in selected]
    if sorted(roles) != ["canonical_success", "moderate_case"]:
        raise ReselectionError(
            "freeze requires exactly canonical_success and moderate_case selections"
        )
    for item, _, _, _ in selected:
        gate = _gate_from_curation(item)
        if not gate.passed:
            raise ReselectionError(
                f"refusing to freeze visual-gate failure {item['image_id']}"
            )
    limitation_source = (
        repository / "inputs" / "real_cases" / "limitation_case" / "source.jpg"
    )
    limitation_sha = sha256_file(limitation_source)
    _archive_displaced_cases(repository)
    frozen_entries = []
    for item, record, annotation, config in selected:
        role = item["selected_role"]
        input_root = repository / "inputs" / "real_cases" / role
        atomic_write_bytes(
            (image_cache / f"{record.image_id}.jpg").read_bytes(),
            input_root / "source.jpg",
            overwrite=True,
            create_parents=True,
        )
        _write_json(input_root / "annotation.json", annotation)
        _write_json(input_root / "construction.json", config)
        manifest = _frozen_case_manifest(record, item, role)
        _write_json(input_root / "case_manifest.json", manifest)
        frozen_entries.append(
            {
                "author": record.author,
                "case_key": role,
                "image_id": record.image_id,
                "license_url": record.license,
                "official_mirror_url": record.official_mirror_url,
                "original_landing_page": record.original_landing_page,
                "sha256": record.sha256,
                "split": "validation",
                "title": record.title,
            }
        )
    limitation_manifest = json.loads(
        (
            repository
            / "inputs"
            / "real_cases"
            / "limitation_case"
            / "case_manifest.json"
        ).read_text(encoding="utf-8")
    )
    frozen_entries.append(
        {
            "author": limitation_manifest["author"],
            "case_key": "limitation_case",
            "image_id": limitation_manifest["image_id"],
            "license_url": limitation_manifest["license_url"],
            "official_mirror_url": limitation_manifest["official_mirror_url"],
            "original_landing_page": limitation_manifest["original_landing_page"],
            "sha256": limitation_manifest["source_image_sha256"],
            "split": "validation",
            "title": limitation_manifest["title"],
        }
    )
    _write_json(
        repository / "datasets" / "open_images" / "frozen_cases.json",
        {
            "annotation_license_url": ("https://creativecommons.org/licenses/by/4.0/"),
            "candidate_count": candidate_count,
            "cases": frozen_entries,
            "dataset": "Open Images",
            "dataset_version": "V7",
            "frozen_case_policy_version": "0.2",
            "preferred_split": "validation",
            "selection_run": "runs/representation_aligned_selection",
        },
    )
    if sha256_file(limitation_source) != limitation_sha:
        raise ReselectionError("Turku limitation source changed during positive freeze")
    build_open_images_cases(
        repository / "results" / "real_cases",
        input_directory=repository / "inputs" / "real_cases",
        overwrite=True,
        verify_determinism=verify_determinism,
    )
    return ("canonical_success", "moderate_case")


def _frozen_case_manifest(
    record: CandidateRecord,
    item: Mapping[str, Any],
    role: str,
) -> dict[str, Any]:
    is_facade = item["family"] == "facade"
    return {
        "annotation_license_url": "https://creativecommons.org/licenses/by/4.0/",
        "annotation_path": "annotation.json",
        "author": record.author,
        "case_role": role,
        "construction_config_path": "construction.json",
        "dataset_name": "Open Images",
        "dataset_supplied_information": [
            "source image",
            "image ID and validation split",
            "human-verified labels",
            "Open Images bounding boxes reviewed during candidate selection",
            "image attribution and Creative Commons license metadata",
        ],
        "dataset_version": "V7",
        "display_title": (
            "Regular planar facade success"
            if is_facade
            else "Structured street and parking success"
        ),
        "expected_outcome": "success",
        "factual_notes": [
            "The frozen source is the official CVDF validation JPEG.",
            "The project annotation was authored before constructor output review.",
            "The candidate passed all ten visual acceptance gates.",
        ],
        "human_verified_positive_labels": list(record.relevant_labels),
        "image_id": record.image_id,
        "known_representation_challenges": (
            ["mild oblique source viewpoint", "partial tree framing"]
            if is_facade
            else ["elevated source viewpoint", "moderate vehicle clutter"]
        ),
        "license_url": record.license,
        "official_mirror_url": record.official_mirror_url,
        "original_landing_page": record.original_landing_page,
        "original_url": record.official_mirror_url,
        "primary_camera": item["camera"],
        "primary_edit_expectation": "repeat_count",
        "privacy_review": (
            "No prominent identifiable faces or readable license plates are "
            "required for the visual story at the frozen resolution."
        ),
        "scene_grammar_kit_derived_information": [
            "proxy 3D bounds",
            "split boundaries and wrappers",
            "repeat acceptance, count, and spacing",
            "split and repeat grammars",
            "execution geometry",
            "semantic renders",
        ],
        "real_case_manifest_version": "0.2",
        "researcher_supplied_information": (
            [
                "facade and horizontal band regions",
                "depth-zone assignments",
                "regularized representative window boxes",
                "repeat membership and x axis",
            ]
            if is_facade
            else [
                "road, side-zone, parking-lane, and building regions",
                "depth-zone assignments",
                "regularized representative parked-car boxes",
                "repeat membership and x axis",
            ]
        ),
        "selection_rationale": item["visual_note"],
        "source_image_path": "source.jpg",
        "source_image_sha256": record.sha256,
        "split": "validation",
        "title": record.title,
        "visual_gate_status": "PASS",
    }


def _archive_displaced_cases(repository: Path) -> None:
    archive_root = repository / "results" / "real_cases" / "archive"
    mapping = {
        "canonical_success": "halifax_city_hall",
        "moderate_case": "ruta_del_modernisme",
    }
    attribution_path = repository / "results" / "phase2_acceptance" / "attribution.json"
    attributions = (
        json.loads(attribution_path.read_text(encoding="utf-8"))
        if attribution_path.is_file()
        else []
    )
    by_role = {item["case_key"]: item for item in attributions}
    for role, archive_name in mapping.items():
        destination = archive_root / archive_name
        input_source = repository / "inputs" / "real_cases" / role
        result_source = repository / "results" / "real_cases" / role
        if destination.exists():
            continue
        if not input_source.is_dir() or not result_source.is_dir():
            raise ReselectionError(f"cannot archive incomplete displaced case {role}")
        shutil.copytree(input_source, destination / "input")
        shutil.copytree(result_source, destination / "result")
        panel = repository / "results" / "real_cases" / "review" / f"{role}.png"
        shutil.copy2(panel, destination / "review_panel.png")
        _write_json(
            destination / "attribution.json",
            by_role.get(
                role,
                json.loads(
                    (input_source / "case_manifest.json").read_text(encoding="utf-8")
                ),
            ),
        )
    atomic_write_text(
        (
            "# Archived representation-misaligned positive cases\n\n"
            "Halifax City Hall and Ruta del Modernisme remain valid, complete "
            "annotation-assisted pipeline outputs. They were replaced as primary "
            "shortlist positives because towers, spires, pitched or ornamental "
            "rooflines, and strong projective structure dominate their visual "
            "identity beyond the current split-and-repeat proxy grammar. No "
            "technical failure is hidden. The replacement aligns the demonstrated "
            "photographs with the claimed approximately Manhattan-world scope.\n"
        ),
        archive_root / "README.md",
        overwrite=True,
        create_parents=True,
    )


def _save_png(image: Image.Image, path: Path) -> None:
    import io

    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=9)
    atomic_write_bytes(
        stream.getvalue(),
        path,
        overwrite=True,
        create_parents=True,
    )


def _write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        path,
        overwrite=True,
        create_parents=True,
    )
