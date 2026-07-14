"""FastAPI application factory.

Serves the JSON API under /api and, if a built React bundle is present at
job_hunt/web/static, serves that SPA for every other path. The scheduler thread
starts with the app.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from job_hunt.web.routes import router
from job_hunt.web.scheduler import scheduler

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="autopilot-jobhunt", lifespan=_lifespan)
    app.include_router(router)

    if _STATIC_DIR.is_dir():
        # Serve hashed assets, then fall back to index.html for client-side routes.
        assets = _STATIC_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        index = _STATIC_DIR / "index.html"

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            candidate = _STATIC_DIR / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            if index.is_file():
                return FileResponse(str(index))
            return JSONResponse({"detail": "SPA not built"}, status_code=404)
    else:
        @app.get("/")
        def _no_ui():
            return JSONResponse(
                {
                    "detail": "API is running. The web UI bundle is not built. "
                    "Build the React app into job_hunt/web/static, or use the Docker image."
                }
            )

    return app


app = create_app()
