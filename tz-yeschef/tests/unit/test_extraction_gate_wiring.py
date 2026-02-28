"""Tests for pre-approval gate wiring in the extraction pipeline."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.tables import (
    MeetingSession,
    MeetingStatus,
    Proposal,
    ProposalStatus,
    Utterance,
)
from src.services.extractor import RollingBuffer


def _make_session(session_id: uuid.UUID, workspace_id: uuid.UUID):
    s = MagicMock(spec=MeetingSession)
    s.id = session_id
    s.workspace_id = workspace_id
    s.status = MeetingStatus.active
    s.title = "Sprint Planning"
    return s


def _make_utterance(session_id: uuid.UUID, speaker: str, text: str, idx: int):
    u = MagicMock(spec=Utterance)
    u.id = uuid.uuid4()
    u.session_id = session_id
    u.speaker = speaker
    u.text = text
    u.timestamp_ms = 1000 * idx
    u.created_at = datetime(2026, 1, 1, 0, 0, idx, tzinfo=timezone.utc)
    return u


GATE_PASS = {
    "scores": {
        "explicitness": 5, "value": 4, "specificity": 4,
        "urgency": 4, "feasibility": 4, "evidence_strength": 5, "readiness": 5,
    },
    "avg_score": 4.43,
    "passed": True,
    "verbatim_evidence_quote": "I'll send that email to Alice",
    "missing_critical_info": [],
}

GATE_FAIL = {
    "scores": {
        "explicitness": 2, "value": 2, "specificity": 2,
        "urgency": 2, "feasibility": 2, "evidence_strength": 2, "readiness": 2,
    },
    "avg_score": 2.0,
    "passed": False,
    "verbatim_evidence_quote": None,
    "missing_critical_info": ["recipient unclear"],
}


@pytest.fixture
def session_ids():
    return uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def buffer():
    buf = RollingBuffer(window_s=9999)
    buf.add("Alice", "Let's send that email to Bob", 1000)
    buf.add("Bob", "Sounds good, I'll draft it", 2000)
    return buf


def _mock_db_context(session_obj, utterances, existing_proposals=None):
    """Create a mock async_session context that handles multiple queries."""
    existing_proposals = existing_proposals or []

    db = AsyncMock()
    call_count = 0

    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        # First call: session lookup
        if call_count == 1:
            result.scalar_one_or_none.return_value = session_obj
        # Second call: new utterances
        elif call_count == 2:
            result.scalars.return_value.all.return_value = utterances
        # Third call: existing proposals for dedup (_get_rag_context is patched)
        elif call_count == 3:
            result.scalars.return_value.all.return_value = existing_proposals
        else:
            result.scalars.return_value.all.return_value = []
        return result

    db.execute = mock_execute
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, db


@pytest.mark.asyncio
async def test_gate_pass_sets_pending_and_broadcasts_created(session_ids, buffer):
    """Proposals passing the gate get status=pending and broadcast proposal_created."""
    session_id, workspace_id = session_ids
    session_obj = _make_session(session_id, workspace_id)
    utterances = [_make_utterance(session_id, "Alice", "Send email to Bob", 1)]

    ctx, db = _mock_db_context(session_obj, utterances)

    raw_items = [{
        "title": "Send email to Bob",
        "action_type": "gmail_draft",
        "body": "Follow up on project",
        "recipient": "bob@example.com",
        "confidence": 0.9,
        "readiness": 5,
        "dedupe_key": "send-email-bob",
    }]

    mock_manager = AsyncMock()

    with (
        patch("src.workers.extraction_loop.async_session", return_value=ctx),
        patch("src.workers.extraction_loop.extract_action_items", new_callable=AsyncMock, return_value=raw_items),
        patch("src.workers.extraction_loop.is_duplicate", new_callable=AsyncMock, return_value=False),
        patch("src.workers.extraction_loop.get_embedding", new_callable=AsyncMock, return_value=[0.1] * 10),
        patch("src.workers.extraction_loop.gate", new_callable=lambda: MagicMock()) as mock_gate_mod,
        patch("src.workers.extraction_loop.manager", mock_manager),
        patch("src.workers.extraction_loop._get_rag_context", new_callable=AsyncMock, return_value=[]),
    ):
        mock_gate_mod.evaluate_action = AsyncMock(return_value=GATE_PASS)

        from src.workers.extraction_loop import _run_extraction_cycle
        result = await _run_extraction_cycle(str(session_id), buffer, None)

    # Verify proposal was added with gate data
    assert db.add.called
    proposal = db.add.call_args[0][0]
    assert proposal.status == ProposalStatus.pending
    assert proposal.gate_passed is True
    assert proposal.gate_scores == GATE_PASS["scores"]
    assert proposal.gate_avg_score == GATE_PASS["avg_score"]
    assert proposal.gate_readiness == 5
    assert proposal.gate_evidence_quote == GATE_PASS["verbatim_evidence_quote"]
    assert proposal.gate_missing_info == GATE_PASS["missing_critical_info"]

    # Verify broadcast was proposal_created with gate data
    mock_manager.broadcast.assert_called_once()
    broadcast_msg = mock_manager.broadcast.call_args[0][1]
    assert broadcast_msg["type"] == "proposal_created"
    assert broadcast_msg["data"]["gate_passed"] is True
    assert "gate_scores" in broadcast_msg["data"]


@pytest.mark.asyncio
async def test_gate_fail_sets_dropped_and_broadcasts_dropped(session_ids, buffer):
    """Proposals failing the gate get status=dropped and broadcast proposal_dropped."""
    session_id, workspace_id = session_ids
    session_obj = _make_session(session_id, workspace_id)
    utterances = [_make_utterance(session_id, "Alice", "Send email to Bob", 1)]

    ctx, db = _mock_db_context(session_obj, utterances)

    raw_items = [{
        "title": "Send email to Bob",
        "action_type": "gmail_draft",
        "body": "Follow up on project",
        "recipient": "bob@example.com",
        "confidence": 0.9,
        "readiness": 5,
        "dedupe_key": "send-email-bob",
    }]

    mock_manager = AsyncMock()

    with (
        patch("src.workers.extraction_loop.async_session", return_value=ctx),
        patch("src.workers.extraction_loop.extract_action_items", new_callable=AsyncMock, return_value=raw_items),
        patch("src.workers.extraction_loop.is_duplicate", new_callable=AsyncMock, return_value=False),
        patch("src.workers.extraction_loop.get_embedding", new_callable=AsyncMock, return_value=[0.1] * 10),
        patch("src.workers.extraction_loop.gate", new_callable=lambda: MagicMock()) as mock_gate_mod,
        patch("src.workers.extraction_loop.manager", mock_manager),
        patch("src.workers.extraction_loop._get_rag_context", new_callable=AsyncMock, return_value=[]),
    ):
        mock_gate_mod.evaluate_action = AsyncMock(return_value=GATE_FAIL)

        from src.workers.extraction_loop import _run_extraction_cycle
        result = await _run_extraction_cycle(str(session_id), buffer, None)

    # Verify proposal was added with dropped status
    assert db.add.called
    proposal = db.add.call_args[0][0]
    assert proposal.status == ProposalStatus.dropped
    assert proposal.gate_passed is False
    assert proposal.gate_scores == GATE_FAIL["scores"]
    assert proposal.gate_avg_score == GATE_FAIL["avg_score"]

    # Verify broadcast was proposal_dropped
    mock_manager.broadcast.assert_called_once()
    broadcast_msg = mock_manager.broadcast.call_args[0][1]
    assert broadcast_msg["type"] == "proposal_dropped"
    assert broadcast_msg["data"]["gate_passed"] is False
    assert "gate_scores" in broadcast_msg["data"]
    assert broadcast_msg["data"]["title"] == "Send email to Bob"


@pytest.mark.asyncio
async def test_gate_results_stored_on_proposal(session_ids, buffer):
    """All gate result fields are stored on the Proposal record."""
    session_id, workspace_id = session_ids
    session_obj = _make_session(session_id, workspace_id)
    utterances = [_make_utterance(session_id, "Alice", "Send email to Bob", 1)]

    ctx, db = _mock_db_context(session_obj, utterances)

    raw_items = [{
        "title": "Send email to Bob",
        "action_type": "gmail_draft",
        "body": "Follow up",
        "confidence": 0.9,
        "readiness": 5,
        "dedupe_key": "send-email-bob",
    }]

    gate_result = {
        "scores": {
            "explicitness": 3, "value": 3, "specificity": 4,
            "urgency": 5, "feasibility": 4, "evidence_strength": 3, "readiness": 4,
        },
        "avg_score": 3.71,
        "passed": True,
        "verbatim_evidence_quote": "Send that email",
        "missing_critical_info": ["deadline not specified"],
    }

    mock_manager = AsyncMock()

    with (
        patch("src.workers.extraction_loop.async_session", return_value=ctx),
        patch("src.workers.extraction_loop.extract_action_items", new_callable=AsyncMock, return_value=raw_items),
        patch("src.workers.extraction_loop.is_duplicate", new_callable=AsyncMock, return_value=False),
        patch("src.workers.extraction_loop.get_embedding", new_callable=AsyncMock, return_value=[0.1] * 10),
        patch("src.workers.extraction_loop.gate", new_callable=lambda: MagicMock()) as mock_gate_mod,
        patch("src.workers.extraction_loop.manager", mock_manager),
        patch("src.workers.extraction_loop._get_rag_context", new_callable=AsyncMock, return_value=[]),
    ):
        mock_gate_mod.evaluate_action = AsyncMock(return_value=gate_result)

        from src.workers.extraction_loop import _run_extraction_cycle
        await _run_extraction_cycle(str(session_id), buffer, None)

    proposal = db.add.call_args[0][0]
    assert proposal.gate_scores == gate_result["scores"]
    assert proposal.gate_avg_score == gate_result["avg_score"]
    assert proposal.gate_readiness == 4
    assert proposal.gate_evidence_quote == "Send that email"
    assert proposal.gate_missing_info == ["deadline not specified"]
    assert proposal.gate_passed is True
