"""CPU-only tests for evaluate policy 0.1."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

from scene_grammar_kit.evaluation import (
    EVALUATION_POLICY_VERSION,
    run_evaluation,
)
from scene_grammar_kit.evaluation.persistence import canonical_json
from scene_grammar_kit.evaluation.runner import (
    FROZEN_METRIC_IMPLEMENTATION_SHA256,
    _flat_baseline,
    _flat_equivalent,
    _metric_implementation_sha256,
)
from scene_grammar_kit.geometry import execute_grammar
from scene_grammar_kit.grammar import load_grammar

REPOSITORY = Path(__file__).resolve().parents[1]
EVALUATION = REPOSITORY / "evaluation" / "benchmark_v0_1"
CASES = EVALUATION / "cases"
CASE_ORDER = (
    "street_01",
    "street_02",
    "street_03",
    "street_04",
    "facade_01",
    "facade_02",
    "facade_03",
    "facade_04",
    "corridor_01",
    "corridor_02",
    "corridor_03",
    "corridor_04",
)
REAL_ORDER = ("canonical_success", "moderate_case", "limitation_case")
REQUIRED_OUTPUTS = {
    "README.md",
    "evaluation_policy.json",
    "controlled_results.json",
    "controlled_results.csv",
    "controlled_summary.json",
    "controlled_summary.csv",
    "controlled_summary.md",
    "real_case_results.json",
    "real_case_results.csv",
    "real_case_results.md",
    "summary_table.json",
    "summary_table.csv",
    "summary_table.md",
    "artifact_index.json",
    "runtime_diagnostics.json",
    "figures/compactness_comparison.png",
    "figures/conformance_summary.png",
    "figures/controlled_case_grid.png",
    "figures/evaluation_panel.png",
    "figures/figure_metadata.json",
}


@pytest.fixture(scope="module")
def evaluation_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("evaluate") / "package"
    result = run_evaluation(output, verify_determinism=True)
    assert len(result.controlled_rows) == 12
    return output


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_policy_and_exact_frozen_case_set() -> None:
    policy = _json(EVALUATION / "evaluation_policy.json")
    paths = sorted(CASES.glob("*.json"))
    assert policy["evaluation_policy_version"] == "0.1"
    assert policy["description"] == (
        "preliminary evidence for an annotation-assisted prototype"
    )
    assert len(paths) == 12
    assert tuple(policy["controlled_case_order"]) == CASE_ORDER


def test_fixed_family_counts_and_expected_properties() -> None:
    definitions = [_json(CASES / f"{case_id}.json") for case_id in CASE_ORDER]
    assert Counter(item["family"] for item in definitions) == {
        "urban_street": 4,
        "repeated_facade": 4,
        "indoor_corridor": 4,
    }
    for item in definitions:
        expected = item["expected"]
        assert expected["region_count"] == 6
        assert expected["instance_count"] == len(expected["repeat_member_ids"])
        assert expected["repeat_count"] == expected["instance_count"]
        assert len(expected["key_split_boundaries"]) == 2
        assert expected["valid_construction_outcome"] is True
        assert expected["required_edit_outcome"] == "applied"


def test_required_output_tree(evaluation_package: Path) -> None:
    actual = {
        path.relative_to(evaluation_package).as_posix()
        for path in evaluation_package.rglob("*")
        if path.is_file()
    }
    assert actual == REQUIRED_OUTPUTS


def test_controlled_outcomes_and_metric_correctness(
    evaluation_package: Path,
) -> None:
    rows = _json(evaluation_package / "controlled_results.json")
    assert tuple(row["case_id"] for row in rows) == CASE_ORDER
    assert all(row["constructor_success"] for row in rows)
    assert all(row["grammar_validation_success"] for row in rows)
    assert all(row["execution_success"] for row in rows)
    assert all(
        row["byte_ratio"]
        == row["repeat_grammar_canonical_bytes"] / row["split_only_canonical_bytes"]
        for row in rows
    )
    assert all(
        row["maximum_key_split_boundary_error"] == max(row["key_split_boundary_errors"])
        for row in rows
    )


def test_observation_coverage_is_complete(evaluation_package: Path) -> None:
    rows = _json(evaluation_package / "controlled_results.json")
    for row in rows:
        assert row["source_observation_coverage"] == 1.0
        assert row["represented_observation_count"] == row["source_observation_count"]
        assert row["omitted_observation_count"] == 0
        assert row["duplicate_observation_count"] == 0


def test_boundary_error_calculation_and_denominator(
    evaluation_package: Path,
) -> None:
    rows = _json(evaluation_package / "controlled_results.json")
    values = [value for row in rows for value in row["key_split_boundary_errors"]]
    summary = _json(evaluation_package / "controlled_summary.json")
    boundary = summary["split_boundary_error"]
    assert len(values) == boundary["observation_count"] == 24
    assert boundary["case_count"] == 12
    assert boundary["minimum"] == min(values)
    assert boundary["maximum"] == max(values)
    assert boundary["range"] == [min(values), max(values)]
    assert boundary["maximum"] < 1e-12


def test_repeat_counts_and_fidelity_are_explicit(
    evaluation_package: Path,
) -> None:
    rows = _json(evaluation_package / "controlled_results.json")
    accepted = [row for row in rows if row["repeat_decision"] == "accepted"]
    fallback = [row for row in rows if row["repeat_decision"] == "rejected_fallback"]
    assert len(accepted) == 8
    assert len(fallback) == 4
    assert all(
        row["supplied_repeat_count"] == row["produced_repeat_count"]
        and row["repeat_count_exact"]
        for row in accepted
    )
    assert all(
        row["produced_repeat_count"] == 0 and not row["repeat_count_exact"]
        for row in fallback
    )
    assert all(row["maximum_accepted_member_proxy_boundary_error"] >= 0 for row in rows)


def test_repeat_compression_reduces_accepted_symbolic_size(
    evaluation_package: Path,
) -> None:
    rows = _json(evaluation_package / "controlled_results.json")
    accepted = [row for row in rows if row["repeat_decision"] == "accepted"]
    assert all(
        row["repeat_grammar_symbolic_node_count"]
        < row["split_only_symbolic_node_count"]
        for row in accepted
    )
    assert all(
        row["repeat_grammar_canonical_bytes"] < row["split_only_canonical_bytes"]
        for row in accepted
    )


def test_flat_baseline_equivalence_and_canonical_bytes(
    evaluation_package: Path,
) -> None:
    rows = _json(evaluation_package / "controlled_results.json")
    assert all(row["flat_baseline_equivalent"] for row in rows)
    assert all(row["flat_terminal_count"] > 0 for row in rows)
    assert all(row["flat_canonical_bytes"] > 0 for row in rows)
    grammar = load_grammar(
        REPOSITORY
        / "results"
        / "real_cases"
        / "canonical_success"
        / "primary"
        / "grammar.json"
    )
    scene = execute_grammar(grammar)
    flat = _flat_baseline(scene)
    text = canonical_json(flat)
    assert _flat_equivalent(flat, scene)
    assert len(text.encode("utf-8")) == len(canonical_json(flat).encode("utf-8"))


def test_edits_are_valid_and_visibly_changed(evaluation_package: Path) -> None:
    rows = _json(evaluation_package / "controlled_results.json")
    assert all(row["predefined_edit_valid"] for row in rows)
    assert all(row["pixel_difference_status"] == "changed" for row in rows)
    assert all(row["changed_pixel_count"] > 0 for row in rows)


def test_aggregate_denominators_are_explicit(evaluation_package: Path) -> None:
    summary = _json(evaluation_package / "controlled_summary.json")
    for key in (
        "valid_grammar_rate",
        "execution_success_rate",
        "complete_observation_coverage_rate",
        "exact_repeat_count_rate",
        "valid_edit_rate",
    ):
        assert summary[key]["denominator"] == 12
        assert 0 <= summary[key]["numerator"] <= 12
    assert summary["accepted_repeat_groups"] == {
        "count": 8,
        "denominator": 12,
    }
    assert summary["fallback_repeat_groups"] == {
        "count": 4,
        "denominator": 12,
    }
    assert summary["median_split_only_bytes"]["denominator"] == 12
    assert summary["median_repeat_bytes"]["denominator"] == 12
    assert summary["median_byte_ratio"]["denominator"] == 12


def test_controlled_json_csv_markdown_agree(evaluation_package: Path) -> None:
    rows = _json(evaluation_package / "controlled_results.json")
    with (evaluation_package / "controlled_results.csv").open(
        newline="",
        encoding="utf-8",
    ) as handle:
        csv_rows = list(csv.DictReader(handle))
    markdown = (evaluation_package / "controlled_summary.md").read_text(
        encoding="utf-8"
    )
    assert tuple(row["case_id"] for row in rows) == tuple(
        row["case_id"] for row in csv_rows
    )
    assert all(case_id in markdown or "12 cases" in markdown for case_id in CASE_ORDER)
    assert "24 boundaries" in markdown


def test_real_cases_are_descriptive_and_complete(
    evaluation_package: Path,
) -> None:
    rows = _json(evaluation_package / "real_case_results.json")
    assert tuple(row["case_key"] for row in rows) == REAL_ORDER
    assert tuple(row["outcome"] for row in rows) == (
        "success",
        "success",
        "degraded_success",
    )
    assert all(row["image_id"] and row["source_license"] for row in rows)
    assert all(row["limitation_description"] for row in rows)
    markdown = (evaluation_package / "real_case_results.md").read_text(encoding="utf-8")
    assert "not a real-case accuracy benchmark" in markdown
    assert "does not preserve curvature or perspective" in markdown


def test_real_json_csv_markdown_agree(evaluation_package: Path) -> None:
    rows = _json(evaluation_package / "real_case_results.json")
    with (evaluation_package / "real_case_results.csv").open(
        newline="",
        encoding="utf-8",
    ) as handle:
        csv_rows = list(csv.DictReader(handle))
    markdown = (evaluation_package / "real_case_results.md").read_text(encoding="utf-8")
    assert tuple(row["case_key"] for row in rows) == tuple(
        row["case_key"] for row in csv_rows
    )
    assert all(row["case_key"] in markdown for row in rows)
    assert all(str(row["image_id"]) in markdown for row in rows)


def test_summary_table_is_consistent(evaluation_package: Path) -> None:
    rows = _json(evaluation_package / "summary_table.json")
    with (evaluation_package / "summary_table.csv").open(
        newline="",
        encoding="utf-8",
    ) as handle:
        csv_rows = list(csv.DictReader(handle))
    markdown = (evaluation_package / "summary_table.md").read_text(encoding="utf-8")
    assert len(rows) == len(csv_rows) == 15
    assert tuple(row["case"] for row in rows) == CASE_ORDER + REAL_ORDER
    assert tuple(row["case"] for row in csv_rows) == CASE_ORDER + REAL_ORDER
    assert all(row["case"] in markdown for row in rows)
    assert "no three-example accuracy" in markdown


def test_figures_are_exact_and_reopen(evaluation_package: Path) -> None:
    expected = {
        "compactness_comparison.png": (1800, 1000),
        "conformance_summary.png": (1800, 1000),
        "controlled_case_grid.png": (1800, 1200),
        "evaluation_panel.png": (2400, 1350),
    }
    for name, size in expected.items():
        with Image.open(evaluation_package / "figures" / name) as image:
            assert image.size == size
            assert image.mode == "RGB"
            image.verify()


def test_figures_are_byte_deterministic(
    evaluation_package: Path,
    tmp_path: Path,
) -> None:
    rebuilt = tmp_path / "rebuilt"
    run_evaluation(rebuilt, verify_determinism=False)
    for name in (
        "compactness_comparison.png",
        "conformance_summary.png",
        "controlled_case_grid.png",
        "evaluation_panel.png",
    ):
        first = evaluation_package / "figures" / name
        second = rebuilt / "figures" / name
        assert first.read_bytes() == second.read_bytes()


def test_provenance_is_complete_and_relative(evaluation_package: Path) -> None:
    for filename in ("controlled_results.json", "real_case_results.json"):
        rows = _json(evaluation_package / filename)
        for row in rows:
            assert row["evaluation_policy_version"] == "0.1"
            assert row["metric_implementation_version"] == "0.1"
            assert len(row["metric_implementation_sha256"]) == 64
            assert len(row["constructor_report_sha256"]) == 64
            assert row["evaluation_snapshot_id"] == "scene-grammar-kit-evaluation-v0.1"
            assert row["artifact_relative_paths"]
            assert all(
                not Path(path).is_absolute() and "\\" not in path
                for path in row["artifact_relative_paths"]
            )


def test_artifact_index_and_runtime_boundary(evaluation_package: Path) -> None:
    index = _json(evaluation_package / "artifact_index.json")
    paths = {item["relative_path"] for item in index["artifacts"]}
    assert "runtime_diagnostics.json" not in paths
    assert "artifact_index.json" not in paths
    assert all(not Path(path).is_absolute() and "\\" not in path for path in paths)
    runtime = _json(evaluation_package / "runtime_diagnostics.json")
    assert runtime["canonical"] is False
    assert set(runtime["diagnostics"]) == set(CASE_ORDER)


def test_canonical_outputs_contain_no_absolute_paths_or_timestamps(
    evaluation_package: Path,
) -> None:
    for path in evaluation_package.glob("*.json"):
        if path.name == "runtime_diagnostics.json":
            continue
        text = path.read_text(encoding="utf-8")
        assert "C:\\" not in text
        assert "/Users/" not in text
        assert "timestamp" not in text.casefold()


def test_no_unsupported_performance_claims(evaluation_package: Path) -> None:
    prohibited = (
        "state-of-the-art",
        "statistically significant",
        "orders of magnitude",
        "robust generalization",
    )
    paths = [
        *evaluation_package.glob("*.md"),
        evaluation_package / "controlled_summary.json",
        evaluation_package / "summary_table.json",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert not any(phrase in combined.casefold() for phrase in prohibited)


def test_metric_hash_matches_current_implementation(
    evaluation_package: Path,
) -> None:
    rows = _json(evaluation_package / "controlled_results.json")
    assert {row["metric_implementation_sha256"] for row in rows} == {
        FROZEN_METRIC_IMPLEMENTATION_SHA256
    }
    assert _metric_implementation_sha256(REPOSITORY) == (
        FROZEN_METRIC_IMPLEMENTATION_SHA256
    )


def test_policy_constant() -> None:
    assert EVALUATION_POLICY_VERSION == "0.1"
