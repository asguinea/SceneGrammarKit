"""Persistence, integrated workflow, and CLI tests for Batch 2.5."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    REPEAT_INDUCTION_ARTIFACT_FILENAMES,
    RepeatInductionFileExistsError,
    RepeatInductionValidationError,
    induce_repeat_grammar,
    induce_repeat_grammar_from_files,
    induce_split_grammar,
    lift_assisted_input,
    load_annotation,
    load_construction_config,
    repeat_induction_report_from_json,
    save_repeat_induction_result,
    save_split_induction_result,
)
from scene_grammar_kit.cli import build_parser, main
from scene_grammar_kit.grammar import load_grammar, validate_grammar

VALID = Path(__file__).parent / "fixtures" / "assisted" / "valid"
ANNOTATION = VALID / "urban_minimal.annotation.json"
CONFIG = VALID / "urban_minimal.construction.json"


@pytest.fixture()
def repeat_result():
    annotation = load_annotation(ANNOTATION)
    config = load_construction_config(CONFIG)
    lifted = lift_assisted_input(annotation, config).scene
    split = induce_split_grammar(annotation, config, lifted)
    return induce_repeat_grammar(annotation, config, lifted, split)


def test_persistence_writes_required_files(tmp_path: Path, repeat_result) -> None:
    saved = save_repeat_induction_result(repeat_result, tmp_path / "output")
    assert {item.name for item in saved.output_directory.iterdir()} == set(
        REPEAT_INDUCTION_ARTIFACT_FILENAMES
    )
    assert validate_grammar(load_grammar(saved.repeat_grammar_path)).is_valid
    assert (
        repeat_induction_report_from_json(
            saved.report_json_path.read_text(encoding="utf-8")
        )
        == repeat_result.report
    )


def test_no_execution_omits_only_execution_files(
    tmp_path: Path,
    repeat_result,
) -> None:
    original = repeat_result
    result = induce_repeat_grammar(
        original.annotation,
        original.construction_config,
        original.lifted_observations,
        original.split_induction_result,
        verify_execution=False,
    )
    saved = save_repeat_induction_result(result, tmp_path / "output")
    names = {item.name for item in saved.output_directory.iterdir()}
    assert "split_only_execution_report.json" not in names
    assert "repeat_execution_report.json" not in names
    assert names == set(REPEAT_INDUCTION_ARTIFACT_FILENAMES) - {
        "split_only_execution_report.json",
        "repeat_execution_report.json",
    }


def test_nonempty_protection_and_overwrite_preserve_unrelated(
    tmp_path: Path,
    repeat_result,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    unrelated = output / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    with pytest.raises(RepeatInductionFileExistsError):
        save_repeat_induction_result(repeat_result, output)
    save_repeat_induction_result(repeat_result, output, overwrite=True)
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_success_report_is_written_last(
    tmp_path: Path,
    repeat_result,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scene_grammar_kit.assisted.repeat_induction_persistence as persistence

    names: list[str] = []
    original = persistence._atomic_write_text

    def recording(text: str, path: Path) -> None:
        names.append(path.name)
        original(text, path)

    monkeypatch.setattr(persistence, "_atomic_write_text", recording)
    save_repeat_induction_result(repeat_result, tmp_path / "output")
    assert names[-1] == "repeat_induction_report.json"
    assert not list((tmp_path / "output").glob("*.tmp"))


def test_integrated_workflow_and_precomputed_bundle_match(tmp_path: Path) -> None:
    direct = induce_repeat_grammar_from_files(ANNOTATION, CONFIG, tmp_path / "direct")
    save_split_induction_result(
        direct.split_induction_result,
        tmp_path / "split",
    )
    precomputed = induce_repeat_grammar_from_files(
        ANNOTATION,
        CONFIG,
        tmp_path / "precomputed",
        split_induction_directory=tmp_path / "split",
    )
    assert direct.repeat_grammar == precomputed.repeat_grammar
    assert direct.report == precomputed.report


def test_precomputed_bundle_missing_report_fails(tmp_path: Path) -> None:
    directory = tmp_path / "split"
    directory.mkdir()
    with pytest.raises(
        RepeatInductionValidationError,
        match="incomplete_split_induction_bundle",
    ):
        induce_repeat_grammar_from_files(
            ANNOTATION,
            CONFIG,
            tmp_path / "output",
            split_induction_directory=directory,
        )


def test_fatal_overwrite_removes_only_stale_success_report(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    stale = output / "repeat_induction_report.json"
    unrelated = output / "notes.txt"
    stale.write_text('{"success":true}', encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")
    missing = tmp_path / "incomplete"
    missing.mkdir()
    with pytest.raises(RepeatInductionValidationError):
        induce_repeat_grammar_from_files(
            ANNOTATION,
            CONFIG,
            output,
            split_induction_directory=missing,
            overwrite=True,
        )
    assert not stale.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_repeat_cli_success_and_help(tmp_path: Path, capsys) -> None:
    assert "induce-repeat-grammar" in build_parser().format_help()
    output = tmp_path / "output"
    code = main(
        [
            "induce-repeat-grammar",
            str(ANNOTATION),
            "--config",
            str(CONFIG),
            "--out",
            str(output),
        ]
    )
    text = capsys.readouterr().out
    assert code == 0
    assert "REPEAT INDUCTION COMPLETE" in text
    assert "accepted_groups=1" in text
    assert "repeat_nodes=1" in text


def test_cli_nonempty_failure_has_no_traceback(
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep.txt").write_text("x", encoding="utf-8")
    code = main(
        [
            "induce-repeat-grammar",
            str(ANNOTATION),
            "--config",
            str(CONFIG),
            "--out",
            str(output),
        ]
    )
    text = capsys.readouterr().out
    assert code == 2
    assert "REPEAT INDUCTION FAILED" in text
    assert "Traceback" not in text


def test_cli_no_verify_execution(tmp_path: Path, capsys) -> None:
    output = tmp_path / "output"
    assert (
        main(
            [
                "induce-repeat-grammar",
                str(ANNOTATION),
                "--config",
                str(CONFIG),
                "--out",
                str(output),
                "--no-verify-execution",
            ]
        )
        == 0
    )
    assert "execution_verified=false" in capsys.readouterr().out
    assert not (output / "repeat_execution_report.json").exists()


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    induce_repeat_grammar_from_files(ANNOTATION, CONFIG, first)
    induce_repeat_grammar_from_files(ANNOTATION, CONFIG, second)
    for filename in REPEAT_INDUCTION_ARTIFACT_FILENAMES:
        left = (first / filename).read_bytes()
        right = (second / filename).read_bytes()
        assert left == right
        assert hashlib.sha256(left).hexdigest() == hashlib.sha256(right).hexdigest()
