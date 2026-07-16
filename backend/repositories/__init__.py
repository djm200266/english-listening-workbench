"""Repository base and JSON implementation.

All data access goes through the repository layer.
Pages or API routes never touch JSON files directly.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models import Task, TaskListItem


def _atomic_write(filepath: Path, data: str) -> None:
    """Write to temp file then atomic replace to avoid corruption."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False,
        dir=filepath.parent, prefix=".tmp_"
    )
    try:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, str(filepath))
    except Exception:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskRepository(ABC):
    """Abstract repository for task persistence."""

    @abstractmethod
    def list_tasks(self) -> list[TaskListItem]: ...

    @abstractmethod
    def get_task(self, task_id: str) -> Optional[Task]: ...

    @abstractmethod
    def save_task(self, task: Task) -> Task: ...

    @abstractmethod
    def delete_task(self, task_id: str) -> bool: ...

    @abstractmethod
    def task_exists(self, task_id: str) -> bool: ...


class JsonTaskRepository(TaskRepository):
    """MVP: each task stored in data/{task_id}/task.json."""

    def __init__(self, data_dir: str | None = None) -> None:
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent / "data")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _task_dir(self, task_id: str) -> Path:
        return self._data_dir / task_id

    def _task_file(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "task.json"

    def list_tasks(self) -> list[TaskListItem]:
        items: list[TaskListItem] = []
        if not self._data_dir.exists():
            return items
        for d in sorted(self._data_dir.iterdir(), key=lambda x: x.name, reverse=True):
            if not d.is_dir():
                continue
            tf = d / "task.json"
            if not tf.exists():
                continue
            try:
                task = Task.model_validate_json(tf.read_text(encoding="utf-8"))
                items.append(TaskListItem(
                    task_id=task.task_id,
                    task_name=task.task_name,
                    topic=task.config.topic,
                    status=task.status,
                    overall_score=task.evaluation.overall_score if task.evaluation else 0.0,
                    s3s4_count=task.evaluation.s3s4_count if task.evaluation else 0,
                    updated_at=task.updated_at,
                    created_at=task.config.created_at,
                ))
            except Exception:
                continue
        return items

    def get_task(self, task_id: str) -> Optional[Task]:
        tf = self._task_file(task_id)
        if not tf.exists():
            return None
        return Task.model_validate_json(tf.read_text(encoding="utf-8"))

    def save_task(self, task: Task) -> Task:
        task.updated_at = _now_iso()
        task_dir = self._task_dir(task.task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        tf = self._task_file(task.task_id)
        _atomic_write(tf, task.model_dump_json(indent=2, exclude_none=True))
        return task

    def delete_task(self, task_id: str) -> bool:
        task_dir = self._task_dir(task_id)
        if not task_dir.exists():
            return False
        shutil.rmtree(task_dir)
        return True

    def task_exists(self, task_id: str) -> bool:
        return self._task_file(task_id).exists()
