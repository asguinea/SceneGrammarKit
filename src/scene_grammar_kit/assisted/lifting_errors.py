"""Domain errors for deterministic coarse annotation lifting."""

from scene_grammar_kit.assisted.errors import AssistedError


class LiftingError(AssistedError):
    """Base class for coarse-lifting failures."""


class LiftingValidationError(LiftingError, ValueError):
    """Raised when inputs or lifted values violate the lifting contract."""


class LiftingSerializationError(LiftingError):
    """Raised when lifted artifacts cannot be parsed or serialized."""


class LiftingIOError(LiftingError, OSError):
    """Base class for lifted-artifact persistence failures."""


class LiftingFileExistsError(LiftingIOError, FileExistsError):
    """Raised when lifting persistence would overwrite silently."""


class LiftingWriteError(LiftingIOError):
    """Raised when a lifted artifact cannot be written atomically."""
