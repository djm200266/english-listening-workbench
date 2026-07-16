"""API routes for tasks."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from config import get_mode
from models import Task, TaskConfig, TaskListItem
from services import TaskService
from repositories import JsonTaskRepository

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

# Singleton: injected by main.py
_task_service: TaskService | None = None


def set_task_service(svc: TaskService) -> None:
    global _task_service
    _task_service = svc


def get_service() -> TaskService:
    global _task_service
    if _task_service is None:
        repo = JsonTaskRepository()
        _task_service = TaskService(repo)
    return _task_service


@router.get("", response_model=list[TaskListItem])
def list_tasks():
    return get_service().list_tasks()


@router.post("", response_model=Task, status_code=201)
def create_task(config: TaskConfig):
    try:
        return get_service().create_task(config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: str):
    task = get_service().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.put("/{task_id}", response_model=Task)
def update_task(task_id: str, config: TaskConfig):
    task = get_service().update_config(task_id, config)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.delete("/{task_id}")
def delete_task(task_id: str):
    ok = get_service().delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return {"ok": True}
