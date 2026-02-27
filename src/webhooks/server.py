import logging

from fastapi import BackgroundTasks, FastAPI, Request

from src.transcription.transcript_manager import TranscriptManager
from src.webhooks.handlers import (
    handle_bot_status,
    handle_participant_join,
    handle_participant_leave,
    handle_transcript_data,
)

logger = logging.getLogger(__name__)


class WebhookRouter:
    """Holds a mutable reference to the active transcript manager."""

    def __init__(self):
        self.transcript_manager: TranscriptManager | None = None

    def set_transcript_manager(self, tm: TranscriptManager) -> None:
        self.transcript_manager = tm


def create_webhook_routes(app: FastAPI, router: WebhookRouter) -> None:
    """Register webhook routes once at app startup."""

    @app.post("/webhooks/recall")
    async def recall_webhook(request: Request, background_tasks: BackgroundTasks):
        """Receive all Recall.ai real-time events. Returns 200 immediately."""
        if not router.transcript_manager:
            return {"status": "no active session"}

        payload = await request.json()
        event = payload.get("event", "")
        tm = router.transcript_manager

        if event == "transcript.data":
            background_tasks.add_task(handle_transcript_data, payload, tm)
        elif event == "participant_events.join":
            background_tasks.add_task(handle_participant_join, payload, tm)
        elif event == "participant_events.leave":
            background_tasks.add_task(handle_participant_leave, payload, tm)
        elif event.startswith("bot."):
            background_tasks.add_task(handle_bot_status, payload)
        else:
            logger.debug(f"Unhandled event: {event}")

        return {"status": "ok"}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}
