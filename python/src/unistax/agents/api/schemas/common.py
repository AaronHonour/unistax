"""Shared schema types and helpers."""

from __future__ import annotations

from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, StringConstraints, field_validator

from unistax.api import PaginatedResponse

IdStr = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}$")]
NameStr = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]
TypeStr = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]

T = TypeVar("T", bound=BaseModel)


def validate_skill_map(value: dict[str, float] | None) -> dict[str, float] | None:
    """Skill names are short identifiers; proficiencies are within 0..1."""
    if value is None:
        return None
    if len(value) > 100:
        raise ValueError("At most 100 skills are allowed")
    for name, proficiency in value.items():
        if not name or len(name) > 64:
            raise ValueError("Skill names must be 1-64 characters")
        if not 0.0 <= proficiency <= 1.0:
            raise ValueError(f"Proficiency for '{name}' must be between 0 and 1")
    return value


class SkillsMixin(BaseModel):
    @field_validator("skills", "required_skills", check_fields=False)
    @classmethod
    def _check_skills(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        return validate_skill_map(value)


def paginate(
    model: type[T], items: list[Any], page: int, page_size: int, total: int
) -> PaginatedResponse[Any]:
    """Build a ``PaginatedResponse`` for ``model`` items."""
    total_pages = max(1, -(-total // page_size)) if total else 0
    return PaginatedResponse[model](  # type: ignore[valid-type]
        data=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )
