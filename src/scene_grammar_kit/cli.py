"""Command-line interface for the SceneGrammarKit foundation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from scene_grammar_kit import __version__
from scene_grammar_kit.assisted import (
    AnnotationOverlayConfig,
    AssistedError,
    AssistedValidationDiagnostic,
    LiftingValidationError,
    construct_assisted_scene,
    induce_repeat_grammar_from_files,
    induce_split_grammar_from_files,
    lift_assisted_input,
    load_and_verify_source_image,
    load_annotation,
    load_construction_config,
    review_assisted_input,
    save_lifting_result,
    validate_assisted_input,
)
from scene_grammar_kit.case_reselection import ReselectionError, run_case_reselection
from scene_grammar_kit.demo import (
    CANONICAL_SCENE_KEYS,
    DemoConfig,
    DemoError,
    run_demo,
)
from scene_grammar_kit.editing import (
    EditError,
    EditOperation,
    SetRepeatCount,
    SetRepeatSpacing,
    SetSplitChildWeight,
    SubstituteTerminalClass,
    apply_edit,
    save_edit_result,
)
from scene_grammar_kit.evaluation import (
    EvaluationError,
    EvaluationPersistenceError,
    run_evaluation,
)
from scene_grammar_kit.geometry import (
    DEFAULT_MAXIMUM_EXECUTION_DEPTH,
    DEFAULT_MAXIMUM_PRIMITIVES,
    GeometryError,
    execute_grammar,
    export_scene,
    save_executed_scene,
    save_execution_report,
)
from scene_grammar_kit.grammar import (
    GrammarError,
    GrammarExpansionLimitError,
    GrammarInspectionError,
    ValidationDiagnostic,
    load_grammar,
    save_grammar,
    validate_grammar,
)
from scene_grammar_kit.grammar.inspection import (
    format_grammar_summary,
    grammar_tree_to_text,
    summarize_grammar,
)
from scene_grammar_kit.paths import OutputDirectoryError, create_output_directory
from scene_grammar_kit.phase2_acceptance import (
    AcceptanceStatus as Phase2AcceptanceStatus,
)
from scene_grammar_kit.phase2_acceptance import (
    Phase2AcceptanceError,
    run_phase2_acceptance,
)
from scene_grammar_kit.real_cases import (
    CASE_KEYS as REAL_CASE_KEYS,
)
from scene_grammar_kit.real_cases import (
    RealCaseBuildError,
    build_open_images_cases,
)
from scene_grammar_kit.rendering import (
    CameraPreset,
    RenderConfig,
    RenderFileExistsError,
    RenderingError,
    render_executed_scene,
    render_report_path_for,
    save_render,
    save_render_report,
)
from scene_grammar_kit.scene_examples import (
    SceneExampleError,
    build_scene_example,
)
from scene_grammar_kit.system_info import (
    collect_environment_report,
    format_environment_report,
)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the SceneGrammarKit argument parser."""
    parser = argparse.ArgumentParser(
        prog="scene-grammar",
        description="Deterministic split-and-repeat grammars for coarse scene structure.",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("version", help="Show package and Python versions.")
    subparsers.add_parser("doctor", help="Check the local CPU-safe environment.")
    validate_parser = subparsers.add_parser(
        "validate", help="Load and semantically validate a grammar."
    )
    validate_parser.add_argument("grammar", type=Path, help="Grammar JSON file.")
    inspect_parser = subparsers.add_parser(
        "inspect", help="Print a validated grammar tree and summary."
    )
    inspect_parser.add_argument("grammar", type=Path, help="Grammar JSON file.")
    execute_parser = subparsers.add_parser(
        "execute", help="Execute a grammar into deterministic proxy geometry."
    )
    execute_parser.add_argument("grammar", type=Path, help="Grammar JSON file.")
    execute_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Structured output directory.",
    )
    execute_parser.add_argument(
        "--maximum-depth",
        type=_positive_int_argument,
        default=DEFAULT_MAXIMUM_EXECUTION_DEPTH,
        help="Maximum symbolic execution depth.",
    )
    execute_parser.add_argument(
        "--maximum-primitives",
        type=_positive_int_argument,
        default=DEFAULT_MAXIMUM_PRIMITIVES,
        help="Maximum renderable primitive count.",
    )
    execute_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reuse a nonempty output directory and replace known artifacts.",
    )
    render_parser = subparsers.add_parser(
        "render", help="Render a grammar as deterministic semantic PNG geometry."
    )
    render_parser.add_argument("grammar", type=Path, help="Grammar JSON file.")
    render_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="PNG output file; a companion .render.json report is also saved.",
    )
    render_parser.add_argument(
        "--camera",
        choices=tuple(item.value for item in CameraPreset),
        default=CameraPreset.ISOMETRIC.value,
        help="Deterministic orthographic camera preset.",
    )
    render_parser.add_argument(
        "--width",
        type=_positive_int_argument,
        default=1024,
        help="Final PNG width in pixels.",
    )
    render_parser.add_argument(
        "--height",
        type=_positive_int_argument,
        default=683,
        help="Final PNG height in pixels.",
    )
    render_parser.add_argument(
        "--supersampling",
        type=_positive_int_argument,
        default=2,
        help="Integer render scale before deterministic downsampling.",
    )
    render_parser.add_argument(
        "--show-bounds",
        action="store_true",
        help="Draw the projected root-bounds wireframe.",
    )
    render_parser.add_argument(
        "--no-ground",
        action="store_true",
        help="Disable the neutral minimum-y ground guide.",
    )
    render_parser.add_argument(
        "--no-edges",
        action="store_true",
        help="Disable semantic primitive outlines.",
    )
    render_parser.add_argument(
        "--transparent",
        action="store_true",
        help="Use a transparent background outside rendered geometry.",
    )
    render_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the PNG and companion report when they already exist.",
    )
    edit_parser = subparsers.add_parser(
        "edit", help="Apply one deterministic immutable grammar edit."
    )
    edit_subparsers = edit_parser.add_subparsers(
        dest="edit_operation",
        required=True,
    )
    split_weight_parser = edit_subparsers.add_parser(
        "split-weight",
        help="Change one direct split-child stored weight.",
    )
    _add_edit_common_arguments(split_weight_parser)
    split_weight_parser.add_argument(
        "--split-id",
        required=True,
        help="Target split node ID.",
    )
    split_weight_parser.add_argument(
        "--child-id",
        required=True,
        help="Direct child node ID.",
    )
    split_weight_parser.add_argument(
        "--weight",
        required=True,
        type=float,
        help="New strictly positive finite stored weight.",
    )
    repeat_count_parser = edit_subparsers.add_parser(
        "repeat-count",
        help="Change a repeat node's integer count.",
    )
    _add_edit_common_arguments(repeat_count_parser)
    repeat_count_parser.add_argument(
        "--repeat-id",
        required=True,
        help="Target repeat node ID.",
    )
    repeat_count_parser.add_argument(
        "--count",
        required=True,
        type=int,
        help="New integer count of at least one.",
    )
    repeat_spacing_parser = edit_subparsers.add_parser(
        "repeat-spacing",
        help="Change a repeat node's nonnegative spacing.",
    )
    _add_edit_common_arguments(repeat_spacing_parser)
    repeat_spacing_parser.add_argument(
        "--repeat-id",
        required=True,
        help="Target repeat node ID.",
    )
    repeat_spacing_parser.add_argument(
        "--spacing",
        required=True,
        type=float,
        help="New finite nonnegative spacing.",
    )
    terminal_parser = edit_subparsers.add_parser(
        "substitute-terminal",
        help="Change only a terminal node's semantic class.",
    )
    _add_edit_common_arguments(terminal_parser)
    terminal_parser.add_argument(
        "--terminal-id",
        required=True,
        help="Target terminal node ID.",
    )
    terminal_parser.add_argument(
        "--semantic-class",
        required=True,
        help="New nonempty semantic class.",
    )
    scene_example_parser = subparsers.add_parser(
        "build-scene-example",
        help="Build one complete canonical scene-example artifact set.",
    )
    scene_example_parser.add_argument(
        "manifest",
        type=Path,
        help="Strict scene_manifest.json source file.",
    )
    scene_example_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Complete generated scene output directory.",
    )
    scene_example_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reuse a nonempty directory and replace known artifacts.",
    )
    demo_parser = subparsers.add_parser(
        "demo",
        help="Build and formally audit an integrated Phase 1 demo bundle.",
    )
    demo_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Self-contained Phase 1 bundle directory.",
    )
    demo_parser.add_argument(
        "--scene",
        action="append",
        choices=CANONICAL_SCENE_KEYS,
        help="Build one canonical scene; repeat to preserve an explicit order.",
    )
    demo_parser.add_argument(
        "--all",
        action="store_true",
        help="Build all canonical scenes in the canonical order (the default).",
    )
    demo_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reuse a nonempty directory while preserving unrelated files.",
    )
    demo_parser.add_argument(
        "--quick",
        action="store_true",
        help="Render at 640x426 without changing grammar, edits, or semantics.",
    )
    demo_parser.add_argument(
        "--seed",
        type=_nonnegative_int_argument,
        default=42,
        help="Nonnegative deterministic seed (default: 42).",
    )
    demo_parser.add_argument(
        "--verify-determinism",
        action="store_true",
        help="Build again temporarily and compare JSON, PNG, and GLB artifacts.",
    )
    assisted_parser = subparsers.add_parser(
        "validate-assisted-input",
        help="Validate an annotation and construction-config pair.",
    )
    assisted_parser.add_argument(
        "annotation",
        type=Path,
        help="Scene annotation JSON file.",
    )
    assisted_parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Construction-configuration JSON file.",
    )
    review_parser = subparsers.add_parser(
        "review-annotation",
        help="Verify and render supplied assisted-annotation evidence.",
    )
    review_parser.add_argument(
        "annotation",
        type=Path,
        help="Scene annotation JSON file.",
    )
    review_parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Construction-configuration JSON file.",
    )
    review_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Directory for the six canonical review artifacts.",
    )
    review_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reuse a nonempty directory and replace known review artifacts.",
    )
    review_parser.add_argument(
        "--max-dimension",
        type=_positive_int_argument,
        default=1600,
        help="Maximum output width or height while preserving aspect ratio.",
    )
    review_parser.add_argument(
        "--line-width",
        type=_positive_int_argument,
        default=3,
        help="Positive annotation outline width in pixels.",
    )
    review_parser.add_argument(
        "--no-labels",
        action="store_true",
        help="Disable all annotation labels while preserving supplied marks.",
    )
    review_parser.add_argument(
        "--no-legend",
        action="store_true",
        help="Disable the supplied-annotation legend.",
    )
    review_parser.add_argument(
        "--show-parent-links",
        action="store_true",
        help="Draw supplied child-to-parent region connectors.",
    )
    review_parser.add_argument(
        "--transparent-layer",
        action="store_true",
        help="Render annotation marks on transparency instead of the source.",
    )
    lifting_parser = subparsers.add_parser(
        "lift-assisted-input",
        help="Lift supplied annotations into non-metric coarse observations.",
    )
    lifting_parser.add_argument(
        "annotation",
        type=Path,
        help="Scene annotation JSON file.",
    )
    lifting_parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Construction-configuration JSON file.",
    )
    lifting_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Directory for the five canonical lifting artifacts.",
    )
    lifting_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reuse a nonempty directory and replace known lifting artifacts.",
    )
    lifting_parser.add_argument(
        "--skip-image-verification",
        action="store_true",
        help="Explicitly lift without opening the image and record a warning.",
    )
    induction_parser = subparsers.add_parser(
        "induce-split-grammar",
        help="Construct a validated split-only grammar from lifted observations.",
    )
    induction_parser.add_argument(
        "annotation",
        type=Path,
        help="Scene annotation JSON file.",
    )
    induction_parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Construction-configuration JSON file.",
    )
    induction_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Directory for canonical split-induction artifacts.",
    )
    induction_parser.add_argument(
        "--lifted-observations",
        type=Path,
        help="Optional precomputed canonical lifted-observations JSON.",
    )
    induction_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reuse a nonempty directory and replace known induction artifacts.",
    )
    induction_parser.add_argument(
        "--skip-image-verification",
        action="store_true",
        help="Explicitly skip source-image verification during coarse lifting.",
    )
    induction_parser.add_argument(
        "--no-verify-execution",
        action="store_true",
        help="Validate but do not execute the induced grammar.",
    )
    induction_parser.add_argument(
        "--maximum-depth",
        type=_positive_int_argument,
        help="Override the configured grammar-depth limit.",
    )
    induction_parser.add_argument(
        "--maximum-primitives",
        type=_positive_int_argument,
        default=DEFAULT_MAXIMUM_PRIMITIVES,
        help="Maximum renderable primitives during execution verification.",
    )
    repeat_parser = subparsers.add_parser(
        "induce-repeat-grammar",
        help="Compress supplied regular groups into validated RepeatNode structures.",
    )
    repeat_parser.add_argument(
        "annotation",
        type=Path,
        help="Scene annotation JSON file.",
    )
    repeat_parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Construction-configuration JSON file.",
    )
    repeat_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Directory for canonical repeat-induction artifacts.",
    )
    repeat_parser.add_argument(
        "--split-induction-directory",
        type=Path,
        help="Optional precomputed canonical Batch 2.4 artifact directory.",
    )
    repeat_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reuse a nonempty directory and replace known repeat artifacts.",
    )
    repeat_parser.add_argument(
        "--skip-image-verification",
        action="store_true",
        help="Explicitly skip source-image verification during coarse lifting.",
    )
    repeat_parser.add_argument(
        "--no-verify-execution",
        action="store_true",
        help="Validate but do not execute the split-only or repeat grammar.",
    )
    repeat_parser.add_argument(
        "--maximum-depth",
        type=_positive_int_argument,
        help="Override the configured grammar-depth limit.",
    )
    repeat_parser.add_argument(
        "--maximum-primitives",
        type=_positive_int_argument,
        default=DEFAULT_MAXIMUM_PRIMITIVES,
        help="Maximum renderable primitives during execution verification.",
    )
    constructor_parser = subparsers.add_parser(
        "construct-assisted-scene",
        help="Build a complete disclosed annotation-assisted scene bundle.",
    )
    constructor_parser.add_argument(
        "annotation", type=Path, help="Scene annotation JSON file."
    )
    constructor_parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Construction-configuration JSON file.",
    )
    constructor_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Directory for the complete constructor bundle.",
    )
    constructor_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace known constructor artifacts in a nonempty directory.",
    )
    constructor_parser.add_argument(
        "--skip-image-verification",
        action="store_true",
        help="Explicitly skip image verification and annotation review rendering.",
    )
    constructor_parser.add_argument(
        "--no-verify-execution",
        action="store_true",
        help="Omit execution, GLB, and render artifacts.",
    )
    constructor_parser.add_argument(
        "--camera",
        default="isometric",
        choices=tuple(item.value for item in CameraPreset),
        help="Deterministic semantic-render camera preset.",
    )
    constructor_parser.add_argument(
        "--width",
        type=_positive_int_argument,
        default=1200,
        help="Semantic-render width in pixels.",
    )
    constructor_parser.add_argument(
        "--height",
        type=_positive_int_argument,
        default=800,
        help="Semantic-render height in pixels.",
    )
    constructor_parser.add_argument(
        "--no-default-edit",
        action="store_true",
        help="Do not select or apply the deterministic procedural edit.",
    )
    constructor_parser.add_argument(
        "--maximum-depth",
        type=_positive_int_argument,
        default=DEFAULT_MAXIMUM_EXECUTION_DEPTH,
        help="Maximum grammar validation and execution depth.",
    )
    constructor_parser.add_argument(
        "--maximum-primitives",
        type=_positive_int_argument,
        default=DEFAULT_MAXIMUM_PRIMITIVES,
        help="Maximum expanded primitives during execution.",
    )
    real_cases_parser = subparsers.add_parser(
        "build-open-images-cases",
        help="Build the three frozen annotation-assisted Open Images cases.",
    )
    real_cases_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Complete real-case result directory.",
    )
    selection = real_cases_parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--all",
        action="store_true",
        help="Build all three frozen cases (the default).",
    )
    selection.add_argument(
        "--case",
        action="append",
        choices=REAL_CASE_KEYS,
        help="Build one case; repeat the option to preserve an explicit order.",
    )
    real_cases_parser.add_argument(
        "--cache-directory",
        type=Path,
        help="Local ignored cache for optional official dataset acquisition.",
    )
    real_cases_parser.add_argument(
        "--candidate-count",
        type=_positive_int_argument,
        default=48,
        help="Candidate-search download limit (frozen builds do not redownload).",
    )
    real_cases_parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="Refresh official metadata during a future candidate-search pass.",
    )
    real_cases_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace known generated artifacts in a nonempty output directory.",
    )
    real_cases_parser.add_argument(
        "--verify-determinism",
        action="store_true",
        help="Build every case twice and compare JSON, PNG, GLB, and reports.",
    )
    reselection_parser = subparsers.add_parser(
        "reselect-cases",
        help="Acquire and visually review representation-aligned Open Images cases.",
    )
    reselection_parser.add_argument(
        "--cache-directory",
        type=Path,
        help="Existing or new ignored cache for official metadata and image pixels.",
    )
    reselection_parser.add_argument(
        "--candidate-count",
        type=_positive_int_argument,
        default=120,
        help="Total attribution-complete validation candidates to evaluate.",
    )
    reselection_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Candidate manifests, contact sheets, previews, and gate records.",
    )
    reselection_parser.add_argument(
        "--freeze-best",
        action="store_true",
        help="Freeze only curated candidates whose ten visual gates all pass.",
    )
    reselection_parser.add_argument(
        "--verify-determinism",
        action="store_true",
        help="Rebuild shortlisted previews and frozen cases and compare artifacts.",
    )
    reselection_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace known reselection artifacts in a nonempty output directory.",
    )
    phase2_parser = subparsers.add_parser(
        "phase2-acceptance",
        help="Audit and package the complete frozen Phase 2 assisted workflow.",
    )
    phase2_parser.add_argument(
        "--cases",
        required=True,
        type=Path,
        help="Directory containing the three frozen real-case inputs.",
    )
    phase2_parser.add_argument(
        "--results",
        required=True,
        type=Path,
        help="Directory containing the frozen Batch 2.7 result bundles.",
    )
    phase2_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory for the complete Phase 2 acceptance package.",
    )
    phase2_parser.add_argument(
        "--verify-determinism",
        action="store_true",
        help="Rebuild locally and compare stable JSON, PNG, GLB, and report evidence.",
    )
    phase2_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace known acceptance artifacts while preserving unrelated files.",
    )
    evaluation_parser = subparsers.add_parser(
        "evaluate",
        help="Generate the frozen evaluation package offline.",
    )
    evaluation_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory for controlled metrics, real-case evidence, and figures.",
    )
    evaluation_parser.add_argument(
        "--verify-determinism",
        action="store_true",
        help="Rebuild controlled cases and figures and compare canonical evidence.",
    )
    evaluation_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace known evaluation artifacts in an existing output directory.",
    )
    return parser


def _add_edit_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared Batch 1.6 editing options to one subcommand."""
    parser.add_argument("grammar", type=Path, help="Grammar JSON file.")
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Directory for before/after grammars and the edit report.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reuse a nonempty output directory and replace known artifacts.",
    )
    parser.add_argument(
        "--no-verify-execution",
        action="store_true",
        help="Skip original/edited execution and omit the geometry diff.",
    )
    parser.add_argument(
        "--maximum-depth",
        type=_positive_int_argument,
        default=DEFAULT_MAXIMUM_EXECUTION_DEPTH,
        help="Maximum grammar validation and execution depth.",
    )
    parser.add_argument(
        "--maximum-primitives",
        type=_positive_int_argument,
        default=DEFAULT_MAXIMUM_PRIMITIVES,
        help="Maximum renderable primitive count during verification.",
    )


def version_command() -> int:
    """Print version information and return a successful exit code."""
    print(f"SceneGrammarKit {__version__}")
    print(f"Python {sys.version.split()[0]}")
    return 0


def doctor_command() -> int:
    """Print an environment report and return its status."""
    report = collect_environment_report()
    print(format_environment_report(report))
    return 0 if report.required_checks_passed else 1


def validate_command(path: Path) -> int:
    """Load and semantically validate one grammar file."""
    try:
        grammar = load_grammar(path)
    except GrammarError as exc:
        print(f"INVALID: {path}")
        print(f"ERROR grammar_load_failed path={path} message={exc}")
        return 2

    report = validate_grammar(grammar)
    if not report.is_valid:
        print(f"INVALID: {path}")
        for diagnostic in report.diagnostics:
            print(_format_diagnostic(diagnostic))
        return 1

    print(f"VALID: {path}")
    try:
        summary = summarize_grammar(grammar)
    except GrammarExpansionLimitError as exc:
        print(f"WARNING summary_expansion_limit path={path} message={exc}")
        return 0
    print(
        f"nodes={summary.total_node_count} "
        f"splits={summary.split_node_count} "
        f"repeats={summary.repeat_node_count} "
        f"terminals={summary.terminal_node_count} "
        f"max_depth={summary.maximum_depth}"
    )
    return 0


def inspect_command(path: Path) -> int:
    """Load, validate, and print one deterministic grammar inspection."""
    try:
        grammar = load_grammar(path)
    except GrammarError as exc:
        print(f"INVALID: {path}")
        print(f"ERROR grammar_load_failed path={path} message={exc}")
        return 2

    report = validate_grammar(grammar)
    if not report.is_valid:
        print(f"INVALID: {path}")
        for diagnostic in report.diagnostics:
            print(_format_diagnostic(diagnostic))
        return 1

    try:
        tree = grammar_tree_to_text(grammar)
        summary = summarize_grammar(grammar)
    except GrammarInspectionError as exc:
        print(f"INSPECTION FAILED: {path}")
        print(f"ERROR inspection_failed path={path} message={exc}")
        return 1

    print(tree, end="")
    print(format_grammar_summary(summary), end="")
    return 0


def execute_command(
    grammar_path: Path,
    output_directory: Path,
    *,
    maximum_depth: int = DEFAULT_MAXIMUM_EXECUTION_DEPTH,
    maximum_primitives: int = DEFAULT_MAXIMUM_PRIMITIVES,
    overwrite: bool = False,
) -> int:
    """Execute one grammar and write the Batch 1.4 artifact set."""
    try:
        grammar = load_grammar(grammar_path)
        scene = execute_grammar(
            grammar,
            maximum_depth=maximum_depth,
            maximum_primitives=maximum_primitives,
        )
    except (GrammarError, GeometryError, ValueError) as exc:
        print(f"EXECUTION FAILED: {grammar_path}")
        print(f"ERROR execution_failed path={grammar_path} message={exc}")
        return 2

    try:
        root = create_output_directory(
            output_directory,
            allow_nonempty=overwrite,
        )
        grammar_directory = root / "grammar"
        geometry_directory = root / "geometry"
        save_grammar(
            grammar,
            grammar_directory / "grammar.json",
            overwrite=overwrite,
            create_parents=True,
        )
        save_grammar(
            grammar,
            grammar_directory / "grammar_canonical.json",
            overwrite=overwrite,
            create_parents=True,
        )
        save_executed_scene(
            scene,
            geometry_directory / "primitives.json",
            overwrite=overwrite,
            create_parents=True,
        )
        export_scene(
            scene,
            geometry_directory / "scene.glb",
            semantic_index_path=geometry_directory / "semantic_index.json",
            overwrite=overwrite,
            create_parents=True,
        )
        save_execution_report(
            scene.report,
            root / "execution_report.json",
            overwrite=overwrite,
            create_parents=True,
        )
    except (GrammarError, GeometryError, OutputDirectoryError, OSError) as exc:
        print(f"EXECUTION OUTPUT FAILED: {output_directory}")
        print(f"ERROR output_failed path={output_directory} message={exc}")
        return 2

    print(f"EXECUTED: {grammar_path}")
    print(f"output={root}")
    print(
        f"primitives={scene.report.primitive_count} "
        f"boxes={scene.report.box_count} "
        f"planes={scene.report.plane_count} "
        f"empty={scene.report.empty_terminal_count}"
    )
    print(f"grammar_sha256={scene.grammar_sha256}")
    return 0


def render_command(
    grammar_path: Path,
    output_path: Path,
    *,
    camera: str = CameraPreset.ISOMETRIC.value,
    width: int = 1024,
    height: int = 683,
    supersampling: int = 2,
    show_bounds: bool = False,
    show_ground: bool = True,
    show_edges: bool = True,
    transparent: bool = False,
    overwrite: bool = False,
) -> int:
    """Execute a grammar and save deterministic PNG and report artifacts."""
    try:
        grammar = load_grammar(grammar_path)
        scene = execute_grammar(grammar)
        config = RenderConfig(
            width=width,
            height=height,
            camera_preset=camera,
            show_bounds=show_bounds,
            show_ground=show_ground,
            show_edges=show_edges,
            transparent_background=transparent,
            supersampling=supersampling,
        )
        result = render_executed_scene(scene, config)
    except (GrammarError, GeometryError, RenderingError, ValueError) as exc:
        print(f"RENDER FAILED: {grammar_path}")
        print(f"ERROR render_failed path={grammar_path} message={exc}")
        return 2

    report_path = render_report_path_for(output_path)
    if not overwrite:
        existing = next(
            (
                path
                for path in (Path(output_path), report_path)
                if path.expanduser().resolve().exists()
            ),
            None,
        )
        if existing is not None:
            error = RenderFileExistsError(
                f"Render output exists; pass --overwrite to replace it: {existing}"
            )
            print(f"RENDER OUTPUT FAILED: {output_path}")
            print(f"ERROR output_failed path={output_path} message={error}")
            return 2

    image_path: Path | None = None
    try:
        image_path = save_render(
            result,
            output_path,
            overwrite=overwrite,
            create_parents=True,
        )
        saved_report_path = save_render_report(
            result.report,
            report_path,
            overwrite=overwrite,
            create_parents=True,
        )
    except RenderingError as exc:
        if image_path is not None and not overwrite:
            try:
                image_path.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"RENDER OUTPUT FAILED: {output_path}")
        print(f"ERROR output_failed path={output_path} message={exc}")
        return 2

    print(f"RENDERED: {grammar_path}")
    print(f"image={image_path}")
    print(f"report={saved_report_path}")
    print(
        f"size={result.report.width}x{result.report.height} "
        f"camera={result.report.camera_preset.value} "
        f"faces={result.report.visible_face_count}"
    )
    print(f"grammar_sha256={result.report.executed_scene_grammar_sha256}")
    return 0


def edit_command(
    grammar_path: Path,
    operation: EditOperation,
    output_directory: Path,
    *,
    verify_execution: bool = True,
    maximum_depth: int = DEFAULT_MAXIMUM_EXECUTION_DEPTH,
    maximum_primitives: int = DEFAULT_MAXIMUM_PRIMITIVES,
    overwrite: bool = False,
) -> int:
    """Apply and persist one typed edit, returning a CLI status code."""
    try:
        grammar = load_grammar(grammar_path)
        result = apply_edit(
            grammar,
            operation,
            verify_execution=verify_execution,
            maximum_depth=maximum_depth,
            maximum_primitives=maximum_primitives,
        )
        root = save_edit_result(
            result,
            output_directory,
            overwrite=overwrite,
        )
    except (GrammarError, EditError, GeometryError, ValueError) as exc:
        print(f"EDIT FAILED: {grammar_path}")
        print(f"ERROR edit_failed path={grammar_path} message={exc}")
        return 2

    print(f"EDITED: {grammar_path}")
    print(f"operation={operation.operation_type}")
    print(f"output={root}")
    print(f"original_grammar_sha256={result.report.original_grammar_sha256}")
    print(f"edited_grammar_sha256={result.report.edited_grammar_sha256}")
    print(
        "directly_modified_nodes="
        + ",".join(result.report.symbolic_diff.directly_modified_node_ids)
    )
    geometry = result.report.geometry_diff
    if geometry is None:
        print("execution_verification=disabled")
    else:
        print(
            f"primitives={geometry.primitive_count_before}"
            f"->{geometry.primitive_count_after} "
            f"added={geometry.added_primitive_count} "
            f"removed={geometry.removed_primitive_count} "
            f"modified={geometry.modified_primitive_count} "
            f"unchanged={geometry.unchanged_primitive_count}"
        )
    return 0


def build_scene_example_command(
    manifest_path: Path,
    output_directory: Path,
    *,
    overwrite: bool = False,
) -> int:
    """Build one canonical scene example and print a concise factual summary."""
    try:
        result = build_scene_example(
            manifest_path,
            output_directory,
            overwrite=overwrite,
        )
    except SceneExampleError as exc:
        print(f"SCENE EXAMPLE BUILD FAILED: {manifest_path}")
        print(f"ERROR scene_example_build_failed message={exc}")
        return 2
    report = result.report
    statistics = report.statistics
    print(f"SCENE EXAMPLE BUILT: {report.scene_key}")
    print(f"output={result.output_directory}")
    print(f"grammar_sha256={report.grammar_sha256}")
    print(
        f"nodes={statistics.symbolic_node_count} "
        f"splits={statistics.split_node_count} "
        f"repeats={statistics.repeat_node_count} "
        f"terminals={statistics.terminal_node_count} "
        f"primitives={statistics.original_primitive_count}"
    )
    for edit in report.edits:
        print(
            f"edit={edit.edit_key} "
            f"parameter={edit.parameter_before}->{edit.parameter_after} "
            f"primitives={edit.primitive_count_before}"
            f"->{edit.primitive_count_after}"
        )
    return 0


def demo_command(
    output_directory: Path,
    *,
    scenes: Sequence[str] | None = None,
    all_scenes: bool = False,
    overwrite: bool = False,
    quick: bool = False,
    seed: int = 42,
    verify_determinism: bool = False,
) -> int:
    """Build the integrated demo and print factual acceptance totals."""
    if all_scenes and scenes:
        print("DEMO FAILED")
        print("ERROR invalid_selection --all cannot be combined with --scene")
        return 2
    selected = tuple(scenes) if scenes else CANONICAL_SCENE_KEYS
    if len(set(selected)) != len(selected):
        print("DEMO FAILED")
        print("ERROR invalid_selection duplicate scene selections are not allowed")
        return 2
    print("selected_scenes=" + ",".join(selected))
    try:
        result = run_demo(
            DemoConfig(
                output_directory=output_directory,
                selected_scene_keys=selected,
                seed=seed,
                quick=quick,
                overwrite=overwrite,
                verify_determinism=verify_determinism,
            )
        )
    except DemoError as exc:
        print("DEMO FAILED")
        print(f"ERROR demo_failed message={exc}")
        return 2
    for scene in result.scene_results:
        print(f"scene={scene.report.scene_key} status=PASS")
    report = result.acceptance_report
    if report is None:
        print("DEMO FAILED")
        print("ERROR acceptance_missing")
        return 2
    print(
        f"acceptance={report.overall_status.value} "
        f"total={report.total_checks} passed={report.passed_checks} "
        f"failed={report.failed_checks} skipped={report.skipped_checks}"
    )
    print(f"bundle={result.output_directory}")
    return 0 if report.overall_status.value == "PASS" else 1


def build_open_images_cases_command(
    output_directory: Path,
    *,
    cases: Sequence[str] | None = None,
    overwrite: bool = False,
    verify_determinism: bool = False,
) -> int:
    """Build frozen real cases and print a concise factual summary."""
    selected = tuple(cases) if cases else REAL_CASE_KEYS
    try:
        summary = build_open_images_cases(
            output_directory,
            cases=selected,
            overwrite=overwrite,
            verify_determinism=verify_determinism,
        )
    except (RealCaseBuildError, OSError, ValueError) as exc:
        print("OPEN IMAGES CASE BUILD FAILED")
        print(f"ERROR real_case_build_failed message={exc}")
        return 2
    print("OPEN IMAGES CASE BUILD COMPLETE")
    for item in summary["cases"]:
        print(
            f"case={item['case_key']} image_id={item['image_id']} "
            f"outcome={item['outcome']}"
        )
    print(f"output={Path(output_directory)}")
    return 0


def phase2_acceptance_command(
    cases_directory: Path,
    results_directory: Path,
    output_directory: Path,
    *,
    verify_determinism: bool = False,
    overwrite: bool = False,
) -> int:
    """Run formal Phase 2 acceptance and print factual totals."""
    try:
        result = run_phase2_acceptance(
            cases_directory,
            results_directory,
            output_directory,
            overwrite=overwrite,
            verify_determinism=verify_determinism,
        )
    except (Phase2AcceptanceError, OSError, ValueError) as exc:
        print("PHASE 2 ACCEPTANCE FAILED")
        print(f"ERROR phase2_acceptance_failed message={exc}")
        return 2
    report = result.report
    print(f"PHASE 2 ACCEPTANCE {report.overall_status.value}")
    print(
        f"checks={report.total_checks} passed={report.passed_checks} "
        f"failed={report.failed_checks} skipped={report.skipped_checks}"
    )
    for case in report.cases:
        print(
            f"case={case.case_key} image_id={case.image_id} "
            f"outcome={case.observed_outcome} status={case.status.value}"
        )
    print(f"output={result.output_directory}")
    return 0 if report.overall_status is Phase2AcceptanceStatus.PASS else 1


def reselect_cases_command(
    output_directory: Path,
    *,
    cache_directory: Path | None = None,
    candidate_count: int = 120,
    freeze_best: bool = False,
    verify_determinism: bool = False,
    overwrite: bool = False,
) -> int:
    """Run official candidate acquisition and the reviewed freeze workflow."""
    try:
        result = run_case_reselection(
            output_directory,
            cache_directory=cache_directory,
            candidate_count=candidate_count,
            freeze_best=freeze_best,
            verify_determinism=verify_determinism,
            overwrite=overwrite,
        )
    except (ReselectionError, OSError, ValueError) as exc:
        print("CASE RESELECTION FAILED")
        print(f"ERROR case_reselection_failed message={exc}")
        return 2
    print("CASE RESELECTION COMPLETE")
    print(
        f"candidates={result.candidate_count} facade={result.facade_count} "
        f"street={result.street_count} shortlisted={result.shortlisted_count}"
    )
    if result.frozen_roles:
        print(f"frozen_roles={','.join(result.frozen_roles)}")
    print(f"output={result.output_directory}")
    return 0


def evaluation_command(
    output_directory: Path,
    *,
    verify_determinism: bool = False,
    overwrite: bool = False,
) -> int:
    """Generate the formal minimal evaluate evidence package."""
    try:
        result = run_evaluation(
            output_directory,
            verify_determinism=verify_determinism,
            overwrite=overwrite,
        )
    except (
        EvaluationError,
        EvaluationPersistenceError,
        OSError,
        ValueError,
    ) as exc:
        print("EVALUATION FAILED")
        print(f"ERROR evaluation_failed message={exc}")
        return 2
    summary = result.controlled_summary
    print("EVALUATION PASS")
    print(
        f"controlled_cases={len(result.controlled_rows)} "
        f"real_cases={len(result.real_rows)}"
    )
    print(
        "valid_grammars="
        f"{summary['valid_grammar_rate']['numerator']}/"
        f"{summary['valid_grammar_rate']['denominator']} "
        "executable="
        f"{summary['execution_success_rate']['numerator']}/"
        f"{summary['execution_success_rate']['denominator']}"
    )
    print(
        "accepted_repeats="
        f"{summary['accepted_repeat_groups']['count']}/"
        f"{summary['accepted_repeat_groups']['denominator']} "
        "fallback_repeats="
        f"{summary['fallback_repeat_groups']['count']}/"
        f"{summary['fallback_repeat_groups']['denominator']}"
    )
    print(f"output={result.output_directory}")
    return 0


def validate_assisted_input_command(
    annotation_path: Path,
    config_path: Path,
) -> int:
    """Load and validate one assisted annotation/configuration pair."""
    try:
        annotation = load_annotation(annotation_path)
        config = load_construction_config(config_path)
    except AssistedError as exc:
        print("INVALID ASSISTED INPUT")
        print(f"ERROR assisted_input_load_failed message={exc}")
        return 2
    report = validate_assisted_input(annotation, config)
    if not report.is_valid:
        print("INVALID ASSISTED INPUT")
        for diagnostic in report.diagnostics:
            print(_format_assisted_diagnostic(diagnostic))
        return 1
    print("VALID ASSISTED INPUT")
    print(f"scene={annotation.scene_id}")
    print(f"regions={len(annotation.regions)}")
    print(f"instances={len(annotation.instances)}")
    print(f"repeat_groups={len(annotation.repeat_groups)}")
    print(
        "depth_zones="
        + ",".join(item.depth_zone.value for item in config.depth_zone_intervals)
    )
    return 0


def review_annotation_command(
    annotation_path: Path,
    config_path: Path,
    output_directory: Path,
    *,
    overwrite: bool = False,
    maximum_dimension: int = 1600,
    line_width: int = 3,
    no_labels: bool = False,
    no_legend: bool = False,
    show_parent_links: bool = False,
    transparent_layer: bool = False,
) -> int:
    """Run the complete Batch 2.2 annotation-review workflow."""
    try:
        overlay_config = AnnotationOverlayConfig(
            maximum_output_dimension=maximum_dimension,
            line_width=line_width,
            draw_region_ids=not no_labels,
            draw_instance_ids=not no_labels,
            draw_semantic_labels=not no_labels,
            draw_depth_zone_labels=not no_labels,
            draw_parent_links=show_parent_links,
            draw_legend=not no_legend,
            transparent_semantic_layer=transparent_layer,
        )
        result = review_assisted_input(
            annotation_path,
            config_path,
            output_directory,
            overlay_config=overlay_config,
            overwrite=overwrite,
        )
    except (AssistedError, OSError, ValueError) as exc:
        print("ANNOTATION REVIEW FAILED")
        print(f"ERROR annotation_review_failed message={exc}")
        return 2
    print("REVIEW COMPLETE")
    print(f"scene={result.summary.scene_id}")
    print(f"image={result.summary.image_id}")
    print(f"regions={result.summary.region_count}")
    print(f"instances={result.summary.instance_count}")
    print(f"repeat_groups={result.summary.repeat_group_count}")
    print(f"overlay={output_directory / 'annotation_overlay.png'}")
    print(f"summary={output_directory / 'annotation_summary.json'}")
    print(f"report={output_directory / 'annotation_review_report.json'}")
    return 0


def lift_assisted_input_command(
    annotation_path: Path,
    config_path: Path,
    output_directory: Path,
    *,
    overwrite: bool = False,
    skip_image_verification: bool = False,
) -> int:
    """Run validated deterministic non-metric annotation lifting."""
    try:
        annotation = load_annotation(annotation_path)
        config = load_construction_config(config_path)
        validation = validate_assisted_input(annotation, config)
        if not validation.is_valid:
            codes = ", ".join(
                diagnostic.code
                for diagnostic in validation.diagnostics
                if diagnostic.severity.value == "error"
            )
            raise LiftingValidationError(
                f"Assisted input validation failed before lifting: {codes}"
            )
        verified = (
            None
            if skip_image_verification
            else load_and_verify_source_image(annotation, annotation_path)
        )
        result = lift_assisted_input(
            annotation,
            config,
            verified_source_image=verified,
        )
        save_lifting_result(
            result,
            output_directory,
            overwrite=overwrite,
        )
    except (AssistedError, OSError, ValueError) as exc:
        print("ASSISTED LIFT FAILED")
        print(f"ERROR assisted_lift_failed message={exc}")
        return 2
    print("LIFT COMPLETE")
    print(f"scene={result.scene.scene_id}")
    print(f"regions={result.report.region_observations_created}")
    print(f"instances={result.report.instance_observations_created}")
    print(f"observations={len(result.scene.observations)}")
    print("image_verified=" + str(result.scene.image_verification_status).lower())
    print(f"output={output_directory}")
    print(f"lifted={output_directory / 'lifted_observations.json'}")
    print(f"report={output_directory / 'lifting_report.json'}")
    return 0


def induce_split_grammar_command(
    annotation_path: Path,
    config_path: Path,
    output_directory: Path,
    *,
    lifted_observations_path: Path | None = None,
    overwrite: bool = False,
    skip_image_verification: bool = False,
    verify_execution: bool = True,
    maximum_depth: int | None = None,
    maximum_primitives: int = DEFAULT_MAXIMUM_PRIMITIVES,
) -> int:
    """Run deterministic constrained split-only grammar induction."""
    try:
        result = induce_split_grammar_from_files(
            annotation_path,
            config_path,
            output_directory,
            lifted_scene_path=lifted_observations_path,
            overwrite=overwrite,
            verify_image=not skip_image_verification,
            verify_execution=verify_execution,
            maximum_grammar_depth=maximum_depth,
            maximum_primitives=maximum_primitives,
        )
    except (AssistedError, OSError, ValueError) as exc:
        print("SPLIT INDUCTION FAILED")
        print(f"ERROR split_induction_failed message={exc}")
        return 2
    report = result.report
    print("SPLIT INDUCTION COMPLETE")
    print(f"scene={report.scene_id}")
    print(f"observations={report.source_observation_count}")
    print(f"represented={report.represented_observation_count}")
    print(f"splits={report.split_node_count}")
    print(f"terminals={report.terminal_node_count}")
    print(f"repeat_nodes={report.repeat_node_count}")
    print("execution_verified=" + str(report.execution_verification_status).lower())
    print(f"output={output_directory}")
    return 0


def induce_repeat_grammar_command(
    annotation_path: Path,
    config_path: Path,
    output_directory: Path,
    *,
    split_induction_directory: Path | None = None,
    overwrite: bool = False,
    skip_image_verification: bool = False,
    verify_execution: bool = True,
    maximum_depth: int | None = None,
    maximum_primitives: int = DEFAULT_MAXIMUM_PRIMITIVES,
) -> int:
    """Run deterministic supplied repeat-group grammar induction."""
    try:
        result = induce_repeat_grammar_from_files(
            annotation_path,
            config_path,
            output_directory,
            split_induction_directory=split_induction_directory,
            overwrite=overwrite,
            verify_image=not skip_image_verification,
            verify_execution=verify_execution,
            maximum_grammar_depth=maximum_depth,
            maximum_primitives=maximum_primitives,
        )
    except (AssistedError, OSError, ValueError) as exc:
        print("REPEAT INDUCTION FAILED")
        print(f"ERROR repeat_induction_failed message={exc}")
        return 2
    report = result.report
    print("REPEAT INDUCTION COMPLETE")
    print(f"scene={report.scene_id}")
    print(f"supplied_groups={report.supplied_repeat_group_count}")
    print(f"accepted_groups={report.accepted_group_count}")
    print(f"fallback_groups={report.fallback_group_count}")
    print(f"repeat_nodes={report.repeat_node_count}")
    print(
        f"split_only_nodes={report.compression_summary.split_only_symbolic_node_count}"
    )
    print(f"repeat_nodes_total={report.compression_summary.repeat_symbolic_node_count}")
    print("execution_verified=" + str(report.execution_status).lower())
    print(f"output={output_directory}")
    return 0


def construct_assisted_scene_command(
    annotation_path: Path,
    config_path: Path,
    output_directory: Path,
    *,
    overwrite: bool = False,
    skip_image_verification: bool = False,
    verify_execution: bool = True,
    camera: str = "isometric",
    width: int = 1200,
    height: int = 800,
    apply_default_edit: bool = True,
    maximum_depth: int = DEFAULT_MAXIMUM_EXECUTION_DEPTH,
    maximum_primitives: int = DEFAULT_MAXIMUM_PRIMITIVES,
) -> int:
    """Run the complete annotation-assisted constructor workflow."""
    try:
        result = construct_assisted_scene(
            annotation_path,
            config_path,
            output_directory,
            overwrite=overwrite,
            verify_image=not skip_image_verification,
            verify_execution=verify_execution,
            render_width=width,
            render_height=height,
            camera=camera,
            apply_default_edit=apply_default_edit,
            maximum_depth=maximum_depth,
            maximum_primitives=maximum_primitives,
        )
    except (
        AssistedError,
        GeometryError,
        RenderingError,
        EditError,
        OSError,
        ValueError,
    ) as exc:
        print("ASSISTED CONSTRUCTION FAILED")
        print(f"ERROR assisted_construction_failed message={exc}")
        return 2
    report = result.report
    print("ASSISTED CONSTRUCTION COMPLETE")
    print(f"scene={report.scene_id}")
    print(f"observations={len(result.lifting_result.scene.observations)}")
    print(f"split_nodes={report.grammar_summaries[0].symbolic_node_count}")
    print(f"repeat_groups={report.supplied_repeat_group_count}")
    print(f"accepted_repeats={report.accepted_repeat_group_count}")
    print(f"primary_grammar={report.primary_grammar_type.value}")
    print(
        "primary_primitives="
        f"{len(result.primary_execution.primitives) if result.primary_execution else 0}"
    )
    print(f"default_edit={report.edit_decision.operation_type or 'skipped'}")
    print(f"output={output_directory}")
    return 0


def _edit_operation_from_arguments(args: argparse.Namespace) -> EditOperation:
    """Construct the selected typed operation from parsed CLI arguments."""
    if args.edit_operation == "split-weight":
        return SetSplitChildWeight(
            split_node_id=args.split_id,
            child_node_id=args.child_id,
            new_weight=args.weight,
        )
    if args.edit_operation == "repeat-count":
        return SetRepeatCount(
            repeat_node_id=args.repeat_id,
            new_count=args.count,
        )
    if args.edit_operation == "repeat-spacing":
        return SetRepeatSpacing(
            repeat_node_id=args.repeat_id,
            new_spacing=args.spacing,
        )
    if args.edit_operation == "substitute-terminal":
        return SubstituteTerminalClass(
            terminal_node_id=args.terminal_id,
            new_semantic_class=args.semantic_class,
        )
    raise ValueError(f"Unsupported edit operation: {args.edit_operation}")


def _format_diagnostic(diagnostic: ValidationDiagnostic) -> str:
    """Format one structured diagnostic deterministically for the CLI."""
    parts = [diagnostic.severity.value.upper(), diagnostic.code]
    if diagnostic.path is not None:
        parts.append(f"path={diagnostic.path}")
    if diagnostic.node_id is not None:
        parts.append(f"node_id={diagnostic.node_id}")
    parts.append(f"message={diagnostic.message}")
    return " ".join(parts)


def _format_assisted_diagnostic(
    diagnostic: AssistedValidationDiagnostic,
) -> str:
    """Format one assisted-input diagnostic deterministically."""
    parts = [
        diagnostic.severity.value.upper(),
        diagnostic.code,
        f"domain={diagnostic.domain.value}",
    ]
    if diagnostic.annotation_id is not None:
        parts.append(f"annotation_id={diagnostic.annotation_id}")
    if diagnostic.path is not None:
        parts.append(f"path={diagnostic.path}")
    parts.append(f"message={diagnostic.message}")
    return " ".join(parts)


def _positive_int_argument(value: str) -> int:
    """Parse a positive integer for argparse execution limits."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _nonnegative_int_argument(value: str) -> int:
    """Parse a nonnegative deterministic seed."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a nonnegative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    """Run the SceneGrammarKit CLI with an optional argument sequence."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        return version_command()
    if args.command == "doctor":
        return doctor_command()
    if args.command == "validate":
        return validate_command(args.grammar)
    if args.command == "inspect":
        return inspect_command(args.grammar)
    if args.command == "execute":
        return execute_command(
            args.grammar,
            args.out,
            maximum_depth=args.maximum_depth,
            maximum_primitives=args.maximum_primitives,
            overwrite=args.overwrite,
        )
    if args.command == "render":
        return render_command(
            args.grammar,
            args.output,
            camera=args.camera,
            width=args.width,
            height=args.height,
            supersampling=args.supersampling,
            show_bounds=args.show_bounds,
            show_ground=not args.no_ground,
            show_edges=not args.no_edges,
            transparent=args.transparent,
            overwrite=args.overwrite,
        )
    if args.command == "edit":
        try:
            operation = _edit_operation_from_arguments(args)
        except (EditError, ValueError) as exc:
            print(f"EDIT FAILED: {args.grammar}")
            print(f"ERROR invalid_edit_operation message={exc}")
            return 2
        return edit_command(
            args.grammar,
            operation,
            args.out,
            verify_execution=not args.no_verify_execution,
            maximum_depth=args.maximum_depth,
            maximum_primitives=args.maximum_primitives,
            overwrite=args.overwrite,
        )
    if args.command == "build-scene-example":
        return build_scene_example_command(
            args.manifest,
            args.out,
            overwrite=args.overwrite,
        )
    if args.command == "demo":
        return demo_command(
            args.output,
            scenes=args.scene,
            all_scenes=args.all,
            overwrite=args.overwrite,
            quick=args.quick,
            seed=args.seed,
            verify_determinism=args.verify_determinism,
        )
    if args.command == "validate-assisted-input":
        return validate_assisted_input_command(
            args.annotation,
            args.config,
        )
    if args.command == "review-annotation":
        return review_annotation_command(
            args.annotation,
            args.config,
            args.out,
            overwrite=args.overwrite,
            maximum_dimension=args.max_dimension,
            line_width=args.line_width,
            no_labels=args.no_labels,
            no_legend=args.no_legend,
            show_parent_links=args.show_parent_links,
            transparent_layer=args.transparent_layer,
        )
    if args.command == "lift-assisted-input":
        return lift_assisted_input_command(
            args.annotation,
            args.config,
            args.out,
            overwrite=args.overwrite,
            skip_image_verification=args.skip_image_verification,
        )
    if args.command == "induce-split-grammar":
        return induce_split_grammar_command(
            args.annotation,
            args.config,
            args.out,
            lifted_observations_path=args.lifted_observations,
            overwrite=args.overwrite,
            skip_image_verification=args.skip_image_verification,
            verify_execution=not args.no_verify_execution,
            maximum_depth=args.maximum_depth,
            maximum_primitives=args.maximum_primitives,
        )
    if args.command == "induce-repeat-grammar":
        return induce_repeat_grammar_command(
            args.annotation,
            args.config,
            args.out,
            split_induction_directory=args.split_induction_directory,
            overwrite=args.overwrite,
            skip_image_verification=args.skip_image_verification,
            verify_execution=not args.no_verify_execution,
            maximum_depth=args.maximum_depth,
            maximum_primitives=args.maximum_primitives,
        )
    if args.command == "construct-assisted-scene":
        return construct_assisted_scene_command(
            args.annotation,
            args.config,
            args.out,
            overwrite=args.overwrite,
            skip_image_verification=args.skip_image_verification,
            verify_execution=not args.no_verify_execution,
            camera=args.camera,
            width=args.width,
            height=args.height,
            apply_default_edit=not args.no_default_edit,
            maximum_depth=args.maximum_depth,
            maximum_primitives=args.maximum_primitives,
        )
    if args.command == "build-open-images-cases":
        return build_open_images_cases_command(
            args.output,
            cases=args.case,
            overwrite=args.overwrite,
            verify_determinism=args.verify_determinism,
        )
    if args.command == "reselect-cases":
        return reselect_cases_command(
            args.output,
            cache_directory=args.cache_directory,
            candidate_count=args.candidate_count,
            freeze_best=args.freeze_best,
            verify_determinism=args.verify_determinism,
            overwrite=args.overwrite,
        )
    if args.command == "phase2-acceptance":
        return phase2_acceptance_command(
            args.cases,
            args.results,
            args.output,
            verify_determinism=args.verify_determinism,
            overwrite=args.overwrite,
        )
    if args.command == "evaluate":
        return evaluation_command(
            args.output,
            verify_determinism=args.verify_determinism,
            overwrite=args.overwrite,
        )
    parser.print_help()
    return 0
