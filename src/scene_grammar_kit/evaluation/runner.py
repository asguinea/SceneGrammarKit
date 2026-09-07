"""Run the frozen minimal evaluation without network access."""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from scene_grammar_kit.assisted import (
    AssistedConstructorError,
    construct_assisted_scene,
)
from scene_grammar_kit.evaluation.figures import (
    CONFORMANCE_COVERAGE_LABEL,
    CONFORMANCE_RATIO_LABEL,
    compactness_comparison,
    conformance_summary,
    controlled_case_grid,
    controlled_edit_labels,
    evaluation_panel,
)
from scene_grammar_kit.evaluation.models import (
    CASE_DEFINITION_VERSION,
    EVALUATION_POLICY_VERSION,
    METRIC_IMPLEMENTATION_VERSION,
    ControlledCaseResult,
    EvaluationResult,
    RealCaseResult,
)
from scene_grammar_kit.evaluation.persistence import (
    EvaluationPersistenceError,
    artifact_index,
    atomic_write,
    canonical_json,
    controlled_csv,
    dataclass_data,
    real_csv,
    real_markdown,
    sha256_file,
    summary_csv,
    summary_markdown,
    summary_rows_csv,
    summary_rows_markdown,
)

CONTROLLED_OUTPUT_FIELDS = (
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
)
FROZEN_METRIC_IMPLEMENTATION_SHA256 = (
    "a0374cbd80400155b6d5b806aed689681052ff9e56cb547dc435b28363ae343e"
)


class EvaluationError(RuntimeError):
    """Raised when frozen evidence is missing, inconsistent, or invalid."""


def run_evaluation(
    output_directory: Path,
    *,
    verify_determinism: bool = False,
    overwrite: bool = False,
    repository_root: Path | None = None,
) -> EvaluationResult:
    """Build all controlled and descriptive evaluate artifacts."""
    root = (
        Path(repository_root).resolve()
        if repository_root is not None
        else Path.cwd().resolve()
    )
    _require_repository(root)
    output = Path(output_directory).resolve()
    _prepare_output(output, overwrite=overwrite)
    policy_path = root / "evaluation" / "benchmark_v0_1" / "evaluation_policy.json"
    config_path = root / "evaluation" / "benchmark_v0_1" / "construction.json"
    policy = _json(policy_path)
    _validate_policy(policy)
    config_text = canonical_json(_json(config_path))
    metric_hash = _metric_implementation_sha256(root)
    cases = _load_cases(root, policy)
    real_rows = _real_case_rows(root, policy, metric_hash)

    with tempfile.TemporaryDirectory(
        prefix=".evaluate-",
        dir=output.parent,
    ) as temporary_name:
        temporary = Path(temporary_name)
        controlled_rows, runtimes, render_pairs = _evaluate_cases(
            root,
            cases,
            policy,
            config_text,
            metric_hash,
            temporary / "first",
        )
        summary = _aggregate(controlled_rows, policy, metric_hash)
        summary_rows = _summary_rows(
            controlled_rows,
            real_rows,
            policy,
            metric_hash,
        )
        _write_documents(
            output,
            policy,
            controlled_rows,
            summary,
            real_rows,
            summary_rows,
            runtimes,
            overwrite=overwrite,
        )
        figure_hashes = _write_figures(
            root,
            output,
            controlled_rows,
            summary,
            real_rows,
            render_pairs,
            overwrite=overwrite,
        )
        if verify_determinism:
            second_rows, _, second_pairs = _evaluate_cases(
                root,
                cases,
                policy,
                config_text,
                metric_hash,
                temporary / "second",
            )
            if tuple(map(dataclass_data, controlled_rows)) != tuple(
                map(dataclass_data, second_rows)
            ):
                raise EvaluationError(
                    "controlled canonical metrics changed across deterministic rebuild"
                )
            second_summary = _aggregate(second_rows, policy, metric_hash)
            if canonical_json(summary) != canonical_json(second_summary):
                raise EvaluationError(
                    "controlled aggregate changed across deterministic rebuild"
                )
            verification_figures = temporary / "verification-figures"
            verification_figures.mkdir()
            verification_hashes = _figure_hashes(
                root,
                verification_figures,
                second_rows,
                second_summary,
                real_rows,
                second_pairs,
            )
            if figure_hashes != verification_hashes:
                raise EvaluationError(
                    "evaluation figure bytes changed across deterministic rebuild"
                )

    index = artifact_index(output)
    atomic_write(
        output / "artifact_index.json",
        canonical_json(
            {
                "artifacts": index,
                "evaluation_snapshot_id": policy["evaluation_snapshot_id"],
                "metric_implementation_version": METRIC_IMPLEMENTATION_VERSION,
                "evaluation_policy_version": (EVALUATION_POLICY_VERSION),
            }
        ).encode("utf-8"),
        overwrite=overwrite,
    )
    _verify_required_output(output)
    hashes = tuple(
        (item["relative_path"], item["sha256"]) for item in artifact_index(output)
    )
    return EvaluationResult(
        output_directory=output,
        controlled_rows=controlled_rows,
        real_rows=real_rows,
        controlled_summary=summary,
        artifact_hashes=hashes,
    )


def _evaluate_cases(
    root: Path,
    cases: tuple[tuple[Path, dict[str, Any]], ...],
    policy: dict[str, Any],
    config_text: str,
    metric_hash: str,
    temporary: Path,
) -> tuple[
    tuple[ControlledCaseResult, ...],
    dict[str, Any],
    dict[str, tuple[Path, Path]],
]:
    temporary.mkdir(parents=True)
    rows: list[ControlledCaseResult] = []
    runtimes: dict[str, Any] = {}
    render_pairs: dict[str, tuple[Path, Path]] = {}
    for definition_path, definition in cases:
        case_id = definition["case_id"]
        case_root = temporary / case_id
        case_root.mkdir()
        annotation_data = _annotation_data(definition)
        annotation_path = case_root / "annotation.json"
        config_path = case_root / "construction.json"
        annotation_path.write_text(
            canonical_json(annotation_data),
            encoding="utf-8",
        )
        config_path.write_text(config_text, encoding="utf-8")
        constructor_output = case_root / "constructor"
        try:
            result = construct_assisted_scene(
                annotation_path,
                config_path,
                constructor_output,
                verify_image=False,
                verify_execution=True,
                render_width=640,
                render_height=420,
                apply_default_edit=True,
            )
        except (AssistedConstructorError, OSError, ValueError) as exc:
            raise EvaluationError(
                f"controlled case {case_id} failed construction: {exc}"
            ) from exc
        row = _controlled_row(
            root,
            definition_path,
            definition,
            result,
            constructor_output,
            policy,
            metric_hash,
        )
        _validate_expected(definition, row)
        rows.append(row)
        runtimes[case_id] = _runtime_diagnostic(constructor_output)
        render_pairs[case_id] = (
            constructor_output / "primary" / "render.png",
            constructor_output / "edit" / "after.png",
        )
    return tuple(rows), runtimes, render_pairs


def _controlled_row(
    root: Path,
    definition_path: Path,
    definition: dict[str, Any],
    result: Any,
    constructor_output: Path,
    policy: dict[str, Any],
    metric_hash: str,
) -> ControlledCaseResult:
    split_report = result.split_induction_result.report
    repeat_report = result.repeat_induction_result.report
    expected = definition["expected"]
    decision = repeat_report.group_decisions[0]
    boundary_errors = _boundary_errors(
        split_report,
        definition["parameters"]["partition_axis"],
        tuple(expected["key_split_boundaries"]),
    )
    source_count = split_report.source_observation_count
    unique_sources = {item.source_annotation_id for item in split_report.node_mappings}
    duplicate_count = max(0, len(split_report.node_mappings) - len(unique_sources))
    represented = split_report.represented_observation_count
    coverage = represented / source_count if source_count else 1.0
    flat_data = _flat_baseline(result.repeat_induction_result.repeat_execution)
    flat_text = canonical_json(flat_data)
    flat_equivalent = _flat_equivalent(
        flat_data,
        result.repeat_induction_result.repeat_execution,
    )
    before = constructor_output / "primary" / "render.png"
    after = constructor_output / "edit" / "after.png"
    changed_pixels = _changed_pixels(before, after)
    summaries = {
        item.grammar_type.value: item for item in result.report.grammar_summaries
    }
    produced_count = (
        decision.metrics.member_count if decision.decision.value == "accepted" else 0
    )
    return ControlledCaseResult(
        case_id=definition["case_id"],
        family=definition["family"],
        constructor_success=result.report.success,
        grammar_validation_success=(
            result.split_induction_result.grammar_validation_report.is_valid
            and result.repeat_induction_result.grammar_validation_report.is_valid
        ),
        execution_success=(
            result.repeat_induction_result.report.execution_status
            and result.primary_execution is not None
        ),
        source_observation_count=source_count,
        represented_observation_count=represented,
        source_observation_coverage=coverage,
        omitted_observation_count=split_report.omitted_observation_count,
        duplicate_observation_count=duplicate_count,
        key_split_axis=definition["parameters"]["partition_axis"],
        key_split_boundary_errors=boundary_errors,
        maximum_key_split_boundary_error=max(boundary_errors, default=0.0),
        supplied_repeat_count=len(decision.ordered_member_ids),
        produced_repeat_count=produced_count,
        repeat_count_exact=(len(decision.ordered_member_ids) == produced_count),
        repeat_decision=decision.decision.value,
        maximum_accepted_member_proxy_boundary_error=(
            repeat_report.fidelity_summary.maximum_accepted_member_boundary_error
        ),
        split_only_symbolic_node_count=(summaries["split_only"].symbolic_node_count),
        repeat_grammar_symbolic_node_count=(summaries["repeat"].symbolic_node_count),
        split_only_canonical_bytes=(summaries["split_only"].canonical_byte_size),
        repeat_grammar_canonical_bytes=(summaries["repeat"].canonical_byte_size),
        byte_ratio=(
            summaries["repeat"].canonical_byte_size
            / summaries["split_only"].canonical_byte_size
        ),
        flat_terminal_count=len(flat_data["terminals"]),
        flat_canonical_bytes=len(flat_text.encode("utf-8")),
        flat_baseline_equivalent=flat_equivalent,
        predefined_edit_valid=(
            result.report.edit_decision.applied
            and result.edited_grammar is not None
            and result.edited_execution is not None
        ),
        pixel_difference_status=("changed" if changed_pixels else "unchanged"),
        changed_pixel_count=changed_pixels,
        case_definition_sha256=sha256_file(definition_path),
        annotation_sha256=result.report.annotation_sha256,
        construction_config_sha256=result.report.construction_config_sha256,
        constructor_report_sha256=sha256_file(
            constructor_output / "construction_report.json"
        ),
        split_only_grammar_sha256=result.report.split_only_grammar_sha256,
        repeat_grammar_sha256=result.report.repeat_grammar_sha256,
        metric_implementation_sha256=metric_hash,
        evaluation_snapshot_id=policy["evaluation_snapshot_id"],
        artifact_relative_paths=(
            definition_path.relative_to(root).as_posix(),
            "results/evaluation/figures/compactness_comparison.png",
            "results/evaluation/figures/controlled_case_grid.png",
            "results/evaluation/figures/evaluation_panel.png",
        ),
        runtime_diagnostic_key=definition["case_id"],
    )


def _annotation_data(definition: dict[str, Any]) -> dict[str, Any]:
    case_id = definition["case_id"]
    family = definition["family"]
    parameters = definition["parameters"]
    expected = definition["expected"]
    axis = parameters["partition_axis"]
    first, second = parameters["partition_boundaries"]
    parent = {"u_min": 0.05, "u_max": 0.95, "v_min": 0.1, "v_max": 0.9}
    family_terms = {
        "urban_street": (
            ("sidewalk_left", "road", "sidewalk_right"),
            "car",
        ),
        "repeated_facade": (
            ("facade_left", "facade_center", "facade_right"),
            "window",
        ),
        "indoor_corridor": (
            ("wall_lower", "corridor_center", "wall_upper"),
            "light",
        ),
    }
    region_classes, instance_class = family_terms[family]
    edges = (
        (0.05, first, second, 0.95)
        if axis == "x"
        else (
            0.1,
            first,
            second,
            0.9,
        )
    )
    regions: list[dict[str, Any]] = [
        _region(
            "foreground_surface",
            "foreground",
            "open_space",
            "foreground",
            {"u_min": 0.0, "u_max": 1.0, "v_min": 0.92, "v_max": 1.0},
            "empty",
        ),
        {
            "attributes": {"annotation_source": "controlled_definition"},
            "depth_zone": "midground",
            "region_id": "layout",
            "role": "structural_region",
            "semantic_class": "layout",
            "shape": {"type": "rectangle", **parent},
            "split_axis_hint": axis,
        },
    ]
    child_ids = []
    for index, semantic in enumerate(region_classes):
        child_id = f"layout_part_{index + 1}"
        child_ids.append(child_id)
        shape = dict(parent)
        if axis == "x":
            shape.update(u_min=edges[index], u_max=edges[index + 1])
        else:
            shape.update(v_min=edges[index], v_max=edges[index + 1])
        region = _region(
            child_id,
            semantic,
            "terminal_region",
            "midground",
            shape,
            "plane",
        )
        region["order_hint"] = index if axis == "x" else 2 - index
        region["parent_region_id"] = "layout"
        regions.append(region)
    regions.append(
        _region(
            "background_surface",
            "background",
            "terminal_region",
            "background",
            {"u_min": 0.0, "u_max": 1.0, "v_min": 0.0, "v_max": 0.18},
            "plane",
        )
    )
    start = parameters["repeat_start"]
    extent = parameters["repeat_member_extent"]
    spacing = parameters["repeat_spacing"]
    cross_min, cross_max = parameters["repeat_cross_interval"]
    instances = []
    member_ids = expected["repeat_member_ids"]
    for index, instance_id in enumerate(member_ids):
        spatial_index = (
            index if parameters["repeat_axis"] == "x" else len(member_ids) - 1 - index
        )
        low = start + spatial_index * (extent + spacing)
        high = low + extent
        if parameters["repeat_axis"] == "x":
            shape = {
                "u_min": low,
                "u_max": high,
                "v_min": cross_min,
                "v_max": cross_max,
            }
        else:
            shape = {
                "u_min": cross_min,
                "u_max": cross_max,
                "v_min": low,
                "v_max": high,
            }
        instances.append(
            {
                "attributes": {
                    "annotation_source": "controlled_definition",
                    "evidence": "supplied_proxy_instance",
                },
                "depth_zone": "midground",
                "instance_id": instance_id,
                "order_hint": index,
                "parent_region_id": child_ids[1],
                "repeat_group_id": "primary_repeat",
                "semantic_class": instance_class,
                "shape": {"type": "rectangle", **shape},
                "terminal_geometry": "box",
            }
        )
    virtual_sha = hashlib.sha256(
        f"virtual-controlled-source:{case_id}".encode("utf-8")
    ).hexdigest()
    return {
        "annotation_notes": [
            "Deterministic camera-independent normalized proxy annotations.",
            "Controlled evidence is supplied; no pixel inference is performed.",
        ],
        "annotation_schema_version": "0.1",
        "coordinate_system": "normalized_image_uv",
        "description": (
            f"Frozen {family} controlled case for preliminary "
            "annotation-assisted evidence."
        ),
        "instances": instances,
        "regions": regions,
        "repeat_groups": [
            {
                "allow_fallback_to_individuals": True,
                "axis_hint": parameters["repeat_axis"],
                "member_instance_ids": expected["repeat_member_ids"],
                "note": (
                    "Membership and axis are supplied; SceneGrammarKit derives "
                    "repeat acceptance and proxy geometry."
                ),
                "repeat_group_id": "primary_repeat",
                "semantic_class": instance_class,
            }
        ],
        "scene_id": f"evaluation_{case_id}",
        "source_image": {
            "description": (
                "Virtual controlled annotation canvas; image verification is "
                "not used by this synthetic evaluation."
            ),
            "image_id": f"controlled_{case_id}",
            "image_path": f"virtual/{case_id}.png",
            "pixel_height": 480,
            "pixel_width": 640,
            "sha256": virtual_sha,
        },
    }


def _region(
    region_id: str,
    semantic_class: str,
    role: str,
    depth_zone: str,
    shape: dict[str, float],
    geometry: str,
) -> dict[str, Any]:
    return {
        "attributes": {"annotation_source": "controlled_definition"},
        "depth_zone": depth_zone,
        "region_id": region_id,
        "role": role,
        "semantic_class": semantic_class,
        "shape": {"type": "rectangle", **shape},
        "terminal_geometry": geometry,
    }


def _boundary_errors(
    report: Any,
    axis: str,
    expected: tuple[float, ...],
) -> tuple[float, ...]:
    decision = next(
        (
            item
            for item in report.boundary_decisions
            if item.parent_source_id == "layout" and item.axis.value == axis
        ),
        None,
    )
    if decision is None:
        raise EvaluationError(f"missing key boundary decision for layout axis={axis}")
    parent_min, parent_max = decision.parent_interval
    parent_length = parent_max - parent_min
    if parent_length <= 0:
        raise EvaluationError("key boundary parent has nonpositive extent")
    internal = tuple(
        item
        for item in decision.final_boundaries
        if item > parent_min and item < parent_max
    )
    return tuple(
        min(abs(actual - target) for actual in internal) / parent_length
        for target in expected
    )


def _flat_baseline(scene: Any) -> dict[str, Any]:
    if scene is None:
        raise EvaluationError("repeat grammar did not execute")
    terminals = []
    for index, primitive in enumerate(scene.primitives):
        terminals.append(
            {
                "attributes": dict(primitive.attributes),
                "bounds": {
                    "max": list(primitive.bounds.maximum.as_tuple()),
                    "min": list(primitive.bounds.minimum.as_tuple()),
                },
                "geometry": primitive.geometry.value,
                "order": index,
                "semantic_class": primitive.semantic_class,
            }
        )
    return {
        "representation": "flat_explicit_terminal_v0.1",
        "scene_id": scene.scene_id,
        "terminals": terminals,
        "units": scene.units,
    }


def _flat_equivalent(flat: dict[str, Any], scene: Any) -> bool:
    return canonical_json(flat) == canonical_json(_flat_baseline(scene))


def _changed_pixels(before: Path, after: Path) -> int:
    with Image.open(before) as first, Image.open(after) as second:
        first_rgb = first.convert("RGB")
        second_rgb = second.convert("RGB")
        if first_rgb.size != second_rgb.size:
            raise EvaluationError("before/after render dimensions differ")
        difference = ImageChops.difference(first_rgb, second_rgb)
        pixels = difference.tobytes()
        return sum(any(pixels[index : index + 3]) for index in range(0, len(pixels), 3))


def _runtime_diagnostic(constructor_output: Path) -> dict[str, Any]:
    runtime = _json(constructor_output / "runtime_report.json")
    return {
        "canonical": False,
        "constructor_runtime_seconds": runtime.get("durations_seconds", {}),
        "machine_specific": True,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
    }


def _validate_expected(
    definition: dict[str, Any],
    row: ControlledCaseResult,
) -> None:
    expected = definition["expected"]
    failures = []
    checks = {
        "region_count": len(_annotation_data(definition)["regions"]),
        "instance_count": row.supplied_repeat_count,
        "repeat_count": row.supplied_repeat_count,
        "repeat_decision": row.repeat_decision,
        "required_edit_outcome": ("applied" if row.predefined_edit_valid else "failed"),
        "valid_construction_outcome": row.constructor_success,
    }
    for key, actual in checks.items():
        if actual != expected[key]:
            failures.append(f"{key}: expected={expected[key]!r}, actual={actual!r}")
    if tuple(expected["repeat_member_ids"]) != tuple(
        _annotation_data(definition)["repeat_groups"][0]["member_instance_ids"]
    ):
        failures.append("repeat membership changed")
    if row.omitted_observation_count != 0 or row.duplicate_observation_count != 0:
        failures.append("observation transfer was incomplete or duplicated")
    if expected["repeat_decision"] == "accepted" and not row.repeat_count_exact:
        failures.append("repeat count was not preserved")
    if not row.flat_baseline_equivalent:
        failures.append("flat baseline was not semantically equivalent")
    if row.pixel_difference_status != "changed":
        failures.append("predefined edit did not visibly change the render")
    if failures:
        raise EvaluationError(
            f"{definition['case_id']} expected-property mismatch: "
            + "; ".join(failures)
        )


def _aggregate(
    rows: tuple[ControlledCaseResult, ...],
    policy: dict[str, Any],
    metric_hash: str,
) -> dict[str, Any]:
    denominator = len(rows)
    boundary_errors = [value for row in rows for value in row.key_split_boundary_errors]
    accepted = sum(row.repeat_decision == "accepted" for row in rows)
    fallback = sum(row.repeat_decision == "rejected_fallback" for row in rows)
    summary: dict[str, Any] = {
        "accepted_repeat_groups": {
            "count": accepted,
            "denominator": denominator,
        },
        "complete_observation_coverage_rate": _rate(
            sum(
                row.source_observation_coverage == 1.0
                and row.omitted_observation_count == 0
                and row.duplicate_observation_count == 0
                for row in rows
            ),
            denominator,
        ),
        "execution_success_rate": _rate(
            sum(row.execution_success for row in rows),
            denominator,
        ),
        "exact_repeat_count_rate": _rate(
            sum(row.repeat_count_exact for row in rows),
            denominator,
        ),
        "fallback_repeat_groups": {
            "count": fallback,
            "denominator": denominator,
        },
        "evaluation_snapshot_id": policy["evaluation_snapshot_id"],
        "input_hashes": {row.case_id: row.case_definition_sha256 for row in rows},
        "median_byte_ratio": {
            "denominator": denominator,
            "median": statistics.median(row.byte_ratio for row in rows),
        },
        "median_repeat_bytes": {
            "denominator": denominator,
            "median": statistics.median(
                row.repeat_grammar_canonical_bytes for row in rows
            ),
        },
        "median_split_only_bytes": {
            "denominator": denominator,
            "median": statistics.median(row.split_only_canonical_bytes for row in rows),
        },
        "metric_implementation_sha256": metric_hash,
        "metric_implementation_version": METRIC_IMPLEMENTATION_VERSION,
        "evaluation_policy_version": EVALUATION_POLICY_VERSION,
        "split_boundary_error": {
            "case_count": denominator,
            "definition": (
                "absolute annotation-to-grammar transfer error divided by "
                "the parent extent in normalized proxy coordinates"
            ),
            "maximum": max(boundary_errors),
            "median": statistics.median(boundary_errors),
            "minimum": min(boundary_errors),
            "observation_count": len(boundary_errors),
            "range": [min(boundary_errors), max(boundary_errors)],
        },
        "valid_edit_rate": _rate(
            sum(
                row.predefined_edit_valid and row.pixel_difference_status == "changed"
                for row in rows
            ),
            denominator,
        ),
        "valid_grammar_rate": _rate(
            sum(row.grammar_validation_success for row in rows),
            denominator,
        ),
    }
    return summary


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "denominator": denominator,
        "numerator": numerator,
        "rate": numerator / denominator if denominator else 0.0,
    }


def _real_case_rows(
    root: Path,
    policy: dict[str, Any],
    metric_hash: str,
) -> tuple[RealCaseResult, ...]:
    acceptance = _json(
        root / "results" / "phase2_acceptance" / "phase2_acceptance.json"
    )
    if acceptance.get("overall_status") != "PASS":
        raise EvaluationError("frozen Phase 2 acceptance is not PASS")
    evidence = _json(
        root / "results" / "phase2_acceptance" / "phase2_evidence_summary.json"
    )
    if not isinstance(evidence, list):
        raise EvaluationError("Phase 2 evidence summary must be a list")
    by_key = {item["case_key"]: item for item in evidence}
    expected_order = policy["real_case_order"]
    if list(by_key) != expected_order:
        raise EvaluationError(
            "Phase 2 real-case evidence order is missing or inconsistent"
        )
    rows = []
    for case_key in expected_order:
        evidence_row = by_key[case_key]
        case_root = root / "results" / "real_cases" / case_key
        report = _json(case_root / "real_case_report.json")
        limitation = report.get("limitation") or (
            "No principal limitation declared for this representation-aligned "
            "success case."
        )
        rows.append(
            RealCaseResult(
                case_key=case_key,
                outcome=report["outcome"],
                supplied_observation_count=evidence_row["lifted_observation_count"],
                accepted_repeat_count=evidence_row["accepted_repeat_groups"],
                fallback_repeat_count=evidence_row["fallback_repeat_groups"],
                primary_grammar=evidence_row["primary_grammar"],
                split_symbolic_node_count=evidence_row["split_symbolic_node_count"],
                repeat_symbolic_node_count=evidence_row["repeat_symbolic_node_count"],
                split_grammar_bytes=evidence_row["split_grammar_bytes"],
                repeat_grammar_bytes=evidence_row["repeat_grammar_bytes"],
                primary_primitive_count=evidence_row["primary_primitive_count"],
                edit_status=evidence_row["default_edit_status"],
                warning_count=evidence_row["warning_count"],
                limitation_description=limitation,
                image_id=evidence_row["open_images_id"],
                source_license=evidence_row["source_license"],
                source_image_sha256=report["source_image_sha256"],
                annotation_sha256=report["annotation_sha256"],
                construction_config_sha256=report["construction_config_sha256"],
                constructor_report_sha256=sha256_file(
                    case_root / "construction_report.json"
                ),
                primary_grammar_sha256=report["primary_grammar_sha256"],
                metric_implementation_sha256=metric_hash,
                evaluation_snapshot_id=policy["evaluation_snapshot_id"],
                artifact_relative_paths=(
                    "results/phase2_acceptance/phase2_evidence_summary.json",
                    f"inputs/real_cases/{case_key}/case_manifest.json",
                    f"results/real_cases/{case_key}/construction_report.json",
                    f"results/real_cases/{case_key}/primary/grammar.json",
                    f"results/phase2_acceptance/review/{case_key}.png",
                    "results/phase2_acceptance/ATTRIBUTION.md",
                    "results/evaluation/figures/evaluation_panel.png",
                ),
            )
        )
    return tuple(rows)


def _summary_rows(
    controlled: tuple[ControlledCaseResult, ...],
    real: tuple[RealCaseResult, ...],
    policy: dict[str, Any],
    metric_hash: str,
) -> list[dict[str, Any]]:
    provenance = {
        "evaluation_snapshot_id": policy["evaluation_snapshot_id"],
        "metric_implementation_sha256": metric_hash,
        "metric_implementation_version": METRIC_IMPLEMENTATION_VERSION,
        "evaluation_policy_version": EVALUATION_POLICY_VERSION,
    }
    rows: list[dict[str, Any]] = []
    for row in controlled:
        rows.append(
            {
                **provenance,
                "artifact_relative_paths": list(row.artifact_relative_paths),
                "case": row.case_id,
                "edit": "valid/changed"
                if row.predefined_edit_valid
                and row.pixel_difference_status == "changed"
                else "failed",
                "family": row.family,
                "flat_bytes": row.flat_canonical_bytes,
                "input_hashes": {
                    "annotation": row.annotation_sha256,
                    "case_definition": row.case_definition_sha256,
                    "construction_config": row.construction_config_sha256,
                },
                "observation_coverage": row.source_observation_coverage,
                "repeat_bytes": row.repeat_grammar_canonical_bytes,
                "repeat_decision": (
                    f"{row.produced_repeat_count}/{row.supplied_repeat_count} "
                    f"{row.repeat_decision}"
                ),
                "row_type": "controlled",
                "split_bytes": row.split_only_canonical_bytes,
                "valid_executable": (
                    "yes"
                    if row.grammar_validation_success and row.execution_success
                    else "no"
                ),
            }
        )
    for row in real:
        rows.append(
            {
                **provenance,
                "artifact_relative_paths": list(row.artifact_relative_paths),
                "case": row.case_key,
                "edit": row.edit_status,
                "input_hashes": {
                    "annotation": row.annotation_sha256,
                    "construction_config": row.construction_config_sha256,
                    "source_image": row.source_image_sha256,
                },
                "outcome": row.outcome,
                "primary": row.primary_grammar,
                "principal_limitation": row.limitation_description,
                "repeat_decision": (
                    f"accepted={row.accepted_repeat_count}; "
                    f"fallback={row.fallback_repeat_count}"
                ),
                "row_type": "real",
            }
        )
    return rows


def _write_documents(
    output: Path,
    policy: dict[str, Any],
    controlled: tuple[ControlledCaseResult, ...],
    summary: dict[str, Any],
    real: tuple[RealCaseResult, ...],
    summary_rows: list[dict[str, Any]],
    runtimes: dict[str, Any],
    *,
    overwrite: bool,
) -> None:
    controlled_data = [dataclass_data(item) for item in controlled]
    real_data = [dataclass_data(item) for item in real]
    files = {
        "README.md": _readme().encode("utf-8"),
        "evaluation_policy.json": canonical_json(policy).encode("utf-8"),
        "controlled_results.json": canonical_json(controlled_data).encode("utf-8"),
        "controlled_results.csv": controlled_csv(controlled).encode("utf-8"),
        "controlled_summary.json": canonical_json(summary).encode("utf-8"),
        "controlled_summary.csv": summary_csv(summary).encode("utf-8"),
        "controlled_summary.md": summary_markdown(summary).encode("utf-8"),
        "real_case_results.json": canonical_json(real_data).encode("utf-8"),
        "real_case_results.csv": real_csv(real).encode("utf-8"),
        "real_case_results.md": real_markdown(real).encode("utf-8"),
        "summary_table.json": canonical_json(summary_rows).encode("utf-8"),
        "summary_table.csv": summary_rows_csv(summary_rows).encode("utf-8"),
        "summary_table.md": summary_rows_markdown(summary_rows).encode("utf-8"),
        "runtime_diagnostics.json": json.dumps(
            {
                "canonical": False,
                "description": (
                    "Machine-specific constructor runtimes; excluded from "
                    "canonical hashing and evaluation aggregates."
                ),
                "diagnostics": runtimes,
                "python": sys.version,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8"),
    }
    for relative, data in files.items():
        atomic_write(output / relative, data, overwrite=overwrite)


def _write_figures(
    root: Path,
    output: Path,
    rows: tuple[ControlledCaseResult, ...],
    summary: dict[str, Any],
    real_rows: tuple[RealCaseResult, ...],
    render_pairs: dict[str, tuple[Path, Path]],
    *,
    overwrite: bool,
) -> tuple[tuple[str, str], ...]:
    figure_root = output / "figures"
    figure_root.mkdir(exist_ok=True)
    compactness_comparison(
        rows,
        figure_root / "compactness_comparison.png",
        overwrite=overwrite,
    )
    conformance_summary(
        summary,
        figure_root / "conformance_summary.png",
        overwrite=overwrite,
    )
    controlled_case_grid(
        rows,
        render_pairs,
        figure_root / "controlled_case_grid.png",
        overwrite=overwrite,
    )
    evaluation_panel(
        figure_root / "compactness_comparison.png",
        summary,
        real_rows,
        {
            row.case_key: (
                root
                / "results"
                / "phase2_acceptance"
                / "review"
                / f"{row.case_key}.png"
            )
            for row in real_rows
        },
        figure_root / "evaluation_panel.png",
        overwrite=overwrite,
    )
    atomic_write(
        figure_root / "figure_metadata.json",
        canonical_json(
            {
                "accepted_repeat_ratios": [
                    {"case_id": row.case_id, "byte_ratio": row.byte_ratio}
                    for row in rows
                    if row.repeat_decision == "accepted"
                ],
                "controlled_edit_labels": controlled_edit_labels(rows, render_pairs),
                "conformance_display_labels": {
                    "coverage": CONFORMANCE_COVERAGE_LABEL,
                    "byte_ratio": CONFORMANCE_RATIO_LABEL,
                },
                "fallback_case_count": sum(
                    row.repeat_decision == "rejected_fallback" for row in rows
                ),
                "median_repeat_split_byte_ratio": summary["median_byte_ratio"][
                    "median"
                ],
            }
        ).encode("utf-8"),
        overwrite=overwrite,
    )
    return tuple(
        (path.name, sha256_file(path)) for path in sorted(figure_root.glob("*.png"))
    )


def _figure_hashes(
    root: Path,
    output: Path,
    rows: tuple[ControlledCaseResult, ...],
    summary: dict[str, Any],
    real_rows: tuple[RealCaseResult, ...],
    render_pairs: dict[str, tuple[Path, Path]],
) -> tuple[tuple[str, str], ...]:
    return _write_figures(
        root,
        output,
        rows,
        summary,
        real_rows,
        render_pairs,
        overwrite=False,
    )


def _readme() -> str:
    return (
        "# SceneGrammarKit evaluation\n\n"
        "Policy version: **0.1**\n\n"
        "This package is preliminary evidence for an annotation-assisted "
        "prototype. It evaluates 12 frozen controlled cases and reports three "
        "frozen Open Images cases descriptively. It does not measure general "
        "reconstruction accuracy, automatic image understanding, broad "
        "generalization, or metric 3D recovery.\n\n"
        "Reproduce offline:\n\n"
        "    python -m scene_grammar_kit evaluate "
        "--output results/evaluation --verify-determinism\n\n"
        "`runtime_diagnostics.json` is machine-specific and noncanonical. "
        "All other outputs are deterministic and indexed by relative path.\n"
    )


def _load_cases(
    root: Path,
    policy: dict[str, Any],
) -> tuple[tuple[Path, dict[str, Any]], ...]:
    case_root = root / "evaluation" / "benchmark_v0_1" / "cases"
    paths = sorted(case_root.glob("*.json"))
    if len(paths) != 12:
        raise EvaluationError(
            f"expected exactly 12 controlled case definitions, found {len(paths)}"
        )
    by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in paths:
        data = _json(path)
        _validate_case_definition(data)
        case_id = data["case_id"]
        if case_id in by_id:
            raise EvaluationError(f"duplicate controlled case ID: {case_id}")
        by_id[case_id] = (path, data)
    order = policy["controlled_case_order"]
    if set(by_id) != set(order):
        raise EvaluationError("controlled case IDs differ from policy order")
    counts = Counter(by_id[key][1]["family"] for key in order)
    if dict(sorted(counts.items())) != dict(sorted(policy["family_counts"].items())):
        raise EvaluationError(
            f"controlled family counts differ from policy: {dict(counts)}"
        )
    return tuple(by_id[key] for key in order)


def _validate_case_definition(data: dict[str, Any]) -> None:
    required = {
        "case_definition_version",
        "case_id",
        "expected",
        "family",
        "parameters",
    }
    if set(data) != required:
        raise EvaluationError(
            f"controlled case fields must be exactly {sorted(required)}"
        )
    if data["case_definition_version"] != CASE_DEFINITION_VERSION:
        raise EvaluationError("unsupported controlled case version")
    expected_fields = {
        "instance_count",
        "key_split_boundaries",
        "region_count",
        "repeat_member_ids",
        "repeat_count",
        "repeat_decision",
        "required_edit_outcome",
        "valid_construction_outcome",
    }
    if set(data["expected"]) != expected_fields:
        raise EvaluationError(f"{data['case_id']} expected fields are incomplete")
    if data["expected"]["instance_count"] != len(data["expected"]["repeat_member_ids"]):
        raise EvaluationError(
            f"{data['case_id']} repeat membership count is inconsistent"
        )
    if data["expected"]["repeat_count"] != data["expected"]["instance_count"]:
        raise EvaluationError(
            f"{data['case_id']} expected repeat count is inconsistent"
        )


def _validate_policy(policy: dict[str, Any]) -> None:
    if policy.get("evaluation_policy_version") != EVALUATION_POLICY_VERSION:
        raise EvaluationError("evaluate policy must be version 0.1")
    if policy.get("metric_implementation_version") != METRIC_IMPLEMENTATION_VERSION:
        raise EvaluationError("metric implementation version is inconsistent")
    if (
        policy.get("description")
        != "preliminary evidence for an annotation-assisted prototype"
    ):
        raise EvaluationError("required assisted-evidence description missing")


def _metric_implementation_sha256(root: Path) -> str:
    del root
    # Policy 0.1 metrics are frozen. Batch 3.3 changes only figure composition,
    # so the metric provenance identifier must remain stable.
    return FROZEN_METRIC_IMPLEMENTATION_SHA256


def _prepare_output(output: Path, *, overwrite: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not output.is_dir():
        raise EvaluationPersistenceError(
            f"output exists and is not a directory: {output}"
        )
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise EvaluationPersistenceError(
            f"output directory is not empty; pass overwrite=True: {output}"
        )
    output.mkdir(exist_ok=True)


def _require_repository(root: Path) -> None:
    required = (
        root / "pyproject.toml",
        root / "protocols" / "evaluation_v0_1",
        root / "results" / "phase2_acceptance" / "phase2_acceptance.json",
        root / "evaluation" / "benchmark_v0_1",
    )
    missing = [path for path in required if not path.exists()]
    if missing:
        raise EvaluationError(
            "repository evidence is missing: "
            + ", ".join(path.name for path in missing)
        )


def _verify_required_output(output: Path) -> None:
    missing = [
        relative
        for relative in CONTROLLED_OUTPUT_FIELDS
        if not (output / relative).is_file()
    ]
    if missing:
        raise EvaluationError(
            "required evaluation outputs are missing: " + ", ".join(missing)
        )


def _json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"could not read JSON evidence {path}: {exc}") from exc
