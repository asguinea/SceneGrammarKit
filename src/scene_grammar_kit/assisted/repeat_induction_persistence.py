"""Safe deterministic persistence for repeat-group induction."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from scene_grammar_kit.assisted.lifting_serialization import (
    lifted_scene_to_canonical_json,
)
from scene_grammar_kit.assisted.repeat_induction_errors import (
    RepeatInductionFileExistsError,
    RepeatInductionWriteError,
)
from scene_grammar_kit.assisted.repeat_induction_models import (
    RepeatInductionReport,
    RepeatInductionResult,
    SavedRepeatInductionResult,
)
from scene_grammar_kit.assisted.repeat_induction_serialization import (
    repeat_induction_report_to_canonical_json,
)
from scene_grammar_kit.assisted.serialization import (
    annotation_to_canonical_json,
    construction_config_to_canonical_json,
)
from scene_grammar_kit.assisted.split_induction_serialization import (
    split_induction_report_to_canonical_json,
)
from scene_grammar_kit.geometry import execution_report_to_canonical_json
from scene_grammar_kit.grammar import grammar_to_canonical_json, grammar_tree_to_text

REPEAT_INDUCTION_ARTIFACT_FILENAMES = (
    "annotation.json",
    "construction_config.json",
    "lifted_observations.json",
    "split_only_grammar.json",
    "split_only_grammar_tree.txt",
    "repeat_grammar.json",
    "repeat_grammar_tree.txt",
    "split_induction_report.json",
    "repeat_induction_report.txt",
    "split_only_execution_report.json",
    "repeat_execution_report.json",
    "repeat_induction_report.json",
)


def clear_repeat_induction_success_report(output_directory: Path) -> None:
    """Remove only a known stale success marker before an overwrite attempt."""
    output = Path(output_directory).expanduser().resolve()
    if output.is_dir():
        _remove_file(
            output / "repeat_induction_report.json",
            "stale success report",
        )


def repeat_induction_report_to_text(report: RepeatInductionReport) -> str:
    """Render a deterministic human-readable report with one final newline."""
    lines = [
        "SceneGrammarKit supplied repeat-group induction",
        f"scene={report.scene_id}",
        f"repeat_induction_policy={report.repeat_induction_policy_version}",
        f"annotation_schema={report.annotation_schema_version}",
        f"construction_config_schema={report.construction_config_schema_version}",
        f"lifting_policy={report.lifting_policy_version}",
        f"split_induction_policy={report.split_induction_policy_version}",
        f"grammar_schema={report.grammar_schema_version}",
        f"execution_policy={report.execution_policy_version}",
        "",
        "Group decisions",
    ]
    if not report.group_decisions:
        lines.append("  none")
    for decision in report.group_decisions:
        metrics = decision.metrics
        lines.extend(
            [
                f"  group={decision.group_id} decision={decision.decision.value}",
                "    supplied_members=" + ",".join(decision.ordered_member_ids),
                f"    supplied_axis={metrics.supplied_axis.value}",
                f"    count={metrics.member_count}",
                f"    spacing={_number(metrics.estimated_spacing)}",
                f"    implied_element_extent={_number(metrics.implied_element_extent)}",
                f"    alignment_error={_number(metrics.alignment_error)}",
                f"    size_error={_number(metrics.size_error)}",
                f"    spacing_error={_number(metrics.spacing_error)}",
                f"    positional_residual={_number(metrics.positional_residual)}",
                "    reasons=" + (",".join(decision.reason_codes) or "none"),
                f"    repeat_node={decision.repeat_node_id or 'none'}",
                "    representative_element="
                + (decision.representative_element_id or "none"),
            ]
        )
    lines.extend(["", "Member mappings"])
    if not report.member_mappings:
        lines.append("  none")
    for mapping in report.member_mappings:
        lines.append(
            f"  group={mapping.repeat_group_id} "
            f"source={mapping.source_instance_id} "
            f"index={mapping.supplied_member_index} "
            f"status={mapping.representation_status.value} "
            f"residual={_number(mapping.boundary_residual)}"
        )
    compression = report.compression_summary
    lines.extend(
        [
            "",
            "Compactness diagnostics",
            f"  split_only_nodes={compression.split_only_symbolic_node_count}",
            f"  repeat_nodes_total={compression.repeat_symbolic_node_count}",
            f"  split_only_splits={compression.split_only_split_count}",
            f"  repeat_splits={compression.repeat_split_count}",
            f"  split_only_terminals={compression.split_only_terminal_count}",
            f"  repeat_terminals={compression.repeat_terminal_count}",
            f"  split_only_repeats={compression.split_only_repeat_count}",
            f"  repeat_repeats={compression.repeat_repeat_count}",
            f"  split_only_bytes={compression.split_only_canonical_bytes}",
            f"  repeat_bytes={compression.repeat_canonical_bytes}",
            f"  byte_difference={compression.absolute_byte_difference}",
            f"  byte_ratio={_number(compression.byte_ratio)}",
            f"  symbolic_node_difference={compression.symbolic_node_difference}",
            f"  primitives_before={compression.primitive_count_before}",
            f"  primitives_after={compression.primitive_count_after}",
            "",
            "Fidelity diagnostics",
            "  conceptual_count_before="
            f"{report.fidelity_summary.source_backed_conceptual_count_before}",
            "  conceptual_count_after="
            f"{report.fidelity_summary.source_backed_conceptual_count_after}",
            "  maximum_accepted_member_boundary_error="
            f"{_number(report.fidelity_summary.maximum_accepted_member_boundary_error)}",
            "  maximum_non_repeat_observation_change="
            f"{_number(report.fidelity_summary.maximum_non_repeat_observation_change)}",
            "  root_bounds_equal="
            + str(report.fidelity_summary.root_bounds_equal).lower(),
            "",
            "Diagnostics",
        ]
    )
    if not report.diagnostics:
        lines.append("  none")
    for diagnostic in report.diagnostics:
        context = (
            f" group={diagnostic.repeat_group_id}" if diagnostic.repeat_group_id else ""
        )
        lines.append(
            f"  {diagnostic.severity.value.upper()} {diagnostic.code}{context}: "
            f"{diagnostic.message}"
        )
    _section(lines, "Supplied information", report.supplied_information)
    _section(lines, "Derived information", report.derived_information)
    _section(lines, "Explicitly not inferred", report.explicitly_not_inferred)
    return "\n".join(lines) + "\n"


def save_repeat_induction_result(
    result: RepeatInductionResult,
    output_directory: Path,
    *,
    overwrite: bool = False,
) -> SavedRepeatInductionResult:
    """Save all artifacts atomically and write the success report last."""
    if not isinstance(result, RepeatInductionResult):
        raise TypeError("result must be a RepeatInductionResult")
    output = _prepare_output_directory(output_directory, overwrite=overwrite)
    report_path = output / "repeat_induction_report.json"
    if overwrite:
        _remove_file(report_path, "stale success report")
    split_execution_path = (
        output / "split_only_execution_report.json"
        if result.split_only_execution is not None
        else None
    )
    repeat_execution_path = (
        output / "repeat_execution_report.json"
        if result.repeat_execution is not None
        else None
    )
    values = [
        ("annotation.json", annotation_to_canonical_json(result.annotation)),
        (
            "construction_config.json",
            construction_config_to_canonical_json(result.construction_config),
        ),
        (
            "lifted_observations.json",
            lifted_scene_to_canonical_json(result.lifted_observations),
        ),
        (
            "split_only_grammar.json",
            grammar_to_canonical_json(result.split_induction_result.induced_grammar),
        ),
        (
            "split_only_grammar_tree.txt",
            grammar_tree_to_text(
                result.split_induction_result.induced_grammar,
                max_depth=result.construction_config.maximum_grammar_depth,
            ),
        ),
        ("repeat_grammar.json", grammar_to_canonical_json(result.repeat_grammar)),
        (
            "repeat_grammar_tree.txt",
            grammar_tree_to_text(
                result.repeat_grammar,
                max_depth=result.construction_config.maximum_grammar_depth,
            ),
        ),
        (
            "split_induction_report.json",
            split_induction_report_to_canonical_json(
                result.split_induction_result.report
            ),
        ),
        (
            "repeat_induction_report.txt",
            repeat_induction_report_to_text(result.report),
        ),
    ]
    if result.split_only_execution is not None:
        values.append(
            (
                "split_only_execution_report.json",
                execution_report_to_canonical_json(result.split_only_execution.report),
            )
        )
    elif overwrite:
        _remove_file(
            output / "split_only_execution_report.json",
            "stale split execution report",
        )
    if result.repeat_execution is not None:
        values.append(
            (
                "repeat_execution_report.json",
                execution_report_to_canonical_json(result.repeat_execution.report),
            )
        )
    elif overwrite:
        _remove_file(
            output / "repeat_execution_report.json",
            "stale repeat execution report",
        )
    try:
        for filename, text in values:
            _atomic_write_text(text, output / filename)
        _atomic_write_text(
            repeat_induction_report_to_canonical_json(result.report),
            report_path,
        )
    except Exception:
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return SavedRepeatInductionResult(
        output_directory=output,
        annotation_path=output / "annotation.json",
        construction_config_path=output / "construction_config.json",
        lifted_observations_path=output / "lifted_observations.json",
        split_only_grammar_path=output / "split_only_grammar.json",
        split_only_grammar_tree_path=output / "split_only_grammar_tree.txt",
        repeat_grammar_path=output / "repeat_grammar.json",
        repeat_grammar_tree_path=output / "repeat_grammar_tree.txt",
        split_induction_report_path=output / "split_induction_report.json",
        report_json_path=report_path,
        report_text_path=output / "repeat_induction_report.txt",
        split_only_execution_report_path=split_execution_path,
        repeat_execution_report_path=repeat_execution_path,
        result=result,
    )


def _prepare_output_directory(path: Path, *, overwrite: bool) -> Path:
    output = Path(path).expanduser().resolve()
    try:
        output.mkdir(parents=True, exist_ok=True)
        nonempty = any(output.iterdir())
    except OSError as exc:
        raise RepeatInductionWriteError(
            f"Could not prepare output directory {output}: {exc}"
        ) from exc
    if nonempty and not overwrite:
        raise RepeatInductionFileExistsError(
            f"Output directory is nonempty; pass overwrite=True to reuse it: {output}"
        )
    return output


def _remove_file(path: Path, label: str) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise RepeatInductionWriteError(f"Could not remove {label}: {exc}") from exc


def _atomic_write_text(text: str, path: Path) -> None:
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise RepeatInductionWriteError(f"Could not write {path.name}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _section(lines: list[str], title: str, values: tuple[str, ...]) -> None:
    lines.extend(["", title])
    lines.extend(f"  - {item}" for item in values)


def _number(value: float) -> str:
    return format(value, ".17g")
