"""Safe persistence, artifact indexing, and text for assisted construction."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

from scene_grammar_kit.assisted.constructor_errors import (
    AssistedConstructorFileExistsError,
    AssistedConstructorWriteError,
)
from scene_grammar_kit.assisted.constructor_models import (
    AssistedConstructionReport,
    ConstructionArtifactIndex,
    ConstructionArtifactRecord,
)
from scene_grammar_kit.assisted.constructor_serialization import (
    assisted_construction_report_to_canonical_json,
)

_KNOWN_ARTIFACTS = {
    "construction_report.json",
    "construction_report.txt",
    "artifact_index.json",
    "runtime_report.json",
    "README.md",
    "input/annotation.json",
    "input/construction_config.json",
    "input/source_image.png",
    "input/source_image.jpg",
    "input/source_image.jpeg",
    "review/annotation_overlay.png",
    "review/annotation_summary.json",
    "review/annotation_summary.txt",
    "review/annotation_review_report.json",
    "lifting/lifted_observations.json",
    "lifting/lifted_observations.txt",
    "lifting/lifting_report.json",
}
for _prefix in ("split_only", "repeat", "primary"):
    _KNOWN_ARTIFACTS.update(
        {
            f"{_prefix}/grammar.json",
            f"{_prefix}/grammar_tree.txt",
            f"{_prefix}/induction_report.json",
            f"{_prefix}/induction_report.txt",
            f"{_prefix}/primitives.json",
            f"{_prefix}/execution_report.json",
            f"{_prefix}/scene.glb",
            f"{_prefix}/semantic_index.json",
            f"{_prefix}/render.png",
            f"{_prefix}/render.json",
        }
    )
_KNOWN_ARTIFACTS.update(
    {
        "edit/edit_specification.json",
        "edit/grammar_before.json",
        "edit/grammar_after.json",
        "edit/edit_report.json",
        "edit/primitives_after.json",
        "edit/execution_report_after.json",
        "edit/scene_after.glb",
        "edit/semantic_index_after.json",
        "edit/before.png",
        "edit/before.render.json",
        "edit/after.png",
        "edit/after.render.json",
    }
)


def prepare_constructor_output(
    output_directory: Path,
    *,
    overwrite: bool,
) -> Path:
    """Protect nonempty output and remove only a stale success marker."""
    output = Path(output_directory).expanduser().resolve()
    try:
        output.mkdir(parents=True, exist_ok=True)
        nonempty = any(output.iterdir())
    except OSError as exc:
        raise AssistedConstructorWriteError(
            f"Could not prepare constructor output: {exc}"
        ) from exc
    if nonempty and not overwrite:
        raise AssistedConstructorFileExistsError(
            f"Output directory is nonempty; pass overwrite=True to reuse it: {output}"
        )
    if overwrite:
        try:
            (output / "construction_report.json").unlink(missing_ok=True)
        except OSError as exc:
            raise AssistedConstructorWriteError(
                f"Could not remove stale construction report: {exc}"
            ) from exc
    return output


def build_artifact_index(
    artifacts: Mapping[str, bytes],
) -> ConstructionArtifactIndex:
    """Index final persisted bytes, excluding the index and success report."""
    records = []
    for path in sorted(artifacts):
        if path in {
            "artifact_index.json",
            "construction_report.json",
            "runtime_report.json",
        }:
            continue
        data = artifacts[path]
        prefix = path.split("/", 1)[0]
        grammar_type = prefix if prefix in {"split_only", "repeat", "primary"} else None
        records.append(
            ConstructionArtifactRecord(
                relative_path=path,
                category=_category(path),
                stage=_stage(path),
                byte_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                required=path != "runtime_report.json",
                grammar_type=grammar_type,
                edit_key="default_edit" if prefix == "edit" else None,
            )
        )
    return ConstructionArtifactIndex(tuple(records))


def persist_constructor_artifacts(
    output_directory: Path,
    artifacts: Mapping[str, bytes],
    report: AssistedConstructionReport,
    *,
    overwrite: bool,
) -> None:
    """Atomically persist the artifact bundle and success report last."""
    output = Path(output_directory).expanduser().resolve()
    report_path = output / "construction_report.json"
    expected = set(artifacts) | {"construction_report.json"}
    if overwrite:
        for relative in sorted(_KNOWN_ARTIFACTS - expected):
            try:
                (output / Path(relative)).unlink(missing_ok=True)
            except OSError as exc:
                raise AssistedConstructorWriteError(
                    f"Could not remove stale artifact {relative}: {exc}"
                ) from exc
    try:
        for relative in sorted(artifacts):
            _atomic_write_bytes(artifacts[relative], output / Path(relative))
        _atomic_write_bytes(
            assisted_construction_report_to_canonical_json(report).encode("utf-8"),
            report_path,
        )
    except Exception:
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def construction_report_to_text(report: AssistedConstructionReport) -> str:
    """Render a deterministic human-readable report with one final newline."""
    lines = [
        "SceneGrammarKit annotation-assisted scene construction",
        f"scene={report.scene_id}",
        f"image={report.image_id}",
        f"constructor_policy={report.constructor_policy_version}",
        f"status={'PASS' if report.success else 'FAIL'}",
        "",
        "Stage summary",
    ]
    for stage in report.stage_statuses:
        lines.append(f"  {stage.stage_name}: {stage.status.value} - {stage.detail}")
    lines.extend(["", "Grammar summaries"])
    for summary in report.grammar_summaries:
        lines.append(
            f"  {summary.grammar_type.value}: "
            f"nodes={summary.symbolic_node_count} "
            f"splits={summary.split_node_count} "
            f"repeats={summary.repeat_node_count} "
            f"terminals={summary.terminal_node_count} "
            f"primitives={summary.primitive_count} "
            f"bytes={summary.canonical_byte_size}"
        )
    lines.extend(
        [
            "",
            "Primary grammar",
            f"  type={report.primary_grammar_type.value}",
            f"  reason={report.primary_selection_reason}",
            f"  sha256={report.primary_grammar_sha256}",
            "",
            "Repeat decisions",
            f"  supplied={report.supplied_repeat_group_count}",
            f"  accepted={report.accepted_repeat_group_count}",
            f"  fallback={report.fallback_repeat_group_count}",
            "",
            "Default edit",
            f"  applied={str(report.edit_decision.applied).lower()}",
            f"  operation={report.edit_decision.operation_type or 'none'}",
            f"  target={report.edit_decision.target_node_id or 'none'}",
            f"  requested={report.edit_decision.requested_value or 'none'}",
            f"  realized={report.edit_decision.realized_value or 'none'}",
            f"  reason={report.edit_decision.reason}",
            "",
            f"Artifacts ({len(report.artifact_relative_paths)})",
        ]
    )
    lines.extend(f"  {path}" for path in report.artifact_relative_paths)
    _section(lines, "Supplied by annotation", report.supplied_information)
    _section(lines, "Supplied by configuration", report.configured_information)
    _section(lines, "Derived by SceneGrammarKit", report.derived_information)
    _section(lines, "Explicitly not inferred", report.explicitly_not_inferred)
    _section(lines, "Warnings", report.construction_warnings or ("none",))
    lines.extend(
        [
            "",
            "Reproduction",
            "  python -m scene_grammar_kit construct-assisted-scene "
            "input/annotation.json --config input/construction_config.json "
            "--out reproduced_bundle --width 1200 --height 800 "
            "--camera isometric",
        ]
    )
    return "\n".join(lines) + "\n"


def bundle_readme(report: AssistedConstructionReport) -> str:
    """Return a deterministic README describing assisted scope and contents."""
    edit = (
        "The edit/ directory demonstrates a user-requested procedural "
        "variation; it is not additional observed reconstruction evidence."
        if report.edit_decision.applied
        else "No safe default procedural edit was selected."
    )
    return (
        "# SceneGrammarKit annotation-assisted construction bundle\n\n"
        "This bundle is an annotation-assisted proxy 3D scene construction. "
        "Semantic regions, object instances, hierarchy, depth zones, and repeat "
        "membership were supplied; SceneGrammarKit deterministically derived proxy "
        "bounds, split structure, repeat compression, execution geometry, and "
        "semantic previews.\n\n"
        "## Directories\n\n"
        "- `input/`: copied source evidence and canonical supplied documents.\n"
        "- `review/`: annotation overlay and supplied-evidence summaries.\n"
        "- `lifting/`: coarse normalized proxy observations.\n"
        "- `split_only/`: Batch 2.4 grammar and generated artifacts.\n"
        "- `repeat/`: Batch 2.5 repeat-compressed grammar and artifacts.\n"
        "- `primary/`: deterministic selected grammar and matching artifacts.\n"
        "- `edit/`: before/after procedural edit evidence when available.\n\n"
        "Inspect grammars with `python -m scene_grammar_kit inspect <grammar.json>`. "
        "Open `scene.glb` in a GLB-compatible viewer. Compare `split_only/` "
        "against `repeat/` to inspect supplied repeat compression.\n\n"
        f"{edit}\n\n"
        "## Reproduction\n\n"
        "Run `python -m scene_grammar_kit construct-assisted-scene "
        "input/annotation.json --config input/construction_config.json "
        "--out reproduced_bundle --width 1200 --height 800 "
        "--camera isometric`.\n\n"
        "## Limitations\n\n"
        "This is coarse normalized proxy geometry, not automatic semantic "
        "segmentation, metric depth, camera calibration, hidden-object recovery, "
        "physical measurement, or photorealistic reconstruction.\n"
    )


def runtime_report_to_json(values: Mapping[str, object]) -> str:
    """Serialize explicitly noncanonical runtime diagnostics."""
    try:
        return json.dumps(
            dict(values),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise AssistedConstructorWriteError(
            f"Could not serialize runtime report: {exc}"
        ) from exc


def _category(path: str) -> str:
    if path.startswith("input/"):
        return "input_evidence"
    if path.endswith((".png", ".glb")):
        return "visual_or_geometry"
    if path.endswith(".json"):
        return "canonical_or_runtime_json"
    if path.endswith((".txt", ".md")):
        return "human_readable"
    return "input_evidence"


def _stage(path: str) -> str:
    if path == "input/annotation.json":
        return "annotation_validation"
    if path == "input/construction_config.json":
        return "config_validation"
    if path.startswith("input/source_image."):
        return "image_verification"
    prefix = path.split("/", 1)[0]
    return {
        "review": "annotation_review",
        "lifting": "lifting",
        "split_only": "split_induction",
        "repeat": "repeat_induction",
        "primary": "rendering",
        "edit": "default_edit",
    }.get(prefix, "persistence")


def _atomic_write_bytes(data: bytes, path: Path) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise AssistedConstructorWriteError(f"Could not write {path}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _section(lines: list[str], title: str, values: tuple[str, ...]) -> None:
    lines.extend(["", title])
    lines.extend(f"  - {value}" for value in values)
