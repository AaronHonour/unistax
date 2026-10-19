"""Retry strategies for HTTP requests."""

from abc import ABC, abstractmethod


class RetryStrategy(ABC):
    """Abstract retry strategy."""

    @abstractmethod
    def should_retry(self, attempt: int, error: Exception) -> bool:
        """Check if should retry."""
        pass

    @abstractmethod
    def get_delay(self, attempt: int) -> float:
        """Get delay before next attempt."""
        pass


class ExponentialBackoff(RetryStrategy):
    """Exponential backoff retry strategy."""

    def __init__(
        self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0
    ) -> None:  # noqa: E501
        """Initialize ExponentialBackoff.

        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def should_retry(self, attempt: int, error: Exception) -> bool:
        """Check if request should be retried.

        Args:
            attempt: Current attempt number
            error: Exception that occurred

        Returns:
            True if should retry
        """
        return attempt < self.max_retries

    def get_delay(self, attempt: int) -> float:
        """Calculate delay before next retry attempt.

        Args:
            attempt: Current attempt number

        Returns:
            Delay in seconds
        """
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        return delay  # type: ignore[no-any-return]
