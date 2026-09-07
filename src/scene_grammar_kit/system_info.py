"""Environment inspection used by the SceneGrammarKit doctor command."""

from __future__ import annotations

import platform
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scene_grammar_kit import __version__


@dataclass(frozen=True)
class EnvironmentReport:
    """Structured result of CPU-safe environment checks."""

    scene_grammar_kit_version: str
    python_version: str
    operating_system: str
    machine_architecture: str
    current_working_directory: Path
    protocol_directory: Path
    protocol_directory_exists: bool
    temporary_directory_writable: bool
    temporary_directory_error: str | None

    @property
    def required_checks_passed(self) -> bool:
        """Return whether all required local checks passed."""
        return self.protocol_directory_exists and self.temporary_directory_writable


def collect_environment_report(cwd: Path | None = None) -> EnvironmentReport:
    """Collect a deterministic local environment report without GPU checks."""
    working_directory = (cwd or Path.cwd()).expanduser().resolve()
    protocol_directory = (working_directory / "protocols" / "evaluation_v0_1").resolve()
    temporary_writable, temporary_error = _check_temporary_directory()
    return EnvironmentReport(
        scene_grammar_kit_version=__version__,
        python_version=platform.python_version(),
        operating_system=f"{platform.system()} {platform.release()}",
        machine_architecture=platform.machine() or "unknown",
        current_working_directory=working_directory,
        protocol_directory=protocol_directory,
        protocol_directory_exists=protocol_directory.is_dir(),
        temporary_directory_writable=temporary_writable,
        temporary_directory_error=temporary_error,
    )


def format_environment_report(report: EnvironmentReport) -> str:
    """Format an environment report for human-readable CLI output."""
    protocol_status = "PASS" if report.protocol_directory_exists else "FAIL"
    temporary_status = "PASS" if report.temporary_directory_writable else "FAIL"
    lines = [
        "SceneGrammarKit environment report",
        f"  SceneGrammarKit version: {report.scene_grammar_kit_version}",
        f"  Python version: {report.python_version}",
        f"  Operating system: {report.operating_system}",
        f"  Machine architecture: {report.machine_architecture}",
        f"  Current working directory: {report.current_working_directory}",
        (f"  Evaluation protocol: {protocol_status} ({report.protocol_directory})"),
        f"  Temporary directory writable: {temporary_status}",
    ]
    if report.temporary_directory_error:
        lines.append(f"  Temporary directory error: {report.temporary_directory_error}")
    lines.append(
        f"Overall status: {'PASS' if report.required_checks_passed else 'FAIL'}"
    )
    return "\n".join(lines)


def _check_temporary_directory() -> tuple[bool, str | None]:
    """Create and write a temporary file, returning status and any error."""
    try:
        with tempfile.TemporaryDirectory(
            prefix="scene_grammar_kit-doctor-"
        ) as temp_dir:
            probe = Path(temp_dir) / "write_probe.txt"
            probe.write_text("ok", encoding="utf-8")
            if probe.read_text(encoding="utf-8") != "ok":
                return False, "Temporary write probe content did not round-trip."
    except OSError as exc:
        return False, str(exc)
    return True, None
