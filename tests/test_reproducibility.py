"""Tests for deterministic seed behavior."""

import random

from scene_grammar_kit.reproducibility import seed_everything


def test_seed_everything_repeats_python_sequence() -> None:
    """The same seed reproduces Python random values and returns a summary."""
    first_summary = seed_everything(2026)
    first_values = [random.random() for _ in range(5)]
    second_summary = seed_everything(2026)
    second_values = [random.random() for _ in range(5)]

    assert first_values == second_values
    assert first_summary == second_summary
    assert first_summary.python_random is True
    assert first_summary.python_hash_seed == "2026"


def test_seed_summary_is_serializable() -> None:
    """Seed configuration can be recorded as structured metadata."""
    summary = seed_everything(7).to_dict()
    assert summary["seed"] == 7
    assert isinstance(summary["numpy"], bool)
