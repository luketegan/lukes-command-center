class TrackerError(Exception):
    """Base tracker error."""


class BudgetExhausted(TrackerError):
    """A configured runtime budget was exhausted."""


class TransientServiceError(TrackerError):
    """A temporary failure that may be retried."""


class TerminalServiceError(TrackerError):
    """A permanent failure that must not be retried."""


class UnsafeUrlError(TrackerError):
    """A URL failed the network safety policy."""

