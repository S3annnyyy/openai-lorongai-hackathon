"""Persistence and mutations for tasks using a JSON file."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from threading import Lock
from typing import Iterable, cast

from .models import Task, TaskCreate, TaskUpdate


class TaskRepository:
    def __init__(self, storage_path: str | Path = "tasks.json"):
        self.storage_path = Path(storage_path)
        self._lock = Lock()
        self._tasks: list[Task] = []
        self._load()

    def list(self, completed: bool | None = None) -> list[Task]:
        with self._lock:
            tasks = list(self._tasks)
        if completed is None:
            return tasks
        return [task for task in tasks if task.completed == completed]

    def get(self, task_id: int) -> Task:
        with self._lock:
            return self._find(task_id)

    def create(self, payload: TaskCreate) -> Task:
        with self._lock:
            if any(task.title.lower() == payload.title.strip().lower() for task in self._tasks):
                raise ValueError("A task with the same title already exists")
            next_id = max((task.id for task in self._tasks), default=0) + 1
            task = Task(id=next_id, title=payload.title, priority=payload.priority)
            self._tasks.append(task)
            self._save()
            return task

    def patch(self, task_id: int, payload: TaskUpdate) -> Task:
        with self._lock:
            task = self._find(task_id)
            if payload.title is not None:
                new_title = payload.title.strip()
                if any(
                    existing.id != task.id and existing.title.lower() == new_title.lower()
                    for existing in self._tasks
                ):
                    raise ValueError("A task with the same title already exists")
                task.title = new_title
            if payload.priority is not None:
                task.priority = payload.priority
            if payload.completed is not None:
                task.completed = payload.completed
            task.touch()
            self._save()
            return task

    def delete(self, task_id: int) -> bool:
        with self._lock:
            before = len(self._tasks)
            self._tasks = [task for task in self._tasks if task.id != task_id]
            removed = len(self._tasks) != before
            if removed:
                self._save()
            return removed

    def stats(self) -> dict:
        with self._lock:
            total = len(self._tasks)
            completed = sum(1 for task in self._tasks if task.completed)
            by_priority = Counter(task.priority for task in self._tasks)
        return {
            "total": total,
            "completed": completed,
            "completion_rate": completed / total if total else 0.0,
            "by_priority": {
                "low": by_priority.get("low", 0),
                "medium": by_priority.get("medium", 0),
                "high": by_priority.get("high", 0),
            },
        }

    def _load(self) -> None:
        if not self.storage_path.exists():
            self._tasks = []
            return
        content = self.storage_path.read_text(encoding="utf-8").strip()
        if not content:
            self._tasks = []
            return
        raw = json.loads(content)
        items = cast(Iterable[dict], raw)
        self._tasks = [Task.from_dict(item) for item in items]

    def _save(self) -> None:
        payload = [task.to_dict() for task in self._tasks]
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def _find(self, task_id: int) -> Task:
        for task in self._tasks:
            if task.id == task_id:
                return task
        raise KeyError(f"task {task_id} not found")

