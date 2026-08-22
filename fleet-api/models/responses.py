from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: Any = None
    errors: list[str] = Field(default_factory=list)
    requires_restart: list[str] = Field(default_factory=list)
    last_modified: str = ""
