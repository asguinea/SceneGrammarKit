from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scene_grammar_kit.editing import EDITING_POLICY_VERSION
from scene_grammar_kit.geometry import EXECUTION_POLICY_VERSION, execute_grammar
from scene_grammar_kit.grammar import SCHEMA_VERSION, load_grammar, summarize_grammar
from scene_grammar_kit.rendering import RENDERER_POLICY_VERSION
from scene_grammar_kit.scene_examples import (
    MANIFEST_POLICY_VERSION,
    load_scene_manifest,
    scene_manifest_to_canonical_json,
)

ROOT = Path(__file__).resolve().parents[1]


def test_phase1_regression_manifest_matches_canonical_sources() -> None:
    lock = json.loads(
        (
            ROOT / "tests" / "fixtures" / "phase1" / "phase1_regression_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert lock["grammar_schema_version"] == SCHEMA_VERSION
    assert lock["manifest_policy_version"] == MANIFEST_POLICY_VERSION
    assert lock["execution_policy_version"] == EXECUTION_POLICY_VERSION
    assert lock["renderer_policy_version"] == RENDERER_POLICY_VERSION
    assert lock["editing_policy_version"] == EDITING_POLICY_VERSION
    for key in lock["scene_keys"]:
        expected = lock["scenes"][key]
        scene_root = ROOT / "examples" / "scene_examples" / key
        grammar_path = scene_root / "grammar.json"
        grammar = load_grammar(grammar_path)
        summary = summarize_grammar(grammar)
        executed = execute_grammar(grammar)
        manifest = load_scene_manifest(scene_root / "scene_manifest.json")
        manifest_bytes = scene_manifest_to_canonical_json(manifest).encode("utf-8")
        assert executed.grammar_sha256 == expected["canonical_grammar_sha256"]
        assert summary.canonical_byte_size == expected["canonical_grammar_byte_size"]
        assert summary.total_node_count == expected["symbolic_node_count"]
        assert executed.report.primitive_count == expected["original_primitive_count"]
        assert (
            hashlib.sha256(grammar_path.read_bytes()).hexdigest()
            == expected["source_grammar_file_sha256"]
        )
        assert (
            hashlib.sha256(manifest_bytes).hexdigest()
            == expected["canonical_manifest_sha256"]
        )
        assert [
            edit.edit_key
            for edit in manifest.canonical_edits
            if edit.primary_example_edit
        ] == expected["primary_edit_keys"]
