"""Canonical serialization and text rendering for Phase 2 acceptance."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from scene_grammar_kit.phase2_acceptance.models import (
    Phase2AcceptanceCheck,
    Phase2AcceptanceReport,
    Phase2ArtifactRecord,
    Phase2CaseAcceptance,
    Phase2EvidenceRow,
)

EVIDENCE_FIELDS = tuple(field.name for field in fields(Phase2EvidenceRow))


def canonical_json(value: Any) -> str:
    """Encode canonical direct-Unicode JSON without a trailing newline."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def check_to_data(check: Phase2AcceptanceCheck) -> dict[str, Any]:
    return {
        "artifact_paths": list(check.artifact_paths),
        "case_key": check.case_key,
        "code": check.code,
        "description": check.description,
        "details": check.details,
        "required": check.required,
        "status": check.status.value,
    }


def case_to_data(case: Phase2CaseAcceptance) -> dict[str, Any]:
    return {
        "accepted_repeat_groups": case.accepted_repeat_groups,
        "case_key": case.case_key,
        "constructor_status": case.constructor_status,
        "expected_outcome": case.expected_outcome,
        "fallback_repeat_groups": case.fallback_repeat_groups,
        "image_id": case.image_id,
        "observed_outcome": case.observed_outcome,
        "primary_grammar": case.primary_grammar,
        "status": case.status.value,
    }


def report_to_data(report: Phase2AcceptanceReport) -> dict[str, Any]:
    return {
        "artifact_paths": list(report.artifact_paths),
        "cases": [case_to_data(item) for item in report.cases],
        "checks": [check_to_data(item) for item in report.checks],
        "failed_checks": report.failed_checks,
        "known_limitations": list(report.known_limitations),
        "next_step": report.next_step,
        "overall_status": report.overall_status.value,
        "passed_checks": report.passed_checks,
        "phase2_acceptance_policy_version": (report.phase2_acceptance_policy_version),
        "policy_versions": dict(report.policy_versions),
        "reproduction_command": report.reproduction_command,
        "required_failed_checks": report.required_failed_checks,
        "skipped_checks": report.skipped_checks,
        "total_checks": report.total_checks,
    }


def evidence_row_to_data(row: Phase2EvidenceRow) -> dict[str, Any]:
    return {field: getattr(row, field) for field in EVIDENCE_FIELDS}


def artifact_to_data(record: Phase2ArtifactRecord) -> dict[str, Any]:
    return {
        "byte_size": record.byte_size,
        "category": record.category,
        "relative_path": record.relative_path,
        "required": record.required,
        "sha256": record.sha256,
    }


def report_to_markdown(
    report: Phase2AcceptanceReport,
    evidence_rows: tuple[Phase2EvidenceRow, ...],
) -> str:
    """Generate the human report solely from structured model values."""
    failed = [item for item in report.checks if item.status.value == "FAIL"]
    skipped = [item for item in report.checks if item.status.value == "SKIP"]
    lines = [
        "# Phase 2 acceptance",
        "",
        f"**Overall status:** {report.overall_status.value}",
        "",
        "## Policy versions",
        "",
    ]
    lines.extend(f"- {name}: `{version}`" for name, version in report.policy_versions)
    lines.extend(
        [
            "",
            "## Case results",
            "",
            "| Case | Image ID | Expected | Observed | Primary | Repeats A/F | Status |",
            "|---|---|---|---|---|---:|---|",
        ]
    )
    for case in report.cases:
        lines.append(
            f"| {case.case_key} | `{case.image_id}` | "
            f"{case.expected_outcome} | {case.observed_outcome} | "
            f"{case.primary_grammar} | {case.accepted_repeat_groups}/"
            f"{case.fallback_repeat_groups} | {case.status.value} |"
        )
    lines.extend(
        [
            "",
            "## Acceptance totals",
            "",
            f"- Total: {report.total_checks}",
            f"- Passed: {report.passed_checks}",
            f"- Failed: {report.failed_checks}",
            f"- Skipped: {report.skipped_checks}",
            f"- Required failures: {report.required_failed_checks}",
            "",
            "## Failed checks",
            "",
        ]
    )
    lines.extend([f"- `{item.code}`: {item.details}" for item in failed] or ["- None."])
    lines.extend(["", "## Skipped checks", ""])
    lines.extend(
        [f"- `{item.code}`: {item.details}" for item in skipped] or ["- None."]
    )
    lines.extend(
        [
            "",
            "## Evidence summary",
            "",
            "One frozen row is reported per case. Missing values use the empty "
            "string. No aggregate statistics or rankings are calculated.",
            "",
            "\n".join(evidence_to_markdown(evidence_rows).splitlines()[4:]),
            "",
            "## Attribution status",
            "",
            "- Complete attribution records are in `attribution.json` and "
            "`ATTRIBUTION.md`.",
            "- Source-image licenses and the Open Images annotation license "
            "are recorded separately.",
            "",
            "## Deterministic verification",
            "",
        ]
    )
    determinism = [
        item for item in report.checks if item.code.startswith("DETERMINISM_")
    ]
    lines.extend(
        f"- `{item.code}`: {item.status.value} — {item.details}" for item in determinism
    )
    lines.extend(["", "## Known limitations", ""])
    lines.extend(f"- {item}" for item in report.known_limitations)
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```console",
            report.reproduction_command,
            "```",
            "",
            "## Explicit next step",
            "",
            report.next_step,
            "",
        ]
    )
    return "\n".join(lines)


def evidence_to_csv(rows: tuple[Phase2EvidenceRow, ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=EVIDENCE_FIELDS,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(evidence_row_to_data(row))
    return stream.getvalue()


def evidence_to_markdown(rows: tuple[Phase2EvidenceRow, ...]) -> str:
    """Render all descriptive evidence fields without aggregation."""
    header = "| " + " | ".join(EVIDENCE_FIELDS) + " |"
    separator = "|" + "|".join("---" for _ in EVIDENCE_FIELDS) + "|"
    lines = [
        "# Phase 2 descriptive evidence summary",
        "",
        "One frozen row is reported per case. Missing values use the empty "
        "string. No aggregate statistics or rankings are calculated.",
        "",
        header,
        separator,
    ]
    for row in rows:
        values = [
            str(getattr(row, field)).replace("|", "\\|") for field in EVIDENCE_FIELDS
        ]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def attribution_to_markdown(records: tuple[dict[str, Any], ...]) -> str:
    lines = [
        "# Open Images attribution",
        "",
        "The image licenses below apply to source photographs. Open Images "
        "annotations are recorded separately as CC BY 4.0.",
        "",
    ]
    for item in records:
        lines.extend(
            [
                f"## {item['case_key']}",
                "",
                f"- Open Images ID: `{item['image_id']}`",
                f"- Title: {item['title']}",
                f"- Author: {item['author']}",
                f"- Original landing page: {item['original_landing_page']}",
                f"- License: {item['license_name']} ({item['license_url']})",
                f"- Dataset: {item['dataset_name']} {item['dataset_version']}",
                f"- Annotation license: {item['annotation_license_url']}",
                "- Assets containing the image:",
            ]
        )
        lines.extend(f"  - `{path}`" for path in item["asset_paths"])
        lines.append("")
    return "\n".join(lines)


def artifact_index(
    root: Path,
    *,
    included: tuple[str, ...] | None = None,
    excluded: tuple[str, ...] = (
        "artifact_index.json",
        "phase2_acceptance.json",
    ),
) -> tuple[Phase2ArtifactRecord, ...]:
    records = []
    for path in sorted(
        (item for item in Path(root).rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix()
        if relative in excluded or path.name.endswith(".tmp"):
            continue
        if included is not None and relative not in included:
            continue
        data = path.read_bytes()
        records.append(
            Phase2ArtifactRecord(
                relative_path=relative,
                category=_artifact_category(relative),
                byte_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                required=True,
            )
        )
    return tuple(records)


def _artifact_category(relative: str) -> str:
    if relative.startswith("review/"):
        return "review_image"
    if relative == "phase2_regression_manifest.json":
        return "regression_manifest"
    if relative.startswith("attribution") or relative == "ATTRIBUTION.md":
        return "attribution"
    if "evidence_summary" in relative:
        return "evidence_summary"
    if "acceptance" in relative:
        return "acceptance_report"
    return "documentation"
