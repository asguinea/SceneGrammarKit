"""Domain exceptions for immutable grammar editing."""


class EditError(RuntimeError):
    """Base class for editing-domain failures."""


class EditTargetNotFoundError(EditError):
    """Raised when an operation target node ID does not exist."""


class EditTargetTypeError(EditError):
    """Raised when a target node has the wrong symbolic type."""


class EditChildNotFoundError(EditError):
    """Raised when a split child is not an immediate child."""


class InvalidEditValueError(EditError):
    """Raised when an operation value violates its field policy."""


class EditValidationError(EditError):
    """Raised when symbolic validation rejects an editing transaction."""


class EditExecutionError(EditError):
    """Raised when execution verification rejects an edited grammar."""


class EditPersistenceError(EditError):
    """Base class for edit-result persistence failures."""


class EditFileExistsError(EditPersistenceError):
    """Raised when an edit output exists without overwrite permission."""


class EditWriteError(EditPersistenceError):
    """Raised when an edit output cannot be written safely."""


class EditSerializationError(EditPersistenceError):
    """Raised when an operation or report cannot be serialized."""
