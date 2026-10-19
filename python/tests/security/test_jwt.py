"""Tests for JWT implementation."""

import time

import pytest

from unistax.security.jwt import (
    JWT,
    JWTDecodeError,
    JWTError,
    JWTExpiredError,
    JWTInvalidAudienceError,
    JWTInvalidIssuerError,
    JWTInvalidSignatureError,
)


@pytest.mark.unit
@pytest.mark.jwt
class TestJWT:
    """Test JWT token generation and validation."""

    def test_basic_token_generation(self):
        """Test basic JWT token generation."""
        jwt = JWT(secret="test-secret-key-minimum-32-chars-long", algorithm="HS256")
        payload = {"user_id": 123, "role": "admin"}

        token = jwt.encode(payload)

        assert isinstance(token, str)
        assert len(token) > 0
        assert token.count(".") == 2  # JWT has 3 parts

    def test_basic_token_validation(self):
        """Test basic JWT token validation."""
        jwt = JWT(secret="test-secret-key-minimum-32-chars-long", algorithm="HS256")
        payload = {"user_id": 123, "role": "admin"}

        token = jwt.encode(payload)
        decoded = jwt.decode(token)

        assert decoded["user_id"] == 123
        assert decoded["role"] == "admin"

    def test_token_expiration(self):
        """Test JWT token expiration."""
        jwt = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
            expiration=1,  # 1 second
        )
        payload = {"user_id": 123}

        token = jwt.encode(payload)

        # Should work immediately
        decoded = jwt.decode(token)
        assert decoded["user_id"] == 123

        # Wait for expiration
        time.sleep(2)

        # Should raise JWTExpiredError
        with pytest.raises(JWTExpiredError):
            jwt.decode(token)

    def test_invalid_signature(self):
        """Test JWT with invalid signature."""
        jwt1 = JWT(secret="secret-key-1-minimum-32-chars-long", algorithm="HS256")
        jwt2 = JWT(secret="secret-key-2-minimum-32-chars-long", algorithm="HS256")

        payload = {"user_id": 123}
        token = jwt1.encode(payload)

        # Different secret should fail
        with pytest.raises(JWTInvalidSignatureError):
            jwt2.decode(token)

    def test_invalid_token_format(self):
        """Test JWT with invalid token format."""
        jwt = JWT(secret="test-secret-key-minimum-32-chars-long", algorithm="HS256")

        with pytest.raises(JWTDecodeError):
            jwt.decode("invalid.token")

        with pytest.raises(JWTDecodeError):
            jwt.decode("not-a-jwt-token")

    def test_audience_validation(self):
        """Test JWT audience validation."""
        jwt = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
            audience="myapp",
        )
        payload = {"user_id": 123}

        token = jwt.encode(payload)
        decoded = jwt.decode(token)
        assert decoded["user_id"] == 123
        assert decoded["aud"] == "myapp"

    def test_invalid_audience(self):
        """Test JWT with invalid audience."""
        jwt_encoder = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
            audience="app1",
        )
        jwt_decoder = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
            audience="app2",
        )

        token = jwt_encoder.encode({"user_id": 123})

        with pytest.raises(JWTInvalidAudienceError):
            jwt_decoder.decode(token)

    def test_issuer_validation(self):
        """Test JWT issuer validation."""
        jwt = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
            issuer="auth-service",
        )
        payload = {"user_id": 123}

        token = jwt.encode(payload)
        decoded = jwt.decode(token)
        assert decoded["user_id"] == 123
        assert decoded["iss"] == "auth-service"

    def test_invalid_issuer(self):
        """Test JWT with invalid issuer."""
        jwt_encoder = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
            issuer="service1",
        )
        jwt_decoder = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
            issuer="service2",
        )

        token = jwt_encoder.encode({"user_id": 123})

        with pytest.raises(JWTInvalidIssuerError):
            jwt_decoder.decode(token)

    def test_weak_secret_warning(self, caplog):
        """Test warning for weak secret."""
        _ = JWT(secret="short", algorithm="HS256")  # Too short
        assert any("too short" in record.message.lower() for record in caplog.records)

    def test_multiple_algorithms(self):
        """Test different JWT algorithms."""
        algorithms = ["HS256", "HS384", "HS512"]

        for alg in algorithms:
            jwt = JWT(
                secret=f"test-secret-key-minimum-32-chars-long-{alg}",
                algorithm=alg,
            )
            payload = {"user_id": 123, "alg": alg}

            token = jwt.encode(payload)
            decoded = jwt.decode(token)

            assert decoded["user_id"] == 123
            assert decoded["alg"] == alg

    def test_not_before_claim(self):
        """Test JWT not-before (nbf) claim."""
        jwt = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
        )

        # Create token that's not valid yet (nbf = now + 2 seconds)
        payload = {"user_id": 123, "nbf": int(time.time()) + 2}
        token = jwt.encode(payload)

        # Should fail immediately
        with pytest.raises(JWTError):
            jwt.decode(token)

        # Wait for nbf to pass
        time.sleep(3)

        # Should work now
        decoded = jwt.decode(token)
        assert decoded["user_id"] == 123

    def test_issued_at_claim(self):
        """Test JWT issued-at (iat) claim."""
        jwt = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
        )
        payload = {"user_id": 123}

        before = int(time.time())
        token = jwt.encode(payload)
        after = int(time.time())

        decoded = jwt.decode(token)

        assert "iat" in decoded
        assert before <= decoded["iat"] <= after

    def test_custom_claims(self):
        """Test JWT with custom claims."""
        jwt = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
        )
        payload = {
            "user_id": 123,
            "username": "testuser",
            "role": "admin",
            "permissions": ["read", "write", "delete"],
            "metadata": {"department": "IT", "level": 5},
        }

        token = jwt.encode(payload)
        decoded = jwt.decode(token)

        assert decoded["user_id"] == 123
        assert decoded["username"] == "testuser"
        assert decoded["role"] == "admin"
        assert decoded["permissions"] == ["read", "write", "delete"]
        assert decoded["metadata"]["department"] == "IT"
        assert decoded["metadata"]["level"] == 5

    def test_leeway_for_clock_skew(self):
        """Test JWT leeway for clock skew."""
        jwt = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
            expiration=1,  # 1 second
            leeway=2,  # 2 seconds leeway
        )
        payload = {"user_id": 123}

        token = jwt.encode(payload)

        # Wait for token to expire
        time.sleep(2)

        # Should still work due to leeway
        decoded = jwt.decode(token)
        assert decoded["user_id"] == 123

    def test_token_without_expiration(self):
        """Test JWT token without expiration."""
        jwt = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
            expiration=None,  # No expiration
        )
        payload = {"user_id": 123}

        token = jwt.encode(payload)

        # Should work even after some time
        time.sleep(1)
        decoded = jwt.decode(token)
        assert decoded["user_id"] == 123

    def test_empty_payload(self):
        """Test JWT with empty payload."""
        jwt = JWT(
            secret="test-secret-key-minimum-32-chars-long",
            algorithm="HS256",
        )
        payload = {}

        token = jwt.encode(payload)
        decoded = jwt.decode(token)

        # Should have at least iat claim
        assert "iat" in decoded
