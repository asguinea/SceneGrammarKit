"""Guardrails for the public source snapshot."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOTS = (
    ".github",
    "datasets",
    "docs",
    "evaluation",
    "examples",
    "inputs",
    "protocols",
    "results",
    "scripts",
    "src",
    "tests",
)
TOP_LEVEL_TEXT = (
    ".gitattributes",
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "REPRODUCIBILITY.md",
    "SECURITY.md",
    "pyproject.toml",
)
TEXT_SUFFIXES = {
    ".cff",
    ".csv",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
FORBIDDEN_RELEASE_TERMS = (
    "proto" + "split",
    "sub" + "mission",
    "manu" + "script",
    "under " + "review",
    "po" + "ster",
)
SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"BEGIN (?:RSA|OPENSSH|EC|DSA) PRIVATE KEY"),
)
GENERATED_PATH_PARTS = {"__pycache__"}


def _public_files() -> list[Path]:
    files = [ROOT / name for name in TOP_LEVEL_TEXT]
    for relative in PUBLIC_ROOTS:
        base = ROOT / relative
        if base.exists():
            files.extend(
                path
                for path in base.rglob("*")
                if path.is_file()
                and not GENERATED_PATH_PARTS.intersection(path.parts)
                and not any(part.endswith(".egg-info") for part in path.parts)
            )
    return files


def test_public_snapshot_has_neutral_names_and_no_obvious_secrets() -> None:
    findings: list[str] = []
    for path in _public_files():
        relative = path.relative_to(ROOT).as_posix()
        lowered_path = relative.lower()
        for term in FORBIDDEN_RELEASE_TERMS:
            if term in lowered_path:
                findings.append(f"{relative}: forbidden path term {term!r}")
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TOP_LEVEL_TEXT:
            continue
        text = path.read_text(encoding="utf-8")
        lowered_text = text.lower()
        if path.name != "LICENSE":
            for term in FORBIDDEN_RELEASE_TERMS:
                if term in lowered_text:
                    findings.append(f"{relative}: forbidden text term {term!r}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"{relative}: possible credential")
    assert not findings, "\n".join(findings)


def test_private_workspace_directories_are_absent() -> None:
    private_paths = (
        ROOT / "definitions",
        ROOT / ("manu" + "script"),
        ROOT / "results" / ("sub" + "mission_assets"),
    )
    assert all(not path.exists() for path in private_paths)


def test_apache_license_is_declared_consistently() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice_text = (ROOT / "NOTICE").read_text(encoding="utf-8")
    project_metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "Apache License" in license_text
    assert "Version 2.0, January 2004" in license_text
    assert 'license = "Apache-2.0"' in project_metadata
    assert "Creative Commons" in notice_text
    assert "Attribution 2.0" in notice_text
    assert "not covered by the Apache License 2.0" in notice_text
