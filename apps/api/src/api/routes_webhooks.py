import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters import get_adapter
from src.adapters.base import AdapterStatus
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


async def _store_and_broadcast(
    db: AsyncSession,
    session: MeetingSession,
    speaker: str,
    text: str,
    timestamp_ms: int,
) -> dict:
    """Common logic: store utterance, activate session, broadcast, start extraction."""
    # Update session status to active on first transcript
    status_changed = False
    if session.status in (MeetingStatus.bot_joining, MeetingStatus.connecting):
        session.status = MeetingStatus.active
        status_changed = True

    utterance = Utterance(
        session_id=session.id,
        speaker=speaker,
        text=text,
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
    try:
        await manager.broadcast(
            str(session.workspace_id),
            {
                "type": "utterance",
                "data": {
                    "id": str(utterance.id),
                    "speaker": speaker,
                    "text": text,
                    "timestamp_ms": timestamp_ms,
                },
            },
        )
    except Exception as e:
        logger.error(f"Broadcast failed: {e}")

    return {"status": "ok"}


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

    adapter = get_adapter("recall")
    bot_id, utterances = adapter.parse_webhook(payload)

    if not utterances:
        return {"status": "ignored"}

    # Find session by bot ID, scoped to workspace
    session = None
    if bot_id:
        result = await db.execute(
            select(MeetingSession).where(
                MeetingSession.recall_bot_id == bot_id,
                MeetingSession.workspace_id == workspace.id,
            )
        )
        session = result.scalar_one_or_none()

    # Fallback: get the most recent active session for this workspace
    if not session:
        result = await db.execute(
            select(MeetingSession)
            .where(
                MeetingSession.workspace_id == workspace.id,
                MeetingSession.status.in_([
                    MeetingStatus.bot_joining,
                    MeetingStatus.connecting,
                    MeetingStatus.active,
                ]),
            )
            .order_by(MeetingSession.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()

    if not session:
        logger.warning(f"No session found for bot_id={bot_id}, workspace={workspace.id}")
        return {"status": "ignored"}

    result = {"status": "ok"}
    for u in utterances:
        result = await _store_and_broadcast(db, session, u.speaker, u.text, u.timestamp_ms)
    return result


@router.post("/recall/{secret}/status")
async def recall_status_webhook(
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Recall bot status changes."""
    workspace = await _get_workspace_by_secret(secret, db)

    payload = await request.json()

    adapter = get_adapter("recall")
    bot_id, adapter_status = adapter.parse_status_webhook(payload)

    if not bot_id:
        raise HTTPException(status_code=400, detail="Missing bot_id in payload")

    result = await db.execute(
        select(MeetingSession).where(
            MeetingSession.recall_bot_id == bot_id,
            MeetingSession.workspace_id == workspace.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if adapter_status == AdapterStatus.ENDED:
        session.status = MeetingStatus.ended
        session.ended_at = datetime.now(timezone.utc)
    elif adapter_status == AdapterStatus.ACTIVE:
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
