"""Domain exceptions for canonical scene-example manifests and builds."""


class SceneExampleError(RuntimeError):
    """Base class for expected scene-example failures."""


class ManifestError(SceneExampleError):
    """Base class for manifest parsing and validation failures."""


class ManifestFileNotFoundError(ManifestError):
    """Raised when a requested manifest file does not exist."""


class ManifestReadError(ManifestError):
    """Raised when a manifest cannot be read as UTF-8."""


class ManifestJSONError(ManifestError):
    """Raised when manifest JSON is malformed."""


class ManifestValidationError(ManifestError):
    """Raised when manifest content violates policy version 0.1."""


class ManifestSerializationError(ManifestError):
    """Raised when a manifest or build report cannot be serialized."""


class SceneExampleBuildError(SceneExampleError):
    """Raised when a canonical scene-example build fails."""


class SceneExamplePersistenceError(SceneExampleError):
    """Raised when scene-example artifacts cannot be saved safely."""


class SceneExampleFileExistsError(SceneExamplePersistenceError):
    """Raised when output exists without explicit overwrite permission."""
