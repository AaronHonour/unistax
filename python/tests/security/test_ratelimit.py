"""Tests for rate limiting implementation."""

import time

import pytest

from unistax.ratelimit import (
    InMemoryStorage,
    RateLimiter,
    RateLimitExceeded,
    RateLimitInfo,
)


@pytest.mark.unit
@pytest.mark.ratelimit
class TestRateLimiter:
    """Test rate limiter functionality."""

    def test_basic_rate_limiting(self):
        """Test basic rate limiting."""
        limiter = RateLimiter(limit=5, window=60)

        # First 5 requests should succeed
        for _ in range(5):
            assert limiter.is_allowed("user:0") is True

        # 6th request for the same key should fail
        assert limiter.is_allowed("user:0") is False

        # Other keys are tracked independently
        assert limiter.is_allowed("user:1") is True

    def test_rate_limit_exceeded_exception(self):
        """Test rate limit exceeded exception."""
        limiter = RateLimiter(limit=3, window=60)

        # First 3 requests should succeed
        for _ in range(3):
            info = limiter.check_limit("user:test")
            assert isinstance(info, RateLimitInfo)

        # 4th request should raise exception
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check_limit("user:test")

        assert exc_info.value.key == "user:test"
        assert exc_info.value.limit == 3
        assert exc_info.value.window == 60

    def test_rate_limit_info(self):
        """Test rate limit info tracking."""
        limiter = RateLimiter(limit=5, window=60)

        # First request
        info = limiter.check_limit("user:test")
        assert info.limit == 5
        assert info.remaining == 4  # 1 used, 4 remaining
        assert info.reset > 0

        # Second request
        info = limiter.check_limit("user:test")
        assert info.remaining == 3  # 2 used, 3 remaining

    def test_independent_keys(self):
        """Test that different keys have independent limits."""
        limiter = RateLimiter(limit=2, window=60)

        # User 1: 2 requests (at limit)
        limiter.check_limit("user:1")
        limiter.check_limit("user:1")

        # User 1: should fail
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit("user:1")

        # User 2: should still work (independent limit)
        info = limiter.check_limit("user:2")
        assert info.remaining == 1

    def test_window_reset(self):
        """Test that rate limit resets after window expires."""
        limiter = RateLimiter(limit=2, window=1)  # 1 second window

        # Use up the limit
        limiter.check_limit("user:test")
        limiter.check_limit("user:test")

        # Should fail now
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit("user:test")

        # Wait for window to expire
        time.sleep(2)

        # Should work again
        info = limiter.check_limit("user:test")
        assert info.remaining >= 0

    def test_reset_limit(self):
        """Test manually resetting a limit."""
        limiter = RateLimiter(limit=2, window=60)

        # Use up the limit
        limiter.check_limit("user:test")
        limiter.check_limit("user:test")

        # Should fail
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit("user:test")

        # Reset the limit
        limiter.reset("user:test")

        # Should work again
        info = limiter.check_limit("user:test")
        assert info.remaining == 1

    def test_clear_all_limits(self):
        """Test clearing all limits."""
        limiter = RateLimiter(limit=1, window=60)

        # Hit limits for multiple keys
        limiter.check_limit("user:1")
        limiter.check_limit("user:2")
        limiter.check_limit("user:3")

        # All should be at limit
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit("user:1")

        # Clear all
        limiter.clear_all()

        # All should work again
        limiter.check_limit("user:1")
        limiter.check_limit("user:2")
        limiter.check_limit("user:3")

    def test_get_limit_info(self):
        """Test getting limit info without incrementing."""
        limiter = RateLimiter(limit=5, window=60)

        # Make one request
        limiter.check_limit("user:test")

        # Get info multiple times without incrementing
        for _ in range(3):
            info = limiter.get_limit_info("user:test")
            assert info.remaining == 4  # Should stay at 4

    def test_tokens_parameter(self):
        """Test consuming multiple tokens at once."""
        limiter = RateLimiter(limit=10, window=60)

        # Consume 3 tokens
        assert limiter.is_allowed("user:test", tokens=3) is True

        # Check remaining
        info = limiter.get_limit_info("user:test")
        assert info.remaining == 7  # 10 - 3 = 7

        # Consume 5 more tokens
        assert limiter.is_allowed("user:test", tokens=5) is True

        # Check remaining
        info = limiter.get_limit_info("user:test")
        assert info.remaining == 2  # 7 - 5 = 2

    def test_retry_after(self):
        """Test retry_after calculation."""
        limiter = RateLimiter(limit=2, window=60)

        # Use up the limit
        limiter.check_limit("user:test")
        limiter.check_limit("user:test")

        # Get limit info
        info = limiter.get_limit_info("user:test")

        # retry_after should be set and positive
        assert info.retry_after is not None
        assert info.retry_after > 0
        assert info.retry_after <= 60


@pytest.mark.unit
@pytest.mark.ratelimit
class TestInMemoryStorage:
    """Test in-memory storage backend."""

    def test_increment(self):
        """Test incrementing a counter."""
        storage = InMemoryStorage()

        count1 = storage.increment("key1", window=60)
        assert count1 == 1

        count2 = storage.increment("key1", window=60)
        assert count2 == 2

    def test_get(self):
        """Test getting a counter value."""
        storage = InMemoryStorage()

        storage.increment("key1", window=60)
        storage.increment("key1", window=60)

        count = storage.get("key1")
        assert count == 2

    def test_delete(self):
        """Test deleting a counter."""
        storage = InMemoryStorage()

        storage.increment("key1", window=60)
        assert storage.get("key1") == 1

        storage.delete("key1")
        assert storage.get("key1") == 0

    def test_clear(self):
        """Test clearing all counters."""
        storage = InMemoryStorage()

        storage.increment("key1", window=60)
        storage.increment("key2", window=60)
        storage.increment("key3", window=60)

        storage.clear()

        assert storage.get("key1") == 0
        assert storage.get("key2") == 0
        assert storage.get("key3") == 0

    def test_independent_keys(self):
        """Test that different keys are independent."""
        storage = InMemoryStorage()

        storage.increment("key1", window=60)
        storage.increment("key1", window=60)
        storage.increment("key2", window=60)

        assert storage.get("key1") == 2
        assert storage.get("key2") == 1


@pytest.mark.unit
@pytest.mark.ratelimit
class TestRateLimitExceeded:
    """Test rate limit exceeded exception."""

    def test_exception_attributes(self):
        """Test exception has correct attributes."""
        exc = RateLimitExceeded(
            message="Rate limit exceeded",
            key="user:123",
            limit=10,
            window=60,
            retry_after=45,
        )

        assert str(exc) == "Rate limit exceeded"
        assert exc.key == "user:123"
        assert exc.limit == 10
        assert exc.window == 60
        assert exc.retry_after == 45

    def test_exception_default_message(self):
        """Test exception default message."""
        exc = RateLimitExceeded()
        assert str(exc) == "Rate limit exceeded"


@pytest.mark.unit
@pytest.mark.ratelimit
class TestRateLimitInfo:
    """Test rate limit info dataclass."""

    def test_rate_limit_info_creation(self):
        """Test creating rate limit info."""
        info = RateLimitInfo(
            limit=100,
            remaining=75,
            reset=1234567890,
            retry_after=30,
        )

        assert info.limit == 100
        assert info.remaining == 75
        assert info.reset == 1234567890
        assert info.retry_after == 30

    def test_rate_limit_info_without_retry_after(self):
        """Test creating rate limit info without retry_after."""
        info = RateLimitInfo(
            limit=100,
            remaining=75,
            reset=1234567890,
        )

        assert info.retry_after is None


@pytest.mark.integration
@pytest.mark.ratelimit
class TestRateLimiterIntegration:
    """Integration tests for rate limiter."""

    def test_concurrent_requests_simulation(self):
        """Test simulating concurrent requests."""
        limiter = RateLimiter(limit=10, window=60)

        # Simulate 20 concurrent requests
        successful = 0
        failed = 0

        for _ in range(20):
            if limiter.is_allowed("user:test"):
                successful += 1
            else:
                failed += 1

        assert successful == 10
        assert failed == 10

    def test_multiple_users_different_limits(self):
        """Test multiple users with independent limits."""
        limiter = RateLimiter(limit=5, window=60)

        users = [f"user:{i}" for i in range(10)]

        # Each user should be able to make 5 requests
        for user in users:
            for _ in range(5):
                assert limiter.is_allowed(user) is True

            # 6th request should fail
            assert limiter.is_allowed(user) is False

    def test_rate_limiting_with_decay(self):
        """Test rate limiting with time-based decay."""
        limiter = RateLimiter(limit=3, window=2)  # 3 requests per 2 seconds

        # Use up the limit
        for _ in range(3):
            limiter.check_limit("user:test")

        # Should fail
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit("user:test")

        # Wait 1 second (half the window)
        time.sleep(1)

        # Should still fail (window not fully expired)
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit("user:test")

        # Wait another 1.5 seconds (total 2.5 seconds)
        time.sleep(1.5)

        # Should work now (window expired)
        limiter.check_limit("user:test")
