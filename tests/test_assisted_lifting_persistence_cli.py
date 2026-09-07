"""Safe lifting persistence, integrated API, CLI, and regression tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import scene_grammar_kit.assisted.lifting_persistence as lifting_persistence
from scene_grammar_kit.assisted import (
    LIFTING_ARTIFACT_FILENAMES,
    LiftingFileExistsError,
    LiftingValidationError,
    LiftingWriteError,
    annotation_to_canonical_json,
    construction_config_to_canonical_json,
    lift_assisted_input,
    lifted_scene_to_canonical_json,
    lifting_report_to_canonical_json,
    load_and_verify_source_image,
    load_annotation,
    load_construction_config,
    render_annotation_overlay,
    save_annotation,
    save_annotation_overlay,
    save_construction_config,
    save_lifted_scene,
    save_lifting_report,
    save_lifting_result,
)
from scene_grammar_kit.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"
VALID = FIXTURES / "valid"
INVALID = FIXTURES / "invalid"
URBAN_ANNOTATION = VALID / "urban_minimal.annotation.json"
URBAN_CONFIG = VALID / "urban_minimal.construction.json"
FACADE_ANNOTATION = VALID / "facade_polygon.annotation.json"
DEFAULT_CONFIG = VALID / "default.construction.json"


def _result(annotation_path: Path = URBAN_ANNOTATION, config_path: Path = URBAN_CONFIG):
    annotation = load_annotation(annotation_path)
    config = load_construction_config(config_path)
    verified = load_and_verify_source_image(annotation, annotation_path)
    return lift_assisted_input(annotation, config, verified_source_image=verified)


def _bytes(root: Path) -> dict[str, bytes]:
    return {name: (root / name).read_bytes() for name in LIFTING_ARTIFACT_FILENAMES}


def test_persistence_writes_five_canonical_files_report_last(
    tmp_path: Path,
) -> None:
    result = _result()
    saved = save_lifting_result(result, tmp_path / "output")
    assert tuple(sorted(path.name for path in saved.output_directory.iterdir())) == (
        tuple(sorted(LIFTING_ARTIFACT_FILENAMES))
    )
    assert saved.annotation_path.read_text("utf-8") == (
        annotation_to_canonical_json(result.annotation)
    )
    assert saved.construction_config_path.read_text("utf-8") == (
        construction_config_to_canonical_json(result.construction_config)
    )
    assert saved.lifted_scene_path.read_text("utf-8") == (
        lifted_scene_to_canonical_json(result.scene)
    )
    assert saved.report_path.read_text("utf-8") == (
        lifting_report_to_canonical_json(result.report)
    )
    assert saved.report_path.stat().st_mtime_ns >= max(
        path.stat().st_mtime_ns
        for path in (
            saved.annotation_path,
            saved.construction_config_path,
            saved.lifted_scene_path,
            saved.lifted_text_path,
        )
    )


def test_nonempty_output_and_individual_overwrite_are_protected(
    tmp_path: Path,
) -> None:
    result = _result()
    output = tmp_path / "output"
    output.mkdir()
    (output / "unrelated.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(LiftingFileExistsError, match="nonempty"):
        save_lifting_result(result, output)
    scene_path = save_lifted_scene(result.scene, tmp_path / "scene.json")
    report_path = save_lifting_report(result.report, tmp_path / "report.json")
    with pytest.raises(LiftingFileExistsError):
        save_lifted_scene(result.scene, scene_path)
    with pytest.raises(LiftingFileExistsError):
        save_lifting_report(result.report, report_path)
    save_lifted_scene(result.scene, scene_path, overwrite=True)
    save_lifting_report(result.report, report_path, overwrite=True)


def test_overwrite_preserves_unrelated_files(tmp_path: Path) -> None:
    result = _result()
    output = tmp_path / "output"
    save_lifting_result(result, output)
    unrelated = output / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    save_lifting_result(result, output, overwrite=True)
    assert unrelated.read_text("utf-8") == "keep"


def test_atomic_failure_cleans_temp_and_removes_stale_success_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    output = tmp_path / "output"
    save_lifting_result(result, output)
    original_replace = lifting_persistence.os.replace

    def fail_scene(source: object, target: object) -> None:
        if str(target).endswith("lifted_observations.json"):
            raise OSError("simulated lifted scene failure")
        original_replace(source, target)

    monkeypatch.setattr(lifting_persistence.os, "replace", fail_scene)
    with pytest.raises(LiftingWriteError, match="simulated"):
        save_lifting_result(result, output, overwrite=True)
    assert not (output / "lifting_report.json").exists()
    assert not tuple(output.glob(".*.tmp"))


def test_repeated_persistence_is_byte_identical(tmp_path: Path) -> None:
    result = _result()
    first = save_lifting_result(result, tmp_path / "first")
    second = save_lifting_result(result, tmp_path / "second")
    assert _bytes(first.output_directory) == _bytes(second.output_directory)


def test_repeated_lifting_produces_identical_models() -> None:
    first = _result()
    second = _result()
    assert first.scene == second.scene
    assert first.report == second.report


def test_polygon_integrated_lifting_succeeds() -> None:
    result = _result(FACADE_ANNOTATION, DEFAULT_CONFIG)
    assert len(result.scene.observations) == 1
    assert result.report.polygon_source_count == 1
    assert result.scene.observations[0].proxy_approximation.value == (
        "image_polygon_bounding_box"
    )


def test_individual_persistence_controls_parent_creation(
    tmp_path: Path,
) -> None:
    result = _result()
    target = tmp_path / "missing" / "scene.json"
    with pytest.raises(LiftingWriteError, match="does not exist"):
        save_lifted_scene(result.scene, target)
    assert save_lifted_scene(result.scene, target, create_parents=True).exists()


def test_invalid_annotation_fails_before_lifting() -> None:
    annotation = load_annotation(INVALID / "duplicate_ids.annotation.json")
    config = load_construction_config(URBAN_CONFIG)
    with pytest.raises(LiftingValidationError, match="before lifting"):
        lift_assisted_input(annotation, config)


def test_incompatible_config_fails_before_lifting() -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    config = replace(
        load_construction_config(URBAN_CONFIG),
        minimum_normalized_region_extent=0.2,
    )
    with pytest.raises(LiftingValidationError, match="before lifting"):
        lift_assisted_input(annotation, config)


def test_verified_image_facts_are_retained() -> None:
    result = _result()
    assert result.verified_source_image is not None
    assert result.scene.verified_source_image_sha256 == (
        result.verified_source_image.byte_sha256
    )
    assert result.report.source_image_sha256 == (
        result.verified_source_image.byte_sha256
    )


@pytest.mark.parametrize(
    ("annotation_path", "config_path", "scene_id"),
    (
        (URBAN_ANNOTATION, URBAN_CONFIG, "urban_assisted_minimal"),
        (FACADE_ANNOTATION, DEFAULT_CONFIG, "facade_polygon"),
    ),
)
def test_cli_valid_lifting_succeeds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    annotation_path: Path,
    config_path: Path,
    scene_id: str,
) -> None:
    output = tmp_path / scene_id
    status = main(
        [
            "lift-assisted-input",
            str(annotation_path),
            "--config",
            str(config_path),
            "--out",
            str(output),
        ]
    )
    assert status == 0
    printed = capsys.readouterr().out
    assert "LIFT COMPLETE" in printed
    assert f"scene={scene_id}" in printed
    assert "image_verified=true" in printed
    assert all((output / name).exists() for name in LIFTING_ARTIFACT_FILENAMES)


def test_cli_skip_image_verification_is_explicit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "output"
    status = main(
        [
            "lift-assisted-input",
            str(URBAN_ANNOTATION),
            "--config",
            str(URBAN_CONFIG),
            "--out",
            str(output),
            "--skip-image-verification",
        ]
    )
    assert status == 0
    assert "image_verified=false" in capsys.readouterr().out
    scene = json.loads((output / "lifted_observations.json").read_text("utf-8"))
    report = json.loads((output / "lifting_report.json").read_text("utf-8"))
    assert scene["verified_source_image_sha256"] is None
    assert report["source_image_sha256"] is None
    assert report["warnings"][0]["code"] == "image_verification_skipped"


@pytest.mark.parametrize(
    ("annotation_path", "config_path"),
    (
        (INVALID / "duplicate_ids.annotation.json", URBAN_CONFIG),
        (
            URBAN_ANNOTATION,
            INVALID / "invalid_depth_intervals.construction.json",
        ),
    ),
)
def test_cli_invalid_inputs_fail_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    annotation_path: Path,
    config_path: Path,
) -> None:
    status = main(
        [
            "lift-assisted-input",
            str(annotation_path),
            "--config",
            str(config_path),
            "--out",
            str(tmp_path / "output"),
        ]
    )
    captured = capsys.readouterr()
    assert status != 0
    assert "ASSISTED LIFT FAILED" in captured.out
    assert "Traceback" not in captured.out + captured.err


def test_cli_compatibility_failure_is_clean(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = replace(
        load_construction_config(URBAN_CONFIG),
        minimum_normalized_region_extent=0.2,
    )
    config_path = save_construction_config(config, tmp_path / "incompatible.json")
    status = main(
        [
            "lift-assisted-input",
            str(URBAN_ANNOTATION),
            "--config",
            str(config_path),
            "--out",
            str(tmp_path / "output"),
        ]
    )
    assert status != 0
    assert "ASSISTED LIFT FAILED" in capsys.readouterr().out


def test_cli_missing_image_fails_but_skip_succeeds(
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
    annotation_path = save_annotation(missing, tmp_path / "annotation.json")
    arguments = [
        "lift-assisted-input",
        str(annotation_path),
        "--config",
        str(URBAN_CONFIG),
        "--out",
        str(tmp_path / "output"),
    ]
    assert main(arguments) != 0
    assert "ASSISTED LIFT FAILED" in capsys.readouterr().out
    assert main(arguments + ["--skip-image-verification"]) == 0


def test_cli_dimension_and_hash_mismatches_fail_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    source = tmp_path / "source"
    (source / "images").mkdir(parents=True)
    (source / "images" / "urban_minimal.png").write_bytes(
        (VALID / "images" / "urban_minimal.png").read_bytes()
    )
    for name, source_ref in (
        (
            "dimension",
            replace(
                annotation.source_image,
                pixel_width=479,
                sha256=None,
            ),
        ),
        (
            "hash",
            replace(annotation.source_image, sha256="0" * 64),
        ),
    ):
        path = save_annotation(
            replace(annotation, source_image=source_ref),
            source / f"{name}.json",
        )
        status = main(
            [
                "lift-assisted-input",
                str(path),
                "--config",
                str(URBAN_CONFIG),
                "--out",
                str(tmp_path / name),
            ]
        )
        assert status != 0
        assert "Traceback" not in capsys.readouterr().out


def test_cli_nonempty_output_protection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    status = main(
        [
            "lift-assisted-input",
            str(URBAN_ANNOTATION),
            "--config",
            str(URBAN_CONFIG),
            "--out",
            str(output),
        ]
    )
    assert status != 0
    assert (output / "keep.txt").read_text("utf-8") == "keep"
    assert "ASSISTED LIFT FAILED" in capsys.readouterr().out


def test_help_includes_lift_assisted_input(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "lift-assisted-input" in capsys.readouterr().out


def test_batch_2_2_overlay_is_deterministic_within_environment(tmp_path: Path) -> None:
    annotation = load_annotation(URBAN_ANNOTATION)
    verified = load_and_verify_source_image(annotation, URBAN_ANNOTATION)
    first = render_annotation_overlay(verified, annotation)
    second = render_annotation_overlay(verified, annotation)
    first_path = save_annotation_overlay(first, tmp_path / "overlay-first.png")
    second_path = save_annotation_overlay(second, tmp_path / "overlay-second.png")
    assert first.image.size == verified.image.size
    assert first.image.mode == "RGBA"
    assert first.image.tobytes() != verified.image.tobytes()
    assert first.image.tobytes() == second.image.tobytes()
    assert first.report == second.report
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
