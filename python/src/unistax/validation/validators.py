"""Validation utilities."""

import re
from collections.abc import Callable
from typing import Any


class ValidationRules:
    """Collection of validation rules."""

    @staticmethod
    def email(value: str) -> bool:
        """Validate email format."""
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(pattern, value))

    @staticmethod
    def url(value: str) -> bool:
        """Validate URL format."""
        pattern = r"^https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b"
        return bool(re.match(pattern, value))

    @staticmethod
    def phone(value: str) -> bool:
        """Validate phone number format."""
        pattern = r"^\+?1?\d{9,15}$"
        return bool(re.match(pattern, value))

    @staticmethod
    def length(value: str, min_len: int = 0, max_len: float = float("inf")) -> bool:
        """Validate string length."""
        return min_len <= len(value) <= max_len

    @staticmethod
    def range_check(
        value: float, min_val: float = float("-inf"), max_val: float = float("inf")
    ) -> bool:  # noqa: E501
        """Validate numeric range."""
        return min_val <= value <= max_val


class Validator:
    """Base validator class.

    Examples:
        >>> validator = Validator()
        >>> validator.add_rule("email", ValidationRules.email)
        >>> validator.validate({"email": "test@example.com"})
    """

    def __init__(self) -> None:
        """Initialize Validator."""
        self.rules: dict[str, list[tuple[Callable[..., Any], str]]] = {}
        self.errors: dict[str, list[str]] = {}

    def add_rule(
        self, field: str, rule: Callable[..., Any], error_message: str = "Validation failed"
    ) -> None:  # noqa: E501
        """Add validation rule for field."""
        if field not in self.rules:
            self.rules[field] = []
        self.rules[field].append((rule, error_message))

    def validate(self, data: dict[str, Any]) -> bool:
        """Validate data against rules.

        Args:
            data: Data to validate

        Returns:
            True if valid
        """
        self.errors = {}
        is_valid = True

        for field, rules in self.rules.items():
            if field not in data:
                self.errors[field] = ["Field is required"]
                is_valid = False
                continue

            value = data[field]
            for rule, error_msg in rules:
                if not rule(value):
                    if field not in self.errors:
                        self.errors[field] = []
                    self.errors[field].append(error_msg)
                    is_valid = False

        return is_valid

    def get_errors(self) -> dict[str, list[str]]:
        """Get validation errors."""
        return self.errors
