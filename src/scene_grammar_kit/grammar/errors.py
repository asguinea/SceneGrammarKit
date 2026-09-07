"""Domain exceptions for SceneGrammarKit grammar models and persistence."""


class GrammarError(Exception):
    """Base class for all grammar-domain errors."""


class GrammarValidationError(GrammarError, ValueError):
    """Raised when grammar data does not satisfy the schema."""


class GrammarSerializationError(GrammarError):
    """Base class for JSON serialization and parsing errors."""


class GrammarJSONError(GrammarSerializationError):
    """Raised when input is not valid JSON."""


class GrammarIOError(GrammarError, OSError):
    """Base class for grammar file-system errors."""


class GrammarFileNotFoundError(GrammarIOError, FileNotFoundError):
    """Raised when a requested grammar file does not exist."""


class GrammarFileExistsError(GrammarIOError, FileExistsError):
    """Raised when saving would overwrite a file without permission."""


class GrammarReadError(GrammarIOError):
    """Raised when a grammar file cannot be read as UTF-8 text."""


class GrammarWriteError(GrammarIOError):
    """Raised when a grammar file cannot be written safely."""


class GrammarInspectionError(GrammarError):
    """Raised when an invalid or unsafe grammar cannot be inspected."""


class GrammarExpansionLimitError(GrammarInspectionError):
    """Raised when conceptual repeat expansion exceeds its safety limit."""
