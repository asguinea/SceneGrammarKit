from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scene_grammar_kit.cli import main
from scene_grammar_kit.demo import (
    CANONICAL_SCENE_KEYS,
    DEMO_POLICY_VERSION,
    FULL_RENDER_HEIGHT,
    FULL_RENDER_WIDTH,
    QUICK_RENDER_HEIGHT,
    QUICK_RENDER_WIDTH,
    AcceptanceStatus,
    DemoConfig,
    DemoConfigurationError,
)


def test_default_config_selects_all_scenes_in_canonical_order() -> None:
    config = DemoConfig(Path("bundle"))
    assert config.selected_scene_keys == CANONICAL_SCENE_KEYS
    assert (config.width, config.height) == (
        FULL_RENDER_WIDTH,
        FULL_RENDER_HEIGHT,
    )


def test_explicit_scene_order_is_preserved() -> None:
    selected = ("indoor_corridor", "urban_street")
    assert (
        DemoConfig(Path("bundle"), selected_scene_keys=selected).selected_scene_keys
        == selected
    )


@pytest.mark.parametrize(
    "scenes",
    [
        ("urban_street", "urban_street"),
        ("unknown_scene",),
        (),
    ],
)
def test_invalid_scene_selections_are_rejected(scenes: tuple[str, ...]) -> None:
    with pytest.raises(DemoConfigurationError):
        DemoConfig(Path("bundle"), selected_scene_keys=scenes)


@pytest.mark.parametrize("seed", [-1, True, 1.5, "42"])
def test_invalid_seeds_are_rejected(seed: object) -> None:
    with pytest.raises(DemoConfigurationError):
        DemoConfig(Path("bundle"), seed=seed)  # type: ignore[arg-type]


def test_quick_resolution_policy_preserves_other_defaults() -> None:
    config = DemoConfig(Path("bundle"), quick=True)
    assert (config.width, config.height) == (
        QUICK_RENDER_WIDTH,
        QUICK_RENDER_HEIGHT,
    )
    assert config.seed == 42
    assert config.verify_glb
    assert config.calculate_hashes


def test_demo_policy_is_separate_and_frozen() -> None:
    assert DEMO_POLICY_VERSION == "0.1"


def test_cli_rejects_all_and_scene_conflict_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(
        [
            "demo",
            "--output",
            str(tmp_path / "bundle"),
            "--all",
            "--scene",
            "urban_street",
        ]
    )
    assert status == 2
    assert "--all cannot be combined" in capsys.readouterr().out


def test_cli_rejects_duplicate_scene_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(
        [
            "demo",
            "--output",
            str(tmp_path / "bundle"),
            "--scene",
            "urban_street",
            "--scene",
            "urban_street",
        ]
    )
    assert status == 2
    assert "duplicate scene" in capsys.readouterr().out


def test_demo_help_lists_every_required_option(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["demo", "--help"])
    assert raised.value.code == 0
    output = capsys.readouterr().out
    for option in (
        "--output",
        "--scene",
        "--all",
        "--overwrite",
        "--quick",
        "--seed",
        "--verify-determinism",
    ):
        assert option in output


def test_cli_quick_scene_selection_succeeds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(
        [
            "demo",
            "--output",
            str(tmp_path / "quick"),
            "--scene",
            "urban_street",
            "--quick",
        ]
    )
    output = capsys.readouterr().out
    assert status == 0
    assert "selected_scenes=urban_street" in output
    assert "acceptance=PASS" in output


def test_cli_full_default_builds_all_scenes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(["demo", "--output", str(tmp_path / "full")])
    output = capsys.readouterr().out
    assert status == 0
    assert "scene=urban_street status=PASS" in output
    assert "scene=repeated_facade status=PASS" in output
    assert "scene=indoor_corridor status=PASS" in output


def test_cli_invalid_scene_fails_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "demo",
                "--output",
                str(tmp_path / "bundle"),
                "--scene",
                "not_a_scene",
            ]
        )
    assert raised.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_cli_nonempty_output_fails_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "marker.txt").write_text("keep", encoding="utf-8")
    status = main(
        [
            "demo",
            "--output",
            str(root),
            "--scene",
            "urban_street",
            "--quick",
        ]
    )
    output = capsys.readouterr().out
    assert status == 2
    assert "DEMO FAILED" in output
    assert "Traceback" not in output


def test_cli_acceptance_failure_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failed_report = SimpleNamespace(
        overall_status=AcceptanceStatus.FAIL,
        total_checks=1,
        passed_checks=0,
        failed_checks=1,
        skipped_checks=0,
    )
    fake_result = SimpleNamespace(
        scene_results=(),
        acceptance_report=failed_report,
        output_directory=tmp_path / "bundle",
    )
    monkeypatch.setattr("scene_grammar_kit.cli.run_demo", lambda config: fake_result)
    status = main(["demo", "--output", str(tmp_path / "bundle")])
    assert status == 1
    assert "acceptance=FAIL" in capsys.readouterr().out


def test_existing_version_command_remains_functional(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["version"]) == 0
    assert "SceneGrammarKit 0.1.0" in capsys.readouterr().out
