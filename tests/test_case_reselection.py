from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from scene_grammar_kit.case_reselection import (
    CandidateRecord,
    ReselectionError,
    VisualGateRecord,
    build_contact_sheets,
    load_candidate_manifest,
    validate_visual_gate,
)
from scene_grammar_kit.case_reselection.runner import GATE_NAMES
from scene_grammar_kit.phase2_acceptance.runner import (
    _controlled_outputs_are_complete,
    _first_repeat,
)

REPOSITORY = Path(__file__).resolve().parents[1]
CURATED = (
    REPOSITORY
    / "src"
    / "scene_grammar_kit"
    / "case_reselection"
    / "curated_shortlist.json"
)


def _candidate(image_id: str, family: str) -> CandidateRecord:
    return CandidateRecord(
        image_id=image_id,
        title=f"Title {image_id}",
        author="Attribution Author",
        license="https://creativecommons.org/licenses/by/2.0/",
        original_landing_page=f"https://example.test/{image_id}",
        official_mirror_url=f"https://example.test/{image_id}.jpg",
        width=640,
        height=480,
        sha256="0" * 64,
        relevant_labels=("Building",),
        family=family,
        preliminary_suitability_score=1.0,
        rejection_flags=(),
        rationale="Synthetic offline test record.",
        box_counts={"Building": 1},
        occluded_relevant_box_count=0,
    )


def test_candidate_manifest_parsing_and_count_validation(tmp_path: Path) -> None:
    record = _candidate("candidate-a", "facade")
    payload = {
        "candidate_count": 1,
        "records": [
            {
                "image_id": record.image_id,
                "title": record.title,
                "author": record.author,
                "license": record.license,
                "original_landing_page": record.original_landing_page,
                "official_mirror_url": record.official_mirror_url,
                "width": record.width,
                "height": record.height,
                "sha256": record.sha256,
                "relevant_labels": list(record.relevant_labels),
                "family": record.family,
                "preliminary_suitability_score": (record.preliminary_suitability_score),
                "rejection_flags": list(record.rejection_flags),
                "rationale": record.rationale,
                "box_counts": record.box_counts,
                "occluded_relevant_box_count": (record.occluded_relevant_box_count),
            }
        ],
    }
    path = tmp_path / "candidate_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_candidate_manifest(path) == (record,)
    payload["candidate_count"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReselectionError, match="count"):
        load_candidate_manifest(path)


def test_contact_sheet_generation_is_deterministic(tmp_path: Path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    records = tuple(
        _candidate(f"{family}-{index}", family)
        for family in ("facade", "street")
        for index in range(4)
    )
    for index, record in enumerate(records):
        Image.new("RGB", (640, 480), (30 * index, 80, 140)).save(
            image_root / f"{record.image_id}.jpg"
        )
    first = build_contact_sheets(records, image_root, tmp_path / "first")
    second = build_contact_sheets(records, image_root, tmp_path / "second")
    assert [path.name for path in first] == [
        "facade_candidates_01.png",
        "facade_candidates_02.png",
        "street_candidates_01.png",
        "street_candidates_02.png",
    ]
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in first] == [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in second
    ]


def test_visual_gate_requires_every_documented_decision() -> None:
    complete = VisualGateRecord(
        image_id="facade",
        family="facade",
        camera="front",
        gates={name: True for name in GATE_NAMES},
        notes={name: "Reviewed at quarter scale." for name in GATE_NAMES},
    )
    validate_visual_gate(complete)
    incomplete = VisualGateRecord(
        image_id=complete.image_id,
        family=complete.family,
        camera=complete.camera,
        gates=dict(complete.gates),
        notes=dict(complete.notes),
    )
    incomplete.notes.pop(GATE_NAMES[-1])
    with pytest.raises(ReselectionError, match="incomplete visual gate"):
        validate_visual_gate(incomplete)


def test_curated_shortlist_has_exactly_two_gate_passing_replacements() -> None:
    records = json.loads(CURATED.read_text(encoding="utf-8"))["records"]
    assert sum(item["family"] == "facade" for item in records) == 5
    assert sum(item["family"] == "street" for item in records) == 5
    selected = [item for item in records if item["selected_role"] is not None]
    assert {item["selected_role"] for item in selected} == {
        "canonical_success",
        "moderate_case",
    }
    assert all(not item["failed_gates"] for item in selected)
    assert (
        next(item for item in selected if item["selected_role"] == "canonical_success")[
            "camera"
        ]
        == "front"
    )
    assert (
        next(item for item in selected if item["selected_role"] == "moderate_case")[
            "camera"
        ]
        == "isometric"
    )


def test_frozen_roles_attribution_overlays_and_actual_repeat_values() -> None:
    expected = {
        "canonical_success": ("736a482693c18962", "front", "window"),
        "moderate_case": ("40992cf7a7bbf20e", "isometric", "car"),
    }
    for role, (image_id, camera, semantic_class) in expected.items():
        input_root = REPOSITORY / "inputs" / "real_cases" / role
        result_root = REPOSITORY / "results" / "real_cases" / role
        manifest = json.loads(
            (input_root / "case_manifest.json").read_text(encoding="utf-8")
        )
        annotation = json.loads(
            (input_root / "annotation.json").read_text(encoding="utf-8")
        )
        grammar = json.loads(
            (result_root / "primary" / "grammar.json").read_text(encoding="utf-8")
        )
        repeat = _first_repeat(grammar["root"])
        report = json.loads(
            (result_root / "construction_report.json").read_text(encoding="utf-8")
        )
        assert manifest["image_id"] == image_id
        assert manifest["primary_camera"] == camera
        assert manifest["author"] and manifest["original_landing_page"]
        assert manifest["visual_gate_status"] == "PASS"
        assert repeat["count"] == len(annotation["instances"]) == 5
        assert repeat["element"]["semantic_class"] == semantic_class
        assert report["edit_decision"]["operation_type"] == "set_repeat_count"
        assert report["edit_decision"]["realized_value"] == "6"
        assert (result_root / "review" / "audit_overlay.png").is_file()
        assert (result_root / "review" / "presentation_overlay.png").is_file()


def test_frozen_limitation_case_identity() -> None:
    frozen = json.loads(
        (REPOSITORY / "datasets" / "open_images" / "frozen_cases.json").read_text(
            encoding="utf-8"
        )
    )
    limitation = next(
        item for item in frozen["cases"] if item["case_key"] == "limitation_case"
    )
    assert limitation["image_id"] == "692c5c6be088dbf8"


def test_controlled_metric_values_are_complete() -> None:
    matches, detail = _controlled_outputs_are_complete(REPOSITORY)
    assert matches, detail
    summary = json.loads(
        (REPOSITORY / "results" / "evaluation" / "controlled_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["valid_grammar_rate"] == {
        "denominator": 12,
        "numerator": 12,
        "rate": 1.0,
    }
    assert summary["accepted_repeat_groups"] == {"count": 8, "denominator": 12}
    assert summary["fallback_repeat_groups"] == {"count": 4, "denominator": 12}
    assert summary["median_byte_ratio"]["median"] == 0.5779244378805716
