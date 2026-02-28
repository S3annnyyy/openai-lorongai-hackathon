"""FastAPI app factory and request handlers."""

from __future__ import annotations
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import TaskCreate, TaskUpdate
from .repository import TaskRepository


def create_app(storage_path: str | Path = "tasks.json") -> FastAPI:
    store = TaskRepository(storage_path=storage_path)
    app_dir = Path(__file__).resolve().parent
    static_dir = app_dir / "static"

    app = FastAPI(title="Task Service")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/tasks")
    def list_tasks(completed: bool | None = None):
        return [task.to_dict() for task in store.list(completed=completed)]

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: int):
        try:
            return store.get(task_id).to_dict()
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error))

    @app.get("/api/report")
    def get_report() -> dict:
        return store.stats()

    @app.post("/api/tasks")
    def create_task(payload: TaskCreate):
        try:
            return store.create(payload).to_dict()
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.patch("/api/tasks/{task_id}")
    def patch_task(task_id: int, payload: TaskUpdate):
        try:
            return store.patch(task_id, payload).to_dict()
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: int):
        removed = store.delete(task_id)
        return {"removed": removed}

    return app


def main() -> None:
    import uvicorn

    storage = Path(__file__).resolve().parents[1] / "tasks.json"
    uvicorn.run(
        app="task_service.main:create_app",
        host="127.0.0.1",
        port=8000,
        factory=True,
        log_level="info",
        reload=False,
        kwargs={"storage_path": str(storage)},
    )


if __name__ == "__main__":
    main()
