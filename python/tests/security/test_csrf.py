"""Tests for CSRF protection implementation."""

import time

import pytest

from unistax.csrf import (
    CSRFProtect,
    CSRFTokenExpired,
    CSRFTokenInvalid,
    CSRFTokenMissing,
)


@pytest.mark.unit
@pytest.mark.csrf
class TestCSRFProtect:
    """Test CSRF protection token generation and validation."""

    def test_token_generation(self):
        """Test basic CSRF token generation."""
        csrf = CSRFProtect(secret="test-secret-key-minimum-32-chars-long")
        token = csrf.generate_token()

        assert isinstance(token, str)
        assert len(token) > 0
        assert "." in token  # Contains signature

    def test_token_validation_success(self):
        """Test successful CSRF token validation."""
        csrf = CSRFProtect(secret="test-secret-key-minimum-32-chars-long")
        token = csrf.generate_token()

        # Double-submit pattern: same token in cookie and header
        csrf.validate_token(cookie_token=token, header_token=token)
        # Should not raise any exception

    def test_token_missing_cookie(self):
        """Test CSRF validation with missing cookie token."""
        csrf = CSRFProtect(secret="test-secret-key-minimum-32-chars-long")

        with pytest.raises(CSRFTokenMissing, match="cookie"):
            csrf.validate_token(cookie_token=None, header_token="some-token")

    def test_token_missing_header(self):
        """Test CSRF validation with missing header token."""
        csrf = CSRFProtect(secret="test-secret-key-minimum-32-chars-long")
        token = csrf.generate_token()

        with pytest.raises(CSRFTokenMissing, match="header"):
            csrf.validate_token(cookie_token=token, header_token=None)

    def test_token_mismatch(self):
        """Test CSRF validation with mismatched tokens."""
        csrf = CSRFProtect(secret="test-secret-key-minimum-32-chars-long")
        token1 = csrf.generate_token()
        token2 = csrf.generate_token()

        with pytest.raises(CSRFTokenInvalid, match="don't match"):
            csrf.validate_token(cookie_token=token1, header_token=token2)

    def test_invalid_signature(self):
        """Test CSRF validation with invalid signature."""
        csrf = CSRFProtect(secret="test-secret-key-minimum-32-chars-long")
        token = csrf.generate_token()

        # Tamper with the token
        parts = token.split(".")
        parts[-1] = "tampered-signature"
        tampered_token = ".".join(parts)

        with pytest.raises(CSRFTokenInvalid, match="signature"):
            csrf.validate_token(cookie_token=tampered_token, header_token=tampered_token)

    def test_token_expiration(self):
        """Test CSRF token expiration."""
        csrf = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_expiration=1,  # 1 second
        )
        token = csrf.generate_token()

        # Should work immediately
        csrf.validate_token(cookie_token=token, header_token=token)

        # Wait for expiration
        time.sleep(2)

        # Should raise CSRFTokenExpired
        with pytest.raises(CSRFTokenExpired, match="expired"):
            csrf.validate_token(cookie_token=token, header_token=token)

    def test_token_without_expiration(self):
        """Test CSRF token without expiration."""
        csrf = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_expiration=None,  # No expiration
        )
        token = csrf.generate_token()

        # Should work even after some time
        time.sleep(1)
        csrf.validate_token(cookie_token=token, header_token=token)

    def test_user_binding(self):
        """Test CSRF token with user binding."""
        csrf = CSRFProtect(secret="test-secret-key-minimum-32-chars-long")

        # Generate token for specific user
        token = csrf.generate_token(user_id="user123")

        # Should validate with same user_id
        csrf.validate_token(cookie_token=token, header_token=token, user_id="user123")

    def test_user_binding_mismatch(self):
        """Test CSRF token with mismatched user binding."""
        csrf = CSRFProtect(secret="test-secret-key-minimum-32-chars-long")

        # Generate token for user123
        token = csrf.generate_token(user_id="user123")

        # Should fail with different user_id
        with pytest.raises(CSRFTokenInvalid, match="signature"):
            csrf.validate_token(cookie_token=token, header_token=token, user_id="user456")

    def test_different_secrets(self):
        """Test CSRF tokens with different secrets."""
        csrf1 = CSRFProtect(secret="secret-key-1-minimum-32-chars-long")
        csrf2 = CSRFProtect(secret="secret-key-2-minimum-32-chars-long")

        token = csrf1.generate_token()

        # Should fail with different secret
        with pytest.raises(CSRFTokenInvalid, match="signature"):
            csrf2.validate_token(cookie_token=token, header_token=token)

    def test_token_length_configuration(self):
        """Test CSRF token length configuration."""
        csrf_short = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_length=16,
        )
        csrf_long = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_length=64,
        )

        token_short = csrf_short.generate_token()
        token_long = csrf_long.generate_token()

        # Longer token should be longer (after URL-safe base64 encoding)
        assert len(token_long) > len(token_short)

    def test_extract_token_data(self):
        """Test extracting metadata from token."""
        csrf = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_expiration=3600,  # 1 hour
        )
        token = csrf.generate_token()

        data = csrf.extract_token_data(token)

        assert "timestamp" in data
        assert "age_seconds" in data
        assert "expires_in" in data
        assert "expired" in data
        assert data["expired"] is False
        assert data["expires_in"] > 0

    def test_extract_token_data_expired(self):
        """Test extracting metadata from expired token."""
        csrf = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_expiration=1,  # 1 second
        )
        token = csrf.generate_token()

        # Wait for expiration
        time.sleep(2)

        data = csrf.extract_token_data(token)

        assert data["expired"] is True
        assert data["expires_in"] <= 0

    def test_invalid_token_format(self):
        """Test CSRF validation with invalid token format."""
        csrf = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_expiration=3600,
        )

        # Too few parts
        with pytest.raises(CSRFTokenInvalid, match="format"):
            csrf.validate_token(cookie_token="invalid", header_token="invalid")

        # Too many parts
        with pytest.raises(CSRFTokenInvalid, match="format"):
            csrf.validate_token(
                cookie_token="a.b.c.d",
                header_token="a.b.c.d",
            )

    def test_invalid_timestamp_format(self):
        """Test CSRF validation with invalid timestamp."""
        csrf = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_expiration=3600,
        )

        # Create token with invalid timestamp
        token = "random.invalid-timestamp.signature"

        with pytest.raises(CSRFTokenInvalid, match="timestamp"):
            csrf.validate_token(cookie_token=token, header_token=token)

    def test_weak_secret_warning(self, caplog):
        """Test warning for weak secret."""
        _ = CSRFProtect(secret="short", token_expiration=None)
        assert any("too short" in record.message.lower() for record in caplog.records)

    def test_multiple_tokens_same_secret(self):
        """Test generating multiple tokens with same secret."""
        csrf = CSRFProtect(secret="test-secret-key-minimum-32-chars-long")

        tokens = [csrf.generate_token() for _ in range(10)]

        # All tokens should be unique
        assert len(set(tokens)) == len(tokens)

        # All tokens should validate
        for token in tokens:
            csrf.validate_token(cookie_token=token, header_token=token)

    def test_token_without_expiration_format(self):
        """Test token format without expiration."""
        csrf = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_expiration=None,
        )
        token = csrf.generate_token()

        parts = token.split(".")

        # Should have 2 parts: random.signature
        assert len(parts) == 2

    def test_token_with_expiration_format(self):
        """Test token format with expiration."""
        csrf = CSRFProtect(
            secret="test-secret-key-minimum-32-chars-long",
            token_expiration=3600,
        )
        token = csrf.generate_token()

        parts = token.split(".")

        # Should have 3 parts: random.timestamp.signature
        assert len(parts) == 3

        # Timestamp should be a valid integer
        timestamp = int(parts[1])
        current_time = int(time.time())
        assert abs(timestamp - current_time) < 2  # Within 2 seconds
