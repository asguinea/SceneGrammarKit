"""Tests for safe output-directory preparation."""

from pathlib import Path

import pytest

from scene_grammar_kit.paths import (
    OutputDirectoryError,
    create_output_directory,
    create_run_directories,
)


def test_create_output_directory_with_parents(tmp_path: Path) -> None:
    """Nested output directories are created and returned as absolute paths."""
    result = create_output_directory(tmp_path / "parent" / "run")
    assert result.is_absolute()
    assert result.is_dir()


def test_nonempty_output_directory_requires_permission(tmp_path: Path) -> None:
    """Existing content cannot be silently overwritten."""
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(OutputDirectoryError, match="not empty"):
        create_output_directory(output)

    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_explicit_nonempty_permission_preserves_content(tmp_path: Path) -> None:
    """Explicit permission reuses a directory without deleting its contents."""
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    assert create_output_directory(output, allow_nonempty=True) == output.resolve()
    assert sentinel.exists()


def test_create_structured_run_directories(tmp_path: Path) -> None:
    """A future run receives the documented minimal subdirectory structure."""
    directories = create_run_directories(tmp_path / "runs" / "example")
    assert directories.root.is_absolute()
    assert directories.artifacts.is_dir()
    assert directories.logs.is_dir()
    assert directories.metadata.is_dir()
