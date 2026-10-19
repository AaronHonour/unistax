"""Password hashing utilities using bcrypt.

SECURITY: This module uses bcrypt for password hashing, which is designed
specifically for password storage with:
- Built-in salting
- Adaptive complexity (resistant to brute-force)
- Industry standard recommended by OWASP
"""

import secrets

try:
    import bcrypt

    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    import hashlib
    import warnings

    warnings.warn(
        "bcrypt not installed. Using insecure SHA256 fallback. " "Install with: pip install bcrypt",
        UserWarning,
        stacklevel=2,
    )


class PasswordHasher:
    """Secure password hashing using bcrypt.

    Uses bcrypt by default, which provides:
    - Automatic salting
    - Configurable computational cost (work factor)
    - Protection against brute-force attacks
    - Resistance to timing attacks

    Falls back to SHA256 if bcrypt is not installed (NOT RECOMMENDED for production).

    Examples:
        >>> hasher = PasswordHasher()
        >>> hashed = hasher.hash("my-password")
        >>> hasher.verify("my-password", hashed)
        True
        >>> hasher.verify("wrong-password", hashed)
        False

    Security Notes:
        - Default rounds=12 provides good security/performance balance
        - Increase rounds as hardware improves (add 1 every ~18 months)
        - Never use rounds < 10 in production
    """

    def __init__(self, rounds: int = 12) -> None:
        """Initialize PasswordHasher.

        Args:
            rounds: bcrypt cost factor (4-31). Default 12 provides ~300ms hashing time.
                   Higher = slower but more secure. Each increment doubles time.
        """
        self.rounds = max(4, min(31, rounds))  # Clamp to valid range
        self.use_bcrypt = BCRYPT_AVAILABLE

    def hash(self, password: str) -> str:
        """Hash password securely.

        Args:
            password: Plain text password

        Returns:
            Hashed password (bcrypt format or fallback format)

        Raises:
            ValueError: If password is empty
        """
        if not password:
            raise ValueError("Password cannot be empty")

        if self.use_bcrypt:
            # bcrypt handles salting automatically
            hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(self.rounds))
            return hashed.decode("utf-8")
        else:
            # INSECURE FALLBACK - only for development
            return self._fallback_hash(password)

    def verify(self, password: str, hashed: str) -> bool:
        """Verify password against hash (timing-attack resistant).

        Args:
            password: Plain text password to verify
            hashed: Previously hashed password

        Returns:
            True if password matches, False otherwise

        Security:
            Uses constant-time comparison to prevent timing attacks
        """
        if not password or not hashed:
            return False

        try:
            if self.use_bcrypt and hashed.startswith("$2"):
                # bcrypt format: $2a$, $2b$, $2x$, $2y$
                return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
            else:
                # Fallback verification
                return self._fallback_verify(password, hashed)
        except (ValueError, AttributeError):
            # Invalid hash format
            return False

    def _fallback_hash(self, password: str) -> str:
        """INSECURE fallback hash using SHA256 (DO NOT USE IN PRODUCTION).

        Args:
            password: Plain text password

        Returns:
            SHA256 hash with salt
        """
        salt = secrets.token_hex(32)
        h = hashlib.sha256()
        h.update((password + salt).encode("utf-8"))
        return f"sha256${salt}${h.hexdigest()}"

    def _fallback_verify(self, password: str, hashed: str) -> bool:
        """Verify fallback SHA256 hash.

        Args:
            password: Plain text password
            hashed: SHA256 hash

        Returns:
            True if password matches
        """
        try:
            algorithm, salt, pwd_hash = hashed.split("$", 2)
            if algorithm != "sha256":
                return False

            h = hashlib.sha256()
            h.update((password + salt).encode("utf-8"))
            computed = h.hexdigest()

            # Timing-safe comparison
            return secrets.compare_digest(computed, pwd_hash)
        except ValueError:
            return False
