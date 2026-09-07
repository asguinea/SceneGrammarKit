"""Deterministic structured validation for assisted inputs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scene_grammar_kit.assisted.annotation_models import (
    ANNOTATION_SCHEMA_VERSION,
    NORMALIZED_IMAGE_COORDINATE_SYSTEM,
    AnnotationRole,
    DepthZone,
    InstanceAnnotation,
    NormalizedPolygon,
    NormalizedRectangle,
    RegionAnnotation,
    SceneAnnotation,
)
from scene_grammar_kit.assisted.config_models import (
    CONSTRUCTION_CONFIG_SCHEMA_VERSION,
    ConstructionAxisPolicy,
    ConstructionConfig,
    ProjectionModel,
)
from scene_grammar_kit.grammar import GeometryType, ValidationSeverity

DEFAULT_MAXIMUM_HIERARCHY_DEPTH = 64


class AssistedDiagnosticDomain(str, Enum):
    """Origin of one assisted-input diagnostic."""

    ANNOTATION = "annotation"
    CONFIGURATION = "configuration"
    COMPATIBILITY = "compatibility"


@dataclass(frozen=True, slots=True)
class AssistedValidationDiagnostic:
    """One ordered stable assisted-input validation finding."""

    code: str
    severity: ValidationSeverity
    message: str
    domain: AssistedDiagnosticDomain
    annotation_id: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class AnnotationValidationReport:
    """Ordered document-level validation results for one annotation."""

    diagnostics: tuple[AssistedValidationDiagnostic, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether no annotation error was found."""
        return self.error_count == 0

    @property
    def error_count(self) -> int:
        """Return the number of annotation errors."""
        return sum(
            item.severity is ValidationSeverity.ERROR for item in self.diagnostics
        )

    @property
    def warning_count(self) -> int:
        """Return the number of annotation warnings."""
        return sum(
            item.severity is ValidationSeverity.WARNING for item in self.diagnostics
        )


@dataclass(frozen=True, slots=True)
class ConstructionConfigValidationReport:
    """Ordered defensive validation results for construction controls."""

    diagnostics: tuple[AssistedValidationDiagnostic, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether no configuration error was found."""
        return self.error_count == 0

    @property
    def error_count(self) -> int:
        """Return the number of configuration errors."""
        return sum(
            item.severity is ValidationSeverity.ERROR for item in self.diagnostics
        )


@dataclass(frozen=True, slots=True)
class AssistedInputValidationReport:
    """Independent and cross-document assisted validation results."""

    annotation_report: AnnotationValidationReport
    config_report: ConstructionConfigValidationReport
    compatibility_diagnostics: tuple[AssistedValidationDiagnostic, ...]

    @property
    def diagnostics(self) -> tuple[AssistedValidationDiagnostic, ...]:
        """Return annotation, configuration, then compatibility findings."""
        return (
            self.annotation_report.diagnostics
            + self.config_report.diagnostics
            + self.compatibility_diagnostics
        )

    @property
    def is_valid(self) -> bool:
        """Return whether every independent and compatibility check passes."""
        return (
            self.annotation_report.is_valid
            and self.config_report.is_valid
            and not any(
                item.severity is ValidationSeverity.ERROR
                for item in self.compatibility_diagnostics
            )
        )

    @property
    def error_count(self) -> int:
        """Return the total error count across all three domains."""
        return sum(
            item.severity is ValidationSeverity.ERROR for item in self.diagnostics
        )


def validate_scene_annotation(
    annotation: SceneAnnotation,
    *,
    maximum_hierarchy_depth: int = DEFAULT_MAXIMUM_HIERARCHY_DEPTH,
) -> AnnotationValidationReport:
    """Validate document relationships in deterministic structural order."""
    _positive_integer(maximum_hierarchy_depth, "maximum_hierarchy_depth")
    if not isinstance(annotation, SceneAnnotation):
        raise TypeError("annotation must be a SceneAnnotation")
    diagnostics: list[AssistedValidationDiagnostic] = []
    if annotation.annotation_schema_version != ANNOTATION_SCHEMA_VERSION:
        _add(
            diagnostics,
            "unsupported_annotation_schema_version",
            f"Supported annotation schema is {ANNOTATION_SCHEMA_VERSION!r}.",
            AssistedDiagnosticDomain.ANNOTATION,
            path="$.annotation_schema_version",
        )
    if not annotation.scene_id.strip():
        _add(
            diagnostics,
            "empty_scene_id",
            "Scene identifier must be nonempty.",
            AssistedDiagnosticDomain.ANNOTATION,
            path="$.scene_id",
        )
    if not annotation.source_image.image_id.strip():
        _add(
            diagnostics,
            "empty_image_id",
            "Image identifier must be nonempty.",
            AssistedDiagnosticDomain.ANNOTATION,
            path="$.source_image.image_id",
        )
    if annotation.coordinate_system != NORMALIZED_IMAGE_COORDINATE_SYSTEM:
        _add(
            diagnostics,
            "unsupported_coordinate_system",
            "Only normalized_image_uv is supported.",
            AssistedDiagnosticDomain.ANNOTATION,
            path="$.coordinate_system",
        )

    first_ids: dict[str, str] = {}
    for kind, values, field in (
        ("region", annotation.regions, "region_id"),
        ("instance", annotation.instances, "instance_id"),
        ("repeat_group", annotation.repeat_groups, "repeat_group_id"),
    ):
        collection = {
            "region": "regions",
            "instance": "instances",
            "repeat_group": "repeat_groups",
        }[kind]
        for index, item in enumerate(values):
            identifier = getattr(item, field)
            path = f"$.{collection}[{index}].{field}"
            previous = first_ids.get(identifier)
            if previous is not None:
                _add(
                    diagnostics,
                    "duplicate_global_annotation_id",
                    f"Identifier {identifier!r} was first used at {previous}.",
                    AssistedDiagnosticDomain.ANNOTATION,
                    annotation_id=identifier,
                    path=path,
                )
            else:
                first_ids[identifier] = path

    region_by_id = {item.region_id: item for item in annotation.regions}
    region_index = {
        item.region_id: index for index, item in enumerate(annotation.regions)
    }
    for index, region in enumerate(annotation.regions):
        parent = region.parent_region_id
        if parent is not None and parent not in region_by_id:
            _add(
                diagnostics,
                "missing_parent_region",
                f"Parent region {parent!r} does not exist.",
                AssistedDiagnosticDomain.ANNOTATION,
                annotation_id=region.region_id,
                path=f"$.regions[{index}].parent_region_id",
            )
    _validate_hierarchy(
        annotation.regions,
        region_by_id,
        region_index,
        maximum_hierarchy_depth,
        diagnostics,
    )
    for index, instance in enumerate(annotation.instances):
        parent = instance.parent_region_id
        if parent is not None and parent not in region_by_id:
            _add(
                diagnostics,
                "missing_instance_parent_region",
                f"Instance parent region {parent!r} does not exist.",
                AssistedDiagnosticDomain.ANNOTATION,
                annotation_id=instance.instance_id,
                path=f"$.instances[{index}].parent_region_id",
            )

    instance_by_id = {item.instance_id: item for item in annotation.instances}
    membership: dict[str, list[str]] = {}
    for group_index, group in enumerate(annotation.repeat_groups):
        resolved: list[InstanceAnnotation] = []
        for member_index, member_id in enumerate(group.member_instance_ids):
            membership.setdefault(member_id, []).append(group.repeat_group_id)
            instance = instance_by_id.get(member_id)
            if instance is None:
                _add(
                    diagnostics,
                    "missing_repeat_member",
                    f"Repeat member {member_id!r} does not reference an instance.",
                    AssistedDiagnosticDomain.ANNOTATION,
                    annotation_id=group.repeat_group_id,
                    path=(
                        f"$.repeat_groups[{group_index}]"
                        f".member_instance_ids[{member_index}]"
                    ),
                )
            else:
                resolved.append(instance)
        _validate_repeat_consistency(
            group,
            group_index,
            resolved,
            diagnostics,
        )

    for index, instance in enumerate(annotation.instances):
        groups = membership.get(instance.instance_id, [])
        if len(groups) > 1:
            _add(
                diagnostics,
                "instance_in_multiple_repeat_groups",
                f"Instance appears in multiple groups: {', '.join(groups)}.",
                AssistedDiagnosticDomain.ANNOTATION,
                annotation_id=instance.instance_id,
                path=f"$.instances[{index}].repeat_group_id",
            )
        declared = instance.repeat_group_id
        actual = groups[0] if len(groups) == 1 else None
        if declared != actual:
            _add(
                diagnostics,
                "repeat_membership_mismatch",
                f"Declared group {declared!r} does not match membership {actual!r}.",
                AssistedDiagnosticDomain.ANNOTATION,
                annotation_id=instance.instance_id,
                path=f"$.instances[{index}].repeat_group_id",
            )

    for index, region in enumerate(annotation.regions):
        _validate_region_defensively(region, index, diagnostics)
    for index, instance in enumerate(annotation.instances):
        _validate_shape_defensively(
            instance.shape,
            instance.instance_id,
            f"$.instances[{index}].shape",
            diagnostics,
        )
    return AnnotationValidationReport(tuple(diagnostics))


def validate_construction_config(
    config: ConstructionConfig,
) -> ConstructionConfigValidationReport:
    """Defensively validate one already typed construction configuration."""
    if not isinstance(config, ConstructionConfig):
        raise TypeError("config must be a ConstructionConfig")
    diagnostics: list[AssistedValidationDiagnostic] = []
    if config.config_schema_version != CONSTRUCTION_CONFIG_SCHEMA_VERSION:
        _add(
            diagnostics,
            "unsupported_config_schema_version",
            f"Supported config schema is {CONSTRUCTION_CONFIG_SCHEMA_VERSION!r}.",
            AssistedDiagnosticDomain.CONFIGURATION,
            path="$.config_schema_version",
        )
    if config.projection_model is not ProjectionModel.NORMALIZED_ORTHOGRAPHIC_PROXY:
        _add(
            diagnostics,
            "unsupported_projection_model",
            "Only normalized_orthographic_proxy is supported.",
            AssistedDiagnosticDomain.CONFIGURATION,
            path="$.projection_model",
        )
    expected = (
        DepthZone.FOREGROUND,
        DepthZone.MIDGROUND,
        DepthZone.BACKGROUND,
    )
    if tuple(item.depth_zone for item in config.depth_zone_intervals) != expected:
        _add(
            diagnostics,
            "invalid_depth_zone_intervals",
            "Exactly three ordered depth-zone intervals are required.",
            AssistedDiagnosticDomain.CONFIGURATION,
            path="$.depth_zone_intervals",
        )
    return ConstructionConfigValidationReport(tuple(diagnostics))


def validate_assisted_input(
    annotation: SceneAnnotation,
    config: ConstructionConfig,
) -> AssistedInputValidationReport:
    """Validate annotation, configuration, and their compatibility."""
    if not isinstance(annotation, SceneAnnotation):
        raise TypeError("annotation must be a SceneAnnotation")
    if not isinstance(config, ConstructionConfig):
        raise TypeError("config must be a ConstructionConfig")
    annotation_report = validate_scene_annotation(annotation)
    config_report = validate_construction_config(config)
    diagnostics: list[AssistedValidationDiagnostic] = []
    zones = {item.depth_zone for item in config.depth_zone_intervals}
    region_by_id = {item.region_id: item for item in annotation.regions}

    for collection_name, values in (
        ("regions", annotation.regions),
        ("instances", annotation.instances),
    ):
        for index, item in enumerate(values):
            identifier = (
                item.region_id
                if isinstance(item, RegionAnnotation)
                else item.instance_id
            )
            if item.depth_zone not in zones:
                _add(
                    diagnostics,
                    "unconfigured_depth_zone",
                    f"Depth zone {item.depth_zone.value!r} has no interval.",
                    AssistedDiagnosticDomain.COMPATIBILITY,
                    annotation_id=identifier,
                    path=f"$.annotation.{collection_name}[{index}].depth_zone",
                )
            bounds = item.shape.bounding_rectangle
            minimum = config.minimum_normalized_region_extent
            if bounds.width < minimum or bounds.height < minimum:
                _add(
                    diagnostics,
                    "shape_below_minimum_extent",
                    f"Shape extent must be at least {minimum:g} on both axes.",
                    AssistedDiagnosticDomain.COMPATIBILITY,
                    annotation_id=identifier,
                    path=f"$.annotation.{collection_name}[{index}].shape",
                )

    for index, region in enumerate(annotation.regions):
        if region.parent_region_id in region_by_id:
            parent = region_by_id[region.parent_region_id]
            if parent.depth_zone is not region.depth_zone:
                _add(
                    diagnostics,
                    "incompatible_parent_child_depth_zone",
                    "Parent and child regions must use the same depth zone.",
                    AssistedDiagnosticDomain.COMPATIBILITY,
                    annotation_id=region.region_id,
                    path=f"$.annotation.regions[{index}].depth_zone",
                )
        if (
            config.axis_policy is ConstructionAxisPolicy.HINTS_REQUIRED
            and region.role is AnnotationRole.STRUCTURAL_REGION
            and region.split_axis_hint is None
        ):
            _add(
                diagnostics,
                "missing_required_split_axis_hint",
                "Structural regions require a supplied split-axis hint.",
                AssistedDiagnosticDomain.COMPATIBILITY,
                annotation_id=region.region_id,
                path=f"$.annotation.regions[{index}].split_axis_hint",
            )
    for index, instance in enumerate(annotation.instances):
        if instance.parent_region_id in region_by_id:
            parent = region_by_id[instance.parent_region_id]
            if parent.depth_zone is not instance.depth_zone:
                _add(
                    diagnostics,
                    "incompatible_instance_parent_depth_zone",
                    "Instance and parent region must use the same depth zone.",
                    AssistedDiagnosticDomain.COMPATIBILITY,
                    annotation_id=instance.instance_id,
                    path=f"$.annotation.instances[{index}].depth_zone",
                )
    return AssistedInputValidationReport(
        annotation_report=annotation_report,
        config_report=config_report,
        compatibility_diagnostics=tuple(diagnostics),
    )


def _validate_hierarchy(
    regions: tuple[RegionAnnotation, ...],
    region_by_id: dict[str, RegionAnnotation],
    region_index: dict[str, int],
    maximum_depth: int,
    diagnostics: list[AssistedValidationDiagnostic],
) -> None:
    reported_cycles: set[frozenset[str]] = set()
    for region in regions:
        chain: list[str] = []
        positions: dict[str, int] = {}
        current: RegionAnnotation | None = region
        while current is not None:
            if current.region_id in positions:
                cycle = frozenset(chain[positions[current.region_id] :])
                if cycle not in reported_cycles:
                    reported_cycles.add(cycle)
                    index = region_index[current.region_id]
                    _add(
                        diagnostics,
                        "region_hierarchy_cycle",
                        "Region hierarchy contains a parent cycle.",
                        AssistedDiagnosticDomain.ANNOTATION,
                        annotation_id=current.region_id,
                        path=f"$.regions[{index}].parent_region_id",
                    )
                break
            positions[current.region_id] = len(chain)
            chain.append(current.region_id)
            if len(chain) > maximum_depth:
                index = region_index[region.region_id]
                _add(
                    diagnostics,
                    "maximum_hierarchy_depth_exceeded",
                    f"Hierarchy depth exceeds configured maximum {maximum_depth}.",
                    AssistedDiagnosticDomain.ANNOTATION,
                    annotation_id=region.region_id,
                    path=f"$.regions[{index}].parent_region_id",
                )
                break
            parent_id = current.parent_region_id
            current = region_by_id.get(parent_id) if parent_id else None


def _validate_repeat_consistency(
    group: object,
    group_index: int,
    resolved: list[InstanceAnnotation],
    diagnostics: list[AssistedValidationDiagnostic],
) -> None:
    if len(resolved) < 2:
        return
    first = resolved[0]
    checks = (
        (
            "repeat_semantic_class_mismatch",
            "semantic_class",
            "Repeat members must share one semantic class.",
        ),
        (
            "repeat_depth_zone_mismatch",
            "depth_zone",
            "Repeat members must share one depth zone.",
        ),
        (
            "repeat_geometry_mismatch",
            "terminal_geometry",
            "Repeat members must share one terminal geometry type.",
        ),
    )
    for code, attribute, message in checks:
        if any(
            getattr(item, attribute) != getattr(first, attribute)
            for item in resolved[1:]
        ):
            _add(
                diagnostics,
                code,
                message,
                AssistedDiagnosticDomain.ANNOTATION,
                annotation_id=group.repeat_group_id,
                path=f"$.repeat_groups[{group_index}].member_instance_ids",
            )
    if group.semantic_class is not None and any(
        item.semantic_class != group.semantic_class for item in resolved
    ):
        _add(
            diagnostics,
            "repeat_group_semantic_class_mismatch",
            "Group semantic class must match every member.",
            AssistedDiagnosticDomain.ANNOTATION,
            annotation_id=group.repeat_group_id,
            path=f"$.repeat_groups[{group_index}].semantic_class",
        )


def _validate_region_defensively(
    region: RegionAnnotation,
    index: int,
    diagnostics: list[AssistedValidationDiagnostic],
) -> None:
    if (
        region.role is AnnotationRole.TERMINAL_REGION
        and region.terminal_geometry is None
    ):
        _add(
            diagnostics,
            "terminal_region_missing_geometry",
            "Terminal regions must provide terminal geometry.",
            AssistedDiagnosticDomain.ANNOTATION,
            annotation_id=region.region_id,
            path=f"$.regions[{index}].terminal_geometry",
        )
    if (
        region.role is AnnotationRole.OPEN_SPACE
        and region.terminal_geometry is not GeometryType.EMPTY
    ):
        _add(
            diagnostics,
            "open_space_geometry_not_empty",
            "Open-space regions must use empty geometry.",
            AssistedDiagnosticDomain.ANNOTATION,
            annotation_id=region.region_id,
            path=f"$.regions[{index}].terminal_geometry",
        )
    _validate_shape_defensively(
        region.shape,
        region.region_id,
        f"$.regions[{index}].shape",
        diagnostics,
    )


def _validate_shape_defensively(
    shape: object,
    identifier: str,
    path: str,
    diagnostics: list[AssistedValidationDiagnostic],
) -> None:
    if not isinstance(shape, (NormalizedRectangle, NormalizedPolygon)):
        _add(
            diagnostics,
            "invalid_annotation_shape",
            "Shape must be a normalized rectangle or polygon.",
            AssistedDiagnosticDomain.ANNOTATION,
            annotation_id=identifier,
            path=path,
        )
        return
    if shape.area <= 0:
        _add(
            diagnostics,
            "zero_area_annotation_shape",
            "Shape must have positive absolute area.",
            AssistedDiagnosticDomain.ANNOTATION,
            annotation_id=identifier,
            path=path,
        )


def _add(
    diagnostics: list[AssistedValidationDiagnostic],
    code: str,
    message: str,
    domain: AssistedDiagnosticDomain,
    *,
    annotation_id: str | None = None,
    path: str | None = None,
) -> None:
    diagnostics.append(
        AssistedValidationDiagnostic(
            code=code,
            severity=ValidationSeverity.ERROR,
            message=message,
            domain=domain,
            annotation_id=annotation_id,
            path=path,
        )
    )


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value
