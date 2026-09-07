"""Persistence, integrated workflow, and CLI tests for Batch 2.2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

import scene_grammar_kit.assisted.review_persistence as review_persistence
from scene_grammar_kit.assisted import (
    REVIEW_ARTIFACT_FILENAMES,
    AnnotationReviewFileExistsError,
    AnnotationReviewValidationError,
    AnnotationReviewWriteError,
    SourceImageHashError,
    annotation_review_report_to_canonical_json,
    annotation_review_summary_to_canonical_json,
    annotation_to_canonical_json,
    build_annotation_review_summary,
    construction_config_to_canonical_json,
    load_and_verify_source_image,
    load_annotation,
    load_construction_config,
    render_annotation_overlay,
    review_assisted_input,
    save_annotation,
    save_annotation_overlay,
    save_annotation_review_report,
    save_annotation_review_summary,
    save_annotation_review_summary_text,
    save_construction_config,
)
from scene_grammar_kit.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"
VALID = FIXTURES / "valid"
INVALID = FIXTURES / "invalid"
URBAN_ANNOTATION = VALID / "urban_minimal.annotation.json"
URBAN_CONFIG = VALID / "urban_minimal.construction.json"
FACADE_ANNOTATION = VALID / "facade_polygon.annotation.json"
DEFAULT_CONFIG = VALID / "default.construction.json"


def _urban_values():
    annotation = load_annotation(URBAN_ANNOTATION)
    config = load_construction_config(URBAN_CONFIG)
    verified = load_and_verify_source_image(annotation, URBAN_ANNOTATION)
    overlay = render_annotation_overlay(verified, annotation)
    summary = build_annotation_review_summary(annotation, verified)
    return annotation, config, verified, overlay, summary


def _artifact_bytes(root: Path) -> dict[str, bytes]:
    return {name: (root / name).read_bytes() for name in REVIEW_ARTIFACT_FILENAMES}


def test_png_reopens_with_exact_dimensions_and_no_timestamp_metadata(
    tmp_path: Path,
) -> None:
    _, _, _, overlay, _ = _urban_values()
    path = save_annotation_overlay(overlay, tmp_path / "overlay.png")
    with Image.open(path) as image:
        image.load()
        assert image.mode == "RGBA"
        assert image.size == (480, 320)
        assert not any("time" in key.lower() for key in image.info)


def test_same_input_produces_identical_pixels_and_png_bytes(
    tmp_path: Path,
) -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    verified = load_and_verify_source_image(annotation, URBAN_ANNOTATION)
    first = render_annotation_overlay(verified, annotation)
    second = render_annotation_overlay(verified, annotation)
    assert first.image.tobytes() == second.image.tobytes()
    first_path = save_annotation_overlay(first, tmp_path / "first.png")
    second_path = save_annotation_overlay(second, tmp_path / "second.png")
    assert first_path.read_bytes() == second_path.read_bytes()


def test_canonical_summary_and_report_json_are_byte_stable() -> None:
    _, _, _, overlay, summary = _urban_values()
    assert annotation_review_summary_to_canonical_json(summary) == (
        annotation_review_summary_to_canonical_json(summary)
    )
    assert annotation_review_report_to_canonical_json(overlay.report) == (
        annotation_review_report_to_canonical_json(overlay.report)
    )


def test_text_summary_is_deterministic_with_one_final_newline(
    tmp_path: Path,
) -> None:
    annotation, _, _, _, summary = _urban_values()
    first = save_annotation_review_summary_text(
        summary, annotation, tmp_path / "first.txt"
    )
    second = save_annotation_review_summary_text(
        summary, annotation, tmp_path / "second.txt"
    )
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"\n")
    assert not first.read_bytes().endswith(b"\n\n")


def test_persistence_overwrite_protection_and_explicit_overwrite(
    tmp_path: Path,
) -> None:
    _, _, _, overlay, summary = _urban_values()
    image_path = save_annotation_overlay(overlay, tmp_path / "overlay.png")
    summary_path = save_annotation_review_summary(summary, tmp_path / "summary.json")
    report_path = save_annotation_review_report(
        overlay.report, tmp_path / "report.json"
    )
    for operation in (
        lambda: save_annotation_overlay(overlay, image_path),
        lambda: save_annotation_review_summary(summary, summary_path),
        lambda: save_annotation_review_report(overlay.report, report_path),
    ):
        with pytest.raises(AnnotationReviewFileExistsError):
            operation()
    save_annotation_overlay(overlay, image_path, overwrite=True)
    save_annotation_review_summary(summary, summary_path, overwrite=True)
    save_annotation_review_report(overlay.report, report_path, overwrite=True)


def test_controlled_parent_creation(tmp_path: Path) -> None:
    _, _, _, overlay, summary = _urban_values()
    nested = tmp_path / "missing" / "summary.json"
    with pytest.raises(AnnotationReviewWriteError, match="does not exist"):
        save_annotation_review_summary(summary, nested)
    assert save_annotation_review_summary(summary, nested, create_parents=True).exists()
    assert save_annotation_overlay(
        overlay,
        tmp_path / "other" / "overlay.png",
        create_parents=True,
    ).exists()


def test_temporary_files_are_cleaned_after_conflict(tmp_path: Path) -> None:
    _, _, _, _, summary = _urban_values()
    target = tmp_path / "summary.json"
    target.write_text("preserve", encoding="utf-8")
    with pytest.raises(AnnotationReviewFileExistsError):
        save_annotation_review_summary(summary, target)
    assert target.read_text(encoding="utf-8") == "preserve"
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_temporary_files_are_cleaned_after_atomic_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, _, summary = _urban_values()

    def fail_link(source: object, target: object) -> None:
        raise OSError("simulated link failure")

    monkeypatch.setattr(review_persistence.os, "link", fail_link)
    with pytest.raises(AnnotationReviewWriteError, match="simulated"):
        save_annotation_review_summary(summary, tmp_path / "summary.json")
    assert not (tmp_path / "summary.json").exists()
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_valid_integrated_review_writes_expected_canonical_files(
    tmp_path: Path,
) -> None:
    result = review_assisted_input(URBAN_ANNOTATION, URBAN_CONFIG, tmp_path / "review")
    assert tuple(
        sorted(path.name for path in result.output_directory.iterdir())
    ) == tuple(sorted(REVIEW_ARTIFACT_FILENAMES))
    annotation = load_annotation(URBAN_ANNOTATION)
    config = load_construction_config(URBAN_CONFIG)
    assert result.annotation_path.read_text("utf-8") == (
        annotation_to_canonical_json(annotation)
    )
    assert result.construction_config_path.read_text("utf-8") == (
        construction_config_to_canonical_json(config)
    )
    assert result.report_path.stat().st_mtime_ns >= max(
        path.stat().st_mtime_ns
        for path in (
            result.annotation_path,
            result.construction_config_path,
            result.overlay_path,
            result.summary_json_path,
            result.summary_text_path,
        )
    )


def test_nonempty_output_is_protected(tmp_path: Path) -> None:
    output = tmp_path / "review"
    output.mkdir()
    (output / "unrelated.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(AnnotationReviewFileExistsError, match="nonempty"):
        review_assisted_input(URBAN_ANNOTATION, URBAN_CONFIG, output)
    assert (output / "unrelated.txt").read_text("utf-8") == "keep"


def test_overwrite_preserves_unrelated_files(tmp_path: Path) -> None:
    output = tmp_path / "review"
    review_assisted_input(URBAN_ANNOTATION, URBAN_CONFIG, output)
    unrelated = output / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    review_assisted_input(URBAN_ANNOTATION, URBAN_CONFIG, output, overwrite=True)
    assert unrelated.read_text("utf-8") == "keep"


def test_failed_image_verification_leaves_no_pass_report(
    tmp_path: Path,
) -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    bad_source = replace(annotation.source_image, sha256="0" * 64)
    bad_annotation = replace(annotation, source_image=bad_source)
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "images").mkdir()
    image_bytes = (VALID / annotation.source_image.image_path).read_bytes()
    (source_root / "images" / "urban_minimal.png").write_bytes(image_bytes)
    annotation_path = save_annotation(bad_annotation, source_root / "annotation.json")
    output = tmp_path / "review"
    with pytest.raises(SourceImageHashError):
        review_assisted_input(annotation_path, URBAN_CONFIG, output)
    assert not (output / "annotation_review_report.json").exists()


def test_validation_occurs_before_image_rendering(tmp_path: Path) -> None:
    output = tmp_path / "review"
    with pytest.raises(AnnotationReviewValidationError):
        review_assisted_input(
            INVALID / "duplicate_ids.annotation.json",
            URBAN_CONFIG,
            output,
        )
    assert not output.exists()


def test_repeated_reviews_match_canonical_outputs_pixels_and_png_bytes(
    tmp_path: Path,
) -> None:
    first = review_assisted_input(URBAN_ANNOTATION, URBAN_CONFIG, tmp_path / "first")
    second = review_assisted_input(URBAN_ANNOTATION, URBAN_CONFIG, tmp_path / "second")
    first_bytes = _artifact_bytes(first.output_directory)
    second_bytes = _artifact_bytes(second.output_directory)
    assert first_bytes == second_bytes
    with (
        Image.open(first.overlay_path) as first_image,
        Image.open(second.overlay_path) as second_image,
    ):
        assert first_image.convert("RGBA").tobytes() == (
            second_image.convert("RGBA").tobytes()
        )


@pytest.mark.parametrize(
    ("annotation", "config"),
    (
        (URBAN_ANNOTATION, URBAN_CONFIG),
        (FACADE_ANNOTATION, DEFAULT_CONFIG),
    ),
)
def test_cli_valid_reviews_succeed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    annotation: Path,
    config: Path,
) -> None:
    output = tmp_path / annotation.stem
    assert (
        main(
            [
                "review-annotation",
                str(annotation),
                "--config",
                str(config),
                "--out",
                str(output),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "REVIEW COMPLETE" in printed
    assert (output / "annotation_overlay.png").exists()


@pytest.mark.parametrize(
    "invalid_annotation",
    (
        INVALID / "duplicate_ids.annotation.json",
        INVALID / "unsupported_annotation_version.annotation.json",
    ),
)
def test_cli_invalid_annotation_fails_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    invalid_annotation: Path,
) -> None:
    status = main(
        [
            "review-annotation",
            str(invalid_annotation),
            "--config",
            str(URBAN_CONFIG),
            "--out",
            str(tmp_path / "review"),
        ]
    )
    assert status != 0
    output = capsys.readouterr()
    assert "ANNOTATION REVIEW FAILED" in output.out
    assert not output.err


def test_cli_invalid_config_fails_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(
        [
            "review-annotation",
            str(URBAN_ANNOTATION),
            "--config",
            str(INVALID / "invalid_depth_intervals.construction.json"),
            "--out",
            str(tmp_path / "review"),
        ]
    )
    assert status != 0
    output = capsys.readouterr()
    assert "ANNOTATION REVIEW FAILED" in output.out
    assert "Traceback" not in output.out + output.err


def test_cli_compatibility_failure_fails_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = load_construction_config(URBAN_CONFIG)
    incompatible = replace(config, minimum_normalized_region_extent=0.2)
    config_path = save_construction_config(incompatible, tmp_path / "incompatible.json")
    status = main(
        [
            "review-annotation",
            str(URBAN_ANNOTATION),
            "--config",
            str(config_path),
            "--out",
            str(tmp_path / "review"),
        ]
    )
    assert status != 0
    assert "ANNOTATION REVIEW FAILED" in capsys.readouterr().out


def test_cli_options_affect_report(
    tmp_path: Path,
) -> None:
    output = tmp_path / "review"
    assert (
        main(
            [
                "review-annotation",
                str(URBAN_ANNOTATION),
                "--config",
                str(URBAN_CONFIG),
                "--out",
                str(output),
                "--no-labels",
                "--no-legend",
                "--show-parent-links",
                "--transparent-layer",
                "--max-dimension",
                "240",
                "--line-width",
                "2",
            ]
        )
        == 0
    )
    report = json.loads((output / "annotation_review_report.json").read_text("utf-8"))
    assert report["labels_drawn"] == 0
    assert report["legend_drawn"] is False
    assert (report["overlay_width"], report["overlay_height"]) == (240, 160)
    with Image.open(output / "annotation_overlay.png") as image:
        assert image.getpixel((0, 0))[3] == 0


def test_cli_missing_image_and_hash_mismatch_fail_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    missing = replace(
        annotation,
        source_image=replace(
            annotation.source_image,
            image_path="images/missing.png",
            sha256=None,
        ),
    )
    source = tmp_path / "source"
    source.mkdir()
    missing_path = save_annotation(missing, source / "missing.json")
    status = main(
        [
            "review-annotation",
            str(missing_path),
            "--config",
            str(URBAN_CONFIG),
            "--out",
            str(tmp_path / "missing-output"),
        ]
    )
    assert status != 0
    assert "Traceback" not in capsys.readouterr().out


def test_cli_hash_mismatch_fails_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    source = tmp_path / "source"
    (source / "images").mkdir(parents=True)
    (source / "images" / "urban_minimal.png").write_bytes(
        (VALID / "images" / "urban_minimal.png").read_bytes()
    )
    mismatch = replace(
        annotation,
        source_image=replace(annotation.source_image, sha256="0" * 64),
    )
    annotation_path = save_annotation(mismatch, source / "mismatch.json")
    status = main(
        [
            "review-annotation",
            str(annotation_path),
            "--config",
            str(URBAN_CONFIG),
            "--out",
            str(tmp_path / "output"),
        ]
    )
    assert status != 0
    output = capsys.readouterr()
    assert "ANNOTATION REVIEW FAILED" in output.out
    assert "Traceback" not in output.out + output.err


def test_cli_dimension_mismatch_fails_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    source = tmp_path / "source"
    (source / "images").mkdir(parents=True)
    (source / "images" / "urban_minimal.png").write_bytes(
        (VALID / "images" / "urban_minimal.png").read_bytes()
    )
    mismatch = replace(
        annotation,
        source_image=replace(
            annotation.source_image,
            pixel_width=479,
            sha256=None,
        ),
    )
    annotation_path = save_annotation(mismatch, source / "mismatch.json")
    status = main(
        [
            "review-annotation",
            str(annotation_path),
            "--config",
            str(URBAN_CONFIG),
            "--out",
            str(tmp_path / "output"),
        ]
    )
    assert status != 0
    assert "ANNOTATION REVIEW FAILED" in capsys.readouterr().out


def test_help_includes_review_annotation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "review-annotation" in capsys.readouterr().out


def test_saved_hashes_match_contents(tmp_path: Path) -> None:
    result = review_assisted_input(URBAN_ANNOTATION, URBAN_CONFIG, tmp_path / "review")
    report = json.loads(result.report_path.read_text("utf-8"))
    assert (
        report["annotation_sha256"]
        == hashlib.sha256(result.annotation_path.read_bytes()).hexdigest()
    )
    assert (
        report["construction_config_sha256"]
        == hashlib.sha256(result.construction_config_path.read_bytes()).hexdigest()
    )
    canonical_report = result.report_path.read_text("utf-8")
    canonical_summary = result.summary_json_path.read_text("utf-8")
    assert str(tmp_path.resolve()) not in canonical_report
    assert str(tmp_path.resolve()) not in canonical_summary
    assert "images/urban_minimal.png" in canonical_summary


@pytest.mark.parametrize(
    ("path", "expected_size", "expected_sha256"),
    (
        (
            URBAN_ANNOTATION,
            3296,
            "294c8b0bae51d656886e4be9e51d92cbb8da66a7beb91015554ba90bf8b7976b",
        ),
        (
            FACADE_ANNOTATION,
            804,
            "a58f3cd4fee43076435d2b47dbd292cb4c2d4ce35111514aad328733d751266c",
        ),
    ),
)
def test_updated_annotation_fixture_hashes_are_locked(
    path: Path,
    expected_size: int,
    expected_sha256: str,
) -> None:
    canonical = annotation_to_canonical_json(load_annotation(path)).encode("utf-8")
    assert len(canonical) == expected_size
    assert hashlib.sha256(canonical).hexdigest() == expected_sha256
