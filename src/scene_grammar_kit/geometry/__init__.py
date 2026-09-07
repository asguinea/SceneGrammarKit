"""Public deterministic SceneGrammarKit geometry execution and export API."""

from scene_grammar_kit.geometry.bounds import (
    axis_extent,
    axis_interval,
    bounds_contain,
    bounds_have_positive_extent,
    repeat_bound_at,
    repeat_bounds,
    replace_axis_interval,
    split_bounds_by_weights,
)
from scene_grammar_kit.geometry.errors import (
    ExecutionDepthError,
    GeometryBoundsError,
    GeometryError,
    GeometryExportError,
    GeometryFileExistsError,
    GeometryIOError,
    GeometrySerializationError,
    GeometryValidationError,
    GeometryWriteError,
    PrimitiveLimitError,
    RepeatFitError,
)
from scene_grammar_kit.geometry.executor import (
    DEFAULT_MAXIMUM_EXECUTION_DEPTH,
    DEFAULT_MAXIMUM_PRIMITIVES,
    execute_grammar,
)
from scene_grammar_kit.geometry.export import (
    GeometryExportResult,
    export_scene,
)
from scene_grammar_kit.geometry.models import (
    EXECUTION_POLICY_VERSION,
    ExecutedScene,
    ExecutionReport,
    PrimitiveBounds,
    SemanticPrimitive,
)
from scene_grammar_kit.geometry.serialization import (
    executed_scene_to_canonical_json,
    execution_report_to_canonical_json,
    save_executed_scene,
    save_execution_report,
)

__all__ = [
    "DEFAULT_MAXIMUM_EXECUTION_DEPTH",
    "DEFAULT_MAXIMUM_PRIMITIVES",
    "EXECUTION_POLICY_VERSION",
    "ExecutedScene",
    "ExecutionDepthError",
    "ExecutionReport",
    "GeometryBoundsError",
    "GeometryError",
    "GeometryExportError",
    "GeometryExportResult",
    "GeometryFileExistsError",
    "GeometryIOError",
    "GeometrySerializationError",
    "GeometryValidationError",
    "GeometryWriteError",
    "PrimitiveBounds",
    "PrimitiveLimitError",
    "RepeatFitError",
    "SemanticPrimitive",
    "axis_extent",
    "axis_interval",
    "bounds_contain",
    "bounds_have_positive_extent",
    "execute_grammar",
    "executed_scene_to_canonical_json",
    "execution_report_to_canonical_json",
    "export_scene",
    "repeat_bound_at",
    "repeat_bounds",
    "replace_axis_interval",
    "save_executed_scene",
    "save_execution_report",
    "split_bounds_by_weights",
]
