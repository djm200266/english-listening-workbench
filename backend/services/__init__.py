"""Task business logic. Orchestrates between Mock and Real adapters."""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from models import Task, TaskConfig, TaskListItem
from repositories import TaskRepository


class TaskService:
    """Service layer for task CRUD. Calls repository, not JSON directly."""

    def __init__(self, repo: TaskRepository) -> None:
        self._repo = repo

    def list_tasks(self) -> list[TaskListItem]:
        return self._repo.list_tasks()

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._repo.get_task(task_id)

    def create_task(self, config: TaskConfig) -> Task:
        task_id = config.task_id or f"G7_DIR_{uuid4().hex[:4].upper()}"
        config.task_id = task_id
        task = Task(task_id=task_id, task_name=config.task_name, config=config)
        return self._repo.save_task(task)

    def update_config(self, task_id: str, config: TaskConfig) -> Optional[Task]:
        task = self._repo.get_task(task_id)
        if task is None:
            return None
        task.config = config
        return self._repo.save_task(task)

    def delete_task(self, task_id: str) -> bool:
        return self._repo.delete_task(task_id)

    def save_task(self, task: Task) -> Task:
        return self._repo.save_task(task)

    def task_exists(self, task_id: str) -> bool:
        return self._repo.task_exists(task_id)
