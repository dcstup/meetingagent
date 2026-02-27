import asyncio
import logging
import sys

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from src.config import Settings
from src.session.meeting_session import MeetingSession
from src.webhooks.server import WebhookRouter, create_webhook_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


settings = Settings()
app = FastAPI(title="Meeting Assistant")

# Shared webhook router — routes registered once, transcript manager swapped per session
_webhook_router = WebhookRouter()
create_webhook_routes(app, _webhook_router)

# Active session (single meeting at a time for MVP)
_session: MeetingSession | None = None


class JoinRequest(BaseModel):
    meeting_url: str


async def _resolve_webhook_base_url() -> str:
    """Get the public webhook URL: from env, or auto-detect from ngrok."""
    if settings.webhook_base_url:
        return settings.webhook_base_url

    # Try to auto-detect ngrok tunnel
    for host in ["ngrok", "localhost"]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://{host}:4040/api/tunnels", timeout=5.0
                )
                tunnels = resp.json().get("tunnels", [])
                if tunnels:
                    url = tunnels[0].get("public_url", "")
                    logger.info(f"Auto-detected ngrok URL: {url}")
                    return url
        except Exception:
            continue

    raise RuntimeError(
        "WEBHOOK_BASE_URL not set and ngrok not detected. "
        "Set WEBHOOK_BASE_URL in .env or start ngrok."
    )


@app.post("/join")
async def join_meeting(req: JoinRequest):
    """Join a Zoom meeting. Creates a bot and starts the agent."""
    global _session

    # Clean up any previous session
    if _session:
        await _session.stop()
        _session = None

    session = MeetingSession(settings=settings, meeting_url=req.meeting_url)
    _session = session

    # Point webhook router to this session's transcript manager
    _webhook_router.set_transcript_manager(session.transcript_manager)

    base_url = await _resolve_webhook_base_url()
    webhook_url = f"{base_url}/webhooks/recall"

    try:
        bot_id = await session.start(webhook_url)
    except Exception as e:
        logger.exception("Failed to start meeting session")
        _session = None
        return {"error": str(e)}

    # Poll for meeting end in background — capture local ref to avoid race
    asyncio.create_task(_watch_session(session))

    return {"bot_id": bot_id, "webhook_url": webhook_url, "status": "joining"}


async def _watch_session(session: MeetingSession):
    """Background task that watches for meeting end and cleans up."""
    global _session
    try:
        await session.poll_until_done()
    finally:
        await session.stop()
        # Only clear global if it's still pointing to this session
        if _session is session:
            _session = None


@app.post("/stop")
async def stop_meeting():
    """Stop the current meeting session."""
    global _session
    if _session and _session.is_running:
        await _session.stop()
        _session = None
        return {"status": "stopped"}
    return {"status": "no active session"}


@app.get("/status")
async def get_status():
    """Get current session status."""
    if _session and _session.is_running:
        transcript = await _session.transcript_manager.get_formatted_transcript()
        participants = await _session.transcript_manager.get_participants()
        return {
            "active": True,
            "meeting_url": _session.meeting_url,
            "participants": [p.name for p in participants],
            "transcript_entries": _session.transcript_manager.entry_count,
            "recent_transcript": transcript,
        }
    return {"active": False}


def main():
    # CLI mode: if a meeting URL is passed, join immediately after server starts
    meeting_url = sys.argv[1] if len(sys.argv) > 1 else None

    if meeting_url:
        logger.info(f"CLI mode: will join {meeting_url} after server starts")

        @app.on_event("startup")
        async def auto_join():
            await asyncio.sleep(1.0)
            asyncio.create_task(
                join_meeting(JoinRequest(meeting_url=meeting_url))
            )

    uvicorn.run(
        app,
        host=settings.webhook_host,
        port=settings.webhook_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
