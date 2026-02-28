import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models.tables import MeetingSession, MeetingStatus, Utterance, Workspace
from src.services.ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks")


async def _get_workspace_by_secret(secret: str, db: AsyncSession) -> Workspace:
    """Look up workspace by webhook secret."""
    result = await db.execute(
        select(Workspace).where(Workspace.webhook_secret == secret)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    return workspace


@router.post("/recall/{secret}/transcript")
async def recall_transcript_webhook(
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive real-time transcript from Recall.ai bot."""
    workspace = await _get_workspace_by_secret(secret, db)

    payload = await request.json()
    logger.debug(f"RECALL_PAYLOAD: {str(payload)[:500]}")

    bot_id = (
        payload.get("bot_id")
        or payload.get("data", {}).get("bot_id")
        or payload.get("bot", {}).get("id")
    )

    # Find session by bot ID, scoped to workspace
    if bot_id:
        result = await db.execute(
            select(MeetingSession).where(
                MeetingSession.recall_bot_id == bot_id,
                MeetingSession.workspace_id == workspace.id,
            )
        )
        session = result.scalar_one_or_none()
    else:
        session = None

    # Fallback: get the most recent active session for this workspace
    if not session:
        result = await db.execute(
            select(MeetingSession)
            .where(
                MeetingSession.workspace_id == workspace.id,
                MeetingSession.status.in_([MeetingStatus.bot_joining, MeetingStatus.active]),
            )
            .order_by(MeetingSession.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()

    if not session:
        # Return 200 to prevent Recall.ai from retrying
        logger.warning(f"No session found for bot_id={bot_id}, workspace={workspace.id}")
        return {"status": "ignored"}

    # Handle transcript data — Recall sends: payload.data.data.words + payload.data.data.participant
    inner_data = payload.get("data", {}).get("data", {})
    words = inner_data.get("words", [])
    participant = inner_data.get("participant", {})

    if words:
        speaker = participant.get("name", "Unknown")
        text = " ".join(
            w.get("text", "") if isinstance(w, dict) else str(w) for w in words
        )
        if isinstance(words[0], dict):
            start_ts = words[0].get("start_timestamp") or {}
            timestamp_ms = int((start_ts.get("relative") or 0) * 1000)
        else:
            timestamp_ms = 0
    else:
        # Fallback for other payload formats
        transcript_data = payload.get("data", {}).get(
            "transcript", payload.get("transcript", {})
        )
        if isinstance(transcript_data, dict):
            speaker = transcript_data.get("speaker", "Unknown")
            text = transcript_data.get("text", "")
            timestamp_ms = int(transcript_data.get("timestamp", 0) * 1000)
        elif isinstance(transcript_data, str):
            speaker = "Unknown"
            text = transcript_data
            timestamp_ms = 0
        else:
            return {"status": "ignored"}

    if not text.strip():
        return {"status": "ignored"}

    # Update session status to active on first transcript
    status_changed = False
    if session.status == MeetingStatus.bot_joining:
        session.status = MeetingStatus.active
        status_changed = True

    utterance = Utterance(
        session_id=session.id,
        speaker=speaker,
        text=text.strip(),
        timestamp_ms=timestamp_ms,
    )
    db.add(utterance)
    await db.commit()

    # Broadcast status change after commit
    if status_changed:
        try:
            await manager.broadcast(
                str(session.workspace_id),
                {"type": "meeting_status", "data": {"session_id": str(session.id), "status": "active"}},
            )
        except Exception:
            pass

    # Start extraction loop when session is active
    if session.status == MeetingStatus.active:
        try:
            from src.workers.extraction_loop import start_extraction
            await start_extraction(str(session.id))
        except Exception:
            pass

    # Broadcast utterance via WS
    ws_key = str(session.workspace_id)
    try:
        await manager.broadcast(
            ws_key,
            {
                "type": "utterance",
                "data": {
                    "id": str(utterance.id),
                    "speaker": speaker,
                    "text": text.strip(),
                    "timestamp_ms": timestamp_ms,
                },
            },
        )
    except Exception as e:
        logger.error(f"Broadcast failed: {e}")

    return {"status": "ok"}


@router.post("/recall/{secret}/status")
async def recall_status_webhook(
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Recall bot status changes."""
    workspace = await _get_workspace_by_secret(secret, db)

    payload = await request.json()
    bot_id = payload.get("bot_id") or payload.get("data", {}).get("bot_id")
    if not bot_id:
        raise HTTPException(status_code=400, detail="Missing bot_id in payload")

    status_code = payload.get("data", {}).get("status", {}).get("code", "")

    result = await db.execute(
        select(MeetingSession).where(
            MeetingSession.recall_bot_id == bot_id,
            MeetingSession.workspace_id == workspace.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if status_code in ("done", "fatal"):
        session.status = MeetingStatus.ended
        session.ended_at = datetime.now(timezone.utc)
    elif status_code == "in_call_recording":
        session.status = MeetingStatus.active
        if not session.started_at:
            session.started_at = datetime.now(timezone.utc)

    await db.commit()

    # Broadcast status update (best-effort)
    try:
        await manager.broadcast(
            str(session.workspace_id),
            {
                "type": "meeting_status",
                "data": {
                    "session_id": str(session.id),
                    "status": session.status.value,
                },
            },
        )
    except Exception:
        pass

    return {"status": "ok"}
