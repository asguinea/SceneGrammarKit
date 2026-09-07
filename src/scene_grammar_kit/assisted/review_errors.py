"""Domain errors for assisted-annotation review workflows."""

from scene_grammar_kit.assisted.errors import AssistedError


class AnnotationReviewError(AssistedError):
    """Base class for annotation-review failures."""


class SourceImageError(AnnotationReviewError):
    """Base class for source-image resolution and verification failures."""


class SourceImagePathError(SourceImageError):
    """Raised when a source-image path escapes its annotation directory."""


class SourceImageNotFoundError(SourceImageError, FileNotFoundError):
    """Raised when the referenced source image does not exist."""


class SourceImageReadError(SourceImageError):
    """Raised when source-image bytes cannot be read."""


class SourceImageFormatError(SourceImageError):
    """Raised when a source image is corrupt or uses an unsupported format."""


class SourceImageDimensionError(SourceImageError):
    """Raised when decoded dimensions differ from the declared dimensions."""


class SourceImageHashError(SourceImageError):
    """Raised when a supplied source-image digest does not match."""


class AnnotationOverlayConfigError(AnnotationReviewError, ValueError):
    """Raised when overlay configuration is invalid."""


class AnnotationOverlayRenderError(AnnotationReviewError):
    """Raised when deterministic overlay rendering fails."""


class AnnotationReviewValidationError(AnnotationReviewError):
    """Raised when assisted annotation/config validation fails."""


class AnnotationReviewSerializationError(AnnotationReviewError):
    """Raised when a review artifact cannot be serialized."""


class AnnotationReviewIOError(AnnotationReviewError, OSError):
    """Base class for review-artifact persistence failures."""


class AnnotationReviewFileExistsError(
    AnnotationReviewIOError,
    FileExistsError,
):
    """Raised when review persistence would silently overwrite data."""


class AnnotationReviewWriteError(AnnotationReviewIOError):
    """Raised when a review artifact cannot be written atomically."""
