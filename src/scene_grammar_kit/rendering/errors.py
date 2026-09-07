"""Domain exceptions for deterministic semantic rendering."""


class RenderingError(RuntimeError):
    """Base class for all rendering-domain failures."""


class RenderConfigError(RenderingError):
    """Raised when a render configuration is invalid."""


class CameraError(RenderingError):
    """Raised when a camera preset or basis is invalid."""


class ProjectionError(RenderingError):
    """Raised when scene projection or framing cannot be computed."""


class RenderSerializationError(RenderingError):
    """Raised when a render report cannot be serialized."""


class RenderPersistenceError(RenderingError):
    """Base class for render-output persistence failures."""


class RenderFileExistsError(RenderPersistenceError):
    """Raised when a render target exists without overwrite permission."""


class RenderWriteError(RenderPersistenceError):
    """Raised when a render output cannot be written safely."""
