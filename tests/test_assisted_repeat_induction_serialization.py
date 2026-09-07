"""Canonical report serialization tests for Batch 2.5."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    RepeatInductionSerializationError,
    induce_repeat_grammar,
    induce_split_grammar,
    lift_assisted_input,
    load_annotation,
    load_construction_config,
    repeat_induction_report_from_json,
    repeat_induction_report_to_canonical_json,
    repeat_induction_report_to_text,
)

VALID = Path(__file__).parent / "fixtures" / "assisted" / "valid"


@pytest.fixture(scope="module")
def report():
    annotation = load_annotation(VALID / "urban_minimal.annotation.json")
    config = load_construction_config(VALID / "urban_minimal.construction.json")
    lifted = lift_assisted_input(annotation, config).scene
    split = induce_split_grammar(annotation, config, lifted)
    return induce_repeat_grammar(annotation, config, lifted, split).report


def test_report_round_trip_and_canonical_bytes_are_stable(report) -> None:
    text = repeat_induction_report_to_canonical_json(report)
    restored = repeat_induction_report_from_json(text)
    assert restored == report
    assert repeat_induction_report_to_canonical_json(restored) == text
    assert text == repeat_induction_report_to_canonical_json(report)


def test_serialization_preserves_list_order_and_unicode(report) -> None:
    changed = replace(
        report,
        warnings=("évidence", "第二"),
        explicitly_not_inferred=("β pixels", *report.explicitly_not_inferred),
    )
    text = repeat_induction_report_to_canonical_json(changed)
    assert "évidence" in text
    assert "第二" in text
    assert repeat_induction_report_from_json(text).warnings == (
        "évidence",
        "第二",
    )


def test_nonfinite_serialization_and_parsing_are_rejected(report) -> None:
    metrics = replace(
        report.group_decisions[0].metrics,
        estimated_spacing=float("nan"),
    )
    decision = replace(report.group_decisions[0], metrics=metrics)
    with pytest.raises(RepeatInductionSerializationError):
        repeat_induction_report_to_canonical_json(
            replace(report, group_decisions=(decision,))
        )
    with pytest.raises(RepeatInductionSerializationError):
        repeat_induction_report_from_json('{"x":NaN}')


def test_report_text_is_deterministic_and_has_one_final_newline(report) -> None:
    first = repeat_induction_report_to_text(report)
    assert first == repeat_induction_report_to_text(report)
    assert first.endswith("\n")
    assert not first.endswith("\n\n")
    assert "supplied_members=car_1,car_2,car_3" in first
    assert "Explicitly not inferred" in first


def test_invalid_json_types_fail_cleanly() -> None:
    with pytest.raises(RepeatInductionSerializationError):
        repeat_induction_report_from_json("[]")
    with pytest.raises(RepeatInductionSerializationError):
        repeat_induction_report_from_json(123)  # type: ignore[arg-type]
