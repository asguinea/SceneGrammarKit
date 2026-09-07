"""Canonical serialization for assisted constructor reports and indexes."""

from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from scene_grammar_kit.assisted.constructor_errors import (
    AssistedConstructorSerializationError,
)
from scene_grammar_kit.assisted.constructor_models import (
    AssistedConstructionReport,
    ConstructionArtifactIndex,
    ConstructionStageOutcome,
    ConstructionStageStatus,
    DefaultEditDecision,
    GrammarConstructionSummary,
    PrimaryGrammarType,
)


def assisted_construction_report_to_canonical_json(
    report: AssistedConstructionReport,
) -> str:
    """Serialize a deterministic constructor report without runtime data."""
    if not isinstance(report, AssistedConstructionReport):
        raise AssistedConstructorSerializationError(
            "report must be an AssistedConstructionReport"
        )
    for path in report.artifact_relative_paths:
        _relative_path(path)
    return _canonical_json(_convert(report), "construction report")


def assisted_construction_report_from_json(
    text: str,
) -> AssistedConstructionReport:
    """Parse strict JSON into an immutable constructor report."""
    if not isinstance(text, str):
        raise AssistedConstructorSerializationError("report JSON must be text")
    try:
        data = _object(
            json.loads(text, parse_constant=_reject_constant),
            "$",
        )
        stages = tuple(
            ConstructionStageStatus(
                stage_name=_string(item["stage_name"]),
                status=ConstructionStageOutcome(_string(item["status"])),
                detail=_string(item["detail"]),
                artifact_paths=tuple(
                    _relative_path(_string(path))
                    for path in _array(item["artifact_paths"])
                ),
                warnings=tuple(_string(value) for value in _array(item["warnings"])),
            )
            for item in (
                _object(value, "$.stage_statuses[]")
                for value in _array(data["stage_statuses"])
            )
        )
        summaries = tuple(
            GrammarConstructionSummary(
                grammar_type=PrimaryGrammarType(_string(item["grammar_type"])),
                symbolic_node_count=_integer(item["symbolic_node_count"]),
                split_node_count=_integer(item["split_node_count"]),
                repeat_node_count=_integer(item["repeat_node_count"]),
                terminal_node_count=_integer(item["terminal_node_count"]),
                primitive_count=_integer(item["primitive_count"]),
                canonical_byte_size=_integer(item["canonical_byte_size"]),
            )
            for item in (
                _object(value, "$.grammar_summaries[]")
                for value in _array(data["grammar_summaries"])
            )
        )
        edit = _object(data["edit_decision"], "$.edit_decision")
        return AssistedConstructionReport(
            success=_boolean(data["success"]),
            annotation_schema_version=_string(data["annotation_schema_version"]),
            construction_config_schema_version=_string(
                data["construction_config_schema_version"]
            ),
            review_policy_version=_string(data["review_policy_version"]),
            lifting_policy_version=_string(data["lifting_policy_version"]),
            split_induction_policy_version=_string(
                data["split_induction_policy_version"]
            ),
            repeat_induction_policy_version=_string(
                data["repeat_induction_policy_version"]
            ),
            grammar_schema_version=_string(data["grammar_schema_version"]),
            execution_policy_version=_string(data["execution_policy_version"]),
            renderer_policy_version=_string(data["renderer_policy_version"]),
            editing_policy_version=_string(data["editing_policy_version"]),
            scene_id=_string(data["scene_id"]),
            image_id=_string(data["image_id"]),
            source_image_sha256=_optional_string(data["source_image_sha256"]),
            annotation_sha256=_string(data["annotation_sha256"]),
            construction_config_sha256=_string(data["construction_config_sha256"]),
            lifted_scene_sha256=_string(data["lifted_scene_sha256"]),
            split_only_grammar_sha256=_string(data["split_only_grammar_sha256"]),
            repeat_grammar_sha256=_string(data["repeat_grammar_sha256"]),
            primary_grammar_sha256=_string(data["primary_grammar_sha256"]),
            primary_grammar_type=PrimaryGrammarType(
                _string(data["primary_grammar_type"])
            ),
            primary_selection_reason=_string(data["primary_selection_reason"]),
            supplied_repeat_group_count=_integer(data["supplied_repeat_group_count"]),
            accepted_repeat_group_count=_integer(data["accepted_repeat_group_count"]),
            fallback_repeat_group_count=_integer(data["fallback_repeat_group_count"]),
            stage_statuses=stages,
            artifact_relative_paths=tuple(
                _relative_path(_string(value))
                for value in _array(data["artifact_relative_paths"])
            ),
            grammar_summaries=summaries,
            construction_warnings=tuple(
                _string(value) for value in _array(data["construction_warnings"])
            ),
            edit_decision=DefaultEditDecision(
                applied=_boolean(edit["applied"]),
                selection_policy=_string(edit["selection_policy"]),
                operation_type=_optional_string(edit["operation_type"]),
                target_node_id=_optional_string(edit["target_node_id"]),
                requested_value=_optional_string(edit["requested_value"]),
                realized_value=_optional_string(edit["realized_value"]),
                reason=_string(edit["reason"]),
                procedural_variation=_boolean(edit["procedural_variation"]),
            ),
            supplied_information=_strings(data["supplied_information"]),
            configured_information=_strings(data["configured_information"]),
            derived_information=_strings(data["derived_information"]),
            explicitly_not_inferred=_strings(data["explicitly_not_inferred"]),
            constructor_policy_version=_string(data["constructor_policy_version"]),
        )
    except AssistedConstructorSerializationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise AssistedConstructorSerializationError(
            f"Invalid construction report JSON: {exc}"
        ) from exc


def artifact_index_to_canonical_json(
    index: ConstructionArtifactIndex,
) -> str:
    """Serialize a lexicographically ordered portable artifact index."""
    if not isinstance(index, ConstructionArtifactIndex):
        raise AssistedConstructorSerializationError(
            "index must be a ConstructionArtifactIndex"
        )
    paths = tuple(record.relative_path for record in index.records)
    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise AssistedConstructorSerializationError(
            "artifact records must have unique sorted relative paths"
        )
    for path in paths:
        _relative_path(path)
    return _canonical_json(_convert(index), "artifact index")


def _convert(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _convert(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return [_convert(item) for item in value]
    if isinstance(value, list):
        return [_convert(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _convert(item) for key, item in value.items()}
    return value


def _canonical_json(value: Any, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise AssistedConstructorSerializationError(
            f"Could not serialize {label}: {exc}"
        ) from exc


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or ":" in value
    ):
        raise AssistedConstructorSerializationError(
            f"artifact path must be safe and relative: {value!r}"
        )
    return path.as_posix()


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssistedConstructorSerializationError(f"{path} must be an object")
    return value


def _array(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise AssistedConstructorSerializationError("value must be an array")
    return value


def _string(value: Any) -> str:
    if not isinstance(value, str):
        raise AssistedConstructorSerializationError("value must be a string")
    return value


def _optional_string(value: Any) -> str | None:
    return None if value is None else _string(value)


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise AssistedConstructorSerializationError("value must be a boolean")
    return value


def _integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssistedConstructorSerializationError("value must be an integer")
    return value


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(_string(item) for item in _array(value))


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value!r} is not allowed")
