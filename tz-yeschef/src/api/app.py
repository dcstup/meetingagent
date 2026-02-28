import asyncio
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings


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
    app = FastAPI(title="YesChef", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from src.api.routes_health import router as health_router
    from src.api.routes_proposals import router as proposals_router
    from src.api.routes_webhooks import router as webhooks_router
    from src.api.routes_ws import router as ws_router
    from src.api.routes_workspace import router as workspace_router

    app.include_router(health_router)
    app.include_router(proposals_router)
    app.include_router(webhooks_router)
    app.include_router(ws_router)
    app.include_router(workspace_router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=True)
