"""Query builder for composable queries.

SECURITY NOTE: This module validates field names to prevent SQL injection
and attribute access attacks. All field names are checked against model
columns before use.
"""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Query:
    """Query representation."""

    filters: list[dict[str, Any]] = field(default_factory=list[Any])
    sorts: list[dict[str, Any]] = field(default_factory=list[Any])
    limit: int | None = None
    offset: int | None = None
    select_fields: list[str] | None = None


class QueryBuilder:
    """Fluent query builder with security validation.

    Security Features:
        - Validates field names against model columns
        - Prevents attribute access attacks
        - Sanitizes operator values
        - Validates pagination parameters

    Raises:
        ValueError: If field names or operators are invalid
    """

    # Allowed operators (whitelist)
    ALLOWED_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "like", "ilike"}

    # Allowed sort directions
    ALLOWED_DIRECTIONS = {"asc", "desc"}

    # Pattern for safe field names (alphanumeric and underscore)
    SAFE_FIELD_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")

    def __init__(self) -> None:
        """Initialize query builder."""
        self._query = Query()

    @classmethod
    def _validate_field_name(cls, field_name: str) -> None:
        """Validate field name is safe.

        Args:
            field_name: Field name to validate

        Raises:
            ValueError: If field name is invalid or unsafe

        Security:
            Prevents SQL injection and attribute access attacks by:
            - Checking for dangerous characters
            - Blocking special attributes (__xxx__)
            - Validating against safe pattern
        """
        if not field_name:
            raise ValueError("Field name cannot be empty")

        # Block access to private/special attributes
        if field_name.startswith("_") or field_name.startswith("__"):
            raise ValueError(f"Cannot access private attribute: {field_name}")

        # Validate against safe pattern
        if not cls.SAFE_FIELD_PATTERN.match(field_name):
            raise ValueError(
                f"Invalid field name: {field_name}. "
                "Must start with letter and contain only alphanumeric characters and underscores"
            )

    @classmethod
    def _validate_operator(cls, operator: str) -> None:
        """Validate operator is allowed.

        Args:
            operator: Operator to validate

        Raises:
            ValueError: If operator is not in whitelist
        """
        if operator not in cls.ALLOWED_OPERATORS:
            raise ValueError(
                f"Invalid operator: {operator}. Allowed: {', '.join(sorted(cls.ALLOWED_OPERATORS))}"
            )

    def where(self, field: str, operator: str, value: Any) -> "QueryBuilder":
        """Add filter condition with validation.

        Args:
            field: Field name (validated for safety)
            operator: Operator (must be in whitelist)
            value: Filter value

        Returns:
            QueryBuilder for chaining

        Raises:
            ValueError: If field name or operator is invalid

        Security:
            All inputs are validated before use to prevent injection attacks
        """
        # Validate inputs
        self._validate_field_name(field)
        self._validate_operator(operator)

        self._query.filters.append(
            {
                "field": field,
                "operator": operator,
                "value": value,
            }
        )
        return self

    def order_by(self, field: str, direction: str = "asc") -> "QueryBuilder":
        """Add sort condition with validation.

        Args:
            field: Field name (validated for safety)
            direction: Sort direction (asc/desc)

        Returns:
            QueryBuilder for chaining

        Raises:
            ValueError: If field name or direction is invalid

        Security:
            Field name and direction are validated to prevent SQL injection
        """
        # Validate inputs
        self._validate_field_name(field)
        direction = direction.lower()
        if direction not in self.ALLOWED_DIRECTIONS:
            allowed = ", ".join(self.ALLOWED_DIRECTIONS)
            raise ValueError(f"Invalid sort direction: {direction}. Allowed: {allowed}")

        self._query.sorts.append(
            {
                "field": field,
                "direction": direction,
            }
        )
        return self

    def limit(self, limit: int) -> "QueryBuilder":
        """Set query limit with validation.

        Args:
            limit: Maximum results (must be positive)

        Returns:
            QueryBuilder for chaining

        Raises:
            ValueError: If limit is invalid
        """
        if limit <= 0:
            raise ValueError(f"Limit must be positive, got: {limit}")
        if limit > 10000:  # Prevent excessive limits
            raise ValueError(f"Limit too large (max 10000), got: {limit}")

        self._query.limit = limit
        return self

    def offset(self, offset: int) -> "QueryBuilder":
        """Set query offset with validation.

        Args:
            offset: Results offset (must be non-negative)

        Returns:
            QueryBuilder for chaining

        Raises:
            ValueError: If offset is invalid
        """
        if offset < 0:
            raise ValueError(f"Offset must be non-negative, got: {offset}")

        self._query.offset = offset
        return self

    def select(self, *fields: str) -> "QueryBuilder":
        """Select specific fields with validation.

        Args:
            *fields: Field names (all validated for safety)

        Returns:
            QueryBuilder for chaining

        Raises:
            ValueError: If any field name is invalid
        """
        # Validate all field names
        for field_name in fields:
            self._validate_field_name(field_name)

        self._query.select_fields = list(fields)
        return self

    def build(self) -> Query:
        """Build query.

        Returns:
            Query object
        """
        return self._query

    def apply_to_sqlalchemy(self, query: Any, model: Any) -> Any:
        """Apply query to SQLAlchemy query object with security validation.

        Args:
            query: SQLAlchemy query
            model: SQLAlchemy model class

        Returns:
            Modified query

        Raises:
            ValueError: If field doesn't exist on model or is invalid

        Security:
            - Validates field exists as column on model
            - Prevents access to non-column attributes
            - All field names pre-validated by where/order_by/select methods
        """
        # Get valid column names from model
        try:
            valid_columns = {col.name for col in model.__table__.columns}
        except AttributeError as e:
            raise ValueError(
                f"Invalid model: {model}. Must be SQLAlchemy model with __table__"
            ) from e

        # Apply filters
        for filter_spec in self._query.filters:
            field_name = filter_spec["field"]

            # Validate field exists as column
            if field_name not in valid_columns:
                raise ValueError(f"Field '{field_name}' is not a valid column on {model.__name__}")

            # Safe to use getattr now - field is validated
            column = getattr(model, field_name)
            op = filter_spec["operator"]
            val = filter_spec["value"]

            if op == "eq":
                query = query.filter(column == val)
            elif op == "ne":
                query = query.filter(column != val)
            elif op == "gt":
                query = query.filter(column > val)
            elif op == "gte":
                query = query.filter(column >= val)
            elif op == "lt":
                query = query.filter(column < val)
            elif op == "lte":
                query = query.filter(column <= val)
            elif op == "in":
                query = query.filter(column.in_(val))
            elif op == "not_in":
                query = query.filter(~column.in_(val))
            elif op == "like":
                query = query.filter(column.like(val))
            elif op == "ilike":
                query = query.filter(column.ilike(val))

        # Apply sorting
        for sort_spec in self._query.sorts:
            field_name = sort_spec["field"]

            # Validate field exists as column
            if field_name not in valid_columns:
                raise ValueError(f"Field '{field_name}' is not a valid column on {model.__name__}")

            column = getattr(model, field_name)
            if sort_spec["direction"] == "desc":
                query = query.order_by(column.desc())
            else:
                query = query.order_by(column.asc())

        # Apply pagination
        if self._query.offset:
            query = query.offset(self._query.offset)
        if self._query.limit:
            query = query.limit(self._query.limit)

        return query
