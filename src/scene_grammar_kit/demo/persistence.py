"""Canonical serialization and safe persistence for demo policy 0.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scene_grammar_kit.demo.errors import DemoPersistenceError
from scene_grammar_kit.demo.models import (
    AcceptanceCheck,
    ArtifactEntry,
    DemoManifest,
    Phase1AcceptanceReport,
    SceneAcceptance,
)
from scene_grammar_kit.geometry.serialization import atomic_write_text


def canonical_json(value: object) -> str:
    """Return compact deterministic JSON with no environment metadata."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise DemoPersistenceError(
            f"could not serialize canonical JSON: {exc}"
        ) from exc


def demo_manifest_to_canonical_json(manifest: DemoManifest) -> str:
    """Serialize one immutable demo manifest."""
    return canonical_json(
        {
            "calculate_hashes": manifest.calculate_hashes,
            "demo_policy_version": manifest.demo_policy_version,
            "mode": manifest.mode,
            "package_version": manifest.package_version,
            "policy_versions": dict(manifest.policy_versions),
            "render_dimensions": {
                "height": manifest.render_height,
                "width": manifest.render_width,
            },
            "required_acceptance_checks": list(manifest.required_acceptance_checks),
            "required_camera_policy": manifest.required_camera_policy,
            "review_images": list(manifest.review_images),
            "scene_keys": list(manifest.scene_keys),
            "seed": manifest.seed,
            "source_manifests": list(manifest.source_manifests),
            "verify_glb": manifest.verify_glb,
        }
    )


def artifact_index_to_canonical_json(entries: tuple[ArtifactEntry, ...]) -> str:
    """Serialize an ordered artifact index."""
    return canonical_json(
        {
            "entries": [
                {
                    "byte_size": item.byte_size,
                    "category": item.category,
                    "edit_key": item.edit_key,
                    "path": item.path,
                    "required": item.required,
                    "scene_key": item.scene_key,
                    "sha256": item.sha256,
                }
                for item in entries
            ],
            "index_policy": (
                "artifact_index.json and phase1_acceptance.json are excluded "
                "to avoid recursive hashes and preserve final-report-last writes"
            ),
        }
    )


def acceptance_report_to_canonical_json(
    report: Phase1AcceptanceReport,
) -> str:
    """Serialize the structured acceptance report canonically."""
    return canonical_json(
        {
            "artifact_index_path": report.artifact_index_path,
            "checks": [_check_data(item) for item in report.checks],
            "demo_policy_version": report.demo_policy_version,
            "editing_policy_version": report.editing_policy_version,
            "execution_policy_version": report.execution_policy_version,
            "failed_checks": report.failed_checks,
            "grammar_schema_version": report.grammar_schema_version,
            "manifest_policy_version": report.manifest_policy_version,
            "overall_status": report.overall_status.value,
            "package_version": report.package_version,
            "passed_checks": report.passed_checks,
            "renderer_policy_version": report.renderer_policy_version,
            "scenes": [_scene_data(item) for item in report.scenes],
            "skipped_checks": report.skipped_checks,
            "total_checks": report.total_checks,
            "warnings": list(report.warnings),
        }
    )


def acceptance_report_to_markdown(
    report: Phase1AcceptanceReport,
    *,
    reproduction_command: str,
) -> str:
    """Derive the human-readable report from the structured report."""
    failures = [item for item in report.checks if item.status.value == "FAIL"]
    warnings = report.warnings
    lines = [
        "# SceneGrammarKit Phase 1 Acceptance",
        "",
        f"Overall status: **{report.overall_status.value}**",
        "",
        "## Policy versions",
        "",
        f"- Demo policy: `{report.demo_policy_version}`",
        f"- Grammar schema: `{report.grammar_schema_version}`",
        f"- Manifest policy: `{report.manifest_policy_version}`",
        f"- Execution policy: `{report.execution_policy_version}`",
        f"- Renderer policy: `{report.renderer_policy_version}`",
        f"- Editing policy: `{report.editing_policy_version}`",
        "",
        "## Scene summary",
        "",
        "| Scene | Status | Pass | Fail | Skip | Total |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| `{scene.scene_key}` | {scene.status.value} | "
        f"{scene.passed_checks} | {scene.failed_checks} | "
        f"{scene.skipped_checks} | {scene.total_checks} |"
        for scene in report.scenes
    )
    lines.extend(
        [
            "",
            "## Check totals",
            "",
            f"- Total: {report.total_checks}",
            f"- Passed: {report.passed_checks}",
            f"- Failed: {report.failed_checks}",
            f"- Skipped: {report.skipped_checks}",
            "",
            "## Failed checks",
            "",
        ]
    )
    if failures:
        lines.extend(
            f"- `{item.code}`"
            + (f" ({item.scene_key})" if item.scene_key else "")
            + f": {item.details}"
            for item in failures
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Canonical index: `{report.artifact_index_path}`",
            "- Scene builds: `scenes/`",
            "- Byte-identical review copies: `review/`",
            "",
            "## Reproduction",
            "",
            "```text",
            reproduction_command,
            "```",
            "",
            "## Phase 1 limitations",
            "",
            "- Grammars are hand-authored.",
            "- Geometry and rendering are schematic semantic proxies.",
            "- No image inference or automatic grammar induction is performed.",
            "- No quantitative recovery evaluation is claimed.",
            "- Rendering is not photorealistic.",
            "",
            "## Next-phase boundary",
            "",
            "Annotation-assisted construction, perception, recovery evaluation, "
            "and final presentation composition remain Phase 2 or later work.",
            "",
        ]
    )
    return "\n".join(lines)


def demo_readme(
    report: Phase1AcceptanceReport,
    *,
    reproduction_command: str,
) -> str:
    """Create a concise bundle guide from verified structured facts."""
    scene_lines = "\n".join(
        f"- `{scene.scene_key}`: {scene.status.value}" for scene in report.scenes
    )
    return (
        "# SceneGrammarKit Phase 1 Demo Bundle\n\n"
        "This bundle demonstrates validation and inspection of hand-authored "
        "grammars, deterministic semantic proxy execution, GLB export, semantic "
        "rendering, structural editing, provenance, and acceptance verification.\n\n"
        "## Reproduce\n\n"
        "```text\n"
        f"{reproduction_command}\n"
        "```\n\n"
        "## Structure\n\n"
        "- `scenes/`: canonical builder outputs\n"
        "- `review/`: byte-identical copies of selected scene renders\n"
        "- `demo_manifest.json`: environment-free run policy\n"
        "- `artifact_index.json`: sizes and SHA-256 hashes\n"
        "- `phase1_acceptance.json` and `.md`: acceptance evidence\n\n"
        "## Canonical scenes\n\n"
        f"{scene_lines}\n\n"
        "The required review images are listed in `demo_manifest.json`. Inspect "
        "grammar JSON and deterministic trees under each scene's `source/` "
        "directory. Open `.glb` files with any glTF 2.0 viewer.\n\n"
        "## Limitations\n\n"
        "The grammars are hand-authored; geometry is schematic; there is no "
        "image inference, quantitative recovery evaluation, or photorealistic "
        "rendering. The scenes were not reconstructed automatically.\n"
    )


def save_text(text: str, path: Path, *, overwrite: bool = True) -> Path:
    """Safely persist UTF-8 text beside an atomic temporary file."""
    try:
        return atomic_write_text(
            text,
            path,
            overwrite=overwrite,
            create_parents=True,
        )
    except Exception as exc:
        raise DemoPersistenceError(
            f"could not persist {Path(path).name}: {exc}"
        ) from exc


def _check_data(item: AcceptanceCheck) -> dict[str, Any]:
    return {
        "artifact_paths": list(item.artifact_paths),
        "code": item.code,
        "description": item.description,
        "details": item.details,
        "required": item.required,
        "scene_key": item.scene_key,
        "status": item.status.value,
    }


def _scene_data(item: SceneAcceptance) -> dict[str, Any]:
    return {
        "failed_checks": item.failed_checks,
        "passed_checks": item.passed_checks,
        "scene_key": item.scene_key,
        "skipped_checks": item.skipped_checks,
        "status": item.status.value,
        "total_checks": item.total_checks,
    }
