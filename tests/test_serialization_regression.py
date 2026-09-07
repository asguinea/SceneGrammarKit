"""Regression locks for Batch 1.2 canonical fixture bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scene_grammar_kit.grammar import grammar_to_canonical_json, load_grammar

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"


@pytest.mark.parametrize(
    ("fixture_name", "byte_size", "sha256"),
    [
        (
            "valid_terminal.json",
            277,
            "267a92cf69dd366dc3b95a2c8ebf652b6a86cbe91d0ad5c4e3bbd101a7a231d4",
        ),
        (
            "valid_split.json",
            409,
            "d85792e0bc485323bbbde2a589b03934032f4225ad7d2e8d6f21d0cbe36f67c5",
        ),
        (
            "valid_repeat.json",
            299,
            "81c9571d8a5e5a4618d48b4b47c1236d814286e107a9e3db5612ad29cd288378",
        ),
        (
            "valid_nested_urban.json",
            986,
            "7966e8d5858060aa9ed496c8e4c45e04667c0ed083ff997f019947418b8137bc",
        ),
    ],
)
def test_batch_12_canonical_bytes_are_unchanged(
    fixture_name: str,
    byte_size: int,
    sha256: str,
) -> None:
    """Existing fixture serialization remains byte-for-byte unchanged."""
    canonical = grammar_to_canonical_json(load_grammar(FIXTURES / fixture_name)).encode(
        "utf-8"
    )
    assert len(canonical) == byte_size
    assert hashlib.sha256(canonical).hexdigest() == sha256
