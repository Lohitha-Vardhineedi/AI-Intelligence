"""Response envelopes: {success, data} and {success, data, pagination}."""

from __future__ import annotations

import math
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int

    @classmethod
    def of(cls, page: int, page_size: int, total: int) -> Pagination:
        return cls(page=page, page_size=page_size, total=total,
                   pages=max(1, math.ceil(total / page_size)))


class PagedResponse(BaseModel, Generic[T]):
    success: bool = True
    data: list[T]
    pagination: Pagination
