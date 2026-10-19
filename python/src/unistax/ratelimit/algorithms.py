"""Rate limiting algorithms."""

import time
from collections import deque


class TokenBucket:
    """Token bucket algorithm for rate limiting.

    Allows bursts while maintaining average rate.
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        """Initialize token bucket.

        Args:
            capacity: Maximum number of tokens
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens: float = capacity
        self.last_refill = time.time()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """Consume tokens.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens available
        """
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class SlidingWindow:
    """Sliding window algorithm for rate limiting.

    More accurate than fixed window, prevents burst at window boundaries.
    """

    def __init__(self, limit: int, window_size: int) -> None:
        """Initialize sliding window.

        Args:
            limit: Maximum requests in window
            window_size: Window size in seconds
        """
        self.limit = limit
        self.window_size = window_size
        self.requests: deque[float] = deque()

    def is_allowed(self, tokens: int = 1) -> bool:
        """Check if request is allowed.

        Args:
            tokens: Number of requests this call counts as

        Returns:
            True if allowed
        """
        now = time.time()
        cutoff = now - self.window_size

        # Remove old requests
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()

        if len(self.requests) + tokens <= self.limit:
            self.requests.extend([now] * tokens)
            return True

        return False
