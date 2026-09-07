"""Strict canonical JSON and atomic persistence for assisted inputs."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scene_grammar_kit.assisted.annotation_models import (
    AnnotationRole,
    AnnotationShape,
    AnnotationShapeType,
    DepthZone,
    InstanceAnnotation,
    NormalizedPoint,
    NormalizedPolygon,
    NormalizedRectangle,
    RegionAnnotation,
    RepeatGroupAnnotation,
    SceneAnnotation,
    SourceImageReference,
)
from scene_grammar_kit.assisted.config_models import (
    ConstructionAxisPolicy,
    ConstructionConfig,
    DepthZoneInterval,
    ProjectionModel,
)
from scene_grammar_kit.assisted.errors import (
    AnnotationValidationError,
    AssistedFileExistsError,
    AssistedFileNotFoundError,
    AssistedJSONError,
    AssistedReadError,
    AssistedSerializationError,
    AssistedWriteError,
    ConstructionConfigValidationError,
)
from scene_grammar_kit.grammar import Axis, Bounds3D, GeometryType, Vector3


def annotation_to_canonical_json(annotation: SceneAnnotation) -> str:
    """Serialize an annotation with ordered lists and sorted object keys."""
    if not isinstance(annotation, SceneAnnotation):
        raise AssistedSerializationError("annotation must be a SceneAnnotation")
    return _canonical_json(_annotation_data(annotation), "annotation")


def annotation_from_json(text: str) -> SceneAnnotation:
    """Parse strict standard JSON into an immutable scene annotation."""
    data = _parse_json(text, "annotation")
    return _parse_annotation(data)


def load_annotation(path: Path) -> SceneAnnotation:
    """Load one UTF-8 annotation file without opening its source image."""
    return annotation_from_json(_read(path, "annotation"))


def save_annotation(
    annotation: SceneAnnotation,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Atomically persist canonical annotation JSON."""
    return _atomic_write_text(
        annotation_to_canonical_json(annotation),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def construction_config_to_canonical_json(
    config: ConstructionConfig,
) -> str:
    """Serialize construction controls as deterministic compact JSON."""
    if not isinstance(config, ConstructionConfig):
        raise AssistedSerializationError("config must be a ConstructionConfig")
    return _canonical_json(_config_data(config), "construction config")


def construction_config_from_json(text: str) -> ConstructionConfig:
    """Parse strict standard JSON into immutable construction controls."""
    data = _parse_json(text, "construction config")
    return _parse_config(data)


def load_construction_config(path: Path) -> ConstructionConfig:
    """Load one strict UTF-8 construction-configuration file."""
    return construction_config_from_json(_read(path, "construction config"))


def save_construction_config(
    config: ConstructionConfig,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Atomically persist canonical construction-configuration JSON."""
    return _atomic_write_text(
        construction_config_to_canonical_json(config),
        path,
        overwrite=overwrite,
        create_parents=create_parents,
    )


def _annotation_data(annotation: SceneAnnotation) -> dict[str, Any]:
    data: dict[str, Any] = {
        "annotation_notes": list(annotation.annotation_notes),
        "annotation_schema_version": annotation.annotation_schema_version,
        "coordinate_system": annotation.coordinate_system,
        "instances": [_instance_data(item) for item in annotation.instances],
        "regions": [_region_data(item) for item in annotation.regions],
        "repeat_groups": [
            _repeat_group_data(item) for item in annotation.repeat_groups
        ],
        "scene_id": annotation.scene_id,
        "source_image": _source_image_data(annotation.source_image),
    }
    if annotation.description is not None:
        data["description"] = annotation.description
    return data


def _source_image_data(source: SourceImageReference) -> dict[str, Any]:
    data: dict[str, Any] = {
        "image_id": source.image_id,
        "image_path": source.image_path,
        "pixel_height": source.pixel_height,
        "pixel_width": source.pixel_width,
    }
    if source.sha256 is not None:
        data["sha256"] = source.sha256
    if source.description is not None:
        data["description"] = source.description
    return data


def _region_data(region: RegionAnnotation) -> dict[str, Any]:
    data: dict[str, Any] = {
        "attributes": dict(region.attributes),
        "depth_zone": region.depth_zone.value,
        "region_id": region.region_id,
        "role": region.role.value,
        "semantic_class": region.semantic_class,
        "shape": _shape_data(region.shape),
    }
    for name, value in (
        ("parent_region_id", region.parent_region_id),
        (
            "split_axis_hint",
            region.split_axis_hint.value
            if region.split_axis_hint is not None
            else None,
        ),
        ("order_hint", region.order_hint),
        (
            "terminal_geometry",
            region.terminal_geometry.value
            if region.terminal_geometry is not None
            else None,
        ),
        ("note", region.note),
    ):
        if value is not None:
            data[name] = value
    return data


def _instance_data(instance: InstanceAnnotation) -> dict[str, Any]:
    data: dict[str, Any] = {
        "attributes": dict(instance.attributes),
        "depth_zone": instance.depth_zone.value,
        "instance_id": instance.instance_id,
        "semantic_class": instance.semantic_class,
        "shape": _shape_data(instance.shape),
        "terminal_geometry": instance.terminal_geometry.value,
    }
    for name, value in (
        ("parent_region_id", instance.parent_region_id),
        ("repeat_group_id", instance.repeat_group_id),
        ("order_hint", instance.order_hint),
        ("note", instance.note),
    ):
        if value is not None:
            data[name] = value
    return data


def _repeat_group_data(group: RepeatGroupAnnotation) -> dict[str, Any]:
    data: dict[str, Any] = {
        "allow_fallback_to_individuals": (group.allow_fallback_to_individuals),
        "axis_hint": group.axis_hint.value,
        "member_instance_ids": list(group.member_instance_ids),
        "repeat_group_id": group.repeat_group_id,
    }
    if group.semantic_class is not None:
        data["semantic_class"] = group.semantic_class
    if group.note is not None:
        data["note"] = group.note
    return data


def _shape_data(shape: AnnotationShape) -> dict[str, Any]:
    if isinstance(shape, NormalizedRectangle):
        return {
            "type": shape.type.value,
            "u_max": shape.u_max,
            "u_min": shape.u_min,
            "v_max": shape.v_max,
            "v_min": shape.v_min,
        }
    if isinstance(shape, NormalizedPolygon):
        return {
            "points": [{"u": point.u, "v": point.v} for point in shape.points],
            "type": shape.type.value,
        }
    raise AssistedSerializationError("unsupported annotation shape")


def _config_data(config: ConstructionConfig) -> dict[str, Any]:
    return {
        "allow_repeat_fallback": config.allow_repeat_fallback,
        "axis_policy": config.axis_policy.value,
        "boundary_merge_tolerance": config.boundary_merge_tolerance,
        "config_schema_version": config.config_schema_version,
        "depth_zone_intervals": [
            {
                "depth_zone": item.depth_zone.value,
                "z_max": item.z_max,
                "z_min": item.z_min,
            }
            for item in config.depth_zone_intervals
        ],
        "maximum_grammar_depth": config.maximum_grammar_depth,
        "minimum_normalized_region_extent": (config.minimum_normalized_region_extent),
        "projection_model": config.projection_model.value,
        "repeat_alignment_tolerance": config.repeat_alignment_tolerance,
        "repeat_size_tolerance": config.repeat_size_tolerance,
        "repeat_spacing_tolerance": config.repeat_spacing_tolerance,
        "require_complete_depth_coverage": (config.require_complete_depth_coverage),
        "root_bounds": {
            "max": list(config.root_bounds.maximum.as_tuple()),
            "min": list(config.root_bounds.minimum.as_tuple()),
        },
    }


def _parse_annotation(value: object) -> SceneAnnotation:
    data = _object(value, "$")
    _exact_fields(
        data,
        required={
            "annotation_schema_version",
            "scene_id",
            "source_image",
            "coordinate_system",
            "regions",
            "instances",
            "repeat_groups",
        },
        optional={"description", "annotation_notes"},
        path="$",
    )
    try:
        return SceneAnnotation(
            annotation_schema_version=_string(
                data["annotation_schema_version"],
                "$.annotation_schema_version",
            ),
            scene_id=_string(data["scene_id"], "$.scene_id"),
            source_image=_parse_source_image(
                data["source_image"],
                "$.source_image",
            ),
            coordinate_system=_string(
                data["coordinate_system"],
                "$.coordinate_system",
            ),
            regions=tuple(
                _parse_region(item, f"$.regions[{index}]")
                for index, item in enumerate(_array(data["regions"], "$.regions"))
            ),
            instances=tuple(
                _parse_instance(item, f"$.instances[{index}]")
                for index, item in enumerate(_array(data["instances"], "$.instances"))
            ),
            repeat_groups=tuple(
                _parse_repeat_group(item, f"$.repeat_groups[{index}]")
                for index, item in enumerate(
                    _array(data["repeat_groups"], "$.repeat_groups")
                )
            ),
            description=_optional_string(
                data.get("description"),
                "$.description",
            ),
            annotation_notes=tuple(
                _string(item, f"$.annotation_notes[{index}]")
                for index, item in enumerate(
                    _array(data.get("annotation_notes", []), "$.annotation_notes")
                )
            ),
        )
    except AnnotationValidationError:
        raise
    except Exception as exc:
        raise AnnotationValidationError(f"Annotation validation failed: {exc}") from exc


def _parse_source_image(value: object, path: str) -> SourceImageReference:
    data = _object(value, path)
    _exact_fields(
        data,
        required={"image_id", "image_path", "pixel_width", "pixel_height"},
        optional={"sha256", "description"},
        path=path,
    )
    return SourceImageReference(
        image_id=_string(data["image_id"], f"{path}.image_id"),
        image_path=_string(data["image_path"], f"{path}.image_path"),
        pixel_width=_integer(data["pixel_width"], f"{path}.pixel_width"),
        pixel_height=_integer(data["pixel_height"], f"{path}.pixel_height"),
        sha256=_optional_string(data.get("sha256"), f"{path}.sha256"),
        description=_optional_string(
            data.get("description"),
            f"{path}.description",
        ),
    )


def _parse_region(value: object, path: str) -> RegionAnnotation:
    data = _object(value, path)
    _exact_fields(
        data,
        required={
            "region_id",
            "semantic_class",
            "shape",
            "depth_zone",
            "role",
        },
        optional={
            "parent_region_id",
            "split_axis_hint",
            "order_hint",
            "terminal_geometry",
            "attributes",
            "note",
        },
        path=path,
    )
    return RegionAnnotation(
        region_id=_string(data["region_id"], f"{path}.region_id"),
        semantic_class=_string(
            data["semantic_class"],
            f"{path}.semantic_class",
        ),
        shape=_parse_shape(data["shape"], f"{path}.shape"),
        depth_zone=_enum(
            data["depth_zone"],
            DepthZone,
            f"{path}.depth_zone",
            AnnotationValidationError,
        ),
        role=_enum(
            data["role"],
            AnnotationRole,
            f"{path}.role",
            AnnotationValidationError,
        ),
        parent_region_id=_optional_string(
            data.get("parent_region_id"),
            f"{path}.parent_region_id",
        ),
        split_axis_hint=_optional_enum(
            data.get("split_axis_hint"),
            Axis,
            f"{path}.split_axis_hint",
            AnnotationValidationError,
        ),
        order_hint=_optional_integer(
            data.get("order_hint"),
            f"{path}.order_hint",
        ),
        terminal_geometry=_optional_enum(
            data.get("terminal_geometry"),
            GeometryType,
            f"{path}.terminal_geometry",
            AnnotationValidationError,
        ),
        attributes=_attributes(data.get("attributes", {}), f"{path}.attributes"),
        note=_optional_string(data.get("note"), f"{path}.note"),
    )


def _parse_instance(value: object, path: str) -> InstanceAnnotation:
    data = _object(value, path)
    _exact_fields(
        data,
        required={
            "instance_id",
            "semantic_class",
            "shape",
            "depth_zone",
            "terminal_geometry",
        },
        optional={
            "parent_region_id",
            "repeat_group_id",
            "order_hint",
            "attributes",
            "note",
        },
        path=path,
    )
    return InstanceAnnotation(
        instance_id=_string(data["instance_id"], f"{path}.instance_id"),
        semantic_class=_string(
            data["semantic_class"],
            f"{path}.semantic_class",
        ),
        shape=_parse_shape(data["shape"], f"{path}.shape"),
        depth_zone=_enum(
            data["depth_zone"],
            DepthZone,
            f"{path}.depth_zone",
            AnnotationValidationError,
        ),
        terminal_geometry=_enum(
            data["terminal_geometry"],
            GeometryType,
            f"{path}.terminal_geometry",
            AnnotationValidationError,
        ),
        parent_region_id=_optional_string(
            data.get("parent_region_id"),
            f"{path}.parent_region_id",
        ),
        repeat_group_id=_optional_string(
            data.get("repeat_group_id"),
            f"{path}.repeat_group_id",
        ),
        order_hint=_optional_integer(
            data.get("order_hint"),
            f"{path}.order_hint",
        ),
        attributes=_attributes(data.get("attributes", {}), f"{path}.attributes"),
        note=_optional_string(data.get("note"), f"{path}.note"),
    )


def _parse_repeat_group(value: object, path: str) -> RepeatGroupAnnotation:
    data = _object(value, path)
    _exact_fields(
        data,
        required={"repeat_group_id", "member_instance_ids", "axis_hint"},
        optional={
            "semantic_class",
            "allow_fallback_to_individuals",
            "note",
        },
        path=path,
    )
    return RepeatGroupAnnotation(
        repeat_group_id=_string(
            data["repeat_group_id"],
            f"{path}.repeat_group_id",
        ),
        member_instance_ids=tuple(
            _string(item, f"{path}.member_instance_ids[{index}]")
            for index, item in enumerate(
                _array(
                    data["member_instance_ids"],
                    f"{path}.member_instance_ids",
                )
            )
        ),
        axis_hint=_enum(
            data["axis_hint"],
            Axis,
            f"{path}.axis_hint",
            AnnotationValidationError,
        ),
        semantic_class=_optional_string(
            data.get("semantic_class"),
            f"{path}.semantic_class",
        ),
        allow_fallback_to_individuals=_boolean(
            data.get("allow_fallback_to_individuals", True),
            f"{path}.allow_fallback_to_individuals",
        ),
        note=_optional_string(data.get("note"), f"{path}.note"),
    )


def _parse_shape(value: object, path: str) -> AnnotationShape:
    data = _object(value, path)
    if "type" not in data:
        raise AnnotationValidationError(f"{path}.type is required")
    shape_type = _enum(
        data["type"],
        AnnotationShapeType,
        f"{path}.type",
        AnnotationValidationError,
    )
    if shape_type is AnnotationShapeType.RECTANGLE:
        _exact_fields(
            data,
            required={"type", "u_min", "v_min", "u_max", "v_max"},
            optional=set(),
            path=path,
        )
        return NormalizedRectangle(
            u_min=_number(data["u_min"], f"{path}.u_min"),
            v_min=_number(data["v_min"], f"{path}.v_min"),
            u_max=_number(data["u_max"], f"{path}.u_max"),
            v_max=_number(data["v_max"], f"{path}.v_max"),
        )
    _exact_fields(
        data,
        required={"type", "points"},
        optional=set(),
        path=path,
    )
    return NormalizedPolygon(
        points=tuple(
            _parse_point(item, f"{path}.points[{index}]")
            for index, item in enumerate(_array(data["points"], f"{path}.points"))
        )
    )


def _parse_point(value: object, path: str) -> NormalizedPoint:
    data = _object(value, path)
    _exact_fields(
        data,
        required={"u", "v"},
        optional=set(),
        path=path,
    )
    return NormalizedPoint(
        u=_number(data["u"], f"{path}.u"),
        v=_number(data["v"], f"{path}.v"),
    )


def _parse_config(value: object) -> ConstructionConfig:
    data = _object(value, "$")
    required = {
        "config_schema_version",
        "projection_model",
        "root_bounds",
        "depth_zone_intervals",
        "axis_policy",
        "minimum_normalized_region_extent",
        "boundary_merge_tolerance",
        "repeat_alignment_tolerance",
        "repeat_size_tolerance",
        "repeat_spacing_tolerance",
        "maximum_grammar_depth",
        "allow_repeat_fallback",
        "require_complete_depth_coverage",
    }
    _exact_fields(data, required=required, optional=set(), path="$")
    bounds = _object(data["root_bounds"], "$.root_bounds")
    _exact_fields(
        bounds,
        required={"min", "max"},
        optional=set(),
        path="$.root_bounds",
    )
    try:
        return ConstructionConfig(
            config_schema_version=_string(
                data["config_schema_version"],
                "$.config_schema_version",
            ),
            projection_model=_enum(
                data["projection_model"],
                ProjectionModel,
                "$.projection_model",
                ConstructionConfigValidationError,
            ),
            root_bounds=Bounds3D(
                minimum=_vector(bounds["min"], "$.root_bounds.min"),
                maximum=_vector(bounds["max"], "$.root_bounds.max"),
            ),
            depth_zone_intervals=tuple(
                _parse_interval(item, f"$.depth_zone_intervals[{index}]")
                for index, item in enumerate(
                    _array(
                        data["depth_zone_intervals"],
                        "$.depth_zone_intervals",
                    )
                )
            ),
            axis_policy=_enum(
                data["axis_policy"],
                ConstructionAxisPolicy,
                "$.axis_policy",
                ConstructionConfigValidationError,
            ),
            minimum_normalized_region_extent=_number(
                data["minimum_normalized_region_extent"],
                "$.minimum_normalized_region_extent",
            ),
            boundary_merge_tolerance=_number(
                data["boundary_merge_tolerance"],
                "$.boundary_merge_tolerance",
            ),
            repeat_alignment_tolerance=_number(
                data["repeat_alignment_tolerance"],
                "$.repeat_alignment_tolerance",
            ),
            repeat_size_tolerance=_number(
                data["repeat_size_tolerance"],
                "$.repeat_size_tolerance",
            ),
            repeat_spacing_tolerance=_number(
                data["repeat_spacing_tolerance"],
                "$.repeat_spacing_tolerance",
            ),
            maximum_grammar_depth=_integer(
                data["maximum_grammar_depth"],
                "$.maximum_grammar_depth",
            ),
            allow_repeat_fallback=_boolean(
                data["allow_repeat_fallback"],
                "$.allow_repeat_fallback",
            ),
            require_complete_depth_coverage=_boolean(
                data["require_complete_depth_coverage"],
                "$.require_complete_depth_coverage",
            ),
        )
    except ConstructionConfigValidationError:
        raise
    except Exception as exc:
        raise ConstructionConfigValidationError(
            f"Construction config validation failed: {exc}"
        ) from exc


def _parse_interval(value: object, path: str) -> DepthZoneInterval:
    data = _object(value, path)
    _exact_fields(
        data,
        required={"depth_zone", "z_min", "z_max"},
        optional=set(),
        path=path,
    )
    return DepthZoneInterval(
        depth_zone=_enum(
            data["depth_zone"],
            DepthZone,
            f"{path}.depth_zone",
            ConstructionConfigValidationError,
        ),
        z_min=_number(data["z_min"], f"{path}.z_min"),
        z_max=_number(data["z_max"], f"{path}.z_max"),
    )


def _parse_json(text: str, label: str) -> object:
    if not isinstance(text, str):
        raise AssistedJSONError(f"{label} JSON input must be text")
    try:
        return json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AssistedJSONError(f"Invalid {label} JSON: {exc}") from exc


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
        raise AssistedSerializationError(
            f"Could not serialize {label} canonically: {exc}"
        ) from exc


def _read(path: Path, label: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise AssistedFileNotFoundError(
            f"{label.capitalize()} file does not exist: {resolved}"
        )
    try:
        return resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AssistedReadError(
            f"Could not read {label} as UTF-8: {resolved}: {exc}"
        ) from exc


def _atomic_write_text(
    text: str,
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
            raise AssistedWriteError(
                f"Could not create output parent {parent}: {exc}"
            ) from exc
    if not parent.is_dir():
        raise AssistedWriteError(
            f"Output parent does not exist: {parent}; "
            "pass create_parents=True to create it"
        )
    if resolved.exists() and not overwrite:
        raise AssistedFileExistsError(
            f"Output exists; pass overwrite=True to replace it: {resolved}"
        )
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, resolved)
        else:
            try:
                os.link(temporary, resolved)
            except FileExistsError as exc:
                raise AssistedFileExistsError(
                    f"Output appeared during save and was preserved: {resolved}"
                ) from exc
            temporary.unlink()
        temporary = None
    except AssistedFileExistsError:
        raise
    except OSError as exc:
        raise AssistedWriteError(
            f"Could not safely write output {resolved}: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return resolved


def _object(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AssistedJSONError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise AssistedJSONError(f"{path} must be an array")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise AssistedJSONError(f"{path} must be a string")
    return value


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssistedJSONError(f"{path} must be an integer")
    return value


def _optional_integer(value: object, path: str) -> int | None:
    if value is None:
        return None
    return _integer(value, path)


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise AssistedJSONError(f"{path} must be a boolean")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AssistedJSONError(f"{path} must be a number")
    normalized = float(value)
    if not (
        normalized == normalized and normalized not in (float("inf"), float("-inf"))
    ):
        raise AssistedJSONError(f"{path} must be finite")
    return normalized


def _vector(value: object, path: str) -> Vector3:
    values = _array(value, path)
    if len(values) != 3:
        raise AssistedJSONError(f"{path} must contain exactly three numbers")
    return Vector3(
        _number(values[0], f"{path}[0]"),
        _number(values[1], f"{path}[1]"),
        _number(values[2], f"{path}[2]"),
    )


def _attributes(
    value: object,
    path: str,
) -> dict[str, str | int | float]:
    data = _object(value, path)
    result: dict[str, str | int | float] = {}
    for key, item in data.items():
        if not key:
            raise AnnotationValidationError(f"{path} keys must be nonempty strings")
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise AnnotationValidationError(
                f"{path}.{key} must be a string, integer, or finite number"
            )
        if isinstance(item, float) and not (
            item == item and item not in (float("inf"), float("-inf"))
        ):
            raise AnnotationValidationError(f"{path}.{key} must be finite")
        result[key] = item
    return result


def _enum(
    value: object,
    enum_type: type,
    path: str,
    error_type: type[Exception],
):
    text = _string(value, path)
    try:
        return enum_type(text)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise error_type(f"{path} must be one of: {allowed}") from exc


def _optional_enum(
    value: object,
    enum_type: type,
    path: str,
    error_type: type[Exception],
):
    if value is None:
        return None
    return _enum(value, enum_type, path, error_type)


def _exact_fields(
    data: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str],
    path: str,
) -> None:
    missing = sorted(required - data.keys())
    if missing:
        raise AssistedJSONError(
            f"{path} missing required field(s): {', '.join(missing)}"
        )
    unexpected = sorted(data.keys() - required - optional)
    if unexpected:
        raise AssistedJSONError(
            f"{path} has unexpected field(s): {', '.join(unexpected)}"
        )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite constant {value!r} is not permitted")
