"""CSRF protection implementation.

Implements double-submit cookie pattern for stateless CSRF protection.
"""

import hashlib
import hmac
import logging
import secrets
import time
from typing import Any

from .exceptions import CSRFTokenExpired, CSRFTokenInvalid, CSRFTokenMissing

logger = logging.getLogger(__name__)


class CSRFProtect:
    """CSRF protection using double-submit cookie pattern.

    Security Features:
        - Cryptographically secure token generation
        - Double-submit cookie pattern (stateless)
        - Token expiration support
        - HMAC-based token validation
        - Constant-time comparison to prevent timing attacks
        - Configurable token lifetime

    The double-submit cookie pattern:
        1. Server generates a random token and sends it in a cookie
        2. Client includes the token in a header/form field for state-changing requests
        3. Server validates that cookie token matches header/form token
        4. Since attackers can't read cookies from other domains (same-origin policy),
           they can't include the correct token in their forged requests

    Examples:
        >>> # Basic usage
        >>> csrf = CSRFProtect(secret="your-secret-key")
        >>> token = csrf.generate_token()
        >>> csrf.validate_token(token, token)  # Cookie token, header token
        >>>
        >>> # With expiration
        >>> csrf = CSRFProtect(secret="your-secret-key", token_expiration=3600)
        >>> token = csrf.generate_token()
        >>> # ... 2 hours later ...
        >>> csrf.validate_token(token, token)  # Raises CSRFTokenExpired
        >>>
        >>> # Handle validation
        >>> try:
        ...     csrf.validate_token(cookie_token, header_token)
        ... except CSRFTokenMissing:
        ...     return {"error": "CSRF token missing"}
        ... except CSRFTokenInvalid:
        ...     return {"error": "CSRF token invalid"}
        ... except CSRFTokenExpired:
        ...     return {"error": "CSRF token expired"}
    """

    def __init__(
        self,
        secret: str,
        token_expiration: int | None = None,
        token_length: int = 32,
    ) -> None:
        """Initialize CSRF protection.

        Args:
            secret: Secret key for token generation (should be app secret)
            token_expiration: Token lifetime in seconds (None = no expiration)
            token_length: Length of random token in bytes (default: 32)

        Security Notes:
            - Use a strong secret key (at least 32 bytes)
            - Set token_expiration for additional security (e.g., 3600 = 1 hour)
            - Use the same secret across all server instances
            - Rotate secret periodically (requires session invalidation)
        """
        if len(secret) < 32:
            logger.warning(
                "CSRF secret key is too short (%d bytes). "
                "Recommended minimum: 32 bytes for security.",
                len(secret),
            )

        self.secret = secret.encode() if isinstance(secret, str) else secret
        self.token_expiration = token_expiration
        self.token_length = token_length

        logger.info(
            "CSRFProtect initialized: token_length=%d, expiration=%s",
            token_length,
            f"{token_expiration}s" if token_expiration else "none",
        )

    def generate_token(self, user_id: str | None = None) -> str:
        """Generate a new CSRF token.

        Args:
            user_id: Optional user identifier to bind token to user

        Returns:
            CSRF token string (base64-encoded)

        Security Note:
            Uses secrets.token_urlsafe() for cryptographically secure randomness.
            Optionally includes timestamp for expiration checking.

        Example:
            >>> csrf = CSRFProtect(secret="my-secret")
            >>> token = csrf.generate_token()
            >>> print(token)  # e.g., "VGhpcyBpcyBhIHRva2Vu.1699887654.abc123"
        """
        # Generate random token
        random_token = secrets.token_urlsafe(self.token_length)

        # Add timestamp if expiration is enabled
        if self.token_expiration:
            timestamp = str(int(time.time()))
            # Create HMAC signature: HMAC(secret, random_token || timestamp || user_id)
            message = f"{random_token}.{timestamp}"
            if user_id:
                message += f".{user_id}"

            signature = hmac.new(
                self.secret,
                message.encode(),
                hashlib.sha256,
            ).hexdigest()[:16]

            token = f"{random_token}.{timestamp}.{signature}"
        else:
            # Create HMAC signature: HMAC(secret, random_token || user_id)
            message = random_token
            if user_id:
                message += f".{user_id}"

            signature = hmac.new(
                self.secret,
                message.encode(),
                hashlib.sha256,
            ).hexdigest()[:16]

            token = f"{random_token}.{signature}"

        logger.debug("Generated CSRF token: %s...", token[:20])
        return token

    def validate_token(
        self,
        cookie_token: str | None,
        header_token: str | None,
        user_id: str | None = None,
    ) -> None:
        """Validate CSRF token using double-submit pattern.

        Args:
            cookie_token: Token from cookie
            header_token: Token from header/form field
            user_id: Optional user identifier (must match token)

        Raises:
            CSRFTokenMissing: If either token is missing
            CSRFTokenInvalid: If tokens don't match or signature is invalid
            CSRFTokenExpired: If token has expired

        Security Notes:
            - Uses constant-time comparison to prevent timing attacks
            - Validates HMAC signature to prevent token forgery
            - Checks expiration if enabled
            - Validates user binding if provided

        Example:
            >>> csrf = CSRFProtect(secret="my-secret")
            >>> token = csrf.generate_token()
            >>> csrf.validate_token(token, token)  # Success
            >>> csrf.validate_token(token, "wrong")  # Raises CSRFTokenInvalid
        """
        # Check if tokens are present
        if not cookie_token:
            logger.warning("CSRF validation failed: cookie token missing")
            raise CSRFTokenMissing("CSRF token missing from cookie")

        if not header_token:
            logger.warning("CSRF validation failed: header token missing")
            raise CSRFTokenMissing("CSRF token missing from header/form")

        # Tokens must match (double-submit pattern)
        if not secrets.compare_digest(cookie_token, header_token):
            logger.warning("CSRF validation failed: tokens don't match (cookie != header)")
            raise CSRFTokenInvalid("CSRF tokens don't match")

        # Parse token components
        parts = cookie_token.split(".")
        if self.token_expiration:
            # Format: random.timestamp.signature
            if len(parts) != 3:
                logger.warning(
                    "CSRF validation failed: invalid token format (expected 3 parts, got %d)",
                    len(parts),
                )
                raise CSRFTokenInvalid("Invalid CSRF token format")

            random_token, timestamp_str, provided_signature = parts

            # Verify timestamp format
            try:
                timestamp = int(timestamp_str)
            except ValueError as e:
                logger.warning("CSRF validation failed: invalid timestamp format")
                raise CSRFTokenInvalid("Invalid CSRF token timestamp") from e

            # Check expiration
            current_time = int(time.time())
            if current_time - timestamp > self.token_expiration:
                logger.warning(
                    "CSRF validation failed: token expired (age=%ds, max=%ds)",
                    current_time - timestamp,
                    self.token_expiration,
                )
                raise CSRFTokenExpired(f"CSRF token expired ({current_time - timestamp}s old)")

            # Verify HMAC signature
            message = f"{random_token}.{timestamp_str}"
            if user_id:
                message += f".{user_id}"

            expected_signature = hmac.new(
                self.secret,
                message.encode(),
                hashlib.sha256,
            ).hexdigest()[:16]

        else:
            # Format: random.signature
            if len(parts) != 2:
                logger.warning(
                    "CSRF validation failed: invalid token format (expected 2 parts, got %d)",
                    len(parts),
                )
                raise CSRFTokenInvalid("Invalid CSRF token format")

            random_token, provided_signature = parts

            # Verify HMAC signature
            message = random_token
            if user_id:
                message += f".{user_id}"

            expected_signature = hmac.new(
                self.secret,
                message.encode(),
                hashlib.sha256,
            ).hexdigest()[:16]

        # Constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(expected_signature, provided_signature):
            logger.warning("CSRF validation failed: invalid signature")
            raise CSRFTokenInvalid("Invalid CSRF token signature")

        logger.debug("CSRF token validated successfully")

    def extract_token_data(self, token: str) -> dict[str, Any]:
        """Extract metadata from token (for debugging/monitoring).

        Args:
            token: CSRF token

        Returns:
            Dictionary with token metadata (timestamp, age, etc.)

        Example:
            >>> csrf = CSRFProtect(secret="my-secret", token_expiration=3600)
            >>> token = csrf.generate_token()
            >>> data = csrf.extract_token_data(token)
            >>> print(data)
            {'timestamp': 1699887654, 'age_seconds': 123, 'expires_in': 3477}
        """
        parts = token.split(".")

        if self.token_expiration and len(parts) >= 2:
            try:
                timestamp = int(parts[1])
                current_time = int(time.time())
                age = current_time - timestamp
                expires_in = self.token_expiration - age

                return {
                    "timestamp": timestamp,
                    "age_seconds": age,
                    "expires_in": expires_in,
                    "expired": expires_in <= 0,
                }
            except (ValueError, IndexError):
                pass

        return {}
