"""Deterministic orchestration for complete canonical scene-example builds."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from scene_grammar_kit.editing import (
    EDITING_POLICY_VERSION,
    EditOperation,
    RepeatCountRealization,
    SetRepeatCount,
    SetRepeatSpacing,
    SetSplitChildWeight,
    SplitWeightRealization,
    SubstituteTerminalClass,
    TerminalSubstitutionRealization,
    apply_edit,
    save_edit_result,
)
from scene_grammar_kit.editing.reports import RepeatSpacingRealization
from scene_grammar_kit.geometry import (
    EXECUTION_POLICY_VERSION,
    ExecutedScene,
    execute_grammar,
    export_scene,
    save_executed_scene,
    save_execution_report,
)
from scene_grammar_kit.geometry.serialization import atomic_write_text
from scene_grammar_kit.grammar import (
    SCHEMA_VERSION,
    RepeatNode,
    SceneGrammar,
    SplitNode,
    TerminalNode,
    grammar_tree_to_text,
    load_grammar,
    save_grammar,
    summarize_grammar,
    validate_grammar,
)
from scene_grammar_kit.paths import OutputDirectoryError, create_output_directory
from scene_grammar_kit.rendering import (
    RENDERER_POLICY_VERSION,
    RenderConfig,
    render_executed_scene,
    save_render,
    save_render_report,
)
from scene_grammar_kit.scene_examples.errors import (
    ManifestValidationError,
    SceneExampleBuildError,
    SceneExampleError,
    SceneExampleFileExistsError,
)
from scene_grammar_kit.scene_examples.models import (
    MANIFEST_POLICY_VERSION,
    CanonicalEditSpec,
    SceneExampleBuildReport,
    SceneExampleBuildResult,
    SceneExampleEditBuild,
    SceneExampleStatistics,
    SceneManifest,
)
from scene_grammar_kit.scene_examples.persistence import (
    load_scene_manifest,
    save_build_report,
    save_scene_manifest,
)


def build_scene_example(
    manifest_path: Path,
    output_directory: Path,
    *,
    overwrite: bool = False,
    render_width: int | None = None,
    render_height: int | None = None,
) -> SceneExampleBuildResult:
    """Build one complete canonical source, geometry, edit, and render set."""
    manifest_file = Path(manifest_path).expanduser().resolve()
    output_requested = Path(output_directory).expanduser().resolve()
    try:
        manifest = load_scene_manifest(manifest_file)
        grammar_path = _resolve_grammar_path(manifest_file, manifest)
        grammar = load_grammar(grammar_path)
        _validate_manifest_expectations(manifest, grammar)
        validation = validate_grammar(grammar)
        if not validation.is_valid:
            first = validation.diagnostics[0]
            raise ManifestValidationError(
                f"Grammar is invalid: {first.code}: {first.message}"
            )
        summary = summarize_grammar(grammar)
        tree_text = grammar_tree_to_text(grammar)
        original_scene = execute_grammar(grammar)
        try:
            root = create_output_directory(
                output_requested,
                allow_nonempty=overwrite,
            )
        except OutputDirectoryError as exc:
            if "not empty" in str(exc) or "not a directory" in str(exc):
                raise SceneExampleFileExistsError(str(exc)) from exc
            raise SceneExampleBuildError(str(exc)) from exc

        artifacts: list[str] = []
        source = root / "source"
        original = root / "original"
        _save_grammar_artifact(
            grammar,
            source / "grammar.json",
            root,
            artifacts,
            overwrite,
        )
        _save_text_artifact(
            tree_text,
            source / "grammar_tree.txt",
            root,
            artifacts,
            overwrite,
        )
        _append(
            save_scene_manifest(
                manifest,
                source / "manifest.json",
                overwrite=overwrite,
                create_parents=True,
            ),
            root,
            artifacts,
        )
        _append(
            save_executed_scene(
                original_scene,
                original / "primitives.json",
                overwrite=overwrite,
                create_parents=True,
            ),
            root,
            artifacts,
        )
        _append(
            save_execution_report(
                original_scene.report,
                original / "execution_report.json",
                overwrite=overwrite,
                create_parents=True,
            ),
            root,
            artifacts,
        )
        original_export = export_scene(
            original_scene,
            original / "scene.glb",
            semantic_index_path=original / "semantic_index.json",
            overwrite=overwrite,
            create_parents=True,
        )
        _append(original_export.glb_path, root, artifacts)
        _append(original_export.semantic_index_path, root, artifacts)
        primary_config = _render_config(
            manifest,
            manifest.primary_camera.value,
            width=render_width,
            height=render_height,
        )
        secondary_config = _render_config(
            manifest,
            manifest.secondary_camera.value,
            width=render_width,
            height=render_height,
        )
        _save_render_pair(
            original_scene,
            primary_config,
            original / "primary.png",
            root,
            artifacts,
            overwrite,
        )
        _save_render_pair(
            original_scene,
            secondary_config,
            original / "secondary.png",
            root,
            artifacts,
            overwrite,
        )

        edit_builds: list[SceneExampleEditBuild] = []
        for edit_spec in manifest.canonical_edits:
            edit_builds.append(
                _build_edit(
                    root,
                    grammar,
                    original_scene,
                    manifest,
                    edit_spec,
                    artifacts,
                    overwrite,
                    render_width,
                    render_height,
                )
            )

        statistics = SceneExampleStatistics(
            symbolic_node_count=summary.total_node_count,
            split_node_count=summary.split_node_count,
            repeat_node_count=summary.repeat_node_count,
            terminal_node_count=summary.terminal_node_count,
            maximum_grammar_depth=summary.maximum_depth,
            canonical_grammar_byte_size=summary.canonical_byte_size,
            original_primitive_count=original_scene.report.primitive_count,
        )
        build_report_path = "build_report.json"
        report = SceneExampleBuildReport(
            success=True,
            manifest_policy_version=MANIFEST_POLICY_VERSION,
            scene_key=manifest.scene_key,
            grammar_sha256=original_scene.grammar_sha256,
            grammar_schema_version=SCHEMA_VERSION,
            execution_policy_version=EXECUTION_POLICY_VERSION,
            renderer_policy_version=RENDERER_POLICY_VERSION,
            editing_policy_version=EDITING_POLICY_VERSION,
            statistics=statistics,
            edit_keys=tuple(item.edit_key for item in manifest.canonical_edits),
            edits=tuple(edit_builds),
            artifact_paths=tuple(sorted(artifacts + [build_report_path])),
            warnings=tuple(manifest.known_limitations),
        )
        save_build_report(
            report,
            root / build_report_path,
            overwrite=overwrite,
        )
        return SceneExampleBuildResult(
            output_directory=root,
            manifest=manifest,
            report=report,
        )
    except SceneExampleError:
        raise
    except Exception as exc:
        raise SceneExampleBuildError(
            f"Could not build scene example from {manifest_file.name}: {exc}"
        ) from exc


def operation_from_edit_spec(spec: CanonicalEditSpec) -> EditOperation:
    """Create one existing immutable edit operation from a manifest entry."""
    parameters = spec.parameters
    try:
        if spec.operation_type == "set_split_child_weight":
            return SetSplitChildWeight(
                split_node_id=cast(str, parameters["split_node_id"]),
                child_node_id=cast(str, parameters["child_node_id"]),
                new_weight=cast(
                    int | float,
                    parameters["new_weight"],
                ),
            )
        if spec.operation_type == "set_repeat_count":
            return SetRepeatCount(
                repeat_node_id=cast(str, parameters["repeat_node_id"]),
                new_count=cast(int, parameters["new_count"]),
            )
        if spec.operation_type == "set_repeat_spacing":
            return SetRepeatSpacing(
                repeat_node_id=cast(str, parameters["repeat_node_id"]),
                new_spacing=cast(
                    int | float,
                    parameters["new_spacing"],
                ),
            )
        if spec.operation_type == "substitute_terminal_class":
            return SubstituteTerminalClass(
                terminal_node_id=cast(str, parameters["terminal_node_id"]),
                new_semantic_class=cast(
                    str,
                    parameters["new_semantic_class"],
                ),
            )
    except Exception as exc:
        raise ManifestValidationError(
            f"Edit {spec.edit_key!r} has invalid parameters: {exc}"
        ) from exc
    raise ManifestValidationError(
        f"Edit {spec.edit_key!r} has an unsupported operation type"
    )


def _build_edit(
    root: Path,
    grammar: SceneGrammar,
    original_scene: ExecutedScene,
    manifest: SceneManifest,
    spec: CanonicalEditSpec,
    artifacts: list[str],
    overwrite: bool,
    render_width: int | None,
    render_height: int | None,
) -> SceneExampleEditBuild:
    operation = operation_from_edit_spec(spec)
    result = apply_edit(grammar, operation)
    if result.edited_execution is None:
        raise SceneExampleBuildError(
            f"Edit {spec.edit_key!r} did not produce verified execution"
        )
    edit_root = root / "edits" / spec.edit_key
    save_edit_result(result, edit_root, overwrite=overwrite)
    for name in (
        "grammar_before.json",
        "grammar_after.json",
        "edit_report.json",
    ):
        _append(edit_root / name, root, artifacts)
    edited_scene = result.edited_execution
    _append(
        save_executed_scene(
            edited_scene,
            edit_root / "primitives_after.json",
            overwrite=overwrite,
        ),
        root,
        artifacts,
    )
    _append(
        save_execution_report(
            edited_scene.report,
            edit_root / "execution_report_after.json",
            overwrite=overwrite,
        ),
        root,
        artifacts,
    )
    export_result = export_scene(
        edited_scene,
        edit_root / "scene_after.glb",
        semantic_index_path=edit_root / "semantic_index_after.json",
        overwrite=overwrite,
    )
    _append(export_result.glb_path, root, artifacts)
    _append(export_result.semantic_index_path, root, artifacts)
    config = _render_config(
        manifest,
        spec.recommended_render_camera.value,
        width=render_width,
        height=render_height,
    )
    _save_render_pair(
        original_scene,
        config,
        edit_root / "before.png",
        root,
        artifacts,
        overwrite,
    )
    _save_render_pair(
        edited_scene,
        config,
        edit_root / "after.png",
        root,
        artifacts,
        overwrite,
    )
    before, after, normalized_before, normalized_after, count_before, count_after = (
        _realization_values(result.report.realizations[0])
    )
    edit_paths = tuple(
        sorted(path for path in artifacts if path.startswith(f"edits/{spec.edit_key}/"))
    )
    return SceneExampleEditBuild(
        edit_key=spec.edit_key,
        operation_type=spec.operation_type,
        original_grammar_sha256=result.report.original_grammar_sha256,
        edited_grammar_sha256=result.report.edited_grammar_sha256,
        primitive_count_before=original_scene.report.primitive_count,
        primitive_count_after=edited_scene.report.primitive_count,
        render_camera=spec.recommended_render_camera.value,
        render_width=config.width,
        render_height=config.height,
        parameter_before=before,
        parameter_after=after,
        normalized_fraction_before=normalized_before,
        normalized_fraction_after=normalized_after,
        conceptual_repeat_count_before=count_before,
        conceptual_repeat_count_after=count_after,
        artifact_paths=edit_paths,
    )


def _realization_values(
    realization: object,
) -> tuple[
    int | float | str,
    int | float | str,
    float | None,
    float | None,
    int | None,
    int | None,
]:
    if isinstance(realization, SplitWeightRealization):
        return (
            realization.old_stored_weight,
            realization.realized_new_stored_weight,
            realization.old_normalized_fraction,
            realization.new_normalized_fraction,
            None,
            None,
        )
    if isinstance(realization, RepeatCountRealization):
        return (
            realization.old_count,
            realization.realized_count,
            None,
            None,
            realization.conceptual_expanded_terminal_count_before,
            realization.conceptual_expanded_terminal_count_after,
        )
    if isinstance(realization, RepeatSpacingRealization):
        return (
            realization.old_spacing,
            realization.realized_spacing,
            None,
            None,
            None,
            None,
        )
    if isinstance(realization, TerminalSubstitutionRealization):
        return (
            realization.old_semantic_class,
            realization.realized_semantic_class,
            None,
            None,
            None,
            None,
        )
    raise SceneExampleBuildError("Edit realization type is unsupported")


def _render_config(
    manifest: SceneManifest,
    camera: str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> RenderConfig:
    return RenderConfig(
        width=manifest.primary_render_width if width is None else width,
        height=manifest.primary_render_height if height is None else height,
        camera_preset=camera,
    )


def _save_render_pair(
    scene: ExecutedScene,
    config: RenderConfig,
    image_path: Path,
    root: Path,
    artifacts: list[str],
    overwrite: bool,
) -> None:
    rendered = render_executed_scene(scene, config)
    _append(
        save_render(
            rendered,
            image_path,
            overwrite=overwrite,
            create_parents=True,
        ),
        root,
        artifacts,
    )
    _append(
        save_render_report(
            rendered.report,
            image_path.with_suffix(".render.json"),
            overwrite=overwrite,
            create_parents=True,
        ),
        root,
        artifacts,
    )


def _save_grammar_artifact(
    grammar: SceneGrammar,
    path: Path,
    root: Path,
    artifacts: list[str],
    overwrite: bool,
) -> None:
    _append(
        save_grammar(
            grammar,
            path,
            overwrite=overwrite,
            create_parents=True,
        ),
        root,
        artifacts,
    )


def _save_text_artifact(
    text: str,
    path: Path,
    root: Path,
    artifacts: list[str],
    overwrite: bool,
) -> None:
    _append(
        atomic_write_text(
            text,
            path,
            overwrite=overwrite,
            create_parents=True,
        ),
        root,
        artifacts,
    )


def _append(path: Path, root: Path, artifacts: list[str]) -> None:
    artifacts.append(path.resolve().relative_to(root).as_posix())


def _resolve_grammar_path(
    manifest_path: Path,
    manifest: SceneManifest,
) -> Path:
    parent = manifest_path.parent.resolve()
    grammar = (parent / manifest.grammar_path).resolve()
    if not grammar.is_relative_to(parent):
        raise ManifestValidationError(
            "grammar_path resolves outside the manifest directory"
        )
    if not grammar.is_file():
        raise ManifestValidationError(
            f"Manifest grammar_path does not exist: {manifest.grammar_path}"
        )
    return grammar


def _validate_manifest_expectations(
    manifest: SceneManifest,
    grammar: SceneGrammar,
) -> None:
    stack = [grammar.root]
    semantic: set[str] = set()
    split_ids: set[str] = set()
    repeat_ids: set[str] = set()
    while stack:
        node = stack.pop()
        if isinstance(node, SplitNode):
            split_ids.add(node.node_id)
            stack.extend(child.node for child in reversed(node.children))
        elif isinstance(node, RepeatNode):
            repeat_ids.add(node.node_id)
            stack.append(node.element)
        elif isinstance(node, TerminalNode):
            semantic.add(node.semantic_class)
    expected = (
        ("semantic classes", semantic, set(manifest.expected_semantic_classes)),
        ("split node IDs", split_ids, set(manifest.expected_split_node_ids)),
        ("repeat node IDs", repeat_ids, set(manifest.expected_repeat_node_ids)),
    )
    for label, actual, declared in expected:
        if actual != declared:
            raise ManifestValidationError(
                f"Manifest {label} do not match grammar: "
                f"actual={sorted(actual)}, declared={sorted(declared)}"
            )
