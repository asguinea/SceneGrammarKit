"""Integrated orchestration for annotation-assisted scene construction."""

from __future__ import annotations

import hashlib
import platform
import sys
import tempfile
import time
from pathlib import Path

from scene_grammar_kit.assisted.constructor_errors import (
    AssistedConstructorValidationError,
)
from scene_grammar_kit.assisted.constructor_models import (
    CONSTRUCTOR_POLICY_VERSION,
    AssistedConstructionReport,
    AssistedConstructionResult,
    ConstructionStageOutcome,
    ConstructionStageStatus,
    DefaultEditDecision,
    GrammarConstructionSummary,
    PrimaryGrammarType,
)
from scene_grammar_kit.assisted.constructor_persistence import (
    build_artifact_index,
    bundle_readme,
    construction_report_to_text,
    persist_constructor_artifacts,
    prepare_constructor_output,
    runtime_report_to_json,
)
from scene_grammar_kit.assisted.constructor_serialization import (
    artifact_index_to_canonical_json,
)
from scene_grammar_kit.assisted.lifting import lift_assisted_input
from scene_grammar_kit.assisted.lifting_models import LIFTING_POLICY_VERSION
from scene_grammar_kit.assisted.lifting_persistence import lifted_scene_to_text
from scene_grammar_kit.assisted.lifting_serialization import (
    lifted_scene_to_canonical_json,
    lifting_report_to_canonical_json,
)
from scene_grammar_kit.assisted.overlay import load_and_verify_source_image
from scene_grammar_kit.assisted.repeat_induction import induce_repeat_grammar
from scene_grammar_kit.assisted.repeat_induction_models import (
    REPEAT_INDUCTION_POLICY_VERSION,
)
from scene_grammar_kit.assisted.repeat_induction_persistence import (
    repeat_induction_report_to_text,
)
from scene_grammar_kit.assisted.repeat_induction_serialization import (
    repeat_induction_report_to_canonical_json,
)
from scene_grammar_kit.assisted.review_models import ANNOTATION_REVIEW_POLICY_VERSION
from scene_grammar_kit.assisted.review_persistence import review_assisted_input
from scene_grammar_kit.assisted.serialization import (
    annotation_to_canonical_json,
    construction_config_to_canonical_json,
    load_annotation,
    load_construction_config,
)
from scene_grammar_kit.assisted.split_induction import induce_split_grammar
from scene_grammar_kit.assisted.split_induction_models import (
    SPLIT_INDUCTION_POLICY_VERSION,
)
from scene_grammar_kit.assisted.split_induction_persistence import (
    split_induction_report_to_text,
)
from scene_grammar_kit.assisted.split_induction_serialization import (
    split_induction_report_to_canonical_json,
)
from scene_grammar_kit.assisted.validation import (
    validate_assisted_input,
    validate_construction_config,
    validate_scene_annotation,
)
from scene_grammar_kit.editing import (
    EDITING_POLICY_VERSION,
    SetRepeatCount,
    SetSplitChildWeight,
    SubstituteTerminalClass,
    apply_edit,
    edit_operation_to_canonical_json,
    edit_report_to_canonical_json,
)
from scene_grammar_kit.geometry import (
    EXECUTION_POLICY_VERSION,
    ExecutedScene,
    executed_scene_to_canonical_json,
    execution_report_to_canonical_json,
    export_scene,
)
from scene_grammar_kit.grammar import (
    SCHEMA_VERSION,
    RepeatNode,
    SceneGrammar,
    SplitNode,
    grammar_to_canonical_json,
    grammar_tree_to_text,
    summarize_grammar,
    validate_grammar,
)
from scene_grammar_kit.grammar.models import GrammarNodeBase
from scene_grammar_kit.rendering import (
    RENDERER_POLICY_VERSION,
    RenderConfig,
    RenderResult,
    render_executed_scene,
    render_report_to_canonical_json,
    save_render,
)

SUPPLIED_CONSTRUCTOR_INFORMATION = (
    "semantic regions",
    "object instances",
    "depth-zone assignments",
    "region hierarchy",
    "split-axis hints",
    "repeat membership",
    "repeat-axis hints",
    "semantic classes",
    "terminal geometry types",
)
CONFIGURED_CONSTRUCTOR_INFORMATION = (
    "root bounds",
    "depth-zone intervals",
    "alignment, size, spacing, and boundary tolerances",
    "axis policy",
    "repeat fallback policy",
    "grammar-depth limits",
)
DERIVED_CONSTRUCTOR_INFORMATION = (
    "proxy 3D bounds",
    "selected split axes when not supplied",
    "split boundaries",
    "explicit gap regions",
    "wrapper splits",
    "repeat acceptance",
    "repeat spacing",
    "representative repeat element",
    "primary grammar selection",
    "execution proxy geometry",
    "semantic preview renders",
)
CONSTRUCTOR_EXPLICIT_NONCLAIMS = (
    "semantic segmentation from pixels",
    "monocular metric depth",
    "camera calibration",
    "hidden objects",
    "additional repeat members",
    "physical dimensions",
    "photorealistic reconstruction",
    "texture or appearance models",
)


def construct_assisted_scene(
    annotation_path: Path,
    config_path: Path,
    output_directory: Path,
    *,
    overwrite: bool = False,
    verify_image: bool = True,
    verify_execution: bool = True,
    render_width: int = 1200,
    render_height: int = 800,
    camera: str = "isometric",
    apply_default_edit: bool = True,
    maximum_depth: int = 128,
    maximum_primitives: int = 1_000_000,
) -> AssistedConstructionResult:
    """Run the complete deterministic annotation-assisted workflow."""
    if not isinstance(verify_image, bool) or not isinstance(verify_execution, bool):
        raise AssistedConstructorValidationError(
            "verification controls must be booleans"
        )
    if not isinstance(apply_default_edit, bool):
        raise AssistedConstructorValidationError("apply_default_edit must be a boolean")
    output = prepare_constructor_output(output_directory, overwrite=overwrite)
    total_start = time.perf_counter()
    durations: dict[str, float] = {}
    stages: list[ConstructionStageStatus] = []
    artifacts: dict[str, bytes] = {}

    annotation = load_annotation(annotation_path)
    config = load_construction_config(config_path)
    annotation_validation = validate_scene_annotation(annotation)
    if not annotation_validation.is_valid:
        raise AssistedConstructorValidationError("annotation validation failed")
    stages.append(_pass("annotation_validation", "Annotation schema is valid."))
    config_validation = validate_construction_config(config)
    if not config_validation.is_valid:
        raise AssistedConstructorValidationError("configuration validation failed")
    stages.append(_pass("config_validation", "Construction configuration is valid."))
    compatibility = validate_assisted_input(annotation, config)
    if not compatibility.is_valid:
        raise AssistedConstructorValidationError(
            "annotation/config compatibility validation failed"
        )
    compatibility_warnings = tuple(
        f"{item.code}: {item.message}"
        for item in compatibility.diagnostics
        if item.severity.value == "warning"
    )
    stages.append(
        _pass(
            "compatibility_validation",
            "Annotation and configuration are compatible.",
            warnings=compatibility_warnings,
        )
    )
    annotation_json = annotation_to_canonical_json(annotation)
    config_json = construction_config_to_canonical_json(config)
    artifacts["input/annotation.json"] = annotation_json.encode("utf-8")
    artifacts["input/construction_config.json"] = config_json.encode("utf-8")

    render_config = RenderConfig(
        width=render_width,
        height=render_height,
        camera_preset=camera,
        image_padding=max(1, min(64, min(render_width, render_height) // 8)),
    )
    with tempfile.TemporaryDirectory(
        prefix=".scene_grammar_kit-constructor-", dir=output.parent
    ) as temporary_name:
        temporary = Path(temporary_name)
        review_start = time.perf_counter()
        verified = None
        review_result = None
        if verify_image:
            verified = load_and_verify_source_image(annotation, annotation_path)
            source_path = Path(annotation_path).expanduser().resolve().parent / Path(
                verified.relative_path
            )
            source_bytes = source_path.read_bytes()
            if hashlib.sha256(source_bytes).hexdigest() != verified.byte_sha256:
                raise AssistedConstructorValidationError(
                    "copied source-image hash verification failed"
                )
            extension = Path(verified.relative_path).suffix.lower()
            if extension not in {".png", ".jpg", ".jpeg"}:
                raise AssistedConstructorValidationError(
                    "verified source extension must be PNG or JPEG"
                )
            source_relative = f"input/source_image{extension}"
            artifacts[source_relative] = source_bytes
            stages.append(
                _pass(
                    "image_verification",
                    "Source image was decoded, hashed, and verified.",
                    (source_relative,),
                )
            )
            review_result = review_assisted_input(
                annotation_path,
                config_path,
                temporary / "review-stage",
            )
            for source_name, target_name in (
                ("annotation_overlay.png", "review/annotation_overlay.png"),
                ("annotation_summary.json", "review/annotation_summary.json"),
                ("annotation_summary.txt", "review/annotation_summary.txt"),
                (
                    "annotation_review_report.json",
                    "review/annotation_review_report.json",
                ),
            ):
                artifacts[target_name] = (
                    review_result.output_directory / source_name
                ).read_bytes()
            stages.append(
                _pass(
                    "annotation_review",
                    "Annotation overlay and supplied-evidence summaries were produced.",
                    tuple(
                        path for path in sorted(artifacts) if path.startswith("review/")
                    ),
                    review_result.report.warnings,
                )
            )
        else:
            stages.append(
                _skip(
                    "image_verification",
                    "Source-image verification was explicitly disabled.",
                )
            )
            stages.append(
                _skip(
                    "annotation_review",
                    "Review rendering was skipped with image verification.",
                )
            )
        durations["review_seconds"] = time.perf_counter() - review_start

        lifting_start = time.perf_counter()
        lifting_result = lift_assisted_input(
            annotation,
            config,
            verified_source_image=verified,
        )
        artifacts["lifting/lifted_observations.json"] = lifted_scene_to_canonical_json(
            lifting_result.scene
        ).encode("utf-8")
        artifacts["lifting/lifted_observations.txt"] = lifted_scene_to_text(
            lifting_result.scene, lifting_result.report
        ).encode("utf-8")
        artifacts["lifting/lifting_report.json"] = lifting_report_to_canonical_json(
            lifting_result.report
        ).encode("utf-8")
        stages.append(
            _pass(
                "lifting",
                f"Created {len(lifting_result.scene.observations)} proxy observations.",
                (
                    "lifting/lifted_observations.json",
                    "lifting/lifted_observations.txt",
                    "lifting/lifting_report.json",
                ),
                tuple(item.message for item in lifting_result.scene.warnings),
            )
        )
        durations["lifting_seconds"] = time.perf_counter() - lifting_start

        split_start = time.perf_counter()
        split_result = induce_split_grammar(
            annotation,
            config,
            lifting_result.scene,
            verify_execution=verify_execution,
            maximum_grammar_depth=maximum_depth,
            maximum_primitives=maximum_primitives,
        )
        _add_induction_artifacts(artifacts, "split_only", split_result)
        stages.append(
            _pass(
                "split_induction",
                "Batch 2.4 split-only grammar was constructed.",
                (
                    "split_only/grammar.json",
                    "split_only/grammar_tree.txt",
                    "split_only/induction_report.json",
                    "split_only/induction_report.txt",
                ),
                split_result.report.warnings,
            )
        )
        durations["split_induction_seconds"] = time.perf_counter() - split_start

        repeat_start = time.perf_counter()
        repeat_result = induce_repeat_grammar(
            annotation,
            config,
            lifting_result.scene,
            split_result,
            verify_execution=verify_execution,
            maximum_grammar_depth=maximum_depth,
            maximum_primitives=maximum_primitives,
        )
        _add_repeat_artifacts(artifacts, repeat_result)
        stages.append(
            _pass(
                "repeat_induction",
                "Batch 2.5 evaluated only supplied repeat groups.",
                (
                    "repeat/grammar.json",
                    "repeat/grammar_tree.txt",
                    "repeat/induction_report.json",
                    "repeat/induction_report.txt",
                ),
                repeat_result.report.warnings,
            )
        )
        durations["repeat_induction_seconds"] = time.perf_counter() - repeat_start

        split_grammar = split_result.induced_grammar
        repeat_grammar = repeat_result.repeat_grammar
        if (
            not validate_grammar(split_grammar, max_depth=maximum_depth).is_valid
            or not validate_grammar(repeat_grammar, max_depth=maximum_depth).is_valid
        ):
            raise AssistedConstructorValidationError(
                "constructed grammar validation failed"
            )
        stages.append(
            _pass(
                "grammar_validation",
                "Split-only and repeat grammars both validate.",
            )
        )

        accepted = repeat_result.report.accepted_group_count
        if accepted:
            primary_type = PrimaryGrammarType.REPEAT
            primary_grammar = repeat_grammar
            primary_execution = repeat_result.repeat_execution
            primary_reason = (
                "Repeat grammar selected because at least one supplied group "
                "was accepted."
            )
            selected_prefix = "repeat"
        else:
            primary_type = PrimaryGrammarType.SPLIT_ONLY
            primary_grammar = split_grammar
            primary_execution = split_result.execution_verification_result
            primary_reason = (
                "Split-only grammar selected because no supplied repeat group "
                "was accepted."
            )
            selected_prefix = "split_only"

        execution_export_start = time.perf_counter()
        primary_render: RenderResult | None = None
        edited_render: RenderResult | None = None
        edit_result = None
        edited_grammar = None
        edited_execution = None
        renders: dict[str, RenderResult] = {}
        rendering_duration = 0.0
        if verify_execution:
            split_execution = split_result.execution_verification_result
            repeat_execution = repeat_result.repeat_execution
            if split_execution is None or repeat_execution is None:
                raise AssistedConstructorValidationError(
                    "execution verification did not return both scenes"
                )
            rendering_duration += _add_execution_artifacts(
                artifacts,
                temporary,
                "split_only",
                split_execution,
                render_config,
                renders,
            )
            rendering_duration += _add_execution_artifacts(
                artifacts,
                temporary,
                "repeat",
                repeat_execution,
                render_config,
                renders,
            )
            _copy_primary_artifacts(artifacts, selected_prefix)
            primary_render = renders[selected_prefix]
            stages.append(
                _pass(
                    "execution",
                    "Split-only and repeat grammars executed successfully.",
                    (
                        "split_only/primitives.json",
                        "repeat/primitives.json",
                        "primary/primitives.json",
                    ),
                )
            )
            stages.append(
                _pass(
                    "export",
                    "Split-only, repeat, and primary GLB artifacts were exported.",
                    (
                        "split_only/scene.glb",
                        "repeat/scene.glb",
                        "primary/scene.glb",
                    ),
                )
            )
            stages.append(
                _pass(
                    "rendering",
                    "All grammar previews use identical deterministic settings.",
                    (
                        "split_only/render.png",
                        "repeat/render.png",
                        "primary/render.png",
                    ),
                )
            )
        else:
            _copy_primary_grammar_artifacts(artifacts, selected_prefix)
            stages.extend(
                (
                    _skip("execution", "Execution was explicitly disabled."),
                    _skip("export", "GLB export requires verified execution."),
                    _skip("rendering", "Rendering requires verified execution."),
                )
            )
        durations["execution_export_seconds"] = (
            time.perf_counter() - execution_export_start - rendering_duration
        )

        edit_start = time.perf_counter()
        edit_decision, operation = _select_default_edit(
            annotation,
            split_result,
            repeat_result,
            primary_grammar,
            enabled=apply_default_edit,
        )
        if operation is not None:
            edit_result = apply_edit(
                primary_grammar,
                operation,
                verify_execution=verify_execution,
                maximum_depth=maximum_depth,
                maximum_primitives=maximum_primitives,
            )
            edited_grammar = edit_result.edited_grammar
            edited_execution = edit_result.edited_execution
            artifacts["edit/edit_specification.json"] = (
                edit_operation_to_canonical_json(operation).encode("utf-8")
            )
            artifacts["edit/grammar_before.json"] = artifacts["primary/grammar.json"]
            artifacts["edit/grammar_after.json"] = grammar_to_canonical_json(
                edited_grammar
            ).encode("utf-8")
            artifacts["edit/edit_report.json"] = edit_report_to_canonical_json(
                edit_result.report
            ).encode("utf-8")
            if verify_execution:
                if edited_execution is None or primary_render is None:
                    raise AssistedConstructorValidationError(
                        "edited execution or primary render is missing"
                    )
                artifacts["edit/primitives_after.json"] = (
                    executed_scene_to_canonical_json(edited_execution).encode("utf-8")
                )
                artifacts["edit/execution_report_after.json"] = (
                    execution_report_to_canonical_json(edited_execution.report).encode(
                        "utf-8"
                    )
                )
                exported = export_scene(
                    edited_execution,
                    temporary / "edit" / "scene_after.glb",
                    semantic_index_path=(
                        temporary / "edit" / "semantic_index_after.json"
                    ),
                    create_parents=True,
                )
                artifacts["edit/scene_after.glb"] = exported.glb_path.read_bytes()
                artifacts["edit/semantic_index_after.json"] = (
                    exported.semantic_index_path.read_bytes()
                )
                artifacts["edit/before.png"] = artifacts["primary/render.png"]
                artifacts["edit/before.render.json"] = artifacts["primary/render.json"]
                edit_render_start = time.perf_counter()
                edited_render = render_executed_scene(edited_execution, render_config)
                rendering_duration += time.perf_counter() - edit_render_start
                after_path = save_render(
                    edited_render,
                    temporary / "edit" / "after.png",
                    create_parents=True,
                )
                artifacts["edit/after.png"] = after_path.read_bytes()
                artifacts["edit/after.render.json"] = render_report_to_canonical_json(
                    edited_render.report
                ).encode("utf-8")
            stages.append(
                _pass(
                    "default_edit",
                    edit_decision.reason,
                    tuple(
                        path for path in sorted(artifacts) if path.startswith("edit/")
                    ),
                )
            )
        else:
            stages.append(_skip("default_edit", edit_decision.reason))
        durations["editing_seconds"] = time.perf_counter() - edit_start

        stages.append(
            _pass(
                "persistence",
                "Canonical success report is written after all other artifacts.",
            )
        )
        split_summary = _grammar_summary(
            PrimaryGrammarType.SPLIT_ONLY,
            split_grammar,
            split_result.execution_verification_result,
        )
        repeat_summary = _grammar_summary(
            PrimaryGrammarType.REPEAT,
            repeat_grammar,
            repeat_result.repeat_execution,
        )
        canonical_paths = tuple(
            sorted(
                {
                    *artifacts,
                    "README.md",
                    "artifact_index.json",
                    "construction_report.json",
                    "construction_report.txt",
                    "runtime_report.json",
                }
            )
        )
        warnings = tuple(
            dict.fromkeys(
                (
                    *compatibility_warnings,
                    *(item.message for item in lifting_result.scene.warnings),
                    *repeat_result.report.warnings,
                )
            )
        )
        report = AssistedConstructionReport(
            success=True,
            annotation_schema_version=annotation.annotation_schema_version,
            construction_config_schema_version=config.config_schema_version,
            review_policy_version=ANNOTATION_REVIEW_POLICY_VERSION,
            lifting_policy_version=LIFTING_POLICY_VERSION,
            split_induction_policy_version=SPLIT_INDUCTION_POLICY_VERSION,
            repeat_induction_policy_version=REPEAT_INDUCTION_POLICY_VERSION,
            grammar_schema_version=SCHEMA_VERSION,
            execution_policy_version=EXECUTION_POLICY_VERSION,
            renderer_policy_version=RENDERER_POLICY_VERSION,
            editing_policy_version=EDITING_POLICY_VERSION,
            scene_id=annotation.scene_id,
            image_id=annotation.source_image.image_id,
            source_image_sha256=verified.byte_sha256 if verified else None,
            annotation_sha256=_sha256(annotation_json),
            construction_config_sha256=_sha256(config_json),
            lifted_scene_sha256=_sha256(
                lifted_scene_to_canonical_json(lifting_result.scene)
            ),
            split_only_grammar_sha256=_sha256(grammar_to_canonical_json(split_grammar)),
            repeat_grammar_sha256=_sha256(grammar_to_canonical_json(repeat_grammar)),
            primary_grammar_sha256=_sha256(grammar_to_canonical_json(primary_grammar)),
            primary_grammar_type=primary_type,
            primary_selection_reason=primary_reason,
            supplied_repeat_group_count=len(annotation.repeat_groups),
            accepted_repeat_group_count=accepted,
            fallback_repeat_group_count=(repeat_result.report.fallback_group_count),
            stage_statuses=tuple(stages),
            artifact_relative_paths=canonical_paths,
            grammar_summaries=(split_summary, repeat_summary),
            construction_warnings=warnings,
            edit_decision=edit_decision,
            supplied_information=SUPPLIED_CONSTRUCTOR_INFORMATION,
            configured_information=CONFIGURED_CONSTRUCTOR_INFORMATION,
            derived_information=DERIVED_CONSTRUCTOR_INFORMATION,
            explicitly_not_inferred=CONSTRUCTOR_EXPLICIT_NONCLAIMS,
        )
        artifacts["construction_report.txt"] = construction_report_to_text(
            report
        ).encode("utf-8")
        artifacts["README.md"] = bundle_readme(report).encode("utf-8")
        durations["rendering_seconds"] = rendering_duration
        durations["total_seconds"] = time.perf_counter() - total_start
        artifacts["runtime_report.json"] = runtime_report_to_json(
            {
                "constructor_policy_version": CONSTRUCTOR_POLICY_VERSION,
                "durations_seconds": durations,
                "machine": platform.machine(),
                "operating_system": platform.system(),
                "python_version": sys.version.split()[0],
                "stable_for_determinism_comparison": False,
            }
        ).encode("utf-8")
        artifact_index = build_artifact_index(artifacts)
        artifacts["artifact_index.json"] = artifact_index_to_canonical_json(
            artifact_index
        ).encode("utf-8")
        persist_constructor_artifacts(
            output,
            artifacts,
            report,
            overwrite=overwrite,
        )
    return AssistedConstructionResult(
        output_directory=output,
        annotation=annotation,
        construction_config=config,
        review_result=review_result,
        lifting_result=lifting_result,
        split_induction_result=split_result,
        repeat_induction_result=repeat_result,
        primary_grammar=primary_grammar,
        primary_execution=primary_execution,
        primary_render=primary_render,
        edited_grammar=edited_grammar,
        edited_execution=edited_execution,
        edited_render=edited_render,
        edit_result=edit_result,
        artifact_index=artifact_index,
        report=report,
    )


def _add_induction_artifacts(artifacts, prefix, result) -> None:
    artifacts[f"{prefix}/grammar.json"] = grammar_to_canonical_json(
        result.induced_grammar
    ).encode("utf-8")
    artifacts[f"{prefix}/grammar_tree.txt"] = grammar_tree_to_text(
        result.induced_grammar
    ).encode("utf-8")
    artifacts[f"{prefix}/induction_report.json"] = (
        split_induction_report_to_canonical_json(result.report).encode("utf-8")
    )
    artifacts[f"{prefix}/induction_report.txt"] = split_induction_report_to_text(
        result.report
    ).encode("utf-8")


def _add_repeat_artifacts(artifacts, result) -> None:
    artifacts["repeat/grammar.json"] = grammar_to_canonical_json(
        result.repeat_grammar
    ).encode("utf-8")
    artifacts["repeat/grammar_tree.txt"] = grammar_tree_to_text(
        result.repeat_grammar
    ).encode("utf-8")
    artifacts["repeat/induction_report.json"] = (
        repeat_induction_report_to_canonical_json(result.report).encode("utf-8")
    )
    artifacts["repeat/induction_report.txt"] = repeat_induction_report_to_text(
        result.report
    ).encode("utf-8")


def _add_execution_artifacts(
    artifacts: dict[str, bytes],
    temporary: Path,
    prefix: str,
    execution: ExecutedScene,
    render_config: RenderConfig,
    renders: dict[str, RenderResult],
) -> float:
    artifacts[f"{prefix}/primitives.json"] = executed_scene_to_canonical_json(
        execution
    ).encode("utf-8")
    artifacts[f"{prefix}/execution_report.json"] = execution_report_to_canonical_json(
        execution.report
    ).encode("utf-8")
    exported = export_scene(
        execution,
        temporary / prefix / "scene.glb",
        semantic_index_path=temporary / prefix / "semantic_index.json",
        create_parents=True,
    )
    artifacts[f"{prefix}/scene.glb"] = exported.glb_path.read_bytes()
    artifacts[f"{prefix}/semantic_index.json"] = (
        exported.semantic_index_path.read_bytes()
    )
    render_start = time.perf_counter()
    render = render_executed_scene(execution, render_config)
    rendering_duration = time.perf_counter() - render_start
    render_path = save_render(
        render,
        temporary / prefix / "render.png",
        create_parents=True,
    )
    artifacts[f"{prefix}/render.png"] = render_path.read_bytes()
    artifacts[f"{prefix}/render.json"] = render_report_to_canonical_json(
        render.report
    ).encode("utf-8")
    renders[prefix] = render
    return rendering_duration


def _copy_primary_grammar_artifacts(
    artifacts: dict[str, bytes], selected_prefix: str
) -> None:
    artifacts["primary/grammar.json"] = artifacts[f"{selected_prefix}/grammar.json"]
    artifacts["primary/grammar_tree.txt"] = artifacts[
        f"{selected_prefix}/grammar_tree.txt"
    ]


def _copy_primary_artifacts(artifacts: dict[str, bytes], selected_prefix: str) -> None:
    _copy_primary_grammar_artifacts(artifacts, selected_prefix)
    for name in (
        "primitives.json",
        "execution_report.json",
        "scene.glb",
        "semantic_index.json",
        "render.png",
        "render.json",
    ):
        artifacts[f"primary/{name}"] = artifacts[f"{selected_prefix}/{name}"]


def _select_default_edit(
    annotation,
    split_result,
    repeat_result,
    primary_grammar,
    *,
    enabled: bool,
):
    policy = (
        "repeat-count, then structural split-weight, then explicit terminal "
        "substitution"
    )
    if not enabled:
        return (
            DefaultEditDecision(
                False,
                policy,
                None,
                None,
                None,
                None,
                "Default editing was explicitly disabled.",
                False,
            ),
            None,
        )
    accepted = next(
        (
            item
            for item in repeat_result.report.group_decisions
            if item.decision.value == "accepted"
        ),
        None,
    )
    if accepted is not None and accepted.repeat_node_id is not None:
        new_count = accepted.metrics.member_count + 1
        operation = SetRepeatCount(accepted.repeat_node_id, new_count)
        return (
            DefaultEditDecision(
                True,
                policy,
                operation.operation_type,
                accepted.repeat_node_id,
                str(new_count),
                str(new_count),
                "Increased the first accepted supplied repeat count as a "
                "user-requested procedural variation; the added instance is "
                "not claimed as observed or inferred.",
                True,
            ),
            operation,
        )
    structural_ids = {
        node_id
        for mapping in split_result.report.node_mappings
        if mapping.source_annotation_type == "region"
        for node_id in mapping.generated_grammar_node_ids
    }
    for node in _walk(primary_grammar.root):
        if (
            isinstance(node, SplitNode)
            and node.node_id in structural_ids
            and len(node.children) >= 3
        ):
            middle = len(node.children) // 2
            child = node.children[middle]
            value = child.weight * 1.25
            operation = SetSplitChildWeight(node.node_id, child.node.node_id, value)
            return (
                DefaultEditDecision(
                    True,
                    policy,
                    operation.operation_type,
                    node.node_id,
                    format(value, ".17g"),
                    format(value, ".17g"),
                    "Increased the deterministic central structural partition "
                    "weight by factor 1.25.",
                    True,
                ),
                operation,
            )
    mappings = {
        item.source_annotation_id: item.primary_generated_node_id
        for item in split_result.report.node_mappings
    }
    for source in (*annotation.regions, *annotation.instances):
        replacement = source.attributes.get("default_edit_semantic_class")
        if not isinstance(replacement, str):
            continue
        source_id = getattr(source, "region_id", None)
        if source_id is None:
            source_id = getattr(source, "instance_id", None)
        target = mappings.get(source_id)
        if target:
            operation = SubstituteTerminalClass(target, replacement)
            return (
                DefaultEditDecision(
                    True,
                    policy,
                    operation.operation_type,
                    target,
                    replacement,
                    replacement,
                    "Applied explicitly supplied semantic substitution.",
                    True,
                ),
                operation,
            )
    return (
        DefaultEditDecision(
            False,
            policy,
            None,
            None,
            None,
            None,
            "No deterministic safe default edit target was available.",
            False,
        ),
        None,
    )


def _walk(root: GrammarNodeBase):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, SplitNode):
            stack.extend(child.node for child in reversed(node.children))
        elif isinstance(node, RepeatNode):
            stack.append(node.element)


def _grammar_summary(
    grammar_type: PrimaryGrammarType,
    grammar: SceneGrammar,
    execution: ExecutedScene | None,
) -> GrammarConstructionSummary:
    summary = summarize_grammar(grammar)
    return GrammarConstructionSummary(
        grammar_type,
        summary.total_node_count,
        summary.split_node_count,
        summary.repeat_node_count,
        summary.terminal_node_count,
        len(execution.primitives) if execution else 0,
        summary.canonical_byte_size,
    )


def _pass(
    name: str,
    detail: str,
    paths: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> ConstructionStageStatus:
    return ConstructionStageStatus(
        name, ConstructionStageOutcome.PASS, detail, paths, warnings
    )


def _skip(name: str, detail: str) -> ConstructionStageStatus:
    return ConstructionStageStatus(name, ConstructionStageOutcome.SKIP, detail)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
