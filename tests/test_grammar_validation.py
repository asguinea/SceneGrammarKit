"""Semantic grammar-validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from scene_grammar_kit.grammar import (
    GrammarValidationError,
    ValidationSeverity,
    grammar_from_json,
    load_grammar,
    validate_grammar,
)

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "valid_terminal.json",
        "valid_repeat.json",
        "valid_split.json",
        "valid_nested_urban.json",
        "valid_nested_repeats.json",
    ],
)
def test_valid_grammars_pass_semantic_validation(fixture_name: str) -> None:
    """Valid symbolic terminal, repeat, split, and nested grammars pass."""
    report = validate_grammar(load_grammar(FIXTURES / fixture_name))
    assert report.is_valid
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.diagnostics == ()


def test_duplicate_node_ids_produce_structured_diagnostic() -> None:
    """Duplicate IDs identify the repeated value and its structural path."""
    grammar = load_grammar(FIXTURES / "duplicate_node_ids.json")
    report = validate_grammar(grammar)
    assert not report.is_valid
    assert report.error_count == 1
    diagnostic = report.diagnostics[0]
    assert diagnostic.code == "duplicate_node_id"
    assert diagnostic.severity is ValidationSeverity.ERROR
    assert diagnostic.node_id == "duplicate_terminal"
    assert diagnostic.path == "root.children[1].node"
    assert "root.children[0].node" in diagnostic.message


def test_diagnostic_order_is_deterministic() -> None:
    """Repeated preorder validation yields identical ordered diagnostics."""
    grammar = load_grammar(FIXTURES / "duplicate_node_ids.json")
    assert validate_grammar(grammar) == validate_grammar(grammar)


def test_relative_split_weights_need_not_sum_to_one() -> None:
    """Phase 0 split weights are relative rather than normalized inputs."""
    grammar = load_grammar(FIXTURES / "valid_split.json")
    assert validate_grammar(grammar).is_valid


def test_unsupported_schema_version_fails_during_loading() -> None:
    """The strict model layer rejects unsupported persisted schema versions."""
    text = (FIXTURES / "valid_terminal.json").read_text(encoding="utf-8")
    with pytest.raises(GrammarValidationError, match="schema_version"):
        grammar_from_json(text.replace('"0.1"', '"9.9"', 1))


def test_semantic_validator_defends_against_mutated_schema_version() -> None:
    """Validation remains defensive for malformed direct in-memory objects."""
    grammar = load_grammar(FIXTURES / "valid_terminal.json")
    object.__setattr__(grammar, "schema_version", "9.9")
    report = validate_grammar(grammar)
    assert report.diagnostics[0].code == "unsupported_schema_version"


def test_excessive_depth_fails_safely() -> None:
    """Traversal stops with a path-bearing depth diagnostic."""
    grammar = load_grammar(FIXTURES / "deeply_nested.json")
    report = validate_grammar(grammar, max_depth=2)
    diagnostic = next(
        item for item in report.diagnostics if item.code == "maximum_depth_exceeded"
    )
    assert diagnostic.path == "root.element.element.element"
    assert diagnostic.node_id == "repeat_3"


@pytest.mark.parametrize("max_depth", [0, -1, True, 1.5, "3"])
def test_invalid_maximum_depth_is_rejected(max_depth: object) -> None:
    """Depth configuration must be a positive integer."""
    grammar = load_grammar(FIXTURES / "valid_terminal.json")
    with pytest.raises(ValueError, match="positive integer"):
        validate_grammar(grammar, max_depth=max_depth)  # type: ignore[arg-type]


def test_malformed_direct_weight_is_reported_without_crash() -> None:
    """A corrupted in-memory child weight produces a stable diagnostic."""
    grammar = load_grammar(FIXTURES / "valid_split.json")
    child = grammar.root.children[0]  # type: ignore[union-attr]
    object.__setattr__(child, "weight", float("nan"))
    report = validate_grammar(grammar)
    assert any(item.code == "invalid_split_weight" for item in report.diagnostics)


def test_malformed_direct_attribute_key_is_reported() -> None:
    """An unrepresentable empty attribute key is handled defensively."""
    grammar = load_grammar(FIXTURES / "valid_terminal.json")
    object.__setattr__(grammar.root, "attributes", {"": 1})
    report = validate_grammar(grammar)
    assert any(item.code == "invalid_attribute_key" for item in report.diagnostics)


def test_object_identity_cycle_is_detected() -> None:
    """A deliberately corrupted in-memory cycle cannot recurse indefinitely."""
    grammar = load_grammar(FIXTURES / "valid_repeat.json")
    repeat = grammar.root
    object.__setattr__(repeat, "element", repeat)
    report = validate_grammar(grammar)
    assert any(item.code == "cycle_detected" for item in report.diagnostics)
