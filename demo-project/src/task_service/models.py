"""Shared models for task entities and API payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal, cast

from pydantic import BaseModel, Field

Priority = Literal["low", "medium", "high"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat() + "Z"


@dataclass
class Task:
    id: int
    title: str
    priority: Priority = "medium"
    completed: bool = False
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title cannot be empty")
        if self.priority not in {"low", "medium", "high"}:
            raise ValueError("priority must be low, medium, or high")
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at

    def touch(self) -> None:
        self.updated_at = _now_iso()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Task":
        return cls(
            id=int(payload["id"]),
            title=str(payload["title"]),
            priority=cast(Priority, str(payload["priority"])),
            completed=bool(payload["completed"]),
            created_at=str(payload["created_at"]),
            updated_at=payload.get("updated_at"),
        )


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    priority: Priority = "medium"


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    priority: Priority | None = None
    completed: bool | None = None

