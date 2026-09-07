"""Artifact, serialization, persistence, determinism, and CLI tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from scene_grammar_kit.assisted import (
    AssistedConstructorFileExistsError,
    artifact_index_to_canonical_json,
    assisted_construction_report_from_json,
    assisted_construction_report_to_canonical_json,
    construct_assisted_scene,
)
from scene_grammar_kit.cli import build_parser, main

VALID = Path(__file__).parent / "fixtures" / "assisted" / "valid"
ANNOTATION = VALID / "urban_minimal.annotation.json"
CONFIG = VALID / "urban_minimal.construction.json"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    output = tmp_path_factory.mktemp("constructor_persistence") / "bundle"
    return construct_assisted_scene(
        ANNOTATION,
        CONFIG,
        output,
        render_width=240,
        render_height=160,
    )


def test_construction_report_round_trip_and_text_newline(bundle) -> None:
    path = bundle.output_directory / "construction_report.json"
    text = path.read_text(encoding="utf-8")
    restored = assisted_construction_report_from_json(text)
    assert restored == bundle.report
    assert assisted_construction_report_to_canonical_json(restored) == text
    human = (bundle.output_directory / "construction_report.txt").read_text()
    assert human.endswith("\n")
    assert not human.endswith("\n\n")


def test_artifact_index_is_sorted_relative_and_hashes_final_bytes(bundle) -> None:
    records = bundle.artifact_index.records
    paths = tuple(item.relative_path for item in records)
    assert paths == tuple(sorted(paths))
    assert "artifact_index.json" not in paths
    assert "construction_report.json" not in paths
    for record in records:
        assert not Path(record.relative_path).is_absolute()
        assert "\\" not in record.relative_path
        data = (bundle.output_directory / record.relative_path).read_bytes()
        assert record.byte_size == len(data)
        assert record.sha256 == hashlib.sha256(data).hexdigest()
    text = artifact_index_to_canonical_json(bundle.artifact_index)
    assert text == (bundle.output_directory / "artifact_index.json").read_text(
        encoding="utf-8"
    )


def test_artifact_categories_and_stages_are_factual(bundle) -> None:
    records = {item.relative_path: item for item in bundle.artifact_index.records}
    assert records["input/source_image.png"].category == "input_evidence"
    assert records["input/source_image.png"].stage == "image_verification"
    assert records["repeat/grammar.json"].stage == "repeat_induction"
    assert records["edit/after.png"].stage == "default_edit"
    assert all(
        item.edit_key == "default_edit"
        for item in records.values()
        if item.relative_path.startswith("edit/")
    )
    assert "runtime_report.json" not in records


def test_runtime_values_are_excluded_from_canonical_report(bundle) -> None:
    report_text = (bundle.output_directory / "construction_report.json").read_text()
    runtime = json.loads((bundle.output_directory / "runtime_report.json").read_text())
    assert "durations_seconds" not in report_text
    assert runtime["stable_for_determinism_comparison"] is False
    assert set(runtime["durations_seconds"]) == {
        "editing_seconds",
        "execution_export_seconds",
        "lifting_seconds",
        "rendering_seconds",
        "repeat_induction_seconds",
        "review_seconds",
        "split_induction_seconds",
        "total_seconds",
    }


def test_overwrite_protection_and_unrelated_preservation(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    unrelated = output / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    with pytest.raises(AssistedConstructorFileExistsError):
        construct_assisted_scene(ANNOTATION, CONFIG, output)
    construct_assisted_scene(
        ANNOTATION,
        CONFIG,
        output,
        overwrite=True,
        verify_execution=False,
        apply_default_edit=False,
        render_width=160,
        render_height=120,
    )
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_stale_success_is_removed_before_required_failure(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    report = output / "construction_report.json"
    report.write_text('{"success":true}', encoding="utf-8")
    missing = tmp_path / "missing.annotation.json"
    with pytest.raises(Exception):
        construct_assisted_scene(
            missing,
            CONFIG,
            output,
            overwrite=True,
        )
    assert not report.exists()


def test_success_report_is_written_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scene_grammar_kit.assisted.constructor_persistence as persistence

    names: list[str] = []
    original = persistence._atomic_write_bytes

    def recording(data: bytes, path: Path) -> None:
        names.append(path.name)
        original(data, path)

    monkeypatch.setattr(persistence, "_atomic_write_bytes", recording)
    construct_assisted_scene(
        ANNOTATION,
        CONFIG,
        tmp_path / "output",
        verify_execution=False,
        apply_default_edit=False,
        render_width=180,
        render_height=120,
    )
    assert names[-1] == "construction_report.json"


def test_two_complete_builds_are_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    construct_assisted_scene(
        ANNOTATION, CONFIG, first, render_width=200, render_height=140
    )
    construct_assisted_scene(
        ANNOTATION, CONFIG, second, render_width=200, render_height=140
    )
    for path in sorted(
        item.relative_path
        for item in json_index_records(first / "artifact_index.json")
        if item.relative_path != "runtime_report.json"
    ):
        assert (first / path).read_bytes() == (second / path).read_bytes()
    assert (first / "construction_report.json").read_bytes() == (
        second / "construction_report.json"
    ).read_bytes()
    assert (first / "artifact_index.json").read_bytes() == (
        second / "artifact_index.json"
    ).read_bytes()
    for relative in (
        "review/annotation_overlay.png",
        "split_only/render.png",
        "repeat/render.png",
        "primary/render.png",
        "edit/before.png",
        "edit/after.png",
    ):
        with (
            Image.open(first / relative) as left,
            Image.open(second / relative) as right,
        ):
            assert ImageChops.difference(left, right).getbbox() is None


class _IndexRecord:
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path


def json_index_records(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return [_IndexRecord(item["relative_path"]) for item in data["records"]]


def test_cli_success_help_and_no_default_edit(
    tmp_path: Path,
    capsys,
) -> None:
    assert "construct-assisted-scene" in build_parser().format_help()
    output = tmp_path / "output"
    assert (
        main(
            [
                "construct-assisted-scene",
                str(ANNOTATION),
                "--config",
                str(CONFIG),
                "--out",
                str(output),
                "--width",
                "180",
                "--height",
                "120",
                "--no-default-edit",
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "ASSISTED CONSTRUCTION COMPLETE" in text
    assert "primary_grammar=repeat" in text
    assert "default_edit=skipped" in text


def test_cli_expected_failure_has_no_traceback(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "construct-assisted-scene",
            str(tmp_path / "missing.json"),
            "--config",
            str(CONFIG),
            "--out",
            str(tmp_path / "output"),
        ]
    )
    text = capsys.readouterr().out
    assert code == 2
    assert "ASSISTED CONSTRUCTION FAILED" in text
    assert "Traceback" not in text
