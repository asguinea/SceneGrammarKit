"""Domain errors for the integrated assisted-scene constructor."""

from scene_grammar_kit.assisted.errors import AssistedError


class AssistedConstructorError(AssistedError):
    """Base constructor-domain error."""


class AssistedConstructorValidationError(AssistedConstructorError, ValueError):
    """Raised when constructor inputs or results violate policy."""


class AssistedConstructorSerializationError(AssistedConstructorError):
    """Raised for canonical constructor serialization failures."""


class AssistedConstructorIOError(AssistedConstructorError, OSError):
    """Raised for constructor persistence failures."""


class AssistedConstructorFileExistsError(AssistedConstructorIOError, FileExistsError):
    """Raised when protected constructor output would be overwritten."""


class AssistedConstructorWriteError(AssistedConstructorIOError):
    """Raised when a constructor artifact cannot be written safely."""
