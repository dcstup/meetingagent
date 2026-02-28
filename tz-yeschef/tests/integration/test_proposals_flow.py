"""Integration tests for proposal approve/dismiss flow."""
import uuid
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.models.tables import (
    Proposal, Execution, ProposalStatus, ExecutionStatus,
)


@pytest_asyncio.fixture
async def proposal(db_session, active_session):
    p = Proposal(
        session_id=active_session.id,
        action_type="gmail_draft",
        title="Follow up on Q3 report",
        body="Hi team, please review the Q3 report.",
        recipient="team@example.com",
        confidence=0.85,
        dedupe_key="follow-up-q3",
        dedupe_hash="abc123",
        status=ProposalStatus.pending,
        source_text="We need to follow up on the Q3 report.",
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.mark.asyncio
class TestApproveProposal:

    async def test_approve_creates_execution(self, client, proposal, db_session):
        with patch("src.api.routes_proposals._run_execution", new_callable=AsyncMock):
            resp = await client.post(f"/api/proposals/{proposal.id}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        result = await db_session.execute(select(Execution))
        execution = result.scalar_one()
        assert execution.proposal_id == proposal.id
        assert execution.status == ExecutionStatus.pending

    async def test_approve_already_approved_returns_400(self, client, proposal, db_session):
        proposal.status = ProposalStatus.approved
        await db_session.commit()
        resp = await client.post(f"/api/proposals/{proposal.id}/approve")
        assert resp.status_code == 400

    async def test_approve_nonexistent_returns_404(self, client):
        resp = await client.post(f"/api/proposals/{uuid.uuid4()}/approve")
        assert resp.status_code == 404

    async def test_approve_broadcasts_execution_started(self, client, proposal):
        broadcast_calls = []

        async def mock_broadcast(ws_id, msg):
            broadcast_calls.append(msg)

        with patch("src.services.ws_manager.manager.broadcast", side_effect=mock_broadcast), \
             patch("src.api.routes_proposals._run_execution", new_callable=AsyncMock):
            await client.post(f"/api/proposals/{proposal.id}/approve")

        types = [c["type"] for c in broadcast_calls]
        assert "execution_started" in types


@pytest.mark.asyncio
class TestDismissProposal:

    async def test_dismiss_updates_status(self, client, proposal, db_session):
        resp = await client.post(f"/api/proposals/{proposal.id}/dismiss")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

        await db_session.refresh(proposal)
        assert proposal.status == ProposalStatus.dismissed

    async def test_dismiss_broadcasts_update(self, client, proposal):
        broadcast_calls = []

        async def mock_broadcast(ws_id, msg):
            broadcast_calls.append(msg)

        with patch("src.services.ws_manager.manager.broadcast", side_effect=mock_broadcast):
            await client.post(f"/api/proposals/{proposal.id}/dismiss")

        types = [c["type"] for c in broadcast_calls]
        assert "proposal_updated" in types

    async def test_dismiss_already_dismissed_returns_400(self, client, proposal, db_session):
        proposal.status = ProposalStatus.dismissed
        await db_session.commit()
        resp = await client.post(f"/api/proposals/{proposal.id}/dismiss")
        assert resp.status_code == 400
