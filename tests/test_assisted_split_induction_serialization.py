"""Canonical report and grammar serialization tests for Batch 2.4."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scene_grammar_kit.assisted import (
    SplitInductionSerializationError,
    induce_split_grammar,
    lift_assisted_input,
    load_annotation,
    load_construction_config,
    split_induction_report_from_json,
    split_induction_report_to_canonical_json,
    split_induction_report_to_text,
)
from scene_grammar_kit.grammar import grammar_to_canonical_json

FIXTURES = Path(__file__).parent / "fixtures" / "assisted"


@pytest.fixture(scope="module")
def result():
    annotation = load_annotation(FIXTURES / "valid" / "urban_minimal.annotation.json")
    config = load_construction_config(
        FIXTURES / "valid" / "urban_minimal.construction.json"
    )
    lifted = lift_assisted_input(annotation, config).scene
    return induce_split_grammar(annotation, config, lifted)


def test_report_round_trip_equality_and_bytes(result) -> None:
    text = split_induction_report_to_canonical_json(result.report)
    parsed = split_induction_report_from_json(text)
    assert parsed == result.report
    assert split_induction_report_to_canonical_json(parsed) == text


def test_report_is_compact_unicode_and_has_no_final_newline(result) -> None:
    unicode_report = replace(
        result.report,
        warnings=("façade Δ",),
    )
    text = split_induction_report_to_canonical_json(unicode_report)
    assert "façade Δ" in text
    assert "\\u00e7" not in text
    assert "\n" not in text
    assert not text.endswith("\n")


def test_decision_mapping_and_member_order_survive_round_trip(result) -> None:
    parsed = split_induction_report_from_json(
        split_induction_report_to_canonical_json(result.report)
    )
    assert parsed.axis_decisions == result.report.axis_decisions
    assert parsed.boundary_decisions == result.report.boundary_decisions
    assert parsed.gap_decisions == result.report.gap_decisions
    assert parsed.node_mappings == result.report.node_mappings
    assert parsed.repeat_candidates[0].ordered_source_member_ids == (
        "car_1",
        "car_2",
        "car_3",
    )


def test_report_rejects_nan_and_infinity(result) -> None:
    text = split_induction_report_to_canonical_json(result.report)
    for replacement in ("NaN", "Infinity", "-Infinity"):
        invalid = text.replace(
            '"canonical_grammar_byte_size":',
            f'"canonical_grammar_byte_size":{replacement},"discard":',
            1,
        )
        with pytest.raises(SplitInductionSerializationError):
            split_induction_report_from_json(invalid)


def test_report_serializer_rejects_wrong_type() -> None:
    with pytest.raises(SplitInductionSerializationError):
        split_induction_report_to_canonical_json(object())  # type: ignore[arg-type]


def test_grammar_and_report_are_identical_across_repeated_induction(result) -> None:
    second = induce_split_grammar(
        result.annotation,
        result.construction_config,
        result.lifted_observations,
    )
    assert grammar_to_canonical_json(
        second.induced_grammar
    ) == grammar_to_canonical_json(result.induced_grammar)
    assert split_induction_report_to_canonical_json(
        second.report
    ) == split_induction_report_to_canonical_json(result.report)


def test_canonical_artifacts_have_no_absolute_paths_or_timestamps(result) -> None:
    grammar = grammar_to_canonical_json(result.induced_grammar)
    report = split_induction_report_to_canonical_json(result.report)
    combined = grammar + report
    assert str(Path.cwd()) not in combined
    assert "C:\\\\" not in combined
    assert "timestamp" not in combined.lower()
    assert "username" not in combined.lower()


def test_human_readable_report_is_deterministic_and_one_newline(result) -> None:
    first = split_induction_report_to_text(result.report)
    second = split_induction_report_to_text(result.report)
    assert first == second
    assert first.endswith("\n")
    assert not first.endswith("\n\n")
    assert "Root depth split" in first
    assert "Source-to-node mapping" in first
    assert "Repeat candidates deferred" in first
    assert "repeat_nodes=0" in first
    first.encode("ascii")
