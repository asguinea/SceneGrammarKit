"""Canonical serialization and safe-persistence tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scene_grammar_kit.grammar import (
    GrammarFileExistsError,
    GrammarFileNotFoundError,
    GrammarJSONError,
    GrammarValidationError,
    SplitNode,
    TerminalNode,
    grammar_from_json,
    grammar_to_canonical_json,
    load_grammar,
    save_grammar,
)

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"


def test_json_round_trip_preserves_structural_equality() -> None:
    """Typed structural equality survives a JSON round trip."""
    original = load_grammar(FIXTURES / "valid_nested_urban.json")
    loaded = grammar_from_json(grammar_to_canonical_json(original))
    assert loaded == original


def test_canonical_json_is_byte_stable() -> None:
    """Repeated canonical serialization yields identical UTF-8 bytes."""
    grammar = load_grammar(FIXTURES / "valid_nested_urban.json")
    first = grammar_to_canonical_json(grammar).encode("utf-8")
    second = grammar_to_canonical_json(grammar).encode("utf-8")
    reloaded = grammar_from_json(first.decode("utf-8"))
    third = grammar_to_canonical_json(reloaded).encode("utf-8")
    assert first == second == third
    assert not first.endswith(b"\n")


def test_child_ordering_is_preserved() -> None:
    """Canonical key sorting does not reorder split children."""
    grammar = load_grammar(FIXTURES / "valid_split.json")
    assert isinstance(grammar.root, SplitNode)
    serialized = json.loads(grammar_to_canonical_json(grammar))
    node_ids = [child["node"]["node_id"] for child in serialized["root"]["children"]]
    assert node_ids == ["left", "right"]


def test_dictionary_order_does_not_affect_canonical_output() -> None:
    """Attribute insertion order has no effect on canonical bytes."""
    first_text = (FIXTURES / "valid_terminal.json").read_text(encoding="utf-8")
    first = grammar_from_json(first_text)
    data = json.loads(first_text)
    data["root"]["attributes"] = {"roughness": 0.8, "material": "asphalt"}
    second = grammar_from_json(json.dumps(data))
    assert grammar_to_canonical_json(first) == grammar_to_canonical_json(second)


def test_saving_and_loading_file_succeeds(tmp_path: Path) -> None:
    """Safe persistence writes canonical UTF-8 and returns an absolute path."""
    grammar = load_grammar(FIXTURES / "valid_repeat.json")
    output = save_grammar(
        grammar,
        tmp_path / "nested" / "grammar.json",
        create_parents=True,
    )
    assert output.is_absolute()
    assert load_grammar(output) == grammar
    assert output.read_bytes() == grammar_to_canonical_json(grammar).encode("utf-8")


def test_saving_does_not_silently_overwrite(tmp_path: Path) -> None:
    """An existing target remains unchanged without explicit overwrite."""
    grammar = load_grammar(FIXTURES / "valid_terminal.json")
    output = tmp_path / "grammar.json"
    output.write_text("sentinel", encoding="utf-8")
    with pytest.raises(GrammarFileExistsError, match="overwrite=True"):
        save_grammar(grammar, output)
    assert output.read_text(encoding="utf-8") == "sentinel"


def test_explicit_overwrite_replaces_existing_file(tmp_path: Path) -> None:
    """Explicit overwrite permission replaces the complete target atomically."""
    grammar = load_grammar(FIXTURES / "valid_terminal.json")
    output = tmp_path / "grammar.json"
    output.write_text("old", encoding="utf-8")
    save_grammar(grammar, output, overwrite=True)
    assert load_grammar(output) == grammar


def test_missing_file_has_domain_error(tmp_path: Path) -> None:
    """Missing files produce a path-bearing grammar-domain exception."""
    missing = tmp_path / "missing.json"
    with pytest.raises(GrammarFileNotFoundError, match="missing.json"):
        load_grammar(missing)


def test_invalid_json_has_domain_error() -> None:
    """Malformed JSON is distinguished from schema validation errors."""
    with pytest.raises(GrammarJSONError, match="Invalid grammar JSON"):
        grammar_from_json('{"root":')


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_nonfinite_json_is_rejected(constant: str) -> None:
    """Python's permissive nonfinite JSON constants are explicitly disabled."""
    text = (FIXTURES / "valid_repeat.json").read_text(encoding="utf-8")
    text = text.replace('"spacing": 0.1', f'"spacing": {constant}')
    with pytest.raises(GrammarJSONError, match="non-finite"):
        grammar_from_json(text)


def test_validation_error_identifies_nested_field() -> None:
    """Nested validation messages identify the relevant node path."""
    text = (FIXTURES / "valid_repeat.json").read_text(encoding="utf-8")
    text = text.replace('"semantic_class": "car"', '"semantic_class": ""')
    with pytest.raises(GrammarValidationError, match="semantic_class"):
        grammar_from_json(text)


def test_unexpected_root_field_is_rejected() -> None:
    """The strict root document rejects undeclared extension fields."""
    data = json.loads((FIXTURES / "valid_terminal.json").read_text(encoding="utf-8"))
    data["timestamp"] = "not-permitted"
    with pytest.raises(GrammarValidationError, match="unexpected field"):
        grammar_from_json(json.dumps(data))


def test_terminal_root_type_after_load() -> None:
    """The discriminated union produces the concrete terminal class."""
    grammar = load_grammar(FIXTURES / "valid_terminal.json")
    assert isinstance(grammar.root, TerminalNode)
