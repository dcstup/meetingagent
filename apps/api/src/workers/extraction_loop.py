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
from src.services.embeddings import get_embedding, cosine_similarity
from src.services import gate
from src.services.ws_manager import manager

logger = logging.getLogger(__name__)


async def _get_rag_context(
    session_id: str, query_text: str, top_k: int = 5,
) -> list[dict]:
    """Retrieve top-k semantically similar utterances as RAG context chunks."""
    try:
        query_embedding = await get_embedding(query_text)
    except Exception as e:
        logger.warning(f"RAG embedding failed for gate context: {e}")
        return []

    async with async_session() as db:
        result = await db.execute(
            select(Utterance)
            .where(Utterance.session_id == uuid.UUID(session_id))
            .order_by(Utterance.created_at)
        )
        utterances = result.scalars().all()

    if not utterances:
        return []

    scored = []
    for u in utterances:
        try:
            u_emb = await get_embedding(u.text)
            sim = cosine_similarity(query_embedding, u_emb)
            scored.append((sim, u))
        except Exception:
            continue

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    top.sort(key=lambda x: x[1].created_at)

    return [
        {"time_offset": str(u.timestamp_ms), "text": f"{u.speaker}: {u.text}"}
        for _, u in top
    ]


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

        # Extract workspace_id early to avoid detached ORM access after commit
        workspace_id = str(session.workspace_id)

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
        logger.info(f"Extracting from {len(new_utterances)} new utterances, buffer={buffer.size}, text_len={len(transcript_text)}")
        raw_items = await extract_action_items(transcript_text)
        logger.info(f"Cerebras returned {len(raw_items)} raw items")

        items, filtered_out = filter_proposals(raw_items)
        logger.info(f"After filtering: {len(items)} passed, {len(filtered_out)} filtered out")

        # Broadcast filtered-out items so the extension debug UI can show them
        if filtered_out:
            for fi in filtered_out:
                try:
                    await manager.broadcast(
                        workspace_id,
                        {
                            "type": "proposal_filtered",
                            "data": {
                                "title": fi.get("title", ""),
                                "body": fi.get("body", ""),
                                "action_type": fi.get("action_type", "general_agent"),
                                "recipient": fi.get("recipient"),
                                "confidence": fi.get("confidence", 0),
                                "readiness": fi.get("readiness"),
                                "filter_reason": fi.get("filter_reason", "unknown"),
                            },
                        },
                    )
                except Exception:
                    pass

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

            # --- Pre-approval gate ---
            candidate = {
                "title": item.get("title", ""),
                "action_type": item.get("action_type", "general_agent"),
                "body": item.get("body", ""),
                "recipient": item.get("recipient"),
            }

            rag_chunks = await _get_rag_context(
                session_id,
                f"{candidate['title']} {candidate['body']}",
            )

            # Collect unique speakers from buffer as participants
            speakers = list({
                e.speaker for e in buffer._entries
            })
            meeting_ctx = {
                "title": getattr(session, "title", ""),
                "participants": speakers,
            }

            gate_result = await gate.evaluate_action(
                candidate=candidate,
                transcript_window=transcript_text,
                rag_context_chunks=rag_chunks,
                meeting_context=meeting_ctx,
            )

            gate_passed = gate_result.get("passed", True)
            gate_scores = gate_result.get("scores", {})

            proposal = Proposal(
                session_id=uuid.UUID(session_id),
                action_type=item.get("action_type", "general_agent"),
                title=item.get("title", ""),
                body=item.get("body", ""),
                recipient=item.get("recipient"),
                confidence=item.get("confidence", 0.5),
                dedupe_key=dedupe_key,
                dedupe_hash=compute_dedupe_hash(session_id, dedupe_key),
                embedding=embedding,
                status=ProposalStatus.pending if gate_passed else ProposalStatus.dropped,
                source_text=transcript_text[:2000],
                gate_scores=gate_scores,
                gate_avg_score=gate_result.get("avg_score"),
                gate_readiness=gate_scores.get("readiness"),
                gate_evidence_quote=gate_result.get("verbatim_evidence_quote"),
                gate_missing_info=gate_result.get("missing_critical_info"),
                gate_passed=gate_passed,
            )
            db.add(proposal)
            await db.flush()
            new_proposals.append(proposal)

            logger.info(
                f"New proposal: {proposal.title} "
                f"(confidence={proposal.confidence}, gate_passed={gate_passed})"
            )

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
                gate_data = {
                    "gate_passed": proposal.gate_passed,
                    "gate_scores": proposal.gate_scores,
                    "gate_avg_score": proposal.gate_avg_score,
                    "gate_evidence_quote": proposal.gate_evidence_quote,
                    "gate_missing_info": proposal.gate_missing_info,
                }

                if proposal.gate_passed:
                    await manager.broadcast(
                        workspace_id,
                        {
                            "type": "proposal_created",
                            "data": {
                                "id": str(proposal.id),
                                "action_type": proposal.action_type,
                                "title": proposal.title,
                                "body": proposal.body,
                                "recipient": proposal.recipient,
                                "confidence": proposal.confidence,
                                **gate_data,
                            },
                        },
                    )
                else:
                    await manager.broadcast(
                        workspace_id,
                        {
                            "type": "proposal_dropped",
                            "data": {
                                "id": str(proposal.id),
                                "action_type": proposal.action_type,
                                "title": proposal.title,
                                "body": proposal.body,
                                "recipient": proposal.recipient,
                                "confidence": proposal.confidence,
                                **gate_data,
                            },
                        },
                    )
            except Exception:
                pass

        return current_last_id
