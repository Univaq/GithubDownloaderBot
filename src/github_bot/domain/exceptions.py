"""Domain-specific errors independent of frameworks and storage."""


class DomainError(Exception):
    """Base class for expected business-rule failures."""


class QueueFullError(DomainError):
    """Raised when the queue cannot accept another job."""


class JobNotFoundError(DomainError):
    """Raised when a job does not exist or is not accessible."""


class InvalidJobStateError(DomainError):
    """Raised when an operation is invalid for a job's current state."""
