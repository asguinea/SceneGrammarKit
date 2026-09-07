"""Domain errors for deterministic repeat-group induction."""

from scene_grammar_kit.assisted.errors import AssistedError


class RepeatInductionError(AssistedError):
    """Base repeat-induction error."""


class RepeatInductionValidationError(RepeatInductionError, ValueError):
    """Raised when repeat inputs or results violate policy."""


class RepeatInductionSerializationError(RepeatInductionError):
    """Raised for canonical repeat-report serialization failures."""


class RepeatInductionIOError(RepeatInductionError, OSError):
    """Raised for repeat-induction persistence failures."""


class RepeatInductionFileExistsError(RepeatInductionIOError, FileExistsError):
    """Raised when protected output would be overwritten."""


class RepeatInductionWriteError(RepeatInductionIOError):
    """Raised when a repeat artifact cannot be written safely."""
