import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.config import settings

logger = logging.getLogger(__name__)


def _resolve_dashboard_dist() -> Path:
    """Return the first existing dashboard dist directory from a list of candidates.

    On Railway, Nixpacks copies the repo into /app with `rootDirectory=apps/api/`,
    so the Python file lives at /app/src/api/app.py and CWD is /app.  The
    buildCommand runs `cd ../dashboard && npm run build`, placing the output at
    a path one level above /app.  We probe several candidates so the app works
    both locally and in production without hardcoding a single path.
    """
    # Allow an explicit override via environment variable.
    env_override = os.environ.get("DASHBOARD_DIST_PATH")
    if env_override:
        return Path(env_override)

    # __file__ = .../src/api/app.py  →  parent×4 = repo root (local)
    #                                    or /         (Railway — too high)
    file_root = Path(__file__).resolve().parent.parent.parent.parent

    candidates: list[Path] = [
        # 1. Bundled inside apps/api/ (works on Railway where only apps/api/ is copied)
        Path.cwd() / "dashboard_dist",
        # 2. Standard local monorepo layout: repo-root/apps/dashboard/dist
        file_root / "apps" / "dashboard" / "dist",
        # 3. Railway: rootDirectory=apps/api  →  CWD=/app, dashboard built at /app/../dashboard/dist
        Path.cwd().parent / "dashboard" / "dist",
        # 4. Nixpacks sometimes lands everything under /app; dashboard may be a sibling
        Path("/app") / ".." / "dashboard" / "dist",
        # 5. Direct absolute fallback
        Path("/dashboard") / "dist",
    ]

    logger.info("Dashboard dist resolution — __file__=%s  cwd=%s", __file__, Path.cwd())
    for i, candidate in enumerate(candidates, 1):
        resolved = candidate.resolve()
        exists = resolved.is_dir()
        logger.info("  candidate %d: %s  (resolved: %s)  exists=%s", i, candidate, resolved, exists)
        if exists:
            logger.info("Dashboard dist found at: %s", resolved)
            return resolved

    # Return the first candidate even if missing so the caller can log it.
    fallback = candidates[0].resolve()
    logger.warning("Dashboard dist not found in any candidate; skipping static mount. Last tried: %s", fallback)
    return fallback


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-generate secrets if empty
    if not settings.webhook_secret:
        settings.webhook_secret = secrets.token_urlsafe(32)
    if not settings.overlay_token:
        settings.overlay_token = secrets.token_urlsafe(32)

    from src.workers.calendar_poll import poll_calendar_events
    task = asyncio.create_task(poll_calendar_events())
    yield
    task.cancel()


def create_app() -> FastAPI:
    # Resolve after import so that logging is already configured by uvicorn.
    dashboard_dist = _resolve_dashboard_dist()

    app = FastAPI(title="YesChef", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from src.api.routes_health import router as health_router
    from src.api.routes_ingest import router as ingest_router
    from src.api.routes_proposals import router as proposals_router
    from src.api.routes_webhooks import router as webhooks_router
    from src.api.routes_ws import router as ws_router
    from src.api.routes_workspace import router as workspace_router

    app.include_router(health_router)
    app.include_router(ingest_router)
    app.include_router(proposals_router)
    app.include_router(webhooks_router)
    app.include_router(ws_router)
    app.include_router(workspace_router)

    # Serve the pre-built Vite dashboard under /dashboard if the dist directory
    # exists. This is conditional so the API still starts cleanly without a
    # dashboard build (local dev with `vite dev` or CI without a frontend build).
    logger.info("Dashboard dist path: %s  (exists=%s)", dashboard_dist, dashboard_dist.is_dir())
    if dashboard_dist.is_dir():
        # Static assets (JS/CSS chunks) — mounted before the catch-all route.
        app.mount(
            "/dashboard/assets",
            StaticFiles(directory=str(dashboard_dist / "assets")),
            name="dashboard-assets",
        )

        # SPA catch-all: any /dashboard/* path that isn't a static asset gets
        # index.html so that client-side routing works.
        @app.get("/dashboard/{path:path}", include_in_schema=False)
        async def dashboard_spa(path: str) -> FileResponse:  # noqa: ARG001
            return FileResponse(str(dashboard_dist / "index.html"))

        # Redirect bare /dashboard to /dashboard/
        @app.get("/dashboard", include_in_schema=False)
        async def dashboard_root() -> FileResponse:
            return FileResponse(str(dashboard_dist / "index.html"))

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=True)
