"""Schemas and types shared by many endpoints."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, PlainSerializer, StringConstraints

T = TypeVar("T")

# Exactly ten digits, e.g. 9876543210
PhoneStr = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{10}$")]

# Decimal that is written as a normal JSON number (e.g. 500.0) in responses
MoneyOut = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


@dataclass
class Pagination:
    skip: int = 0
    limit: int = 20


class MessageOut(BaseModel):
    message: str


class Page(BaseModel, Generic[T]):
    """Standard envelope for every list endpoint."""

    items: list[T]
    total: int
    skip: int
    limit: int
