"""Canonical JSON serialization for coarse lifted observations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from scene_grammar_kit.assisted.annotation_models import (
    AnnotationRole,
    DepthZone,
    NormalizedPoint,
    NormalizedPolygon,
    NormalizedRectangle,
)
from scene_grammar_kit.assisted.config_models import (
    DepthZoneInterval,
    ProjectionModel,
)
from scene_grammar_kit.assisted.lifting_errors import LiftingSerializationError
from scene_grammar_kit.assisted.lifting_models import (
    ConfigurationObservationProvenance,
    DerivedDepthPolicy,
    DerivedObservationProvenance,
    LiftedObservation,
    LiftedSceneObservations,
    LiftingReport,
    LiftingWarning,
    ObservationProvenance,
    ObservationPurpose,
    ObservationSourceType,
    ProxyApproximation,
    SuppliedObservationProvenance,
)
from scene_grammar_kit.grammar import Axis, Bounds3D, GeometryType, Vector3


def lifted_scene_to_canonical_json(scene: LiftedSceneObservations) -> str:
    """Serialize a lifted scene with stable ordered observations and points."""
    if not isinstance(scene, LiftedSceneObservations):
        raise LiftingSerializationError("scene must be a LiftedSceneObservations")
    return _canonical_json(_scene_data(scene), "lifted scene")


def lifting_report_to_canonical_json(report: LiftingReport) -> str:
    """Serialize a lifting report as compact deterministic JSON."""
    if not isinstance(report, LiftingReport):
        raise LiftingSerializationError("report must be a LiftingReport")
    return _canonical_json(_report_data(report), "lifting report")


def lifted_scene_from_json(text: str) -> LiftedSceneObservations:
    """Parse strict JSON into an immutable lifted-scene document."""
    try:
        data = _object(_parse_json(text), "$")
        return LiftedSceneObservations(
            lifting_policy_version=_string(
                data["lifting_policy_version"], "$.lifting_policy_version"
            ),
            annotation_schema_version=_string(
                data["annotation_schema_version"],
                "$.annotation_schema_version",
            ),
            construction_config_schema_version=_string(
                data["construction_config_schema_version"],
                "$.construction_config_schema_version",
            ),
            scene_id=_string(data["scene_id"], "$.scene_id"),
            image_id=_string(data["image_id"], "$.image_id"),
            source_image_relative_path=_string(
                data["source_image_relative_path"],
                "$.source_image_relative_path",
            ),
            image_verification_status=_boolean(
                data["image_verification_status"],
                "$.image_verification_status",
            ),
            verified_source_image_sha256=_optional_string(
                data["verified_source_image_sha256"],
                "$.verified_source_image_sha256",
            ),
            annotation_sha256=_string(data["annotation_sha256"], "$.annotation_sha256"),
            construction_config_sha256=_string(
                data["construction_config_sha256"],
                "$.construction_config_sha256",
            ),
            coordinate_system=_string(data["coordinate_system"], "$.coordinate_system"),
            projection_model=_enum(
                ProjectionModel,
                data["projection_model"],
                "$.projection_model",
            ),
            root_bounds=_parse_bounds(data["root_bounds"], "$.root_bounds"),
            depth_zone_intervals=tuple(
                _parse_interval(item, f"$.depth_zone_intervals[{index}]")
                for index, item in enumerate(
                    _array(
                        data["depth_zone_intervals"],
                        "$.depth_zone_intervals",
                    )
                )
            ),
            observations=tuple(
                _parse_observation(item, f"$.observations[{index}]")
                for index, item in enumerate(
                    _array(data["observations"], "$.observations")
                )
            ),
            source_pixels_used_for_geometric_inference=_boolean(
                data["source_pixels_used_for_geometric_inference"],
                "$.source_pixels_used_for_geometric_inference",
            ),
            assumptions=_strings(data["assumptions"], "$.assumptions"),
            warnings=tuple(
                _parse_warning(item, f"$.warnings[{index}]")
                for index, item in enumerate(_array(data["warnings"], "$.warnings"))
            ),
        )
    except LiftingSerializationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise LiftingSerializationError(
            f"Invalid lifted scene document: {exc}"
        ) from exc


def lifting_report_from_json(text: str) -> LiftingReport:
    """Parse strict JSON into an immutable deterministic lifting report."""
    try:
        data = _object(_parse_json(text), "$")
        return LiftingReport(
            success=_boolean(data["success"], "$.success"),
            lifting_policy_version=_string(
                data["lifting_policy_version"], "$.lifting_policy_version"
            ),
            scene_id=_string(data["scene_id"], "$.scene_id"),
            image_verification_status=_boolean(
                data["image_verification_status"],
                "$.image_verification_status",
            ),
            source_image_sha256=_optional_string(
                data["source_image_sha256"], "$.source_image_sha256"
            ),
            annotation_sha256=_string(data["annotation_sha256"], "$.annotation_sha256"),
            construction_config_sha256=_string(
                data["construction_config_sha256"],
                "$.construction_config_sha256",
            ),
            region_observations_created=_integer(
                data["region_observations_created"],
                "$.region_observations_created",
            ),
            instance_observations_created=_integer(
                data["instance_observations_created"],
                "$.instance_observations_created",
            ),
            structural_observations=_integer(
                data["structural_observations"],
                "$.structural_observations",
            ),
            terminal_candidate_observations=_integer(
                data["terminal_candidate_observations"],
                "$.terminal_candidate_observations",
            ),
            open_space_observations=_integer(
                data["open_space_observations"],
                "$.open_space_observations",
            ),
            object_instance_observations=_integer(
                data["object_instance_observations"],
                "$.object_instance_observations",
            ),
            rectangle_source_count=_integer(
                data["rectangle_source_count"], "$.rectangle_source_count"
            ),
            polygon_source_count=_integer(
                data["polygon_source_count"], "$.polygon_source_count"
            ),
            depth_zone_frequency=_counts(
                data["depth_zone_frequency"], "$.depth_zone_frequency"
            ),
            geometry_type_frequency=_counts(
                data["geometry_type_frequency"],
                "$.geometry_type_frequency",
            ),
            observations_with_split_axis_hints=_integer(
                data["observations_with_split_axis_hints"],
                "$.observations_with_split_axis_hints",
            ),
            observations_with_repeat_group_membership=_integer(
                data["observations_with_repeat_group_membership"],
                "$.observations_with_repeat_group_membership",
            ),
            assumptions=_strings(data["assumptions"], "$.assumptions"),
            warnings=tuple(
                _parse_warning(item, f"$.warnings[{index}]")
                for index, item in enumerate(_array(data["warnings"], "$.warnings"))
            ),
            supplied_information=_strings(
                data["supplied_information"], "$.supplied_information"
            ),
            derived_information=_strings(
                data["derived_information"], "$.derived_information"
            ),
            explicitly_not_inferred=_strings(
                data["explicitly_not_inferred"],
                "$.explicitly_not_inferred",
            ),
        )
    except LiftingSerializationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise LiftingSerializationError(
            f"Invalid lifting report document: {exc}"
        ) from exc


def _scene_data(scene: LiftedSceneObservations) -> dict[str, Any]:
    return {
        "annotation_schema_version": scene.annotation_schema_version,
        "annotation_sha256": scene.annotation_sha256,
        "assumptions": list(scene.assumptions),
        "construction_config_schema_version": (
            scene.construction_config_schema_version
        ),
        "construction_config_sha256": scene.construction_config_sha256,
        "coordinate_system": scene.coordinate_system,
        "depth_zone_intervals": [
            _interval_data(item) for item in scene.depth_zone_intervals
        ],
        "image_id": scene.image_id,
        "image_verification_status": scene.image_verification_status,
        "lifting_policy_version": scene.lifting_policy_version,
        "observations": [_observation_data(item) for item in scene.observations],
        "projection_model": scene.projection_model.value,
        "root_bounds": _bounds_data(scene.root_bounds),
        "scene_id": scene.scene_id,
        "source_image_relative_path": scene.source_image_relative_path,
        "source_pixels_used_for_geometric_inference": (
            scene.source_pixels_used_for_geometric_inference
        ),
        "verified_source_image_sha256": (scene.verified_source_image_sha256),
        "warnings": [_warning_data(item) for item in scene.warnings],
    }


def _report_data(report: LiftingReport) -> dict[str, Any]:
    return {
        "annotation_sha256": report.annotation_sha256,
        "assumptions": list(report.assumptions),
        "construction_config_sha256": report.construction_config_sha256,
        "depth_zone_frequency": dict(report.depth_zone_frequency),
        "derived_information": list(report.derived_information),
        "explicitly_not_inferred": list(report.explicitly_not_inferred),
        "geometry_type_frequency": dict(report.geometry_type_frequency),
        "image_verification_status": report.image_verification_status,
        "instance_observations_created": (report.instance_observations_created),
        "lifting_policy_version": report.lifting_policy_version,
        "object_instance_observations": report.object_instance_observations,
        "observations_with_repeat_group_membership": (
            report.observations_with_repeat_group_membership
        ),
        "observations_with_split_axis_hints": (
            report.observations_with_split_axis_hints
        ),
        "open_space_observations": report.open_space_observations,
        "polygon_source_count": report.polygon_source_count,
        "rectangle_source_count": report.rectangle_source_count,
        "region_observations_created": report.region_observations_created,
        "scene_id": report.scene_id,
        "source_image_sha256": report.source_image_sha256,
        "structural_observations": report.structural_observations,
        "success": report.success,
        "supplied_information": list(report.supplied_information),
        "terminal_candidate_observations": (report.terminal_candidate_observations),
        "warnings": [_warning_data(item) for item in report.warnings],
    }


def _observation_data(observation: LiftedObservation) -> dict[str, Any]:
    return {
        "attributes": dict(observation.attributes),
        "depth_policy": observation.depth_policy.value,
        "depth_zone": observation.depth_zone.value,
        "normalized_source_bounds": _rectangle_data(
            observation.normalized_source_bounds
        ),
        "normalized_source_signed_area": (observation.normalized_source_signed_area),
        "normalized_source_area": observation.normalized_source_area,
        "normalized_source_centroid": {
            "u": observation.normalized_source_centroid.u,
            "v": observation.normalized_source_centroid.v,
        },
        "normalized_source_shape": _shape_data(observation.normalized_source_shape),
        "observation_id": observation.observation_id,
        "parent_region_id": observation.parent_region_id,
        "provenance": _provenance_data(observation.provenance),
        "proxy_approximation": observation.proxy_approximation.value,
        "purpose": observation.purpose.value,
        "repeat_group_id": observation.repeat_group_id,
        "semantic_class": observation.semantic_class,
        "source_annotation_id": observation.source_annotation_id,
        "source_annotation_type": observation.source_annotation_type.value,
        "supplied_order_hint": observation.supplied_order_hint,
        "supplied_split_axis_hint": (
            observation.supplied_split_axis_hint.value
            if observation.supplied_split_axis_hint is not None
            else None
        ),
        "terminal_geometry": (
            observation.terminal_geometry.value
            if observation.terminal_geometry is not None
            else None
        ),
        "world_bounds": _bounds_data(observation.world_bounds),
        "world_centroid": _vector_data(observation.world_centroid),
    }


def _provenance_data(provenance: ObservationProvenance) -> dict[str, Any]:
    supplied = provenance.supplied
    configuration = provenance.configuration
    derived = provenance.derived
    return {
        "configuration": {
            "construction_config_sha256": (configuration.construction_config_sha256),
            "depth_zone_interval": _interval_data(configuration.depth_zone_interval),
            "projection_model": configuration.projection_model.value,
            "root_bounds": _bounds_data(configuration.root_bounds),
        },
        "derived": {
            "depth_policy": derived.depth_policy.value,
            "lifting_policy_version": derived.lifting_policy_version,
            "proxy_approximation": derived.proxy_approximation.value,
            "world_bounds": _bounds_data(derived.world_bounds),
            "world_centroid": _vector_data(derived.world_centroid),
        },
        "supplied": {
            "annotation_id": supplied.annotation_id,
            "attributes": dict(supplied.attributes),
            "depth_zone": supplied.depth_zone.value,
            "image_shape": _shape_data(supplied.image_shape),
            "order_hint": supplied.order_hint,
            "parent_region_id": supplied.parent_region_id,
            "region_role": (
                supplied.region_role.value if supplied.region_role is not None else None
            ),
            "repeat_axis_hint": (
                supplied.repeat_axis_hint.value
                if supplied.repeat_axis_hint is not None
                else None
            ),
            "repeat_group_id": supplied.repeat_group_id,
            "semantic_class": supplied.semantic_class,
            "split_axis_hint": (
                supplied.split_axis_hint.value
                if supplied.split_axis_hint is not None
                else None
            ),
            "terminal_geometry": (
                supplied.terminal_geometry.value
                if supplied.terminal_geometry is not None
                else None
            ),
        },
    }


def _parse_observation(value: object, path: str) -> LiftedObservation:
    data = _object(value, path)
    provenance = _parse_provenance(data["provenance"], path + ".provenance")
    return LiftedObservation(
        observation_id=_string(data["observation_id"], path + ".observation_id"),
        source_annotation_type=_enum(
            ObservationSourceType,
            data["source_annotation_type"],
            path + ".source_annotation_type",
        ),
        source_annotation_id=_string(
            data["source_annotation_id"], path + ".source_annotation_id"
        ),
        semantic_class=_string(data["semantic_class"], path + ".semantic_class"),
        depth_zone=_enum(DepthZone, data["depth_zone"], path + ".depth_zone"),
        purpose=_enum(ObservationPurpose, data["purpose"], path + ".purpose"),
        terminal_geometry=_optional_enum(
            GeometryType,
            data["terminal_geometry"],
            path + ".terminal_geometry",
        ),
        normalized_source_shape=_parse_shape(
            data["normalized_source_shape"],
            path + ".normalized_source_shape",
        ),
        normalized_source_bounds=_parse_rectangle(
            data["normalized_source_bounds"],
            path + ".normalized_source_bounds",
        ),
        normalized_source_signed_area=_number(
            data["normalized_source_signed_area"],
            path + ".normalized_source_signed_area",
        ),
        normalized_source_area=_number(
            data["normalized_source_area"],
            path + ".normalized_source_area",
        ),
        normalized_source_centroid=NormalizedPoint(
            _number(
                _object(
                    data["normalized_source_centroid"],
                    path + ".normalized_source_centroid",
                )["u"],
                path + ".normalized_source_centroid.u",
            ),
            _number(
                _object(
                    data["normalized_source_centroid"],
                    path + ".normalized_source_centroid",
                )["v"],
                path + ".normalized_source_centroid.v",
            ),
        ),
        world_bounds=_parse_bounds(data["world_bounds"], path + ".world_bounds"),
        world_centroid=_parse_vector(data["world_centroid"], path + ".world_centroid"),
        depth_policy=_enum(
            DerivedDepthPolicy, data["depth_policy"], path + ".depth_policy"
        ),
        proxy_approximation=_enum(
            ProxyApproximation,
            data["proxy_approximation"],
            path + ".proxy_approximation",
        ),
        parent_region_id=_optional_string(
            data["parent_region_id"], path + ".parent_region_id"
        ),
        repeat_group_id=_optional_string(
            data["repeat_group_id"], path + ".repeat_group_id"
        ),
        supplied_split_axis_hint=_optional_enum(
            Axis,
            data["supplied_split_axis_hint"],
            path + ".supplied_split_axis_hint",
        ),
        supplied_order_hint=_optional_integer(
            data["supplied_order_hint"], path + ".supplied_order_hint"
        ),
        attributes=_attributes(data["attributes"], path + ".attributes"),
        provenance=provenance,
    )


def _parse_provenance(value: object, path: str) -> ObservationProvenance:
    data = _object(value, path)
    supplied_data = _object(data["supplied"], path + ".supplied")
    config_data = _object(data["configuration"], path + ".configuration")
    derived_data = _object(data["derived"], path + ".derived")
    supplied = SuppliedObservationProvenance(
        annotation_id=_string(
            supplied_data["annotation_id"], path + ".supplied.annotation_id"
        ),
        semantic_class=_string(
            supplied_data["semantic_class"], path + ".supplied.semantic_class"
        ),
        image_shape=_parse_shape(
            supplied_data["image_shape"], path + ".supplied.image_shape"
        ),
        depth_zone=_enum(
            DepthZone,
            supplied_data["depth_zone"],
            path + ".supplied.depth_zone",
        ),
        region_role=_optional_enum(
            AnnotationRole,
            supplied_data["region_role"],
            path + ".supplied.region_role",
        ),
        terminal_geometry=_optional_enum(
            GeometryType,
            supplied_data["terminal_geometry"],
            path + ".supplied.terminal_geometry",
        ),
        parent_region_id=_optional_string(
            supplied_data["parent_region_id"],
            path + ".supplied.parent_region_id",
        ),
        repeat_group_id=_optional_string(
            supplied_data["repeat_group_id"],
            path + ".supplied.repeat_group_id",
        ),
        split_axis_hint=_optional_enum(
            Axis,
            supplied_data["split_axis_hint"],
            path + ".supplied.split_axis_hint",
        ),
        repeat_axis_hint=_optional_enum(
            Axis,
            supplied_data["repeat_axis_hint"],
            path + ".supplied.repeat_axis_hint",
        ),
        order_hint=_optional_integer(
            supplied_data["order_hint"], path + ".supplied.order_hint"
        ),
        attributes=_attributes(
            supplied_data["attributes"], path + ".supplied.attributes"
        ),
    )
    configuration = ConfigurationObservationProvenance(
        root_bounds=_parse_bounds(
            config_data["root_bounds"], path + ".configuration.root_bounds"
        ),
        depth_zone_interval=_parse_interval(
            config_data["depth_zone_interval"],
            path + ".configuration.depth_zone_interval",
        ),
        projection_model=_enum(
            ProjectionModel,
            config_data["projection_model"],
            path + ".configuration.projection_model",
        ),
        construction_config_sha256=_string(
            config_data["construction_config_sha256"],
            path + ".configuration.construction_config_sha256",
        ),
    )
    derived = DerivedObservationProvenance(
        world_bounds=_parse_bounds(
            derived_data["world_bounds"], path + ".derived.world_bounds"
        ),
        world_centroid=_parse_vector(
            derived_data["world_centroid"], path + ".derived.world_centroid"
        ),
        depth_policy=_enum(
            DerivedDepthPolicy,
            derived_data["depth_policy"],
            path + ".derived.depth_policy",
        ),
        proxy_approximation=_enum(
            ProxyApproximation,
            derived_data["proxy_approximation"],
            path + ".derived.proxy_approximation",
        ),
        lifting_policy_version=_string(
            derived_data["lifting_policy_version"],
            path + ".derived.lifting_policy_version",
        ),
    )
    return ObservationProvenance(supplied, configuration, derived)


def _warning_data(warning: LiftingWarning) -> dict[str, Any]:
    return {
        "annotation_id": warning.annotation_id,
        "code": warning.code,
        "message": warning.message,
    }


def _parse_warning(value: object, path: str) -> LiftingWarning:
    data = _object(value, path)
    return LiftingWarning(
        code=_string(data["code"], path + ".code"),
        message=_string(data["message"], path + ".message"),
        annotation_id=_optional_string(data["annotation_id"], path + ".annotation_id"),
    )


def _shape_data(shape: object) -> dict[str, Any]:
    if isinstance(shape, NormalizedRectangle):
        return _rectangle_data(shape)
    if isinstance(shape, NormalizedPolygon):
        return {
            "points": [{"u": point.u, "v": point.v} for point in shape.points],
            "type": "polygon",
        }
    raise LiftingSerializationError("unsupported normalized source shape")


def _rectangle_data(bounds: NormalizedRectangle) -> dict[str, Any]:
    return {
        "type": "rectangle",
        "u_max": bounds.u_max,
        "u_min": bounds.u_min,
        "v_max": bounds.v_max,
        "v_min": bounds.v_min,
    }


def _parse_shape(value: object, path: str):
    data = _object(value, path)
    shape_type = _string(data["type"], path + ".type")
    if shape_type == "rectangle":
        return _parse_rectangle(value, path)
    if shape_type == "polygon":
        return NormalizedPolygon(
            tuple(
                NormalizedPoint(
                    _number(_object(point, point_path)["u"], point_path + ".u"),
                    _number(_object(point, point_path)["v"], point_path + ".v"),
                )
                for index, point in enumerate(_array(data["points"], path + ".points"))
                for point_path in (f"{path}.points[{index}]",)
            )
        )
    raise LiftingSerializationError(f"{path}.type is unsupported")


def _parse_rectangle(value: object, path: str) -> NormalizedRectangle:
    data = _object(value, path)
    return NormalizedRectangle(
        _number(data["u_min"], path + ".u_min"),
        _number(data["v_min"], path + ".v_min"),
        _number(data["u_max"], path + ".u_max"),
        _number(data["v_max"], path + ".v_max"),
    )


def _bounds_data(bounds: Bounds3D) -> dict[str, Any]:
    return {
        "max": _vector_data(bounds.maximum),
        "min": _vector_data(bounds.minimum),
    }


def _vector_data(vector: Vector3) -> list[float]:
    return list(vector.as_tuple())


def _parse_bounds(value: object, path: str) -> Bounds3D:
    data = _object(value, path)
    return Bounds3D(
        _parse_vector(data["min"], path + ".min"),
        _parse_vector(data["max"], path + ".max"),
    )


def _parse_vector(value: object, path: str) -> Vector3:
    values = _array(value, path)
    if len(values) != 3:
        raise LiftingSerializationError(f"{path} must contain three numbers")
    return Vector3(*(_number(item, f"{path}[{i}]") for i, item in enumerate(values)))


def _interval_data(interval: DepthZoneInterval) -> dict[str, Any]:
    return {
        "depth_zone": interval.depth_zone.value,
        "z_max": interval.z_max,
        "z_min": interval.z_min,
    }


def _parse_interval(value: object, path: str) -> DepthZoneInterval:
    data = _object(value, path)
    return DepthZoneInterval(
        _enum(DepthZone, data["depth_zone"], path + ".depth_zone"),
        _number(data["z_min"], path + ".z_min"),
        _number(data["z_max"], path + ".z_max"),
    )


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
        raise LiftingSerializationError(
            f"Could not serialize {label} canonically: {exc}"
        ) from exc


def _parse_json(text: str) -> object:
    if not isinstance(text, str):
        raise LiftingSerializationError("JSON input must be text")
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LiftingSerializationError(f"Invalid strict JSON: {exc}") from exc


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value} is not permitted")


def _object(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise LiftingSerializationError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise LiftingSerializationError(f"{path} must be an array")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise LiftingSerializationError(f"{path} must be a nonempty string")
    return value


def _optional_string(value: object, path: str) -> str | None:
    return None if value is None else _string(value, path)


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise LiftingSerializationError(f"{path} must be a boolean")
    return value


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LiftingSerializationError(f"{path} must be an integer")
    return value


def _optional_integer(value: object, path: str) -> int | None:
    return None if value is None else _integer(value, path)


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiftingSerializationError(f"{path} must be a finite number")
    number = float(value)
    if not __import__("math").isfinite(number):
        raise LiftingSerializationError(f"{path} must be finite")
    return number


def _strings(value: object, path: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )


def _counts(value: object, path: str) -> dict[str, int]:
    data = _object(value, path)
    return {
        _string(key, path + ".key"): _integer(item, f"{path}.{key}")
        for key, item in data.items()
    }


def _attributes(value: object, path: str) -> dict[str, str | int | float]:
    data = _object(value, path)
    result: dict[str, str | int | float] = {}
    for key, item in data.items():
        _string(key, path + ".key")
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise LiftingSerializationError(f"{path}.{key} must be a scalar or string")
        if isinstance(item, float) and not __import__("math").isfinite(item):
            raise LiftingSerializationError(f"{path}.{key} must be finite")
        result[key] = item
    return result


def _enum(enum_type: type, value: object, path: str):
    try:
        return enum_type(_string(value, path))
    except ValueError as exc:
        raise LiftingSerializationError(f"{path} is unsupported") from exc


def _optional_enum(enum_type: type, value: object, path: str):
    return None if value is None else _enum(enum_type, value, path)
