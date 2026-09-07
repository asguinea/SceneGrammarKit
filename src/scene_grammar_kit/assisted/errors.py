"""Domain exceptions for annotation-assisted input contracts."""


class AssistedError(Exception):
    """Base class for all assisted-input domain errors."""


class AssistedValidationError(AssistedError, ValueError):
    """Raised when assisted model data violates a field-level contract."""


class AnnotationValidationError(AssistedValidationError):
    """Raised for invalid annotation model fields."""


class ConstructionConfigValidationError(AssistedValidationError):
    """Raised for invalid construction-configuration fields."""


class AssistedSerializationError(AssistedError):
    """Base class for assisted JSON serialization and parsing errors."""


class AssistedJSONError(AssistedSerializationError):
    """Raised when assisted input is not strict standard JSON."""


class AssistedIOError(AssistedError, OSError):
    """Base class for assisted-input file-system failures."""


class AssistedFileNotFoundError(AssistedIOError, FileNotFoundError):
    """Raised when an assisted input file does not exist."""


class AssistedFileExistsError(AssistedIOError, FileExistsError):
    """Raised when persistence would silently overwrite a file."""


class AssistedReadError(AssistedIOError):
    """Raised when an assisted input cannot be read as UTF-8."""


class AssistedWriteError(AssistedIOError):
    """Raised when an assisted input cannot be written atomically."""
