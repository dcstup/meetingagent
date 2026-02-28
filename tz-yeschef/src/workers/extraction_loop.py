import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from src.config.constants import EXTRACTION_INTERVAL_S
from src.db.engine import async_session
from src.models.tables import (
    MeetingSession,
    Utterance,
    Proposal,
    MeetingStatus,
    ProposalStatus,
)
from src.services.extractor import RollingBuffer, filter_proposals
from src.services.cerebras import extract_action_items
from src.services.deduper import compute_dedupe_hash, is_duplicate
from src.services.embeddings import get_embedding

logger = logging.getLogger(__name__)

# Active extraction tasks per session
_active_sessions: dict[str, asyncio.Task] = {}


async def start_extraction(session_id: str):
    """Start extraction loop for a meeting session."""
    sid = str(session_id)
    if sid in _active_sessions:
        return
    task = asyncio.create_task(_extraction_loop(sid))
    _active_sessions[sid] = task


async def stop_extraction(session_id: str):
    """Stop extraction loop for a session."""
    sid = str(session_id)
    task = _active_sessions.pop(sid, None)
    if task:
        task.cancel()


async def _extraction_loop(session_id: str):
    """Main extraction loop for a session."""
    buffer = RollingBuffer()
    last_utterance_id: uuid.UUID | None = None

    try:
        while True:
            await asyncio.sleep(EXTRACTION_INTERVAL_S)

            try:
                last_utterance_id = await _run_extraction_cycle(
                    session_id, buffer, last_utterance_id
                )
            except _SessionEnded:
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Extraction cycle error for {session_id}: {e}", exc_info=True)
    except asyncio.CancelledError:
        pass
    finally:
        _active_sessions.pop(session_id, None)


class _SessionEnded(Exception):
    pass


async def _run_extraction_cycle(
    session_id: str,
    buffer: RollingBuffer,
    last_utterance_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Single extraction cycle. Returns updated last_utterance_id."""
    async with async_session() as db:
        # Check session is still active
        result = await db.execute(
            select(MeetingSession).where(
                MeetingSession.id == uuid.UUID(session_id)
            )
        )
        session = result.scalar_one_or_none()
        if not session or session.status in (
            MeetingStatus.ended,
            MeetingStatus.failed,
        ):
            raise _SessionEnded()

        # Only fetch NEW utterances since last processed
        query = (
            select(Utterance)
            .where(Utterance.session_id == uuid.UUID(session_id))
            .order_by(Utterance.created_at)
        )
        if last_utterance_id:
            # Get utterances created after the last one we processed
            last_result = await db.execute(
                select(Utterance.created_at).where(Utterance.id == last_utterance_id)
            )
            last_created = last_result.scalar_one_or_none()
            if last_created:
                query = query.where(Utterance.created_at > last_created)

        result = await db.execute(query)
        new_utterances = result.scalars().all()

        if not new_utterances:
            return last_utterance_id

        for u in new_utterances:
            buffer.add(u.speaker, u.text, u.timestamp_ms)

        # Track cursor
        current_last_id = new_utterances[-1].id

        transcript_text = buffer.get_text()
        if not transcript_text.strip():
            return current_last_id

        # Guard against excessively large context
        MAX_CHARS = 12000  # ~3000 tokens
        if len(transcript_text) > MAX_CHARS:
            transcript_text = transcript_text[-MAX_CHARS:]

        # Extract action items via Cerebras
        logger.info(f"Extracting from {len(new_utterances)} new utterances, buffer={buffer.size}")
        raw_items = await extract_action_items(transcript_text)
        logger.info(f"Cerebras returned {len(raw_items)} raw items")

        items = filter_proposals(raw_items)
        logger.info(f"After filtering: {len(items)} items")

        if not items:
            return current_last_id

        # Get existing proposals for dedup
        result = await db.execute(
            select(Proposal).where(
                Proposal.session_id == uuid.UUID(session_id)
            )
        )
        existing = result.scalars().all()
        existing_dicts = [
            {"dedupe_hash": p.dedupe_hash, "embedding": p.embedding}
            for p in existing
        ]

        new_proposals = []
        for item in items:
            dedupe_key = item.get("dedupe_key", item.get("title", ""))

            is_dup = await is_duplicate(
                session_id,
                dedupe_key,
                item.get("body", item.get("title", "")),
                existing_dicts,
            )
            if is_dup:
                logger.info(f"Duplicate skipped: {item.get('title', '')}")
                continue

            # Get embedding for new proposal
            embedding = None
            try:
                embedding = await get_embedding(
                    item.get("body", item.get("title", ""))
                )
            except Exception as e:
                logger.warning(f"Embedding failed (dedup will use hash only): {e}")

            proposal = Proposal(
                session_id=uuid.UUID(session_id),
                action_type=item.get("action_type", "generic_draft"),
                title=item.get("title", ""),
                body=item.get("body", ""),
                recipient=item.get("recipient"),
                confidence=item.get("confidence", 0.5),
                dedupe_key=dedupe_key,
                dedupe_hash=compute_dedupe_hash(session_id, dedupe_key),
                embedding=embedding,
                status=ProposalStatus.pending,
                source_text=transcript_text[:2000],
            )
            db.add(proposal)
            await db.flush()
            new_proposals.append(proposal)

            logger.info(f"New proposal: {proposal.title} (confidence={proposal.confidence})")

            existing_dicts.append(
                {
                    "dedupe_hash": proposal.dedupe_hash,
                    "embedding": embedding,
                }
            )

        # Commit all proposals atomically, then broadcast
        await db.commit()

        for proposal in new_proposals:
            try:
                from src.services.ws_manager import manager

                await manager.broadcast(
                    str(session.workspace_id),
                    {
                        "type": "proposal_created",
                        "data": {
                            "id": str(proposal.id),
                            "action_type": proposal.action_type,
                            "title": proposal.title,
                            "body": proposal.body,
                            "recipient": proposal.recipient,
                            "confidence": proposal.confidence,
                        },
                    },
                )
            except Exception:
                pass

        return current_last_id
