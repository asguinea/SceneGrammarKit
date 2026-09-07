"""Canonical edit serialization and safe artifact persistence tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scene_grammar_kit.editing import (
    EditFileExistsError,
    EditWriteError,
    SetRepeatCount,
    SetSplitChildWeight,
    apply_edit,
    edit_operation_to_canonical_json,
    edit_report_to_canonical_json,
    save_edit_report,
    save_edit_result,
)
from scene_grammar_kit.grammar import grammar_to_canonical_json, load_grammar

FIXTURE = Path(__file__).parent / "fixtures" / "grammars" / "editable_urban.json"


def result():
    return apply_edit(
        load_grammar(FIXTURE),
        SetSplitChildWeight("midground_layout", "road_region", 8),
    )


def test_operation_json_is_exact_and_byte_stable() -> None:
    operation = SetRepeatCount("parked_cars", 6)
    expected = (
        '{"new_count":6,"operation_type":"set_repeat_count",'
        '"repeat_node_id":"parked_cars"}'
    )
    assert edit_operation_to_canonical_json(operation) == expected
    assert edit_operation_to_canonical_json(operation).encode() == expected.encode()


def test_report_json_is_standard_deterministic_environment_free_json() -> None:
    edit_result = result()
    first = edit_report_to_canonical_json(edit_result.report)
    second = edit_report_to_canonical_json(edit_result.report)
    assert first == second
    assert not first.endswith("\n")
    parsed = json.loads(first)
    assert parsed["success"] is True
    assert parsed["editing_policy_version"] == "0.1"
    assert parsed["operations"][0]["operation_type"] == "set_split_child_weight"
    assert "timestamp" not in first
    assert str(Path.cwd()) not in first


def test_save_report_parent_policy_and_overwrite(tmp_path: Path) -> None:
    edit_result = result()
    path = tmp_path / "nested" / "edit_report.json"
    with pytest.raises(EditWriteError, match="parent does not exist"):
        save_edit_report(edit_result.report, path)
    saved = save_edit_report(edit_result.report, path, create_parents=True)
    assert saved == path.resolve()
    assert saved.read_bytes() == edit_report_to_canonical_json(
        edit_result.report
    ).encode("utf-8")
    with pytest.raises(EditFileExistsError):
        save_edit_report(edit_result.report, path)
    save_edit_report(edit_result.report, path, overwrite=True)


def test_save_result_writes_exact_canonical_artifact_set(tmp_path: Path) -> None:
    edit_result = result()
    root = save_edit_result(edit_result, tmp_path / "edit")
    assert {item.name for item in root.iterdir()} == {
        "grammar_before.json",
        "grammar_after.json",
        "edit_report.json",
    }
    assert (root / "grammar_before.json").read_bytes() == (
        grammar_to_canonical_json(edit_result.original_grammar).encode("utf-8")
    )
    assert (root / "grammar_after.json").read_bytes() == (
        grammar_to_canonical_json(edit_result.edited_grammar).encode("utf-8")
    )
    assert (root / "edit_report.json").read_bytes() == (
        edit_report_to_canonical_json(edit_result.report).encode("utf-8")
    )


def test_save_result_refuses_nonempty_and_preserves_unrelated_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "edit"
    root.mkdir()
    sentinel = root / "user-note.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(EditFileExistsError, match="not empty"):
        save_edit_result(result(), root)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    save_edit_result(result(), root, overwrite=True)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_save_result_explicit_overwrite_updates_known_files(tmp_path: Path) -> None:
    root = tmp_path / "edit"
    first = apply_edit(
        load_grammar(FIXTURE),
        SetRepeatCount("parked_cars", 5),
    )
    second = apply_edit(
        load_grammar(FIXTURE),
        SetRepeatCount("parked_cars", 6),
    )
    save_edit_result(first, root)
    first_after = (root / "grammar_after.json").read_bytes()
    save_edit_result(second, root, overwrite=True)
    assert (root / "grammar_after.json").read_bytes() != first_after
    assert (root / "grammar_after.json").read_bytes() == (
        grammar_to_canonical_json(second.edited_grammar).encode("utf-8")
    )
