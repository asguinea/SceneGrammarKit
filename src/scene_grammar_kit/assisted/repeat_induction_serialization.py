"""Canonical JSON serialization for repeat-induction policy reports."""

from __future__ import annotations

import json
from typing import Any

from scene_grammar_kit.assisted.repeat_induction_errors import (
    RepeatInductionSerializationError,
)
from scene_grammar_kit.assisted.repeat_induction_models import (
    RepeatCompressionSummary,
    RepeatDecision,
    RepeatDiagnostic,
    RepeatDiagnosticSeverity,
    RepeatFidelitySummary,
    RepeatGroupDecision,
    RepeatInductionReport,
    RepeatMemberMapping,
    RepeatRegularityMetrics,
    RepeatRepresentationStatus,
)
from scene_grammar_kit.grammar import Axis, Bounds3D, GeometryType, Vector3


def repeat_induction_report_to_canonical_json(
    report: RepeatInductionReport,
) -> str:
    """Serialize a report as compact deterministic direct-Unicode JSON."""
    if not isinstance(report, RepeatInductionReport):
        raise RepeatInductionSerializationError(
            "report must be a RepeatInductionReport"
        )
    try:
        return json.dumps(
            _report_data(report),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise RepeatInductionSerializationError(
            f"Could not serialize repeat-induction report: {exc}"
        ) from exc


def repeat_induction_report_from_json(text: str) -> RepeatInductionReport:
    """Parse strict JSON into an immutable repeat-induction report."""
    if not isinstance(text, str):
        raise RepeatInductionSerializationError("report JSON must be text")
    try:
        value = json.loads(text, parse_constant=_reject_constant)
        data = _object(value, "$")
        return RepeatInductionReport(
            success=_boolean(data["success"], "$.success"),
            annotation_schema_version=_string(
                data["annotation_schema_version"], "$.annotation_schema_version"
            ),
            construction_config_schema_version=_string(
                data["construction_config_schema_version"],
                "$.construction_config_schema_version",
            ),
            lifting_policy_version=_string(
                data["lifting_policy_version"], "$.lifting_policy_version"
            ),
            split_induction_policy_version=_string(
                data["split_induction_policy_version"],
                "$.split_induction_policy_version",
            ),
            grammar_schema_version=_string(
                data["grammar_schema_version"], "$.grammar_schema_version"
            ),
            execution_policy_version=_string(
                data["execution_policy_version"], "$.execution_policy_version"
            ),
            scene_id=_string(data["scene_id"], "$.scene_id"),
            annotation_sha256=_string(data["annotation_sha256"], "$.annotation_sha256"),
            construction_config_sha256=_string(
                data["construction_config_sha256"],
                "$.construction_config_sha256",
            ),
            lifted_observations_sha256=_string(
                data["lifted_observations_sha256"],
                "$.lifted_observations_sha256",
            ),
            split_only_grammar_sha256=_string(
                data["split_only_grammar_sha256"],
                "$.split_only_grammar_sha256",
            ),
            repeat_grammar_sha256=_string(
                data["repeat_grammar_sha256"], "$.repeat_grammar_sha256"
            ),
            supplied_repeat_group_count=_integer(
                data["supplied_repeat_group_count"],
                "$.supplied_repeat_group_count",
            ),
            accepted_group_count=_integer(
                data["accepted_group_count"], "$.accepted_group_count"
            ),
            fallback_group_count=_integer(
                data["fallback_group_count"], "$.fallback_group_count"
            ),
            fatal_group_count=_integer(
                data["fatal_group_count"], "$.fatal_group_count"
            ),
            group_decisions=tuple(
                _group_decision(item, f"$.group_decisions[{index}]")
                for index, item in enumerate(
                    _array(data["group_decisions"], "$.group_decisions")
                )
            ),
            member_mappings=tuple(
                _member_mapping(item, f"$.member_mappings[{index}]")
                for index, item in enumerate(
                    _array(data["member_mappings"], "$.member_mappings")
                )
            ),
            compression_summary=_compression(
                data["compression_summary"], "$.compression_summary"
            ),
            fidelity_summary=_fidelity(data["fidelity_summary"], "$.fidelity_summary"),
            repeat_node_count=_integer(
                data["repeat_node_count"], "$.repeat_node_count"
            ),
            validation_status=_boolean(
                data["validation_status"], "$.validation_status"
            ),
            execution_status=_boolean(data["execution_status"], "$.execution_status"),
            supplied_information=_strings(
                data["supplied_information"], "$.supplied_information"
            ),
            derived_information=_strings(
                data["derived_information"], "$.derived_information"
            ),
            explicitly_not_inferred=_strings(
                data["explicitly_not_inferred"], "$.explicitly_not_inferred"
            ),
            diagnostics=tuple(
                _diagnostic(item, f"$.diagnostics[{index}]")
                for index, item in enumerate(
                    _array(data["diagnostics"], "$.diagnostics")
                )
            ),
            warnings=_strings(data["warnings"], "$.warnings"),
            repeat_induction_policy_version=_string(
                data["repeat_induction_policy_version"],
                "$.repeat_induction_policy_version",
            ),
        )
    except RepeatInductionSerializationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise RepeatInductionSerializationError(
            f"Invalid repeat-induction report JSON: {exc}"
        ) from exc


def _report_data(report: RepeatInductionReport) -> dict[str, Any]:
    return {
        "success": report.success,
        "repeat_induction_policy_version": report.repeat_induction_policy_version,
        "annotation_schema_version": report.annotation_schema_version,
        "construction_config_schema_version": (
            report.construction_config_schema_version
        ),
        "lifting_policy_version": report.lifting_policy_version,
        "split_induction_policy_version": report.split_induction_policy_version,
        "grammar_schema_version": report.grammar_schema_version,
        "execution_policy_version": report.execution_policy_version,
        "scene_id": report.scene_id,
        "annotation_sha256": report.annotation_sha256,
        "construction_config_sha256": report.construction_config_sha256,
        "lifted_observations_sha256": report.lifted_observations_sha256,
        "split_only_grammar_sha256": report.split_only_grammar_sha256,
        "repeat_grammar_sha256": report.repeat_grammar_sha256,
        "supplied_repeat_group_count": report.supplied_repeat_group_count,
        "accepted_group_count": report.accepted_group_count,
        "fallback_group_count": report.fallback_group_count,
        "fatal_group_count": report.fatal_group_count,
        "group_decisions": [_group_data(item) for item in report.group_decisions],
        "member_mappings": [_mapping_data(item) for item in report.member_mappings],
        "compression_summary": _compression_data(report.compression_summary),
        "fidelity_summary": _fidelity_data(report.fidelity_summary),
        "repeat_node_count": report.repeat_node_count,
        "validation_status": report.validation_status,
        "execution_status": report.execution_status,
        "supplied_information": list(report.supplied_information),
        "derived_information": list(report.derived_information),
        "explicitly_not_inferred": list(report.explicitly_not_inferred),
        "diagnostics": [_diagnostic_data(item) for item in report.diagnostics],
        "warnings": list(report.warnings),
    }


def _metrics_data(value: RepeatRegularityMetrics) -> dict[str, Any]:
    return {
        "group_id": value.group_id,
        "supplied_axis": value.supplied_axis.value,
        "member_count": value.member_count,
        "member_intervals": [list(item) for item in value.member_intervals],
        "member_extents": [list(item) for item in value.member_extents],
        "pairwise_gaps": list(value.pairwise_gaps),
        "group_span": list(value.group_span),
        "estimated_spacing": value.estimated_spacing,
        "implied_element_extent": value.implied_element_extent,
        "cross_axis_median_centers": [
            list(item) for item in value.cross_axis_median_centers
        ],
        "cross_axis_median_extents": [
            list(item) for item in value.cross_axis_median_extents
        ],
        "alignment_error": value.alignment_error,
        "size_error": value.size_error,
        "spacing_error": value.spacing_error,
        "positional_residual": value.positional_residual,
        "alignment_tolerance": value.alignment_tolerance,
        "size_tolerance": value.size_tolerance,
        "spacing_tolerance": value.spacing_tolerance,
    }


def _group_data(value: RepeatGroupDecision) -> dict[str, Any]:
    return {
        "group_id": value.group_id,
        "decision": value.decision.value,
        "ordered_member_ids": list(value.ordered_member_ids),
        "reason_codes": list(value.reason_codes),
        "repeat_node_id": value.repeat_node_id,
        "representative_element_id": value.representative_element_id,
        "metrics": _metrics_data(value.metrics),
        "source_parent_id": value.source_parent_id,
        "supplied_semantic_class": value.supplied_semantic_class,
        "geometry_type": value.geometry_type.value,
    }


def _bounds_data(value: Bounds3D) -> dict[str, list[float]]:
    return {
        "minimum": list(value.minimum.as_tuple()),
        "maximum": list(value.maximum.as_tuple()),
    }


def _mapping_data(value: RepeatMemberMapping) -> dict[str, Any]:
    return {
        "repeat_group_id": value.repeat_group_id,
        "source_instance_id": value.source_instance_id,
        "supplied_member_index": value.supplied_member_index,
        "repeat_node_id": value.repeat_node_id,
        "representative_element_node_id": value.representative_element_node_id,
        "fallback_terminal_node_id": value.fallback_terminal_node_id,
        "observed_world_bounds": _bounds_data(value.observed_world_bounds),
        "predicted_world_bounds": (
            None
            if value.predicted_world_bounds is None
            else _bounds_data(value.predicted_world_bounds)
        ),
        "boundary_residual": value.boundary_residual,
        "representation_status": value.representation_status.value,
    }


def _compression_data(value: RepeatCompressionSummary) -> dict[str, Any]:
    return {
        name: getattr(value, name)
        for name in RepeatCompressionSummary.__dataclass_fields__
    }


def _fidelity_data(value: RepeatFidelitySummary) -> dict[str, Any]:
    return {
        name: getattr(value, name)
        for name in RepeatFidelitySummary.__dataclass_fields__
    }


def _diagnostic_data(value: RepeatDiagnostic) -> dict[str, Any]:
    return {
        "code": value.code,
        "severity": value.severity.value,
        "message": value.message,
        "repeat_group_id": value.repeat_group_id,
        "member_id": value.member_id,
        "grammar_node_id": value.grammar_node_id,
        "structural_path": value.structural_path,
    }


def _metrics(value: Any, path: str) -> RepeatRegularityMetrics:
    data = _object(value, path)
    return RepeatRegularityMetrics(
        group_id=_string(data["group_id"], path + ".group_id"),
        supplied_axis=Axis(_string(data["supplied_axis"], path + ".supplied_axis")),
        member_count=_integer(data["member_count"], path + ".member_count"),
        member_intervals=_number_rows(
            data["member_intervals"], path + ".member_intervals", 2
        ),
        member_extents=_number_rows(
            data["member_extents"], path + ".member_extents", 3
        ),
        pairwise_gaps=_numbers(data["pairwise_gaps"], path + ".pairwise_gaps"),
        group_span=_number_row(data["group_span"], path + ".group_span", 2),
        estimated_spacing=_number(
            data["estimated_spacing"], path + ".estimated_spacing"
        ),
        implied_element_extent=_number(
            data["implied_element_extent"], path + ".implied_element_extent"
        ),
        cross_axis_median_centers=_named_numbers(
            data["cross_axis_median_centers"],
            path + ".cross_axis_median_centers",
        ),
        cross_axis_median_extents=_named_numbers(
            data["cross_axis_median_extents"],
            path + ".cross_axis_median_extents",
        ),
        alignment_error=_number(data["alignment_error"], path + ".alignment_error"),
        size_error=_number(data["size_error"], path + ".size_error"),
        spacing_error=_number(data["spacing_error"], path + ".spacing_error"),
        positional_residual=_number(
            data["positional_residual"], path + ".positional_residual"
        ),
        alignment_tolerance=_number(
            data["alignment_tolerance"], path + ".alignment_tolerance"
        ),
        size_tolerance=_number(data["size_tolerance"], path + ".size_tolerance"),
        spacing_tolerance=_number(
            data["spacing_tolerance"], path + ".spacing_tolerance"
        ),
    )


def _group_decision(value: Any, path: str) -> RepeatGroupDecision:
    data = _object(value, path)
    return RepeatGroupDecision(
        group_id=_string(data["group_id"], path + ".group_id"),
        decision=RepeatDecision(_string(data["decision"], path + ".decision")),
        ordered_member_ids=_strings(
            data["ordered_member_ids"], path + ".ordered_member_ids"
        ),
        reason_codes=_strings(data["reason_codes"], path + ".reason_codes"),
        repeat_node_id=_optional_string(
            data["repeat_node_id"], path + ".repeat_node_id"
        ),
        representative_element_id=_optional_string(
            data["representative_element_id"],
            path + ".representative_element_id",
        ),
        metrics=_metrics(data["metrics"], path + ".metrics"),
        source_parent_id=_optional_string(
            data["source_parent_id"], path + ".source_parent_id"
        ),
        supplied_semantic_class=_string(
            data["supplied_semantic_class"], path + ".supplied_semantic_class"
        ),
        geometry_type=GeometryType(
            _string(data["geometry_type"], path + ".geometry_type")
        ),
    )


def _member_mapping(value: Any, path: str) -> RepeatMemberMapping:
    data = _object(value, path)
    predicted = data["predicted_world_bounds"]
    return RepeatMemberMapping(
        repeat_group_id=_string(data["repeat_group_id"], path + ".repeat_group_id"),
        source_instance_id=_string(
            data["source_instance_id"], path + ".source_instance_id"
        ),
        supplied_member_index=_integer(
            data["supplied_member_index"], path + ".supplied_member_index"
        ),
        repeat_node_id=_optional_string(
            data["repeat_node_id"], path + ".repeat_node_id"
        ),
        representative_element_node_id=_optional_string(
            data["representative_element_node_id"],
            path + ".representative_element_node_id",
        ),
        fallback_terminal_node_id=_optional_string(
            data["fallback_terminal_node_id"],
            path + ".fallback_terminal_node_id",
        ),
        observed_world_bounds=_bounds(
            data["observed_world_bounds"], path + ".observed_world_bounds"
        ),
        predicted_world_bounds=(
            None
            if predicted is None
            else _bounds(predicted, path + ".predicted_world_bounds")
        ),
        boundary_residual=_number(
            data["boundary_residual"], path + ".boundary_residual"
        ),
        representation_status=RepeatRepresentationStatus(
            _string(data["representation_status"], path + ".representation_status")
        ),
    )


def _compression(value: Any, path: str) -> RepeatCompressionSummary:
    data = _object(value, path)
    integer_names = (
        "split_only_symbolic_node_count",
        "repeat_symbolic_node_count",
        "split_only_split_count",
        "repeat_split_count",
        "split_only_terminal_count",
        "repeat_terminal_count",
        "split_only_repeat_count",
        "repeat_repeat_count",
        "split_only_canonical_bytes",
        "repeat_canonical_bytes",
        "absolute_byte_difference",
        "symbolic_node_difference",
        "primitive_count_before",
        "primitive_count_after",
    )
    values = {name: _integer(data[name], f"{path}.{name}") for name in integer_names}
    values["byte_ratio"] = _number(data["byte_ratio"], path + ".byte_ratio")
    return RepeatCompressionSummary(**values)


def _fidelity(value: Any, path: str) -> RepeatFidelitySummary:
    data = _object(value, path)
    return RepeatFidelitySummary(
        source_backed_conceptual_count_before=_integer(
            data["source_backed_conceptual_count_before"],
            path + ".source_backed_conceptual_count_before",
        ),
        source_backed_conceptual_count_after=_integer(
            data["source_backed_conceptual_count_after"],
            path + ".source_backed_conceptual_count_after",
        ),
        maximum_accepted_member_boundary_error=_number(
            data["maximum_accepted_member_boundary_error"],
            path + ".maximum_accepted_member_boundary_error",
        ),
        maximum_non_repeat_observation_change=_number(
            data["maximum_non_repeat_observation_change"],
            path + ".maximum_non_repeat_observation_change",
        ),
        root_bounds_equal=_boolean(
            data["root_bounds_equal"], path + ".root_bounds_equal"
        ),
        split_only_execution_success=_boolean(
            data["split_only_execution_success"],
            path + ".split_only_execution_success",
        ),
        repeat_execution_success=_boolean(
            data["repeat_execution_success"], path + ".repeat_execution_success"
        ),
    )


def _diagnostic(value: Any, path: str) -> RepeatDiagnostic:
    data = _object(value, path)
    return RepeatDiagnostic(
        code=_string(data["code"], path + ".code"),
        severity=RepeatDiagnosticSeverity(
            _string(data["severity"], path + ".severity")
        ),
        message=_string(data["message"], path + ".message"),
        repeat_group_id=_optional_string(
            data["repeat_group_id"], path + ".repeat_group_id"
        ),
        member_id=_optional_string(data["member_id"], path + ".member_id"),
        grammar_node_id=_optional_string(
            data["grammar_node_id"], path + ".grammar_node_id"
        ),
        structural_path=_optional_string(
            data["structural_path"], path + ".structural_path"
        ),
    )


def _bounds(value: Any, path: str) -> Bounds3D:
    data = _object(value, path)
    minimum = _number_row(data["minimum"], path + ".minimum", 3)
    maximum = _number_row(data["maximum"], path + ".maximum", 3)
    return Bounds3D(Vector3(*minimum), Vector3(*maximum))


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RepeatInductionSerializationError(f"{path} must be an object")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise RepeatInductionSerializationError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise RepeatInductionSerializationError(f"{path} must be a string")
    return value


def _optional_string(value: Any, path: str) -> str | None:
    return None if value is None else _string(value, path)


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise RepeatInductionSerializationError(f"{path} must be a boolean")
    return value


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RepeatInductionSerializationError(f"{path} must be an integer")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RepeatInductionSerializationError(f"{path} must be a number")
    result = float(value)
    if not (-float("inf") < result < float("inf")):
        raise RepeatInductionSerializationError(f"{path} must be finite")
    return result


def _strings(value: Any, path: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )


def _numbers(value: Any, path: str) -> tuple[float, ...]:
    return tuple(
        _number(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )


def _number_row(value: Any, path: str, length: int) -> tuple[float, ...]:
    result = _numbers(value, path)
    if len(result) != length:
        raise RepeatInductionSerializationError(f"{path} must contain {length} numbers")
    return result


def _number_rows(value: Any, path: str, length: int) -> tuple[tuple[float, ...], ...]:
    return tuple(
        _number_row(item, f"{path}[{index}]", length)
        for index, item in enumerate(_array(value, path))
    )


def _named_numbers(value: Any, path: str) -> tuple[tuple[str, float], ...]:
    result = []
    for index, item in enumerate(_array(value, path)):
        row = _array(item, f"{path}[{index}]")
        if len(row) != 2:
            raise RepeatInductionSerializationError(
                f"{path}[{index}] must contain a name and number"
            )
        result.append(
            (
                _string(row[0], f"{path}[{index}][0]"),
                _number(row[1], f"{path}[{index}][1]"),
            )
        )
    return tuple(result)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value!r} is not allowed")
