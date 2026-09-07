"""Canonical persistence and integrated assisted-annotation review workflow."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scene_grammar_kit.assisted.annotation_models import SceneAnnotation
from scene_grammar_kit.assisted.overlay import (
    annotation_review_summary_to_text,
    build_annotation_review_summary,
    load_and_verify_source_image,
    render_annotation_overlay,
)
from scene_grammar_kit.assisted.review_errors import (
    AnnotationReviewFileExistsError,
    AnnotationReviewSerializationError,
    AnnotationReviewValidationError,
    AnnotationReviewWriteError,
)
from scene_grammar_kit.assisted.review_models import (
    AnnotationOverlayConfig,
    AnnotationOverlayResult,
    AnnotationReviewReport,
    AnnotationReviewResult,
    AnnotationReviewSummary,
)
from scene_grammar_kit.assisted.serialization import (
    construction_config_to_canonical_json,
    load_annotation,
    load_construction_config,
    save_annotation,
    save_construction_config,
)
from scene_grammar_kit.assisted.validation import validate_assisted_input

REVIEW_ARTIFACT_FILENAMES = (
    "annotation.json",
    "construction_config.json",
    "annotation_overlay.png",
    "annotation_summary.json",
    "annotation_summary.txt",
    "annotation_review_report.json",
)


def annotation_review_summary_to_canonical_json(
    summary: AnnotationReviewSummary,
) -> str:
    """Serialize a review summary as compact stable direct-Unicode JSON."""
    if not isinstance(summary, AnnotationReviewSummary):
        raise AnnotationReviewSerializationError(
            "summary must be an AnnotationReviewSummary"
        )
    return _canonical_json(_summary_data(summary), "annotation review summary")


def annotation_review_report_to_canonical_json(
    report: AnnotationReviewReport,
) -> str:
    """Serialize a review report as compact stable direct-Unicode JSON."""
    if not isinstance(report, AnnotationReviewReport):
        raise AnnotationReviewSerializationError(
            "report must be an AnnotationReviewReport"
        )
    return _canonical_json(_report_data(report), "annotation review report")


def save_annotation_overlay(
    result: AnnotationOverlayResult,
    image_path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save metadata-free RGBA PNG with fixed compression and atomic replace."""
    if not isinstance(result, AnnotationOverlayResult):
        raise AnnotationReviewSerializationError(
            "result must be an AnnotationOverlayResult"
        )
    resolved = Path(image_path).expanduser().resolve()
    if resolved.suffix.lower() != ".png":
        raise AnnotationReviewWriteError(
            "annotation overlay path must use the .png suffix"
        )
    stream = io.BytesIO()
    try:
        result.image.save(
            stream,
            format="PNG",
            compress_level=9,
            optimize=False,
        )
    except (OSError, ValueError) as exc:
        raise AnnotationReviewWriteError(
            f"Could not encode annotation overlay PNG: {exc}"
        ) from exc
    return _atomic_write_bytes(
        stream.getvalue(),
        resolved,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_annotation_review_summary(
    summary: AnnotationReviewSummary,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save one canonical annotation-review summary JSON file."""
    return _atomic_write_bytes(
        annotation_review_summary_to_canonical_json(summary).encode("utf-8"),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_annotation_review_summary_text(
    summary: AnnotationReviewSummary,
    annotation: SceneAnnotation,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save deterministic human-readable review text with one final newline."""
    return _atomic_write_bytes(
        annotation_review_summary_to_text(summary, annotation).encode("utf-8"),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def save_annotation_review_report(
    report: AnnotationReviewReport,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Save one canonical annotation-review success report."""
    return _atomic_write_bytes(
        annotation_review_report_to_canonical_json(report).encode("utf-8"),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def review_assisted_input(
    annotation_path: Path,
    config_path: Path,
    output_directory: Path,
    *,
    overlay_config: AnnotationOverlayConfig | None = None,
    overwrite: bool = False,
) -> AnnotationReviewResult:
    """Validate, verify, render, summarize, and persist six review artifacts."""
    annotation = load_annotation(annotation_path)
    config = load_construction_config(config_path)
    validation = validate_assisted_input(annotation, config)
    if not validation.is_valid:
        codes = ", ".join(
            diagnostic.code
            for diagnostic in validation.diagnostics
            if diagnostic.severity.value == "error"
        )
        raise AnnotationReviewValidationError(
            f"Assisted input validation failed: {codes}"
        )
    warnings = tuple(
        f"{diagnostic.code}: {diagnostic.message}"
        for diagnostic in validation.diagnostics
        if diagnostic.severity.value == "warning"
    )
    verified = load_and_verify_source_image(annotation, annotation_path)
    config_json = construction_config_to_canonical_json(config)
    config_sha256 = _sha256_text(config_json)
    overlay = render_annotation_overlay(
        verified,
        annotation,
        overlay_config,
        construction_config_sha256=config_sha256,
        warnings=warnings,
    )
    summary = build_annotation_review_summary(
        annotation,
        verified,
        warnings=warnings,
    )

    root = _prepare_output_directory(output_directory, overwrite=overwrite)
    paths = {name: root / name for name in REVIEW_ARTIFACT_FILENAMES}
    save_annotation(
        annotation,
        paths["annotation.json"],
        overwrite=overwrite,
        create_parents=True,
    )
    save_construction_config(
        config,
        paths["construction_config.json"],
        overwrite=overwrite,
        create_parents=True,
    )
    save_annotation_overlay(
        overlay,
        paths["annotation_overlay.png"],
        overwrite=overwrite,
        create_parents=True,
    )
    save_annotation_review_summary(
        summary,
        paths["annotation_summary.json"],
        overwrite=overwrite,
        create_parents=True,
    )
    save_annotation_review_summary_text(
        summary,
        annotation,
        paths["annotation_summary.txt"],
        overwrite=overwrite,
        create_parents=True,
    )
    # The factual success report is deliberately persisted last.
    report_path = save_annotation_review_report(
        overlay.report,
        paths["annotation_review_report.json"],
        overwrite=overwrite,
        create_parents=True,
    )
    return AnnotationReviewResult(
        output_directory=root,
        annotation_path=paths["annotation.json"],
        construction_config_path=paths["construction_config.json"],
        overlay_path=paths["annotation_overlay.png"],
        summary_json_path=paths["annotation_summary.json"],
        summary_text_path=paths["annotation_summary.txt"],
        report_path=report_path,
        overlay=overlay,
        summary=summary,
        report=overlay.report,
    )


def _summary_data(summary: AnnotationReviewSummary) -> dict[str, Any]:
    return {
        "annotation_schema_version": summary.annotation_schema_version,
        "coordinate_system": summary.coordinate_system,
        "declared_image_dimensions": list(summary.declared_image_dimensions),
        "depth_zone_frequencies": dict(summary.depth_zone_frequencies),
        "explicitly_absent_derived_information": list(
            summary.explicitly_absent_derived_information
        ),
        "geometry_type_frequencies": dict(summary.geometry_type_frequencies),
        "image_id": summary.image_id,
        "instance_count": summary.instance_count,
        "instances_by_repeat_group": {
            key: list(values)
            for key, values in summary.instances_by_repeat_group.items()
        },
        "region_count": summary.region_count,
        "region_hierarchy_maximum_depth": (summary.region_hierarchy_maximum_depth),
        "region_role_frequencies": dict(summary.region_role_frequencies),
        "regions_by_depth_zone": {
            key: list(values) for key, values in summary.regions_by_depth_zone.items()
        },
        "repeat_axis_hint_frequencies": dict(summary.repeat_axis_hint_frequencies),
        "repeat_group_count": summary.repeat_group_count,
        "review_policy_version": summary.review_policy_version,
        "scene_id": summary.scene_id,
        "semantic_class_frequencies": dict(summary.semantic_class_frequencies),
        "source_image_relative_path": summary.source_image_relative_path,
        "source_image_sha256": summary.source_image_sha256,
        "split_axis_hint_frequencies": dict(summary.split_axis_hint_frequencies),
        "supplied_information": list(summary.supplied_information),
        "verified_image_dimensions": list(summary.verified_image_dimensions),
        "warnings": list(summary.warnings),
    }


def _report_data(report: AnnotationReviewReport) -> dict[str, Any]:
    return {
        "annotation_sha256": report.annotation_sha256,
        "construction_config_sha256": report.construction_config_sha256,
        "image_verification_status": report.image_verification_status,
        "instances_drawn": report.instances_drawn,
        "labels_drawn": report.labels_drawn,
        "legend_drawn": report.legend_drawn,
        "overlay_height": report.overlay_height,
        "overlay_width": report.overlay_width,
        "region_polygons_drawn": report.region_polygons_drawn,
        "region_rectangles_drawn": report.region_rectangles_drawn,
        "repeat_connectors_drawn": report.repeat_connectors_drawn,
        "review_policy_version": report.review_policy_version,
        "scene_id": report.scene_id,
        "semantic_palette": {
            semantic_class: list(color)
            for semantic_class, color in report.semantic_palette.items()
        },
        "source_image_sha256": report.source_image_sha256,
        "success": report.success,
        "warnings": list(report.warnings),
    }


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
        raise AnnotationReviewSerializationError(
            f"Could not serialize {label} canonically: {exc}"
        ) from exc


def _prepare_output_directory(path: Path, *, overwrite: bool) -> Path:
    root = Path(path).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise AnnotationReviewWriteError(
            f"Review output path is not a directory: {root}"
        )
    if root.is_dir():
        try:
            entries = tuple(root.iterdir())
        except OSError as exc:
            raise AnnotationReviewWriteError(
                f"Could not inspect review output directory {root}: {exc}"
            ) from exc
        if entries and not overwrite:
            raise AnnotationReviewFileExistsError(
                "Review output directory is nonempty; pass overwrite=True "
                f"to replace known artifacts: {root}"
            )
    else:
        try:
            root.mkdir(parents=True)
        except OSError as exc:
            raise AnnotationReviewWriteError(
                f"Could not create review output directory {root}: {exc}"
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
            raise AnnotationReviewWriteError(
                f"Could not create review parent directory {parent}: {exc}"
            ) from exc
    if not parent.is_dir():
        raise AnnotationReviewWriteError(
            f"Review parent directory does not exist: {parent}; "
            "pass create_parents=True to create it"
        )
    if resolved.exists() and not overwrite:
        raise AnnotationReviewFileExistsError(
            f"Review artifact exists; pass overwrite=True to replace it: {resolved}"
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
                raise AnnotationReviewFileExistsError(
                    f"Review artifact appeared during save and was preserved: "
                    f"{resolved}"
                ) from exc
            temporary_path.unlink()
        temporary_path = None
    except AnnotationReviewFileExistsError:
        raise
    except OSError as exc:
        raise AnnotationReviewWriteError(
            f"Could not safely write review artifact {resolved}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return resolved


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
