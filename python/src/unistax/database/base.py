"""Database base models and mixins."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Integer  # type: ignore[import-not-found]
from sqlalchemy.ext.declarative import (  # type: ignore[import-not-found]
    declarative_base,
    declared_attr,
)
from sqlalchemy.orm import DeclarativeMeta  # type: ignore[import-not-found]

# Base class for all models
Base: DeclarativeMeta = declarative_base()


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""

    @declared_attr  # type: ignore[misc]
    def created_at(cls) -> Column:
        """Created at timestamp.

        Returns:
            SQLAlchemy column
        """
        return Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    @declared_attr  # type: ignore[misc]
    def updated_at(cls) -> Column:
        """Updated at timestamp.

        Returns:
            SQLAlchemy column
        """
        return Column(
            DateTime,
            default=lambda: datetime.now(timezone.utc),
            onupdate=lambda: datetime.now(timezone.utc),
            nullable=False,
        )


class SoftDeleteMixin:
    """Mixin for soft delete functionality."""

    @declared_attr  # type: ignore[misc]
    def deleted_at(cls) -> Column:
        """Deleted at timestamp.

        Returns:
            SQLAlchemy column
        """
        return Column(DateTime, nullable=True)

    @declared_attr  # type: ignore[misc]
    def is_deleted(cls) -> Column:
        """Is deleted flag.

        Returns:
            SQLAlchemy column
        """
        return Column(Boolean, default=False, nullable=False)

    def soft_delete(self) -> None:
        """Soft delete the record."""
        self.deleted_at = datetime.now(timezone.utc)
        self.is_deleted = True

    def restore(self) -> None:
        """Restore a soft deleted record."""
        self.deleted_at = None
        self.is_deleted = False


class AuditMixin(TimestampMixin):
    """Mixin for audit fields."""

    @declared_attr  # type: ignore[misc]
    def created_by(cls) -> Column:
        """Created by user ID.

        Returns:
            SQLAlchemy column
        """
        return Column(Integer, nullable=True)

    @declared_attr  # type: ignore[misc]
    def updated_by(cls) -> Column:
        """Updated by user ID.

        Returns:
            SQLAlchemy column
        """
        return Column(Integer, nullable=True)


class BaseModel(Base, TimestampMixin):  # type: ignore[misc]
    """Base model with timestamp fields.

    Attributes:
        id: Primary key
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    __abstract__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary.

        Returns:
            Dictionary representation
        """
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self) -> str:
        """String representation.

        Returns:
            String representation
        """
        attrs = ", ".join(f"{k}={v!r}" for k, v in self.to_dict().items() if k != "id")
        return f"{self.__class__.__name__}(id={self.id}, {attrs})"
