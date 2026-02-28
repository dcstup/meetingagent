"""Generic utterance ingest endpoint -- adapter-agnostic.

Used by the future DeepGram browser integration (and any other adapter that
pushes utterances directly rather than via webhooks).
"""

import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models.tables import MeetingSession, MeetingStatus, Utterance
from src.services.ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class IngestUtteranceRequest(BaseModel):
    session_id: str
    speaker: str
    text: str
    timestamp_ms: int


@router.post("/ingest/utterance")
async def ingest_utterance(
    body: IngestUtteranceRequest,
    db: AsyncSession = Depends(get_db),
):
    """Accept a single utterance and feed it into the standard pipeline.

    This is the same store-and-broadcast logic used by the webhook handler
    but without any adapter-specific payload parsing.
    """
    try:
        sid = _uuid.UUID(body.session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    result = await db.execute(
        select(MeetingSession).where(
            MeetingSession.id == sid,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    text = body.text.strip()
    if not text:
        return {"status": "ignored"}

    # Activate session on first utterance
    status_changed = False
    if session.status in (MeetingStatus.bot_joining, MeetingStatus.connecting):
        session.status = MeetingStatus.active
        status_changed = True

    utterance = Utterance(
        session_id=session.id,
        speaker=body.speaker,
        text=text,
        timestamp_ms=body.timestamp_ms,
    )
    db.add(utterance)
    await db.commit()

    if status_changed:
        try:
            await manager.broadcast(
                str(session.workspace_id),
                {"type": "meeting_status", "data": {"session_id": str(session.id), "status": "active"}},
            )
        except Exception:
            pass

    if session.status == MeetingStatus.active:
        try:
            from src.workers.extraction_loop import start_extraction
            await start_extraction(str(session.id))
        except Exception:
            pass

    try:
        await manager.broadcast(
            str(session.workspace_id),
            {
                "type": "utterance",
                "data": {
                    "id": str(utterance.id),
                    "speaker": body.speaker,
                    "text": text,
                    "timestamp_ms": body.timestamp_ms,
                },
            },
        )
    except Exception as e:
        logger.error(f"Broadcast failed: {e}")

    return {"status": "ok"}
