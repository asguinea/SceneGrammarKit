"""Persistence, path workflow, CLI, and regression tests for Batch 2.4."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    SplitInductionFileExistsError,
    SplitInductionWriteError,
    induce_split_grammar,
    induce_split_grammar_from_files,
    lift_assisted_input,
    lifted_scene_to_canonical_json,
    load_and_verify_source_image,
    load_annotation,
    load_construction_config,
    save_split_induction_result,
    split_induction_report_from_json,
)
from scene_grammar_kit.cli import main
from scene_grammar_kit.grammar import load_grammar, validate_grammar

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"
VALID = FIXTURES / "valid"


@pytest.fixture()
def urban_result():
    annotation_path = VALID / "urban_minimal.annotation.json"
    annotation = load_annotation(annotation_path)
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    verified = load_and_verify_source_image(annotation, annotation_path)
    lifted = lift_assisted_input(
        annotation,
        config,
        verified_source_image=verified,
    ).scene
    return induce_split_grammar(annotation, config, lifted)


def test_persistence_writes_required_canonical_files(
    tmp_path: Path,
    urban_result,
) -> None:
    saved = save_split_induction_result(urban_result, tmp_path / "output")
    expected = {
        "annotation.json",
        "construction_config.json",
        "lifted_observations.json",
        "induced_grammar.json",
        "grammar_tree.txt",
        "split_induction_report.json",
        "split_induction_report.txt",
        "execution_report.json",
    }
    assert {item.name for item in saved.output_directory.iterdir()} == expected
    assert load_grammar(saved.induced_grammar_path) == urban_result.induced_grammar
    assert validate_grammar(load_grammar(saved.induced_grammar_path)).is_valid
    assert (
        split_induction_report_from_json(
            saved.report_json_path.read_text(encoding="utf-8")
        )
        == urban_result.report
    )


def test_nonempty_output_protected_and_overwrite_preserves_unrelated(
    tmp_path: Path,
    urban_result,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    unrelated = output / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    with pytest.raises(SplitInductionFileExistsError):
        save_split_induction_result(urban_result, output)
    save_split_induction_result(urban_result, output, overwrite=True)
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_success_report_is_written_last(
    tmp_path: Path,
    urban_result,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scene_grammar_kit.assisted.split_induction_persistence as persistence

    names: list[str] = []
    original = persistence._atomic_write_text

    def recording(text: str, path: Path, *, overwrite: bool) -> None:
        names.append(path.name)
        original(text, path, overwrite=overwrite)

    monkeypatch.setattr(persistence, "_atomic_write_text", recording)
    save_split_induction_result(urban_result, tmp_path / "output")
    assert names[-1] == "split_induction_report.json"


def test_failed_write_removes_stale_success_and_temporary_files(
    tmp_path: Path,
    urban_result,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scene_grammar_kit.assisted.split_induction_persistence as persistence

    output = tmp_path / "output"
    save_split_induction_result(urban_result, output)
    original = persistence._atomic_write_text

    def failing(text: str, path: Path, *, overwrite: bool) -> None:
        if path.name == "induced_grammar.json":
            raise SplitInductionWriteError("injected failure")
        original(text, path, overwrite=overwrite)

    monkeypatch.setattr(persistence, "_atomic_write_text", failing)
    with pytest.raises(SplitInductionWriteError):
        save_split_induction_result(urban_result, output, overwrite=True)
    assert not (output / "split_induction_report.json").exists()
    assert not list(output.glob("*.tmp"))


def test_repeated_persistence_is_byte_identical(
    tmp_path: Path,
    urban_result,
) -> None:
    first = save_split_induction_result(urban_result, tmp_path / "first")
    second = save_split_induction_result(urban_result, tmp_path / "second")
    for name in (
        "annotation.json",
        "construction_config.json",
        "lifted_observations.json",
        "induced_grammar.json",
        "grammar_tree.txt",
        "split_induction_report.json",
        "split_induction_report.txt",
        "execution_report.json",
    ):
        assert (first.output_directory / name).read_bytes() == (
            second.output_directory / name
        ).read_bytes()


def test_path_workflow_computes_or_loads_lifted_observations(
    tmp_path: Path,
) -> None:
    annotation = VALID / "urban_minimal.annotation.json"
    config = VALID / "urban_minimal.construction.json"
    computed = induce_split_grammar_from_files(
        annotation,
        config,
        tmp_path / "computed",
    )
    precomputed = induce_split_grammar_from_files(
        annotation,
        config,
        tmp_path / "precomputed",
        lifted_scene_path=(tmp_path / "computed" / "lifted_observations.json"),
    )
    assert precomputed.induced_grammar == computed.induced_grammar
    assert precomputed.report == computed.report


def test_path_workflow_can_disable_execution_and_image_verification(
    tmp_path: Path,
) -> None:
    result = induce_split_grammar_from_files(
        VALID / "urban_minimal.annotation.json",
        VALID / "urban_minimal.construction.json",
        tmp_path / "output",
        verify_image=False,
        verify_execution=False,
    )
    assert result.execution_verification_result is None
    assert result.report.execution_verification_status is False
    assert not (tmp_path / "output" / "execution_report.json").exists()
    assert result.lifted_observations.image_verification_status is False


def test_cli_canonical_urban_and_precomputed_commands_succeed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "first"
    code = main(
        [
            "induce-split-grammar",
            str(VALID / "urban_minimal.annotation.json"),
            "--config",
            str(VALID / "urban_minimal.construction.json"),
            "--out",
            str(first),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "SPLIT INDUCTION COMPLETE" in output
    assert "observations=9" in output
    assert "represented=9" in output
    assert "repeat_nodes=0" in output
    assert "execution_verified=true" in output

    second = tmp_path / "second"
    code = main(
        [
            "induce-split-grammar",
            str(VALID / "urban_minimal.annotation.json"),
            "--config",
            str(VALID / "urban_minimal.construction.json"),
            "--lifted-observations",
            str(first / "lifted_observations.json"),
            "--out",
            str(second),
        ]
    )
    assert code == 0
    assert (first / "induced_grammar.json").read_bytes() == (
        second / "induced_grammar.json"
    ).read_bytes()


def test_cli_no_verify_execution_and_nonempty_protection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "output"
    args = [
        "induce-split-grammar",
        str(VALID / "urban_minimal.annotation.json"),
        "--config",
        str(VALID / "urban_minimal.construction.json"),
        "--out",
        str(output),
        "--no-verify-execution",
    ]
    assert main(args) == 0
    text = capsys.readouterr().out
    assert "execution_verified=false" in text
    assert not (output / "execution_report.json").exists()
    assert main(args) == 2
    failed = capsys.readouterr().out
    assert "SPLIT INDUCTION FAILED" in failed
    assert "Traceback" not in failed


@pytest.mark.parametrize(
    ("annotation", "config"),
    [
        (
            FIXTURES / "invalid" / "invalid_polygon.annotation.json",
            VALID / "default.construction.json",
        ),
        (
            VALID / "urban_minimal.annotation.json",
            FIXTURES / "invalid" / "invalid_depth_intervals.construction.json",
        ),
    ],
)
def test_cli_invalid_inputs_fail_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    annotation: Path,
    config: Path,
) -> None:
    code = main(
        [
            "induce-split-grammar",
            str(annotation),
            "--config",
            str(config),
            "--out",
            str(tmp_path / "output"),
        ]
    )
    assert code == 2
    text = capsys.readouterr().out
    assert "SPLIT INDUCTION FAILED" in text
    assert "Traceback" not in text


def test_cli_help_includes_command_and_all_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["induce-split-grammar", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    for option in (
        "--lifted-observations",
        "--overwrite",
        "--skip-image-verification",
        "--no-verify-execution",
        "--maximum-depth",
        "--maximum-primitives",
    ):
        assert option in text


def test_batch_2_3_verified_lifting_hash_remains_unchanged(
    urban_result,
) -> None:
    data = lifted_scene_to_canonical_json(urban_result.lifted_observations).encode(
        "utf-8"
    )
    assert len(data) == 18_362
    assert hashlib.sha256(data).hexdigest() == (
        "daa4346b1221c6130a3caf6b25254cd7ccbc3ab83bdc0c9cbb4a64207f37d6b7"
    )
