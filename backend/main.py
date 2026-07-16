"""FastAPI application entry point."""

from __future__ import annotations

import asyncio, os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.health import router as health_router
from api.script_routes import router as script_router
from api.audio_routes import router as audio_router
from api.image_routes import router as image_router
from api.question_routes import router as question_router
from api.prompt_assistant_routes import router as prompt_assistant_router
from api.evaluation_routes import router as evaluation_router
from api.export_routes import router as export_router
from api.version_routes import router as version_router
from api.diagnostics_routes import router as diagnostics_router
from api.comfyui_routes import router as comfyui_router
from api import router as task_router, set_task_service
from config import load_config, get_mode, get_config, is_cloudstudio
from repositories import JsonTaskRepository
from services import TaskService


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_config()
    repo = JsonTaskRepository()
    svc = TaskService(repo)
    set_task_service(svc)

    # Auto-start ComfyUI in background if enabled
    cfg2 = get_config().get("comfyui", {})
    if cfg2.get("enabled", True) and cfg2.get("autoStart", True):
        import threading
        def _auto_start_comfyui():
            try:
                from services.comfyui_process_manager import get_comfyui_manager
                mgr = get_comfyui_manager()
                if not mgr.is_running():
                    print("[Lifespan] Auto-starting ComfyUI in background...")
                    result = mgr.ensure_running()
                    if result["ok"]:
                        print(f"[Lifespan] ComfyUI auto-start: {result['message']}")
                    else:
                        print(f"[Lifespan] ComfyUI auto-start failed: {result.get('message', 'unknown')}")
                else:
                    print("[Lifespan] ComfyUI already running, reusing")
            except Exception as e:
                print(f"[Lifespan] ComfyUI auto-start error: {e}")
        t = threading.Thread(target=_auto_start_comfyui, daemon=True)
        t.start()

    # Ollama warmup: disabled to speed up startup (lazy on first use)

    yield

    # Shutdown: optionally stop ComfyUI
    cfg2 = get_config().get("comfyui", {})
    if not cfg2.get("stopOnBackendExit", False):
        try:
            from services.comfyui_process_manager import get_comfyui_manager
            get_comfyui_manager().stop_if_owned()
        except Exception:
            pass


app = FastAPI(
    title="English Listening Workbench API",
    version="0.1.0",
    lifespan=lifespan,
)

cfg = load_config()

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.get("backend", {}).get("corsOrigins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Resolve paths robustly (not dependent on CWD) ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"
assets_root = cfg.get("assets", {}).get("rootDir", "storage")

# ── API routers (registered BEFORE static/catch-all so they take priority) ──
app.include_router(health_router)
app.include_router(task_router)
app.include_router(script_router)
app.include_router(audio_router)
app.include_router(image_router)
app.include_router(question_router)
app.include_router(prompt_assistant_router)
app.include_router(evaluation_router)
app.include_router(export_router)
app.include_router(version_router)
app.include_router(diagnostics_router)
app.include_router(comfyui_router)


def _is_api_path(path: str) -> bool:
    """Check if a path is an API endpoint — starts with 'api/' or is just 'api'."""
    return path == "api" or path.startswith("api/")


def _serve_static_file(full_path: str) -> FileResponse | None:
    """Try to serve a static file from frontend/dist or data assets directory.
    Priority: 1) frontend Vite output  2) generated assets (images, audio).
    Returns None if file not found in either location.
    """
    # 1. Frontend Vite output (JS, CSS, other build artifacts)
    if FRONTEND_DIST.is_dir():
        fp = FRONTEND_DIST / full_path
        if fp.is_file():
            return FileResponse(fp)

    # 2. Generated data assets (images, audio — stored as /assets/G7_DIR_*/...)
    assets_root_str = str(assets_root)
    if os.path.isdir(assets_root_str):
        dp = Path(assets_root_str) / full_path
        if dp.is_file():
            return FileResponse(dp)

    return None


if is_cloudstudio():
    if FRONTEND_DIST.is_dir() and (FRONTEND_DIST / "index.html").is_file():
        # ── SPA catch-all: frontend is built, serve it ──
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve static files or SPA index.html. API routes already matched above."""
            if _is_api_path(full_path):
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse("Not Found", status_code=404)

            file_resp = _serve_static_file(full_path)
            if file_resp is not None:
                return file_resp

            return FileResponse(FRONTEND_DIST / "index.html")

        @app.get("/")
        async def serve_root():
            return FileResponse(FRONTEND_DIST / "index.html")

    else:
        # ── frontend/dist missing: return 503 for web routes, keep API working ──
        from fastapi.responses import JSONResponse

        _DIST_MISSING_MSG = {
            "status": "frontend_not_built",
            "message": "前端未构建。请先运行: bash deploy/cloudstudio/setup-cloudstudio.sh",
            "frontend_dist": str(FRONTEND_DIST),
            "index_html_exists": False,
        }

        @app.get("/{full_path:path}")
        async def serve_spa_missing(full_path: str):
            """API routes already matched. Non-API routes get 503 when dist is missing."""
            if _is_api_path(full_path):
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse("Not Found", status_code=404)

            # Try to serve from data assets anyway
            file_resp = _serve_static_file(full_path)
            if file_resp is not None:
                return file_resp

            return JSONResponse(_DIST_MISSING_MSG, status_code=503)

        @app.get("/")
        async def serve_root_missing():
            """Root path: 503 because frontend is not built."""
            return JSONResponse(_DIST_MISSING_MSG, status_code=503)
else:
    # Windows / dev: mount assets directory at /assets/ as before
    assets_root_str = str(assets_root)
    if os.path.isdir(assets_root_str):
        app.mount("/assets", StaticFiles(directory=assets_root_str), name="data_assets")


if __name__ == "__main__":
    host = cfg.get("backend", {}).get("host", "127.0.0.1")
    port = cfg.get("backend", {}).get("port", 8000)
    uvicorn.run("main:app", host=host, port=port, reload=False)
