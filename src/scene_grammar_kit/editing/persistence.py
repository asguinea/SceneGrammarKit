"""Canonical serialization and safe persistence for grammar edit results."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scene_grammar_kit.editing.errors import (
    EditFileExistsError,
    EditSerializationError,
    EditWriteError,
)
from scene_grammar_kit.editing.operations import (
    EditOperation,
    SetRepeatCount,
    SetRepeatSpacing,
    SetSplitChildWeight,
    SubstituteTerminalClass,
)
from scene_grammar_kit.editing.reports import EditReport, EditResult
from scene_grammar_kit.grammar import GrammarError, save_grammar
from scene_grammar_kit.paths import OutputDirectoryError, create_output_directory


def edit_operation_to_canonical_json(operation: EditOperation) -> str:
    """Serialize one typed operation to deterministic compact JSON."""
    return _canonical_json(_operation_data(operation), "edit operation")


def edit_report_to_canonical_json(report: EditReport) -> str:
    """Serialize an edit report without paths, timestamps, or machine data."""
    if not isinstance(report, EditReport):
        raise EditSerializationError("report must be an EditReport")
    return _canonical_json(_report_data(report), "edit report")


def save_edit_report(
    report: EditReport,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Atomically save a canonical edit report without silent overwrite."""
    return _atomic_write_text(
        edit_report_to_canonical_json(report),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_edit_result(
    result: EditResult,
    output_directory: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Save canonical before/after grammars and report as one safe artifact set."""
    if not isinstance(result, EditResult):
        raise EditSerializationError("result must be an EditResult")
    requested = Path(output_directory).expanduser().resolve()
    directory_existed = requested.exists()
    root: Path | None = None
    written: list[Path] = []
    try:
        root = create_output_directory(requested, allow_nonempty=overwrite)
        targets = (
            root / "grammar_before.json",
            root / "grammar_after.json",
            root / "edit_report.json",
        )
        if not overwrite:
            existing = next((path for path in targets if path.exists()), None)
            if existing is not None:
                raise EditFileExistsError(
                    f"Edit output exists; pass overwrite=True to replace it: {existing}"
                )
        written.append(
            save_grammar(
                result.original_grammar,
                targets[0],
                overwrite=overwrite,
            )
        )
        written.append(
            save_grammar(
                result.edited_grammar,
                targets[1],
                overwrite=overwrite,
            )
        )
        written.append(
            save_edit_report(
                result.report,
                targets[2],
                overwrite=overwrite,
            )
        )
    except EditFileExistsError:
        _clean_failed_new_output(root, written, directory_existed, overwrite)
        raise
    except OutputDirectoryError as exc:
        _clean_failed_new_output(root, written, directory_existed, overwrite)
        message = str(exc)
        if "not empty" in message or "not a directory" in message:
            raise EditFileExistsError(message) from exc
        raise EditWriteError(message) from exc
    except (GrammarError, EditWriteError, OSError) as exc:
        _clean_failed_new_output(root, written, directory_existed, overwrite)
        if isinstance(exc, EditWriteError):
            raise
        raise EditWriteError(
            f"Could not save edit result to {requested}: {exc}"
        ) from exc
    if root is None:
        raise EditWriteError(f"Could not prepare edit output: {requested}")
    return root


def _operation_data(operation: EditOperation) -> dict[str, Any]:
    if isinstance(operation, SetSplitChildWeight):
        return {
            "child_node_id": operation.child_node_id,
            "new_weight": operation.new_weight,
            "operation_type": operation.operation_type,
            "split_node_id": operation.split_node_id,
        }
    if isinstance(operation, SetRepeatCount):
        return {
            "new_count": operation.new_count,
            "operation_type": operation.operation_type,
            "repeat_node_id": operation.repeat_node_id,
        }
    if isinstance(operation, SetRepeatSpacing):
        return {
            "new_spacing": operation.new_spacing,
            "operation_type": operation.operation_type,
            "repeat_node_id": operation.repeat_node_id,
        }
    if isinstance(operation, SubstituteTerminalClass):
        return {
            "new_semantic_class": operation.new_semantic_class,
            "operation_type": operation.operation_type,
            "terminal_node_id": operation.terminal_node_id,
        }
    raise EditSerializationError("operation must be a supported EditOperation")


def _report_data(report: EditReport) -> dict[str, Any]:
    geometry = (
        None
        if report.geometry_diff is None
        else _tuples_to_lists(asdict(report.geometry_diff))
    )
    return {
        "edited_grammar_sha256": report.edited_grammar_sha256,
        "editing_policy_version": report.editing_policy_version,
        "execution_verification_succeeded": (report.execution_verification_succeeded),
        "geometry_diff": geometry,
        "grammar_schema_version": report.grammar_schema_version,
        "operations": [_operation_data(item) for item in report.operations],
        "original_grammar_sha256": report.original_grammar_sha256,
        "realizations": [
            _tuples_to_lists(asdict(item)) for item in report.realizations
        ],
        "success": report.success,
        "symbolic_diff": _tuples_to_lists(asdict(report.symbolic_diff)),
        "validation_succeeded": report.validation_succeeded,
        "warnings": list(report.warnings),
    }


def _tuples_to_lists(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _tuples_to_lists(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_tuples_to_lists(item) for item in value]
    if isinstance(value, list):
        return [_tuples_to_lists(item) for item in value]
    return value


def _canonical_json(value: object, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise EditSerializationError(
            f"Could not serialize {label} canonically: {exc}"
        ) from exc


def _atomic_write_text(
    text: str,
    path: Path,
    *,
    overwrite: bool,
    create_parents: bool,
) -> Path:
    resolved = Path(path).expanduser().resolve()
    parent = resolved.parent
    if create_parents:
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise EditWriteError(
                f"Could not create edit-report parent {parent}: {exc}"
            ) from exc
    if not parent.is_dir():
        raise EditWriteError(
            f"Edit-report parent does not exist: {parent}; "
            "pass create_parents=True to create it"
        )
    if resolved.exists() and not overwrite:
        raise EditFileExistsError(
            f"Edit report exists; pass overwrite=True to replace it: {resolved}"
        )

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary_path, resolved)
        else:
            try:
                os.link(temporary_path, resolved)
            except FileExistsError as exc:
                raise EditFileExistsError(
                    f"Edit report appeared during save and was preserved: {resolved}"
                ) from exc
            temporary_path.unlink()
        temporary_path = None
    except EditFileExistsError:
        raise
    except OSError as exc:
        raise EditWriteError(
            f"Could not safely write edit report {resolved}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return resolved


def _clean_failed_new_output(
    root: Path | None,
    written: list[Path],
    directory_existed: bool,
    overwrite: bool,
) -> None:
    if overwrite:
        return
    for path in reversed(written):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    if root is not None and not directory_existed:
        try:
            root.rmdir()
        except OSError:
            pass
