"""Safe persistence and deterministic text for coarse lifting artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from scene_grammar_kit.assisted.lifting_errors import (
    LiftingFileExistsError,
    LiftingSerializationError,
    LiftingWriteError,
)
from scene_grammar_kit.assisted.lifting_models import (
    LiftedSceneObservations,
    LiftingReport,
    LiftingResult,
    SavedLiftingResult,
)
from scene_grammar_kit.assisted.lifting_serialization import (
    lifted_scene_to_canonical_json,
    lifting_report_to_canonical_json,
)
from scene_grammar_kit.assisted.serialization import (
    save_annotation,
    save_construction_config,
)

LIFTING_ARTIFACT_FILENAMES = (
    "annotation.json",
    "construction_config.json",
    "lifted_observations.json",
    "lifted_observations.txt",
    "lifting_report.json",
)


def lifted_scene_to_text(
    scene: LiftedSceneObservations,
    report: LiftingReport,
) -> str:
    """Format deterministic ASCII-safe lifted observations with one newline."""
    if not isinstance(scene, LiftedSceneObservations):
        raise LiftingSerializationError("scene must be a LiftedSceneObservations")
    if not isinstance(report, LiftingReport):
        raise LiftingSerializationError("report must be a LiftingReport")
    root = scene.root_bounds
    lines = [
        "SceneGrammarKit coarse lifted observations",
        "====================================",
        f"Scene: {scene.scene_id}",
        f"Image: {scene.image_id}",
        f"Image verified: {str(scene.image_verification_status).lower()}",
        "Source pixels used for geometric inference: false",
        (
            "Root bounds: "
            f"min={_vector_text(root.minimum)} max={_vector_text(root.maximum)}"
        ),
        "",
        "Depth-zone intervals",
        "--------------------",
    ]
    lines.extend(
        f"- {item.depth_zone.value}: [{item.z_min:g}, {item.z_max:g}]"
        for item in scene.depth_zone_intervals
    )
    lines.extend(("", "Lifting assumptions", "-------------------"))
    lines.extend(f"- {item}" for item in scene.assumptions)
    lines.extend(
        (
            "",
            "Observation summary",
            "-------------------",
            (
                f"- regions={report.region_observations_created}, "
                f"instances={report.instance_observations_created}, "
                f"total={len(scene.observations)}"
            ),
            "",
            "Observations",
            "------------",
        )
    )
    for observation in scene.observations:
        source_bounds = observation.normalized_source_bounds
        lines.extend(
            (
                (
                    f"- {observation.observation_id}: "
                    f"purpose={observation.purpose.value}; "
                    f"semantic={observation.semantic_class}; "
                    f"zone={observation.depth_zone.value}"
                ),
                (
                    "  image_bounds="
                    f"[{source_bounds.u_min:g},{source_bounds.v_min:g}]"
                    f"-[{source_bounds.u_max:g},{source_bounds.v_max:g}]"
                ),
                (
                    "  world_bounds="
                    f"min={_vector_text(observation.world_bounds.minimum)} "
                    f"max={_vector_text(observation.world_bounds.maximum)}"
                ),
                (
                    f"  depth_policy={observation.depth_policy.value}; "
                    f"approximation={observation.proxy_approximation.value}"
                ),
                (
                    "  supplied="
                    f"parent={observation.parent_region_id or 'none'}; "
                    f"repeat_group={observation.repeat_group_id or 'none'}; "
                    "split_hint="
                    f"{observation.supplied_split_axis_hint.value if observation.supplied_split_axis_hint else 'none'}; "
                    f"order_hint={observation.supplied_order_hint if observation.supplied_order_hint is not None else 'none'}"
                ),
            )
        )
    lines.extend(("", "Warnings", "--------"))
    lines.extend(
        (
            f"- {warning.code}"
            + (
                f" [{warning.annotation_id}]"
                if warning.annotation_id is not None
                else ""
            )
            + f": {warning.message}"
        )
        for warning in report.warnings
    )
    if not report.warnings:
        lines.append("- none")
    lines.extend(("", "Not inferred", "------------"))
    lines.extend(f"- {item}" for item in report.explicitly_not_inferred)
    return "\n".join(lines) + "\n"


def save_lifted_scene(
    scene: LiftedSceneObservations,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save canonical lifted-scene JSON atomically."""
    return _atomic_write_bytes(
        lifted_scene_to_canonical_json(scene).encode("utf-8"),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_lifting_report(
    report: LiftingReport,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save canonical lifting-report JSON atomically."""
    return _atomic_write_bytes(
        lifting_report_to_canonical_json(report).encode("utf-8"),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_lifted_observations_text(
    scene: LiftedSceneObservations,
    report: LiftingReport,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save deterministic human-readable lifted observations."""
    return _atomic_write_bytes(
        lifted_scene_to_text(scene, report).encode("utf-8"),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_lifting_result(
    result: LiftingResult,
    output_directory: Path,
    *,
    overwrite: bool = False,
) -> SavedLiftingResult:
    """Persist the five-file lifting bundle with its success report last."""
    if not isinstance(result, LiftingResult):
        raise LiftingSerializationError("result must be a LiftingResult")
    root = _prepare_output_directory(output_directory, overwrite=overwrite)
    paths = {name: root / name for name in LIFTING_ARTIFACT_FILENAMES}
    report_path = paths["lifting_report.json"]
    if overwrite and report_path.exists():
        try:
            report_path.unlink()
        except OSError as exc:
            raise LiftingWriteError(
                f"Could not remove stale lifting success report: {exc}"
            ) from exc
    save_annotation(
        result.annotation,
        paths["annotation.json"],
        overwrite=overwrite,
        create_parents=True,
    )
    save_construction_config(
        result.construction_config,
        paths["construction_config.json"],
        overwrite=overwrite,
        create_parents=True,
    )
    save_lifted_scene(
        result.scene,
        paths["lifted_observations.json"],
        overwrite=overwrite,
        create_parents=True,
    )
    save_lifted_observations_text(
        result.scene,
        result.report,
        paths["lifted_observations.txt"],
        overwrite=overwrite,
        create_parents=True,
    )
    saved_report = save_lifting_report(
        result.report,
        report_path,
        overwrite=overwrite,
        create_parents=True,
    )
    return SavedLiftingResult(
        output_directory=root,
        annotation_path=paths["annotation.json"],
        construction_config_path=paths["construction_config.json"],
        lifted_scene_path=paths["lifted_observations.json"],
        lifted_text_path=paths["lifted_observations.txt"],
        report_path=saved_report,
        result=result,
    )


def _prepare_output_directory(path: Path, *, overwrite: bool) -> Path:
    root = Path(path).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise LiftingWriteError(f"Lifting output is not a directory: {root}")
    if root.is_dir():
        try:
            entries = tuple(root.iterdir())
        except OSError as exc:
            raise LiftingWriteError(
                f"Could not inspect lifting output directory {root}: {exc}"
            ) from exc
        if entries and not overwrite:
            raise LiftingFileExistsError(
                f"Lifting output directory is nonempty; pass overwrite=True: {root}"
            )
    else:
        try:
            root.mkdir(parents=True)
        except OSError as exc:
            raise LiftingWriteError(
                f"Could not create lifting output directory {root}: {exc}"
            ) from exc
    return root


def _atomic_write_bytes(
    data: bytes,
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
            raise LiftingWriteError(
                f"Could not create lifting parent {parent}: {exc}"
            ) from exc
    if not parent.is_dir():
        raise LiftingWriteError(
            f"Lifting parent does not exist: {parent}; pass create_parents=True"
        )
    if resolved.exists() and not overwrite:
        raise LiftingFileExistsError(
            f"Lifting artifact exists; pass overwrite=True: {resolved}"
        )
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary_path, resolved)
        else:
            try:
                os.link(temporary_path, resolved)
            except FileExistsError as exc:
                raise LiftingFileExistsError(
                    f"Lifting artifact appeared during save: {resolved}"
                ) from exc
            temporary_path.unlink()
        temporary_path = None
    except LiftingFileExistsError:
        raise
    except OSError as exc:
        raise LiftingWriteError(
            f"Could not safely write lifting artifact {resolved}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return resolved


def _vector_text(vector: object) -> str:
    return f"({vector.x:g},{vector.y:g},{vector.z:g})"
