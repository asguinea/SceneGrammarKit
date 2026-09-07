"""Deterministic non-metric lifting of supplied 2D annotation evidence."""

from __future__ import annotations

import hashlib
from collections import Counter

from scene_grammar_kit.assisted.annotation_models import (
    AnnotationRole,
    AnnotationShape,
    DepthZone,
    InstanceAnnotation,
    NormalizedPolygon,
    NormalizedRectangle,
    RegionAnnotation,
    SceneAnnotation,
)
from scene_grammar_kit.assisted.config_models import (
    ConstructionConfig,
    DepthZoneInterval,
)
from scene_grammar_kit.assisted.lifting_errors import LiftingValidationError
from scene_grammar_kit.assisted.lifting_models import (
    INSTANCE_DEPTH_FRACTION,
    ConfigurationObservationProvenance,
    DerivedDepthPolicy,
    DerivedObservationProvenance,
    LiftedObservation,
    LiftedSceneObservations,
    LiftingReport,
    LiftingResult,
    LiftingWarning,
    ObservationProvenance,
    ObservationPurpose,
    ObservationSourceType,
    ProxyApproximation,
    SuppliedObservationProvenance,
)
from scene_grammar_kit.assisted.review_models import VerifiedSourceImage
from scene_grammar_kit.assisted.serialization import (
    annotation_to_canonical_json,
    construction_config_to_canonical_json,
)
from scene_grammar_kit.assisted.validation import validate_assisted_input
from scene_grammar_kit.grammar import Axis, Bounds3D, GeometryType, Vector3

LIFTING_ASSUMPTIONS = (
    "Coordinates form a non-metric normalized orthographic proxy.",
    "Supplied depth-zone labels select configured z intervals.",
    "Region proxy depth uses the complete configured zone interval.",
    "Instance proxy depth uses the image bottom edge and 5% zone thickness.",
    "Polygon proxy bounds use the supplied polygon bounding rectangle.",
    "Source-image pixels are verified for provenance but not analyzed.",
)

SUPPLIED_LIFTING_INFORMATION = (
    "annotation geometry",
    "semantic classes",
    "depth-zone labels",
    "region roles",
    "parent-region relationships",
    "terminal geometry labels",
    "split-axis hints",
    "repeat-group membership and axis hints",
    "order hints",
    "attributes",
)

DERIVED_LIFTING_INFORMATION = (
    "world x/y proxy bounds from normalized image coordinates",
    "proxy z intervals from configured zones and frozen depth policies",
    "world centroids from proxy bounds",
    "polygon bounding-box approximation labels",
)

EXPLICITLY_NOT_INFERRED = (
    "metric depth",
    "camera intrinsics",
    "camera extrinsics",
    "physical object dimensions",
    "split hierarchy",
    "split boundaries",
    "repeat count beyond supplied membership",
    "repeat spacing",
    "grammar",
    "reconstructed mesh",
)


def map_normalized_u_to_world_x(
    u: float,
    root_bounds: Bounds3D,
) -> float:
    """Map normalized image horizontal coordinate to root-world x."""
    _normalized_coordinate(u, "u")
    extent = root_bounds.maximum.x - root_bounds.minimum.x
    return root_bounds.minimum.x + u * extent


def map_normalized_v_to_world_y(
    v: float,
    root_bounds: Bounds3D,
) -> float:
    """Map downward image v to upward root-world y using ``1 - v``."""
    _normalized_coordinate(v, "v")
    extent = root_bounds.maximum.y - root_bounds.minimum.y
    return root_bounds.minimum.y + (1.0 - v) * extent


def normalized_bounds_to_world_xy(
    bounds: NormalizedRectangle,
    root_bounds: Bounds3D,
) -> tuple[float, float, float, float]:
    """Return exact world x-min, y-min, x-max, y-max proxy bounds."""
    if not isinstance(bounds, NormalizedRectangle):
        raise TypeError("bounds must be a NormalizedRectangle")
    return (
        map_normalized_u_to_world_x(bounds.u_min, root_bounds),
        map_normalized_v_to_world_y(bounds.v_max, root_bounds),
        map_normalized_u_to_world_x(bounds.u_max, root_bounds),
        map_normalized_v_to_world_y(bounds.v_min, root_bounds),
    )


def instance_proxy_depth_interval(
    bottom_v: float,
    interval: DepthZoneInterval,
) -> tuple[float, float]:
    """Derive a fixed 5% zone-depth interval around the bottom-edge anchor."""
    _normalized_coordinate(bottom_v, "bottom_v")
    if not isinstance(interval, DepthZoneInterval):
        raise TypeError("interval must be a DepthZoneInterval")
    zone_extent = interval.z_max - interval.z_min
    depth_extent = zone_extent * INSTANCE_DEPTH_FRACTION
    half_extent = depth_extent / 2.0
    raw_center = interval.z_min + (1.0 - bottom_v) * zone_extent
    center = min(
        max(raw_center, interval.z_min + half_extent),
        interval.z_max - half_extent,
    )
    return (center - half_extent, center + half_extent)


def lift_assisted_input(
    annotation: SceneAnnotation,
    config: ConstructionConfig,
    *,
    verified_source_image: VerifiedSourceImage | None = None,
) -> LiftingResult:
    """Validate and lift annotations into ordered coarse 3D observations."""
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
    if (
        verified_source_image is not None
        and verified_source_image.annotation != annotation
    ):
        raise LiftingValidationError(
            "verified source image belongs to a different annotation"
        )

    annotation_sha256 = _sha256_text(annotation_to_canonical_json(annotation))
    config_sha256 = _sha256_text(construction_config_to_canonical_json(config))
    interval_by_zone = {
        interval.depth_zone: interval for interval in config.depth_zone_intervals
    }
    group_by_id = {group.repeat_group_id: group for group in annotation.repeat_groups}
    observations: list[LiftedObservation] = []
    for region in annotation.regions:
        observations.append(
            _lift_region(
                region,
                config,
                interval_by_zone[region.depth_zone],
                config_sha256,
            )
        )
    for instance in annotation.instances:
        group = (
            group_by_id.get(instance.repeat_group_id)
            if instance.repeat_group_id is not None
            else None
        )
        observations.append(
            _lift_instance(
                instance,
                config,
                interval_by_zone[instance.depth_zone],
                config_sha256,
                repeat_axis_hint=group.axis_hint if group is not None else None,
            )
        )

    warnings = _lifting_warnings(
        annotation,
        verified=verified_source_image is not None,
    )
    image_verified = verified_source_image is not None
    source_hash = (
        verified_source_image.byte_sha256 if verified_source_image is not None else None
    )
    scene = LiftedSceneObservations(
        annotation_schema_version=annotation.annotation_schema_version,
        construction_config_schema_version=config.config_schema_version,
        scene_id=annotation.scene_id,
        image_id=annotation.source_image.image_id,
        source_image_relative_path=annotation.source_image.image_path,
        image_verification_status=image_verified,
        verified_source_image_sha256=source_hash,
        annotation_sha256=annotation_sha256,
        construction_config_sha256=config_sha256,
        coordinate_system=annotation.coordinate_system,
        projection_model=config.projection_model,
        root_bounds=config.root_bounds,
        depth_zone_intervals=config.depth_zone_intervals,
        observations=tuple(observations),
        source_pixels_used_for_geometric_inference=False,
        assumptions=LIFTING_ASSUMPTIONS,
        warnings=warnings,
    )
    purpose_counts = Counter(item.purpose.value for item in observations)
    shape_counts = Counter(
        item.normalized_source_shape.type.value for item in observations
    )
    zone_counts = Counter(item.depth_zone.value for item in observations)
    for zone in DepthZone:
        zone_counts.setdefault(zone.value, 0)
    geometry_counts = Counter(
        item.terminal_geometry.value
        for item in observations
        if item.terminal_geometry is not None
    )
    report = LiftingReport(
        success=True,
        scene_id=annotation.scene_id,
        image_verification_status=image_verified,
        source_image_sha256=source_hash,
        annotation_sha256=annotation_sha256,
        construction_config_sha256=config_sha256,
        region_observations_created=len(annotation.regions),
        instance_observations_created=len(annotation.instances),
        structural_observations=purpose_counts["structural"],
        terminal_candidate_observations=purpose_counts["terminal_candidate"],
        open_space_observations=purpose_counts["open_space"],
        object_instance_observations=purpose_counts["object_instance"],
        rectangle_source_count=shape_counts["rectangle"],
        polygon_source_count=shape_counts["polygon"],
        depth_zone_frequency=dict(zone_counts),
        geometry_type_frequency=dict(geometry_counts),
        observations_with_split_axis_hints=sum(
            item.supplied_split_axis_hint is not None for item in observations
        ),
        observations_with_repeat_group_membership=sum(
            item.repeat_group_id is not None for item in observations
        ),
        assumptions=LIFTING_ASSUMPTIONS,
        warnings=warnings,
        supplied_information=SUPPLIED_LIFTING_INFORMATION,
        derived_information=DERIVED_LIFTING_INFORMATION,
        explicitly_not_inferred=EXPLICITLY_NOT_INFERRED,
    )
    return LiftingResult(
        scene=scene,
        report=report,
        annotation=annotation,
        construction_config=config,
        verified_source_image=verified_source_image,
    )


def _lift_region(
    region: RegionAnnotation,
    config: ConstructionConfig,
    interval: DepthZoneInterval,
    config_sha256: str,
) -> LiftedObservation:
    bounds = region.shape.bounding_rectangle
    x_min, y_min, x_max, y_max = normalized_bounds_to_world_xy(
        bounds, config.root_bounds
    )
    world_bounds = Bounds3D(
        Vector3(x_min, y_min, interval.z_min),
        Vector3(x_max, y_max, interval.z_max),
    )
    purpose = {
        AnnotationRole.STRUCTURAL_REGION: ObservationPurpose.STRUCTURAL,
        AnnotationRole.TERMINAL_REGION: ObservationPurpose.TERMINAL_CANDIDATE,
        AnnotationRole.OPEN_SPACE: ObservationPurpose.OPEN_SPACE,
    }[region.role]
    approximation = _approximation(region.shape)
    supplied = SuppliedObservationProvenance(
        annotation_id=region.region_id,
        semantic_class=region.semantic_class,
        image_shape=region.shape,
        depth_zone=region.depth_zone,
        region_role=region.role,
        terminal_geometry=region.terminal_geometry,
        parent_region_id=region.parent_region_id,
        repeat_group_id=None,
        split_axis_hint=region.split_axis_hint,
        repeat_axis_hint=None,
        order_hint=region.order_hint,
        attributes=region.attributes,
    )
    configuration = ConfigurationObservationProvenance(
        root_bounds=config.root_bounds,
        depth_zone_interval=interval,
        projection_model=config.projection_model,
        construction_config_sha256=config_sha256,
    )
    derived = DerivedObservationProvenance(
        world_bounds=world_bounds,
        world_centroid=_bounds_centroid(world_bounds),
        depth_policy=DerivedDepthPolicy.FULL_ZONE_INTERVAL,
        proxy_approximation=approximation,
    )
    return LiftedObservation(
        observation_id=f"region:{region.region_id}",
        source_annotation_type=ObservationSourceType.REGION,
        source_annotation_id=region.region_id,
        semantic_class=region.semantic_class,
        depth_zone=region.depth_zone,
        purpose=purpose,
        terminal_geometry=region.terminal_geometry,
        normalized_source_shape=region.shape,
        normalized_source_bounds=bounds,
        normalized_source_signed_area=region.shape.signed_area,
        normalized_source_area=region.shape.area,
        normalized_source_centroid=region.shape.centroid,
        world_bounds=world_bounds,
        world_centroid=derived.world_centroid,
        depth_policy=derived.depth_policy,
        proxy_approximation=approximation,
        parent_region_id=region.parent_region_id,
        repeat_group_id=None,
        supplied_split_axis_hint=region.split_axis_hint,
        supplied_order_hint=region.order_hint,
        attributes=region.attributes,
        provenance=ObservationProvenance(supplied, configuration, derived),
    )


def _lift_instance(
    instance: InstanceAnnotation,
    config: ConstructionConfig,
    interval: DepthZoneInterval,
    config_sha256: str,
    *,
    repeat_axis_hint: Axis | None,
) -> LiftedObservation:
    bounds = instance.shape.bounding_rectangle
    x_min, y_min, x_max, y_max = normalized_bounds_to_world_xy(
        bounds, config.root_bounds
    )
    z_min, z_max = instance_proxy_depth_interval(bounds.v_max, interval)
    world_bounds = Bounds3D(
        Vector3(x_min, y_min, z_min),
        Vector3(x_max, y_max, z_max),
    )
    approximation = _approximation(instance.shape)
    supplied = SuppliedObservationProvenance(
        annotation_id=instance.instance_id,
        semantic_class=instance.semantic_class,
        image_shape=instance.shape,
        depth_zone=instance.depth_zone,
        region_role=None,
        terminal_geometry=instance.terminal_geometry,
        parent_region_id=instance.parent_region_id,
        repeat_group_id=instance.repeat_group_id,
        split_axis_hint=None,
        repeat_axis_hint=repeat_axis_hint,
        order_hint=instance.order_hint,
        attributes=instance.attributes,
    )
    configuration = ConfigurationObservationProvenance(
        root_bounds=config.root_bounds,
        depth_zone_interval=interval,
        projection_model=config.projection_model,
        construction_config_sha256=config_sha256,
    )
    derived = DerivedObservationProvenance(
        world_bounds=world_bounds,
        world_centroid=_bounds_centroid(world_bounds),
        depth_policy=DerivedDepthPolicy.IMAGE_BOTTOM_PROXY_ANCHOR,
        proxy_approximation=approximation,
    )
    return LiftedObservation(
        observation_id=f"instance:{instance.instance_id}",
        source_annotation_type=ObservationSourceType.INSTANCE,
        source_annotation_id=instance.instance_id,
        semantic_class=instance.semantic_class,
        depth_zone=instance.depth_zone,
        purpose=ObservationPurpose.OBJECT_INSTANCE,
        terminal_geometry=instance.terminal_geometry,
        normalized_source_shape=instance.shape,
        normalized_source_bounds=bounds,
        normalized_source_signed_area=instance.shape.signed_area,
        normalized_source_area=instance.shape.area,
        normalized_source_centroid=instance.shape.centroid,
        world_bounds=world_bounds,
        world_centroid=derived.world_centroid,
        depth_policy=derived.depth_policy,
        proxy_approximation=approximation,
        parent_region_id=instance.parent_region_id,
        repeat_group_id=instance.repeat_group_id,
        supplied_split_axis_hint=None,
        supplied_order_hint=instance.order_hint,
        attributes=instance.attributes,
        provenance=ObservationProvenance(supplied, configuration, derived),
    )


def _lifting_warnings(
    annotation: SceneAnnotation,
    *,
    verified: bool,
) -> tuple[LiftingWarning, ...]:
    warnings: list[LiftingWarning] = []
    if not verified:
        warnings.append(
            LiftingWarning(
                "image_verification_skipped",
                "Source-image verification was explicitly unavailable or skipped.",
            )
        )
    for item in annotation.regions + annotation.instances:
        if isinstance(item.shape, NormalizedPolygon):
            identifier = (
                item.region_id
                if isinstance(item, RegionAnnotation)
                else item.instance_id
            )
            warnings.append(
                LiftingWarning(
                    "polygon_bounding_box_proxy",
                    "Supplied polygon evidence uses its bounding box for the 3D proxy.",
                    identifier,
                )
            )
    region_by_id = {item.region_id: item for item in annotation.regions}
    for region in annotation.regions:
        if region.parent_region_id is not None and not _contains(
            region_by_id[region.parent_region_id].shape.bounding_rectangle,
            region.shape.bounding_rectangle,
        ):
            warnings.append(
                LiftingWarning(
                    "region_outside_declared_parent",
                    "Region bounds are not spatially contained in its declared parent.",
                    region.region_id,
                )
            )
    for instance in annotation.instances:
        if instance.parent_region_id is not None and not _contains(
            region_by_id[instance.parent_region_id].shape.bounding_rectangle,
            instance.shape.bounding_rectangle,
        ):
            warnings.append(
                LiftingWarning(
                    "instance_outside_declared_parent",
                    "Instance bounds are not spatially contained in its declared parent.",
                    instance.instance_id,
                )
            )
    structural = [
        region
        for region in annotation.regions
        if region.role is AnnotationRole.STRUCTURAL_REGION
    ]
    for first_index, first in enumerate(structural):
        for second in structural[first_index + 1 :]:
            if (
                first.parent_region_id == second.parent_region_id
                and first.depth_zone is second.depth_zone
                and _overlaps(
                    first.shape.bounding_rectangle,
                    second.shape.bounding_rectangle,
                )
            ):
                warnings.append(
                    LiftingWarning(
                        "overlapping_structural_regions",
                        f"Structural regions {first.region_id!r} and "
                        f"{second.region_id!r} overlap within one parent and zone.",
                        first.region_id,
                    )
                )
    for instance in annotation.instances:
        if instance.terminal_geometry is GeometryType.EMPTY:
            warnings.append(
                LiftingWarning(
                    "empty_instance_terminal_geometry",
                    "Object instance supplies terminal geometry empty.",
                    instance.instance_id,
                )
            )
    instance_by_id = {
        instance.instance_id: instance for instance in annotation.instances
    }
    for group in annotation.repeat_groups:
        missing = tuple(
            member
            for member in group.member_instance_ids
            if instance_by_id[member].order_hint is None
        )
        if missing:
            warnings.append(
                LiftingWarning(
                    "missing_repeat_member_order_hint",
                    "Repeat-group members lack optional order hints: "
                    + ", ".join(missing),
                    group.repeat_group_id,
                )
            )
    return tuple(warnings)


def _approximation(shape: AnnotationShape) -> ProxyApproximation:
    return (
        ProxyApproximation.IMAGE_POLYGON_BOUNDING_BOX
        if isinstance(shape, NormalizedPolygon)
        else ProxyApproximation.RECTANGLE_BOUNDS
    )


def _bounds_centroid(bounds: Bounds3D) -> Vector3:
    return Vector3(
        (bounds.minimum.x + bounds.maximum.x) / 2.0,
        (bounds.minimum.y + bounds.maximum.y) / 2.0,
        (bounds.minimum.z + bounds.maximum.z) / 2.0,
    )


def _contains(
    outer: NormalizedRectangle,
    inner: NormalizedRectangle,
) -> bool:
    return (
        outer.u_min <= inner.u_min
        and outer.v_min <= inner.v_min
        and outer.u_max >= inner.u_max
        and outer.v_max >= inner.v_max
    )


def _overlaps(
    first: NormalizedRectangle,
    second: NormalizedRectangle,
) -> bool:
    return min(first.u_max, second.u_max) > max(first.u_min, second.u_min) and min(
        first.v_max, second.v_max
    ) > max(first.v_min, second.v_min)


def _normalized_coordinate(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiftingValidationError(f"{name} must be a normalized number")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise LiftingValidationError(f"{name} must be within [0, 1]")
    return normalized


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
