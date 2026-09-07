"""Domain exceptions for deterministic SceneGrammarKit geometry execution."""


class GeometryError(Exception):
    """Base class for geometry execution, persistence, and export errors."""


class GeometryValidationError(GeometryError, ValueError):
    """Raised when a grammar is not safe to execute."""


class GeometryBoundsError(GeometryError, ValueError):
    """Raised when a bounds operation would create invalid geometry."""


class RepeatFitError(GeometryBoundsError):
    """Raised when repeat spacing leaves no positive element extent."""


class ExecutionDepthError(GeometryError):
    """Raised when execution exceeds its configured depth."""


class PrimitiveLimitError(GeometryError):
    """Raised before execution would exceed its primitive safety limit."""


class GeometrySerializationError(GeometryError):
    """Raised when executed geometry cannot be serialized."""


class GeometryIOError(GeometryError, OSError):
    """Base class for geometry persistence errors."""


class GeometryFileExistsError(GeometryIOError, FileExistsError):
    """Raised when persistence would overwrite a file without permission."""


class GeometryWriteError(GeometryIOError):
    """Raised when geometry output cannot be written safely."""


class GeometryExportError(GeometryError):
    """Raised when headless geometry export fails."""
