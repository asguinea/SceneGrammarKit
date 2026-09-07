"""Domain errors for deterministic constrained split induction."""

from scene_grammar_kit.assisted.errors import AssistedError


class SplitInductionError(AssistedError):
    """Base error for split-induction operations."""


class SplitInductionValidationError(SplitInductionError, ValueError):
    """Raised when inputs or an induced structure violate policy."""


class SplitInductionSerializationError(SplitInductionError):
    """Raised when an induction report cannot be serialized or parsed."""


class SplitInductionIOError(SplitInductionError, OSError):
    """Raised for split-induction persistence failures."""


class SplitInductionFileExistsError(
    SplitInductionIOError,
    FileExistsError,
):
    """Raised when protected output would be overwritten."""


class SplitInductionWriteError(SplitInductionIOError):
    """Raised when an induction artifact cannot be written safely."""
