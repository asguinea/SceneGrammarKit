"""Safe deterministic persistence for constrained split induction."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from scene_grammar_kit.assisted.lifting_serialization import (
    lifted_scene_to_canonical_json,
)
from scene_grammar_kit.assisted.serialization import (
    annotation_to_canonical_json,
    construction_config_to_canonical_json,
)
from scene_grammar_kit.assisted.split_induction_errors import (
    SplitInductionFileExistsError,
    SplitInductionWriteError,
)
from scene_grammar_kit.assisted.split_induction_models import (
    SavedSplitInductionResult,
    SplitInductionReport,
    SplitInductionResult,
)
from scene_grammar_kit.assisted.split_induction_serialization import (
    split_induction_report_to_canonical_json,
)
from scene_grammar_kit.geometry import execution_report_to_canonical_json
from scene_grammar_kit.grammar import grammar_to_canonical_json, grammar_tree_to_text

SPLIT_INDUCTION_ARTIFACT_FILENAMES = (
    "annotation.json",
    "construction_config.json",
    "lifted_observations.json",
    "induced_grammar.json",
    "grammar_tree.txt",
    "split_induction_report.txt",
    "execution_report.json",
    "split_induction_report.json",
)


def split_induction_report_to_text(
    report: SplitInductionReport,
) -> str:
    """Render a deterministic ASCII-safe report with one final newline."""
    lines = [
        "SceneGrammarKit constrained split induction",
        f"scene={report.scene_id}",
        f"split_induction_policy={report.split_induction_policy_version}",
        f"lifting_policy={report.lifting_policy_version}",
        f"grammar_schema={report.grammar_schema_version}",
        "",
        "Root depth split",
        f"  node={report.root_construction_decision.root_node_id}",
        f"  axis={report.root_construction_decision.axis.value}",
    ]
    for zone, interval, weight in zip(
        report.root_construction_decision.ordered_zones,
        report.root_construction_decision.configured_intervals,
        report.root_construction_decision.weights,
    ):
        lines.append(
            f"  {zone}: interval=[{_number(interval[0])},"
            f"{_number(interval[1])}] weight={_number(weight)}"
        )
    lines.extend(["", "Axis decisions"])
    for item in report.axis_decisions:
        lines.append(
            f"  parent={item.parent_source_id} axis={item.selected_axis.value} "
            f"source={item.selection_source.value} "
            f"tolerance={_number(item.world_tolerance)}"
        )
        for score in item.candidate_scores:
            lines.append(
                f"    candidate={score.axis.value} valid="
                f"{str(score.valid).lower()} overlap={score.overlap_violations} "
                f"spread={_number(score.normalized_centroid_spread)} "
                f"coverage={_number(score.normalized_coverage)} "
                f"gaps={score.explicit_gap_count}"
            )
    lines.extend(["", "Boundary decisions"])
    for item in report.boundary_decisions:
        lines.append(
            f"  parent={item.parent_source_id} axis={item.axis.value} "
            f"bounds={_interval(item.parent_interval)} "
            f"weights={','.join(_number(value) for value in item.final_weights)}"
        )
        for interval in item.intervals:
            lines.append(
                f"    source={interval.source_annotation_id} "
                f"input=[{_number(interval.source_minimum)},"
                f"{_number(interval.source_maximum)}] "
                f"final=[{_number(interval.final_minimum)},"
                f"{_number(interval.final_maximum)}]"
            )
    lines.extend(["", "Generated gaps and margins"])
    if not report.gap_decisions:
        lines.append("  none")
    for item in report.gap_decisions:
        lines.append(
            f"  parent={item.parent_source_id} axis={item.axis.value} "
            f"interval={_interval(item.gap_interval)} "
            f"reason={item.reason.value} node={item.generated_empty_node_id}"
        )
    lines.extend(["", "Source-to-node mapping"])
    for item in report.node_mappings:
        lines.append(
            f"  {item.source_annotation_type}:{item.source_annotation_id} "
            f"purpose={item.represented_purpose} "
            f"primary={item.primary_generated_node_id}"
        )
        lines.append("    nodes=" + ",".join(item.generated_grammar_node_ids))
    lines.extend(["", "Repeat candidates deferred"])
    if not report.repeat_candidates:
        lines.append("  none")
    for item in report.repeat_candidates:
        lines.append(
            f"  group={item.repeat_group_id} axis={item.supplied_axis.value} "
            f"members={','.join(item.ordered_source_member_ids)} "
            f"status={item.compression_status.value}"
        )
    lines.extend(
        [
            "",
            "Grammar statistics",
            f"  source_observations={report.source_observation_count}",
            f"  represented={report.represented_observation_count}",
            f"  omitted={report.omitted_observation_count}",
            f"  splits={report.split_node_count}",
            f"  terminals={report.terminal_node_count}",
            f"  empty_terminals={report.empty_terminal_count}",
            f"  repeat_nodes={report.repeat_node_count}",
            f"  maximum_depth={report.maximum_grammar_depth}",
            f"  canonical_grammar_bytes={report.canonical_grammar_byte_size}",
            f"  validation={str(report.validation_status).lower()}",
            "  execution_verified=" + str(report.execution_verification_status).lower(),
            "",
            "Diagnostics",
        ]
    )
    if not report.diagnostics:
        lines.append("  none")
    for item in report.diagnostics:
        source = (
            f" source={item.source_annotation_id}"
            if item.source_annotation_id is not None
            else ""
        )
        node = (
            f" node={item.grammar_node_id}" if item.grammar_node_id is not None else ""
        )
        lines.append(
            f"  {item.severity.value.upper()} {item.code}{source}{node}: {item.message}"
        )
    _section(lines, "Supplied information", report.supplied_information)
    _section(lines, "Derived information", report.derived_information)
    _section(lines, "Explicitly not inferred", report.explicitly_not_inferred)
    return (
        "\n".join(lines).encode("ascii", errors="backslashreplace").decode("ascii")
        + "\n"
    )


def save_split_induction_result(
    result: SplitInductionResult,
    output_directory: Path,
    *,
    overwrite: bool = False,
) -> SavedSplitInductionResult:
    """Save the integrated artifact set atomically, writing success JSON last."""
    if not isinstance(result, SplitInductionResult):
        raise TypeError("result must be a SplitInductionResult")
    output = _prepare_output_directory(output_directory, overwrite=overwrite)
    report_path = output / "split_induction_report.json"
    if overwrite:
        try:
            report_path.unlink(missing_ok=True)
        except OSError as exc:
            raise SplitInductionWriteError(
                f"Could not remove stale success report: {exc}"
            ) from exc
    values: list[tuple[str, str]] = [
        (
            "annotation.json",
            annotation_to_canonical_json(result.annotation),
        ),
        (
            "construction_config.json",
            construction_config_to_canonical_json(result.construction_config),
        ),
        (
            "lifted_observations.json",
            lifted_scene_to_canonical_json(result.lifted_observations),
        ),
        (
            "induced_grammar.json",
            grammar_to_canonical_json(result.induced_grammar),
        ),
        (
            "grammar_tree.txt",
            grammar_tree_to_text(
                result.induced_grammar,
                max_depth=result.construction_config.maximum_grammar_depth,
            ),
        ),
        (
            "split_induction_report.txt",
            split_induction_report_to_text(result.report),
        ),
    ]
    execution_path: Path | None = None
    if result.execution_verification_result is not None:
        execution_path = output / "execution_report.json"
        values.append(
            (
                "execution_report.json",
                execution_report_to_canonical_json(
                    result.execution_verification_result.report
                ),
            )
        )
    elif overwrite:
        try:
            (output / "execution_report.json").unlink(missing_ok=True)
        except OSError as exc:
            raise SplitInductionWriteError(
                f"Could not remove stale execution report: {exc}"
            ) from exc
    try:
        for name, text in values:
            _atomic_write_text(text, output / name, overwrite=True)
        _atomic_write_text(
            split_induction_report_to_canonical_json(result.report),
            report_path,
            overwrite=True,
        )
    except Exception:
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return SavedSplitInductionResult(
        output_directory=output,
        annotation_path=output / "annotation.json",
        construction_config_path=output / "construction_config.json",
        lifted_observations_path=output / "lifted_observations.json",
        induced_grammar_path=output / "induced_grammar.json",
        grammar_tree_path=output / "grammar_tree.txt",
        report_json_path=report_path,
        report_text_path=output / "split_induction_report.txt",
        execution_report_path=execution_path,
        result=result,
    )


def _prepare_output_directory(path: Path, *, overwrite: bool) -> Path:
    output = Path(path).expanduser().resolve()
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SplitInductionWriteError(
            f"Could not create output directory {output}: {exc}"
        ) from exc
    try:
        nonempty = any(output.iterdir())
    except OSError as exc:
        raise SplitInductionWriteError(
            f"Could not inspect output directory {output}: {exc}"
        ) from exc
    if nonempty and not overwrite:
        raise SplitInductionFileExistsError(
            f"Output directory is nonempty; pass overwrite=True to reuse it: {output}"
        )
    return output


def _atomic_write_text(text: str, path: Path, *, overwrite: bool) -> None:
    data = text.encode("utf-8")
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
        temporary = None
    except OSError as exc:
        raise SplitInductionWriteError(
            f"Could not atomically write {path}: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _section(lines: list[str], title: str, values: tuple[str, ...]) -> None:
    lines.extend(["", title])
    lines.extend(f"  - {value}" for value in values)


def _number(value: float) -> str:
    return format(value, ".15g")


def _interval(value: tuple[float, float]) -> str:
    return f"[{_number(value[0])},{_number(value[1])}]"
