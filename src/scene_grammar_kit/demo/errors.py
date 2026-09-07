"""Domain errors for the integrated Phase 1 demonstration."""


class DemoError(RuntimeError):
    """Base class for expected demo failures."""


class DemoConfigurationError(DemoError):
    """Raised when a demo configuration is invalid."""


class DemoBuildError(DemoError):
    """Raised when the integrated bundle cannot be built."""


class DemoPersistenceError(DemoError):
    """Raised when a canonical demo artifact cannot be persisted."""
