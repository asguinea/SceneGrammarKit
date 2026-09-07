"""Canonical serialization for split-induction policy reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from scene_grammar_kit.assisted.split_induction_errors import (
    SplitInductionSerializationError,
)
from scene_grammar_kit.assisted.split_induction_models import (
    AxisCandidateScore,
    AxisDecision,
    AxisSelectionSource,
    BoundaryDecision,
    GapDecision,
    GapReason,
    InductionDiagnostic,
    InductionDiagnosticSeverity,
    IntervalDecision,
    NodeMapping,
    RepeatCandidateRecord,
    RepeatCompressionStatus,
    RootConstructionDecision,
    SplitInductionReport,
)
from scene_grammar_kit.grammar import Axis


def split_induction_report_to_canonical_json(
    report: SplitInductionReport,
) -> str:
    """Serialize a report as compact deterministic direct-Unicode JSON."""
    if not isinstance(report, SplitInductionReport):
        raise SplitInductionSerializationError("report must be a SplitInductionReport")
    try:
        return json.dumps(
            _report_data(report),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise SplitInductionSerializationError(
            f"Could not serialize split-induction report: {exc}"
        ) from exc


def split_induction_report_from_json(text: str) -> SplitInductionReport:
    """Parse strict JSON into an immutable split-induction report."""
    if not isinstance(text, str):
        raise SplitInductionSerializationError("report JSON must be text")
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SplitInductionSerializationError(
            f"Invalid split-induction report JSON: {exc}"
        ) from exc
    data = _object(value, "$")
    try:
        return SplitInductionReport(
            success=_boolean(data["success"], "$.success"),
            grammar_schema_version=_string(
                data["grammar_schema_version"],
                "$.grammar_schema_version",
            ),
            lifting_policy_version=_string(
                data["lifting_policy_version"],
                "$.lifting_policy_version",
            ),
            scene_id=_string(data["scene_id"], "$.scene_id"),
            annotation_sha256=_string(
                data["annotation_sha256"],
                "$.annotation_sha256",
            ),
            construction_config_sha256=_string(
                data["construction_config_sha256"],
                "$.construction_config_sha256",
            ),
            lifted_observations_sha256=_string(
                data["lifted_observations_sha256"],
                "$.lifted_observations_sha256",
            ),
            induced_grammar_sha256=_string(
                data["induced_grammar_sha256"],
                "$.induced_grammar_sha256",
            ),
            root_construction_decision=_root_decision(
                data["root_construction_decision"],
                "$.root_construction_decision",
            ),
            axis_decisions=tuple(
                _axis_decision(item, f"$.axis_decisions[{index}]")
                for index, item in enumerate(
                    _array(data["axis_decisions"], "$.axis_decisions")
                )
            ),
            boundary_decisions=tuple(
                _boundary_decision(item, f"$.boundary_decisions[{index}]")
                for index, item in enumerate(
                    _array(
                        data["boundary_decisions"],
                        "$.boundary_decisions",
                    )
                )
            ),
            gap_decisions=tuple(
                _gap_decision(item, f"$.gap_decisions[{index}]")
                for index, item in enumerate(
                    _array(data["gap_decisions"], "$.gap_decisions")
                )
            ),
            node_mappings=tuple(
                _node_mapping(item, f"$.node_mappings[{index}]")
                for index, item in enumerate(
                    _array(data["node_mappings"], "$.node_mappings")
                )
            ),
            repeat_candidates=tuple(
                _repeat_candidate(item, f"$.repeat_candidates[{index}]")
                for index, item in enumerate(
                    _array(
                        data["repeat_candidates"],
                        "$.repeat_candidates",
                    )
                )
            ),
            source_observation_count=_integer(
                data["source_observation_count"],
                "$.source_observation_count",
            ),
            represented_observation_count=_integer(
                data["represented_observation_count"],
                "$.represented_observation_count",
            ),
            omitted_observation_count=_integer(
                data["omitted_observation_count"],
                "$.omitted_observation_count",
            ),
            split_node_count=_integer(
                data["split_node_count"],
                "$.split_node_count",
            ),
            terminal_node_count=_integer(
                data["terminal_node_count"],
                "$.terminal_node_count",
            ),
            empty_terminal_count=_integer(
                data["empty_terminal_count"],
                "$.empty_terminal_count",
            ),
            repeat_node_count=_integer(
                data["repeat_node_count"],
                "$.repeat_node_count",
            ),
            maximum_grammar_depth=_integer(
                data["maximum_grammar_depth"],
                "$.maximum_grammar_depth",
            ),
            canonical_grammar_byte_size=_integer(
                data["canonical_grammar_byte_size"],
                "$.canonical_grammar_byte_size",
            ),
            validation_status=_boolean(
                data["validation_status"],
                "$.validation_status",
            ),
            execution_verification_status=_boolean(
                data["execution_verification_status"],
                "$.execution_verification_status",
            ),
            supplied_information=_strings(
                data["supplied_information"],
                "$.supplied_information",
            ),
            derived_information=_strings(
                data["derived_information"],
                "$.derived_information",
            ),
            explicitly_not_inferred=_strings(
                data["explicitly_not_inferred"],
                "$.explicitly_not_inferred",
            ),
            diagnostics=tuple(
                _diagnostic(item, f"$.diagnostics[{index}]")
                for index, item in enumerate(
                    _array(data["diagnostics"], "$.diagnostics")
                )
            ),
            warnings=_strings(data["warnings"], "$.warnings"),
            split_induction_policy_version=_string(
                data["split_induction_policy_version"],
                "$.split_induction_policy_version",
            ),
        )
    except KeyError as exc:
        raise SplitInductionSerializationError(
            f"Missing required report field: {exc.args[0]}"
        ) from exc
    except (TypeError, ValueError) as exc:
        if isinstance(exc, SplitInductionSerializationError):
            raise
        raise SplitInductionSerializationError(
            f"Invalid split-induction report: {exc}"
        ) from exc


def _report_data(report: SplitInductionReport) -> dict[str, Any]:
    return {
        "success": report.success,
        "split_induction_policy_version": (report.split_induction_policy_version),
        "grammar_schema_version": report.grammar_schema_version,
        "lifting_policy_version": report.lifting_policy_version,
        "scene_id": report.scene_id,
        "annotation_sha256": report.annotation_sha256,
        "construction_config_sha256": report.construction_config_sha256,
        "lifted_observations_sha256": report.lifted_observations_sha256,
        "induced_grammar_sha256": report.induced_grammar_sha256,
        "root_construction_decision": _root_data(report.root_construction_decision),
        "axis_decisions": [_axis_data(item) for item in report.axis_decisions],
        "boundary_decisions": [
            _boundary_data(item) for item in report.boundary_decisions
        ],
        "gap_decisions": [_gap_data(item) for item in report.gap_decisions],
        "node_mappings": [_mapping_data(item) for item in report.node_mappings],
        "repeat_candidates": [_repeat_data(item) for item in report.repeat_candidates],
        "source_observation_count": report.source_observation_count,
        "represented_observation_count": report.represented_observation_count,
        "omitted_observation_count": report.omitted_observation_count,
        "split_node_count": report.split_node_count,
        "terminal_node_count": report.terminal_node_count,
        "empty_terminal_count": report.empty_terminal_count,
        "repeat_node_count": report.repeat_node_count,
        "maximum_grammar_depth": report.maximum_grammar_depth,
        "canonical_grammar_byte_size": report.canonical_grammar_byte_size,
        "validation_status": report.validation_status,
        "execution_verification_status": (report.execution_verification_status),
        "supplied_information": list(report.supplied_information),
        "derived_information": list(report.derived_information),
        "explicitly_not_inferred": list(report.explicitly_not_inferred),
        "diagnostics": [
            {
                "code": item.code,
                "severity": item.severity.value,
                "message": item.message,
                "source_annotation_id": item.source_annotation_id,
                "grammar_node_id": item.grammar_node_id,
                "structural_path": item.structural_path,
            }
            for item in report.diagnostics
        ],
        "warnings": list(report.warnings),
    }


def _root_data(item: RootConstructionDecision) -> dict[str, Any]:
    return {
        "root_node_id": item.root_node_id,
        "axis": item.axis.value,
        "ordered_zones": list(item.ordered_zones),
        "configured_intervals": [
            [low, high] for low, high in item.configured_intervals
        ],
        "weights": list(item.weights),
    }


def _axis_data(item: AxisDecision) -> dict[str, Any]:
    return {
        "parent_source_id": item.parent_source_id,
        "candidate_scores": [
            {
                "axis": score.axis.value,
                "valid": score.valid,
                "overlap_violations": score.overlap_violations,
                "normalized_centroid_spread": (score.normalized_centroid_spread),
                "normalized_coverage": score.normalized_coverage,
                "explicit_gap_count": score.explicit_gap_count,
            }
            for score in item.candidate_scores
        ],
        "selected_axis": item.selected_axis.value,
        "selection_source": item.selection_source.value,
        "world_tolerance": item.world_tolerance,
        "structural_path": item.structural_path,
    }


def _boundary_data(item: BoundaryDecision) -> dict[str, Any]:
    return {
        "parent_source_id": item.parent_source_id,
        "axis": item.axis.value,
        "parent_interval": list(item.parent_interval),
        "intervals": [
            {
                "source_annotation_id": interval.source_annotation_id,
                "source_minimum": interval.source_minimum,
                "source_maximum": interval.source_maximum,
                "final_minimum": interval.final_minimum,
                "final_maximum": interval.final_maximum,
            }
            for interval in item.intervals
        ],
        "final_boundaries": list(item.final_boundaries),
        "final_weights": list(item.final_weights),
        "world_tolerance": item.world_tolerance,
        "affected_source_ids": list(item.affected_source_ids),
        "structural_path": item.structural_path,
    }


def _gap_data(item: GapDecision) -> dict[str, Any]:
    return {
        "parent_source_id": item.parent_source_id,
        "axis": item.axis.value,
        "gap_interval": list(item.gap_interval),
        "reason": item.reason.value,
        "generated_empty_node_id": item.generated_empty_node_id,
        "structural_path": item.structural_path,
    }


def _mapping_data(item: NodeMapping) -> dict[str, Any]:
    return {
        "source_annotation_type": item.source_annotation_type,
        "source_annotation_id": item.source_annotation_id,
        "generated_grammar_node_ids": list(item.generated_grammar_node_ids),
        "primary_generated_node_id": item.primary_generated_node_id,
        "represented_purpose": item.represented_purpose,
    }


def _repeat_data(item: RepeatCandidateRecord) -> dict[str, Any]:
    return {
        "repeat_group_id": item.repeat_group_id,
        "supplied_axis": item.supplied_axis.value,
        "ordered_source_member_ids": list(item.ordered_source_member_ids),
        "generated_independent_terminal_ids": list(
            item.generated_independent_terminal_ids
        ),
        "compression_status": item.compression_status.value,
    }


def _root_decision(value: object, path: str) -> RootConstructionDecision:
    data = _object(value, path)
    return RootConstructionDecision(
        root_node_id=_string(data["root_node_id"], f"{path}.root_node_id"),
        axis=_enum(Axis, data["axis"], f"{path}.axis"),
        ordered_zones=_strings(
            data["ordered_zones"],
            f"{path}.ordered_zones",
        ),
        configured_intervals=tuple(
            _interval(item, f"{path}.configured_intervals[{index}]")
            for index, item in enumerate(
                _array(
                    data["configured_intervals"],
                    f"{path}.configured_intervals",
                )
            )
        ),
        weights=_numbers(data["weights"], f"{path}.weights"),
    )


def _axis_decision(value: object, path: str) -> AxisDecision:
    data = _object(value, path)
    return AxisDecision(
        parent_source_id=_string(
            data["parent_source_id"],
            f"{path}.parent_source_id",
        ),
        candidate_scores=tuple(
            _candidate(item, f"{path}.candidate_scores[{index}]")
            for index, item in enumerate(
                _array(data["candidate_scores"], f"{path}.candidate_scores")
            )
        ),
        selected_axis=_enum(
            Axis,
            data["selected_axis"],
            f"{path}.selected_axis",
        ),
        selection_source=_enum(
            AxisSelectionSource,
            data["selection_source"],
            f"{path}.selection_source",
        ),
        world_tolerance=_number(
            data["world_tolerance"],
            f"{path}.world_tolerance",
        ),
        structural_path=_string(
            data["structural_path"],
            f"{path}.structural_path",
        ),
    )


def _candidate(value: object, path: str) -> AxisCandidateScore:
    data = _object(value, path)
    return AxisCandidateScore(
        axis=_enum(Axis, data["axis"], f"{path}.axis"),
        valid=_boolean(data["valid"], f"{path}.valid"),
        overlap_violations=_integer(
            data["overlap_violations"],
            f"{path}.overlap_violations",
        ),
        normalized_centroid_spread=_number(
            data["normalized_centroid_spread"],
            f"{path}.normalized_centroid_spread",
        ),
        normalized_coverage=_number(
            data["normalized_coverage"],
            f"{path}.normalized_coverage",
        ),
        explicit_gap_count=_integer(
            data["explicit_gap_count"],
            f"{path}.explicit_gap_count",
        ),
    )


def _boundary_decision(value: object, path: str) -> BoundaryDecision:
    data = _object(value, path)
    return BoundaryDecision(
        parent_source_id=_string(
            data["parent_source_id"],
            f"{path}.parent_source_id",
        ),
        axis=_enum(Axis, data["axis"], f"{path}.axis"),
        parent_interval=_interval(
            data["parent_interval"],
            f"{path}.parent_interval",
        ),
        intervals=tuple(
            _interval_decision(item, f"{path}.intervals[{index}]")
            for index, item in enumerate(_array(data["intervals"], f"{path}.intervals"))
        ),
        final_boundaries=_numbers(
            data["final_boundaries"],
            f"{path}.final_boundaries",
        ),
        final_weights=_numbers(
            data["final_weights"],
            f"{path}.final_weights",
        ),
        world_tolerance=_number(
            data["world_tolerance"],
            f"{path}.world_tolerance",
        ),
        affected_source_ids=_strings(
            data["affected_source_ids"],
            f"{path}.affected_source_ids",
        ),
        structural_path=_string(
            data["structural_path"],
            f"{path}.structural_path",
        ),
    )


def _interval_decision(value: object, path: str) -> IntervalDecision:
    data = _object(value, path)
    return IntervalDecision(
        source_annotation_id=_string(
            data["source_annotation_id"],
            f"{path}.source_annotation_id",
        ),
        source_minimum=_number(
            data["source_minimum"],
            f"{path}.source_minimum",
        ),
        source_maximum=_number(
            data["source_maximum"],
            f"{path}.source_maximum",
        ),
        final_minimum=_number(
            data["final_minimum"],
            f"{path}.final_minimum",
        ),
        final_maximum=_number(
            data["final_maximum"],
            f"{path}.final_maximum",
        ),
    )


def _gap_decision(value: object, path: str) -> GapDecision:
    data = _object(value, path)
    return GapDecision(
        parent_source_id=_string(
            data["parent_source_id"],
            f"{path}.parent_source_id",
        ),
        axis=_enum(Axis, data["axis"], f"{path}.axis"),
        gap_interval=_interval(
            data["gap_interval"],
            f"{path}.gap_interval",
        ),
        reason=_enum(GapReason, data["reason"], f"{path}.reason"),
        generated_empty_node_id=_string(
            data["generated_empty_node_id"],
            f"{path}.generated_empty_node_id",
        ),
        structural_path=_string(
            data["structural_path"],
            f"{path}.structural_path",
        ),
    )


def _node_mapping(value: object, path: str) -> NodeMapping:
    data = _object(value, path)
    return NodeMapping(
        source_annotation_type=_string(
            data["source_annotation_type"],
            f"{path}.source_annotation_type",
        ),
        source_annotation_id=_string(
            data["source_annotation_id"],
            f"{path}.source_annotation_id",
        ),
        generated_grammar_node_ids=_strings(
            data["generated_grammar_node_ids"],
            f"{path}.generated_grammar_node_ids",
        ),
        primary_generated_node_id=_string(
            data["primary_generated_node_id"],
            f"{path}.primary_generated_node_id",
        ),
        represented_purpose=_string(
            data["represented_purpose"],
            f"{path}.represented_purpose",
        ),
    )


def _repeat_candidate(value: object, path: str) -> RepeatCandidateRecord:
    data = _object(value, path)
    return RepeatCandidateRecord(
        repeat_group_id=_string(
            data["repeat_group_id"],
            f"{path}.repeat_group_id",
        ),
        supplied_axis=_enum(
            Axis,
            data["supplied_axis"],
            f"{path}.supplied_axis",
        ),
        ordered_source_member_ids=_strings(
            data["ordered_source_member_ids"],
            f"{path}.ordered_source_member_ids",
        ),
        generated_independent_terminal_ids=_strings(
            data["generated_independent_terminal_ids"],
            f"{path}.generated_independent_terminal_ids",
        ),
        compression_status=_enum(
            RepeatCompressionStatus,
            data["compression_status"],
            f"{path}.compression_status",
        ),
    )


def _diagnostic(value: object, path: str) -> InductionDiagnostic:
    data = _object(value, path)
    return InductionDiagnostic(
        code=_string(data["code"], f"{path}.code"),
        severity=_enum(
            InductionDiagnosticSeverity,
            data["severity"],
            f"{path}.severity",
        ),
        message=_string(data["message"], f"{path}.message"),
        source_annotation_id=_optional_string(
            data["source_annotation_id"],
            f"{path}.source_annotation_id",
        ),
        grammar_node_id=_optional_string(
            data["grammar_node_id"],
            f"{path}.grammar_node_id",
        ),
        structural_path=_optional_string(
            data["structural_path"],
            f"{path}.structural_path",
        ),
    )


def _object(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SplitInductionSerializationError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise SplitInductionSerializationError(f"{path} must be an array")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise SplitInductionSerializationError(f"{path} must be a nonempty string")
    return value


def _optional_string(value: object, path: str) -> str | None:
    return None if value is None else _string(value, path)


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise SplitInductionSerializationError(f"{path} must be a boolean")
    return value


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SplitInductionSerializationError(f"{path} must be an integer")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SplitInductionSerializationError(f"{path} must be a number")
    result = float(value)
    if not (float("-inf") < result < float("inf")):
        raise SplitInductionSerializationError(f"{path} must be finite")
    return result


def _strings(value: object, path: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )


def _numbers(value: object, path: str) -> tuple[float, ...]:
    return tuple(
        _number(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )


def _interval(value: object, path: str) -> tuple[float, float]:
    items = _numbers(value, path)
    if len(items) != 2:
        raise SplitInductionSerializationError(f"{path} must contain two numbers")
    return (items[0], items[1])


def _enum(enum_type: type, value: object, path: str):
    text = _string(value, path)
    try:
        return enum_type(text)
    except ValueError as exc:
        raise SplitInductionSerializationError(
            f"{path} has unsupported value {text!r}"
        ) from exc


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite constant {value} is not allowed")
