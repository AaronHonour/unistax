"""JWT token handling using industry-standard PyJWT library.

This module provides secure JWT token encoding and decoding using the PyJWT
library, which is actively maintained and security-audited.

Security Features:
- Industry-standard implementation (PyJWT)
- Support for multiple algorithms (HS256, HS384, HS512, RS256, RS384, RS512, ES256, ES384, ES512)
- Proper signature verification
- Expiration (exp) claim validation
- Not-before (nbf) claim validation
- Issued-at (iat) claim validation
- Audience (aud) claim validation
- Issuer (iss) claim validation
- Algorithm verification (prevents algorithm confusion attacks)
"""

import logging
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Check if PyJWT is available
try:
    import jwt
    from jwt.exceptions import (
        DecodeError,
        ExpiredSignatureError,
        InvalidAudienceError,
        InvalidIssuerError,
        InvalidSignatureError,
        InvalidTokenError,
    )

    PYJWT_AVAILABLE = True
except ImportError:
    PYJWT_AVAILABLE = False
    logger.warning(
        "PyJWT not installed. JWT functionality requires PyJWT. "
        "Install with: pip install 'unistax[security]'"
    )


class JWTError(Exception):
    """Base exception for JWT errors."""

    pass


class JWTDecodeError(JWTError):
    """Raised when JWT token cannot be decoded."""

    pass


class JWTExpiredError(JWTError):
    """Raised when JWT token has expired."""

    pass


class JWTInvalidSignatureError(JWTError):
    """Raised when JWT signature is invalid."""

    pass


class JWTInvalidAudienceError(JWTError):
    """Raised when JWT audience is invalid."""

    pass


class JWTInvalidIssuerError(JWTError):
    """Raised when JWT issuer is invalid."""

    pass


class JWT:
    """Secure JWT token encoder/decoder using PyJWT.

    Supports multiple algorithms and provides comprehensive claim validation.

    Security Notes:
        - Always use strong secrets (min 256 bits for HS256)
        - Use RS256 or ES256 for public/private key scenarios
        - Set expiration times appropriate for your use case
        - Validate audience and issuer claims when possible
        - Never disable signature verification in production

    Examples:
        >>> # Symmetric key (HS256)
        >>> jwt_manager = JWT(secret="your-256-bit-secret", algorithm="HS256")
        >>> token = jwt_manager.encode({"user_id": 123, "role": "admin"})
        >>> claims = jwt_manager.decode(token)
        >>>
        >>> # With audience and issuer validation
        >>> jwt_manager = JWT(
        ...     secret="your-secret",
        ...     audience="myapp",
        ...     issuer="auth-service"
        ... )
        >>> token = jwt_manager.encode({"user_id": 123})
        >>> claims = jwt_manager.decode(token)  # Validates aud and iss
        >>>
        >>> # Asymmetric key (RS256)
        >>> with open("private_key.pem") as f:
        ...     private_key = f.read()
        >>> with open("public_key.pem") as f:
        ...     public_key = f.read()
        >>> jwt_manager = JWT(
        ...     secret=private_key,
        ...     public_key=public_key,
        ...     algorithm="RS256"
        ... )
        >>> token = jwt_manager.encode({"user_id": 123})
        >>> claims = jwt_manager.decode(token)
    """

    def __init__(
        self,
        secret: str,
        algorithm: str = "HS256",
        expiration: int = 3600,
        audience: str | list[str] | None = None,
        issuer: str | None = None,
        public_key: str | None = None,
        leeway: int = 0,
    ) -> None:
        """Initialize JWT manager.

        Args:
            secret: Secret key for signing tokens (or private key for RS*/ES* algorithms)
            algorithm: Signing algorithm. Options:
                - HS256, HS384, HS512 (HMAC with SHA-256/384/512)
                - RS256, RS384, RS512 (RSA with SHA-256/384/512)
                - ES256, ES384, ES512 (ECDSA with SHA-256/384/512)
                Default: HS256 (recommended for symmetric keys)
            expiration: Default expiration time in seconds (default: 3600 = 1 hour)
            audience: Expected audience (aud claim). Can be string or list.
                     Will be validated during decode if set.
            issuer: Expected issuer (iss claim). Will be validated during decode if set.
            public_key: Public key for verification (required for RS*/ES* algorithms).
                       For HS* algorithms, leave as None (uses secret for verification).
            leeway: Time leeway in seconds for exp, nbf, and iat claims validation.
                   Useful for clock skew between systems (default: 0)

        Raises:
            ImportError: If PyJWT is not installed
            ValueError: If algorithm requires public_key but not provided

        Security Recommendations:
            - Use secrets of at least 256 bits (32 characters) for HS256
            - Use 384 bits (48 chars) for HS384, 512 bits (64 chars) for HS512
            - For RS*/ES* algorithms, use proper key management and key rotation
            - Set expiration times as short as practical for your use case
            - Always validate audience and issuer in production
        """
        if not PYJWT_AVAILABLE:
            raise ImportError(
                "PyJWT is required for JWT functionality. "
                "Install with: pip install 'unistax[security]'"
            )

        self.secret = secret
        self.algorithm = algorithm
        self.expiration = expiration
        self.audience = audience
        self.issuer = issuer
        self.public_key = public_key or secret  # Use secret for symmetric algorithms
        self.leeway = leeway

        # Validate algorithm and key configuration
        if algorithm.startswith(("RS", "ES", "PS")) and public_key is None:
            warnings.warn(
                f"Algorithm {algorithm} requires a public key for verification. "
                f"Using secret as verification key may cause errors.",
                UserWarning,
                stacklevel=2,
            )

        # Validate secret strength for HMAC algorithms
        if algorithm.startswith("HS"):
            min_length = {"HS256": 32, "HS384": 48, "HS512": 64}.get(algorithm, 32)
            if len(secret) < min_length:
                logger.warning(
                    "JWT secret is too short for %s (%d < %d characters)",
                    algorithm,
                    len(secret),
                    min_length,
                )
                warnings.warn(
                    f"Secret for {algorithm} should be at least {min_length} characters. "
                    f"Current length: {len(secret)}. Weak secrets are vulnerable to brute force.",
                    UserWarning,
                    stacklevel=2,
                )

    def encode(
        self,
        payload: dict[str, Any],
        exp: int | None = None,
        nbf: datetime | None = None,
        additional_headers: dict[str, Any] | None = None,
    ) -> str:
        """Encode payload to JWT token.

        Args:
            payload: Data to encode (claims)
            exp: Expiration time in seconds from now (overrides default)
            nbf: Not-before time (token not valid before this time)
            additional_headers: Additional headers to include in JWT header

        Returns:
            JWT token string

        Raises:
            JWTError: If encoding fails

        Example:
            >>> jwt_manager = JWT(secret="my-secret")
            >>> # Expires in 1 hour (default)
            >>> token = jwt_manager.encode({"user_id": 123})
            >>>
            >>> # Custom expiration (30 minutes)
            >>> token = jwt_manager.encode({"user_id": 123}, exp=1800)
            >>>
            >>> # Not valid before 5 minutes from now
            >>> from datetime import datetime, timedelta, timezone
            >>> nbf_time = datetime.now(timezone.utc) + timedelta(minutes=5)
            >>> token = jwt_manager.encode({"user_id": 123}, nbf=nbf_time)
        """
        try:
            # Create a copy to avoid mutating input
            claims = dict(payload)

            # Add standard claims
            now = datetime.now(timezone.utc)
            claims["iat"] = now

            # Add expiration
            if exp is None:
                exp = self.expiration
            if exp is not None:
                claims["exp"] = now + timedelta(seconds=exp)

            # Add not-before if provided
            if nbf is not None:
                claims["nbf"] = nbf

            # Add audience if configured
            if self.audience is not None:
                claims["aud"] = self.audience

            # Add issuer if configured
            if self.issuer is not None:
                claims["iss"] = self.issuer

            # Encode token
            token = jwt.encode(
                claims,
                self.secret,
                algorithm=self.algorithm,
                headers=additional_headers,
            )

            return token

        except Exception as e:
            logger.error("Failed to encode JWT token: %s", e, exc_info=True)
            raise JWTError(f"Failed to encode JWT token: {e}") from e

    def decode(
        self,
        token: str,
        verify: bool = True,
        audience: str | list[str] | None = None,
        issuer: str | None = None,
        algorithms: list[str] | None = None,
    ) -> dict[str, Any]:
        """Decode and verify JWT token.

        Args:
            token: JWT token string to decode
            verify: Whether to verify signature and claims (default: True).
                   NEVER set to False in production!
            audience: Override audience for this decode operation.
                     Uses instance audience if not provided.
            issuer: Override issuer for this decode operation.
                   Uses instance issuer if not provided.
            algorithms: List of allowed algorithms. Defaults to [self.algorithm].
                       Prevents algorithm confusion attacks.

        Returns:
            Decoded payload (claims)

        Raises:
            JWTDecodeError: If token format is invalid
            JWTExpiredError: If token has expired
            JWTInvalidSignatureError: If signature verification fails
            JWTInvalidAudienceError: If audience validation fails
            JWTInvalidIssuerError: If issuer validation fails
            JWTError: For other JWT-related errors

        Security Notes:
            - NEVER set verify=False in production
            - Always validate audience and issuer when possible
            - Always specify allowed algorithms to prevent algorithm confusion

        Example:
            >>> jwt_manager = JWT(secret="my-secret", audience="myapp", issuer="auth")
            >>> try:
            ...     claims = jwt_manager.decode(token)
            ...     user_id = claims["user_id"]
            ... except JWTExpiredError:
            ...     # Handle expired token (e.g., refresh)
            ...     pass
            ... except JWTInvalidSignatureError:
            ...     # Handle forged token (security alert!)
            ...     pass
        """
        if not verify:
            warnings.warn(
                "JWT signature verification is disabled! This is EXTREMELY INSECURE. "
                "NEVER disable verification in production.",
                UserWarning,
                stacklevel=2,
            )

        try:
            # Use instance values if not overridden
            aud = audience if audience is not None else self.audience
            iss = issuer if issuer is not None else self.issuer
            algs = algorithms if algorithms is not None else [self.algorithm]

            # Decode and verify token
            options = {"verify_signature": verify}
            if not verify:
                # Disable all verification if verify=False
                options.update(
                    {
                        "verify_exp": False,
                        "verify_nbf": False,
                        "verify_iat": False,
                        "verify_aud": False,
                        "verify_iss": False,
                    }
                )

            claims = jwt.decode(
                token,
                self.public_key,
                algorithms=algs,
                audience=aud,
                issuer=iss,
                leeway=self.leeway,
                options=options,
            )

            return claims  # type: ignore[no-any-return]

        except ExpiredSignatureError as e:
            logger.debug("JWT token expired: %s", e)
            raise JWTExpiredError("Token has expired") from e

        except InvalidSignatureError as e:
            logger.warning("JWT signature verification failed: %s", e)
            raise JWTInvalidSignatureError("Invalid token signature") from e

        except InvalidAudienceError as e:
            logger.warning("JWT audience validation failed: %s", e)
            raise JWTInvalidAudienceError(f"Invalid audience: {e}") from e

        except InvalidIssuerError as e:
            logger.warning("JWT issuer validation failed: %s", e)
            raise JWTInvalidIssuerError(f"Invalid issuer: {e}") from e

        except DecodeError as e:
            logger.warning("JWT decode error: %s", e)
            raise JWTDecodeError(f"Failed to decode token: {e}") from e

        except InvalidTokenError as e:
            logger.warning("Invalid JWT token: %s", e)
            raise JWTError(f"Invalid token: {e}") from e

        except Exception as e:
            logger.error("Unexpected error decoding JWT: %s", e, exc_info=True)
            raise JWTError(f"Failed to decode token: {e}") from e

    def decode_unverified(self, token: str) -> dict[str, Any]:
        """Decode token without verification (INSECURE - use with caution).

        This method decodes the token without verifying the signature or claims.
        Use only for:
        - Inspecting token contents for debugging
        - Extracting claims before verification
        - Checking token structure

        NEVER use this for authentication or authorization decisions!

        Args:
            token: JWT token string

        Returns:
            Decoded payload (unverified)

        Raises:
            JWTDecodeError: If token format is invalid

        Warning:
            This method does NOT verify:
            - Signature validity
            - Expiration time
            - Audience
            - Issuer
            - Any other claims

        Example:
            >>> jwt_manager = JWT(secret="my-secret")
            >>> # Inspect token without verification (debugging only!)
            >>> claims = jwt_manager.decode_unverified(token)
            >>> print(f"Token issued for user: {claims.get('user_id')}")
        """
        try:
            return jwt.decode(token, options={"verify_signature": False})  # type: ignore[no-any-return]
        except Exception as e:
            raise JWTDecodeError(f"Failed to decode token: {e}") from e

    def get_unverified_header(self, token: str) -> dict[str, Any]:
        """Get JWT header without verification.

        Useful for extracting algorithm, key ID (kid), or other header information
        before verification.

        Args:
            token: JWT token string

        Returns:
            JWT header dictionary

        Raises:
            JWTDecodeError: If token format is invalid

        Example:
            >>> jwt_manager = JWT(secret="my-secret")
            >>> header = jwt_manager.get_unverified_header(token)
            >>> algorithm = header["alg"]
            >>> key_id = header.get("kid")  # Key ID if present
        """
        try:
            return jwt.get_unverified_header(token)  # type: ignore[no-any-return]
        except Exception as e:
            raise JWTDecodeError(f"Failed to get token header: {e}") from e
