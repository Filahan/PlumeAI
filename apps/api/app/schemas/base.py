"""Pydantic base config used across the API: camelCase JSON output, snake_case Python fields."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class APISchema(BaseModel):
    """Base class enforcing the API's JSON convention.

    - Field names in Python: snake_case (idiomatic Python).
    - Field names in JSON: camelCase (matches the existing TypeScript client shapes so the
      frontend can switch from Drizzle/server-actions to fetch with zero JSON-shape diff).
    - `populate_by_name`: accept both `default_model` and `defaultModel` on input.
    - `from_attributes`: allow constructing from SQLAlchemy ORM instances directly.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
