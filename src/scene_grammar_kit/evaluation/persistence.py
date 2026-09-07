"""Canonical serialization and safe persistence for evaluation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterable

from scene_grammar_kit.evaluation.models import (
    ControlledCaseResult,
    RealCaseResult,
)


class EvaluationPersistenceError(RuntimeError):
    """Raised when an evaluation package cannot be persisted safely."""


def canonical_json(value: object) -> str:
    """Serialize canonical compact UTF-8 JSON without timestamps."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def dataclass_data(value: object) -> dict[str, Any]:
    """Convert one flat immutable metric row to canonical data."""
    data: dict[str, Any] = {}
    for item in fields(value):
        field_value = getattr(value, item.name)
        data[item.name] = (
            list(field_value) if isinstance(field_value, tuple) else field_value
        )
    return data


def controlled_csv(rows: Iterable[ControlledCaseResult]) -> str:
    return _rows_csv([dataclass_data(item) for item in rows])


def real_csv(rows: Iterable[RealCaseResult]) -> str:
    return _rows_csv([dataclass_data(item) for item in rows])


def summary_rows_csv(rows: list[dict[str, Any]]) -> str:
    return _rows_csv(rows)


def summary_csv(summary: dict[str, Any]) -> str:
    rows: list[dict[str, Any]] = []
    for key, value in summary.items():
        if isinstance(value, dict):
            rows.append(
                {
                    "metric": key,
                    "numerator": value.get("numerator", ""),
                    "denominator": value.get(
                        "denominator", value.get("observation_count", "")
                    ),
                    "value": value.get(
                        "rate",
                        value.get(
                            "median",
                            value.get("count", value.get("range", "")),
                        ),
                    ),
                    "minimum": value.get("minimum", ""),
                    "maximum": value.get("maximum", ""),
                }
            )
        else:
            rows.append(
                {
                    "metric": key,
                    "numerator": "",
                    "denominator": "",
                    "value": value,
                    "minimum": "",
                    "maximum": "",
                }
            )
    return _rows_csv(rows)


def controlled_markdown(rows: tuple[ControlledCaseResult, ...]) -> str:
    lines = [
        "# Controlled results",
        "",
        "Preliminary evidence for an annotation-assisted prototype. Boundary "
        "errors are absolute errors in normalized proxy coordinates.",
        "",
        "| Case | Family | Valid/executable | Coverage | Boundary max | "
        "Repeat supplied/produced | Decision | Split bytes | Repeat bytes | "
        "Flat bytes | Edit | Pixels |",
        "|---|---|---|---:|---:|---:|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.case_id} | {row.family} | "
            f"{_yes(row.grammar_validation_success and row.execution_success)} | "
            f"{_decimal(row.source_observation_coverage)} | "
            f"{_decimal(row.maximum_key_split_boundary_error)} | "
            f"{row.supplied_repeat_count}/{row.produced_repeat_count} | "
            f"{row.repeat_decision} | {row.split_only_canonical_bytes} | "
            f"{row.repeat_grammar_canonical_bytes} | "
            f"{row.flat_canonical_bytes} | "
            f"{_yes(row.predefined_edit_valid)} | "
            f"{row.pixel_difference_status} |"
        )
    lines.extend(
        [
            "",
            "Every row uses an equivalent ordered flat terminal baseline. "
            "Machine-specific runtimes are stored separately as noncanonical "
            "diagnostics.",
        ]
    )
    return "\n".join(lines) + "\n"


def real_markdown(rows: tuple[RealCaseResult, ...]) -> str:
    lines = [
        "# Frozen real-case descriptive evidence",
        "",
        "These three Open Images examples are descriptive annotation-assisted "
        "evidence. They are not a real-case accuracy benchmark.",
        "",
        "| Case | Outcome | Observations | Repeat A/F | Primary | Nodes S/R | "
        "Bytes S/R | Primitives | Edit | Warnings | Limitation | Image ID | "
        "License |",
        "|---|---|---:|---:|---|---:|---:|---:|---|---:|---|---|---|",
    ]
    for row in rows:
        limitation = row.limitation_description or ""
        lines.append(
            f"| {row.case_key} | {row.outcome} | "
            f"{row.supplied_observation_count} | "
            f"{row.accepted_repeat_count}/{row.fallback_repeat_count} | "
            f"{row.primary_grammar} | "
            f"{row.split_symbolic_node_count}/{row.repeat_symbolic_node_count} | "
            f"{row.split_grammar_bytes}/{row.repeat_grammar_bytes} | "
            f"{row.primary_primitive_count} | {row.edit_status} | "
            f"{row.warning_count} | {limitation} | `{row.image_id}` | "
            f"{row.source_license} |"
        )
    return "\n".join(lines) + "\n"


def summary_markdown(summary: dict[str, Any]) -> str:
    boundary = summary["split_boundary_error"]
    lines = [
        "# Controlled summary",
        "",
        "Preliminary evidence for an annotation-assisted prototype. All "
        "denominators refer only to the 12 frozen controlled cases.",
        "",
        "| Metric | Result | Denominator |",
        "|---|---:|---:|",
    ]
    for key, label in (
        ("valid_grammar_rate", "Valid grammar rate"),
        ("execution_success_rate", "Execution-success rate"),
        ("complete_observation_coverage_rate", "Complete coverage rate"),
        ("exact_repeat_count_rate", "Exact repeat-count rate"),
        ("valid_edit_rate", "Valid-edit rate"),
    ):
        item = summary[key]
        lines.append(
            f"| {label} | {item['numerator']}/{item['denominator']} "
            f"({_decimal(item['rate'])}) | {item['denominator']} cases |"
        )
    lines.extend(
        [
            f"| Split-boundary absolute error, median [range] | "
            f"{_decimal(boundary['median'])} "
            f"[{_decimal(boundary['minimum'])}, "
            f"{_decimal(boundary['maximum'])}] | "
            f"{boundary['observation_count']} boundaries in "
            f"{boundary['case_count']} cases |",
            f"| Accepted repeat groups | "
            f"{summary['accepted_repeat_groups']['count']} | "
            f"{summary['accepted_repeat_groups']['denominator']} groups |",
            f"| Fallback repeat groups | "
            f"{summary['fallback_repeat_groups']['count']} | "
            f"{summary['fallback_repeat_groups']['denominator']} groups |",
            f"| Median split-only bytes | "
            f"{_decimal(summary['median_split_only_bytes']['median'])} | "
            f"{summary['median_split_only_bytes']['denominator']} cases |",
            f"| Median repeat bytes | "
            f"{_decimal(summary['median_repeat_bytes']['median'])} | "
            f"{summary['median_repeat_bytes']['denominator']} cases |",
            f"| Median repeat/split byte ratio | "
            f"{_decimal(summary['median_byte_ratio']['median'])} | "
            f"{summary['median_byte_ratio']['denominator']} cases |",
            "",
            "No significance test or cross-family boundary-type average is "
            "reported. All boundary observations use the same normalized "
            "parent-coordinate definition; per-case values remain available.",
        ]
    )
    return "\n".join(lines) + "\n"


def summary_rows_markdown(rows: list[dict[str, Any]]) -> str:
    controlled = [row for row in rows if row["row_type"] == "controlled"]
    real = [row for row in rows if row["row_type"] == "real"]
    lines = [
        "# Evaluation table",
        "",
        "Preliminary evidence for an annotation-assisted prototype.",
        "",
        "## Controlled cases",
        "",
        "| Case | Family | Valid/executable | Coverage | Repeat | Split B | "
        "Repeat B | Flat B | Edit |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in controlled:
        lines.append(
            f"| {row['case']} | {row['family']} | "
            f"{row['valid_executable']} | {row['observation_coverage']} | "
            f"{row['repeat_decision']} | {row['split_bytes']} | "
            f"{row['repeat_bytes']} | {row['flat_bytes']} | "
            f"{row['edit']} |"
        )
    lines.extend(
        [
            "",
            "## Frozen real assisted cases",
            "",
            "| Case | Outcome | Primary | Repeat | Edit | Principal limitation |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in real:
        lines.append(
            f"| {row['case']} | {row['outcome']} | {row['primary']} | "
            f"{row['repeat_decision']} | {row['edit']} | "
            f"{row['principal_limitation']} |"
        )
    lines.extend(
        [
            "",
            "The real cases are descriptive; no three-example accuracy is calculated.",
        ]
    )
    return "\n".join(lines) + "\n"


def atomic_write(
    path: Path,
    data: bytes,
    *,
    overwrite: bool,
    create_parents: bool = True,
) -> Path:
    """Atomically write one file and preserve conflicts by default."""
    resolved = Path(path).resolve()
    if create_parents:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() and not overwrite:
        raise EvaluationPersistenceError(
            f"Output exists; pass overwrite=True to replace it: {resolved}"
        )
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, resolved)
        else:
            os.link(temporary, resolved)
            temporary.unlink()
        temporary = None
    except OSError as exc:
        raise EvaluationPersistenceError(
            f"Could not persist {resolved}: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return resolved


def artifact_index(
    root: Path,
    *,
    excluded: tuple[str, ...] = (
        "artifact_index.json",
        "runtime_diagnostics.json",
    ),
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(
        (item for item in Path(root).rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix()
        if relative in excluded or path.name.endswith(".tmp"):
            continue
        data = path.read_bytes()
        records.append(
            {
                "byte_size": len(data),
                "canonical": True,
                "relative_path": relative,
                "sha256": sha256_bytes(data),
            }
        )
    return records


def _rows_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    names: list[str] = []
    for row in rows:
        for key in row:
            if key not in names:
                names.append(key)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(row.get(key, "")) for key in names})
    return stream.getvalue()


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, dict)):
        return canonical_json(value)
    return value


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def _decimal(value: float) -> str:
    return format(float(value), ".6g")
