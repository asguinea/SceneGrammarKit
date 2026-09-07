"""Safe output-directory conventions for SceneGrammarKit runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class OutputDirectoryError(RuntimeError):
    """Raised when an output directory cannot be prepared safely."""


@dataclass(frozen=True)
class RunDirectories:
    """Resolved paths for a minimal structured run directory."""

    root: Path
    artifacts: Path
    logs: Path
    metadata: Path


def create_output_directory(
    path: Path,
    *,
    allow_nonempty: bool = False,
) -> Path:
    """Create and return a resolved output directory safely.

    Existing files are rejected. Existing nonempty directories require explicit
    ``allow_nonempty=True`` permission. No existing content is deleted.
    """
    resolved = Path(path).expanduser().resolve()

    if resolved.exists():
        if not resolved.is_dir():
            raise OutputDirectoryError(
                f"Output path exists and is not a directory: {resolved}"
            )
        if any(resolved.iterdir()) and not allow_nonempty:
            raise OutputDirectoryError(
                "Output directory is not empty; pass allow_nonempty=True to use "
                f"it without deleting its contents: {resolved}"
            )
        return resolved

    try:
        resolved.mkdir(parents=True)
    except OSError as exc:
        raise OutputDirectoryError(
            f"Could not create output directory {resolved}: {exc}"
        ) from exc
    return resolved


def create_run_directories(
    path: Path,
    *,
    allow_nonempty: bool = False,
) -> RunDirectories:
    """Create a run root with ``artifacts``, ``logs``, and ``metadata`` folders."""
    root = create_output_directory(path, allow_nonempty=allow_nonempty)
    artifacts = _create_child(root / "artifacts")
    logs = _create_child(root / "logs")
    metadata = _create_child(root / "metadata")
    return RunDirectories(root=root, artifacts=artifacts, logs=logs, metadata=metadata)


def _create_child(path: Path) -> Path:
    """Create one known child directory without removing existing content."""
    try:
        path.mkdir(exist_ok=True)
    except OSError as exc:
        raise OutputDirectoryError(
            f"Could not create run directory {path}: {exc}"
        ) from exc
    if not path.is_dir():
        raise OutputDirectoryError(f"Run path exists and is not a directory: {path}")
    return path.resolve()
