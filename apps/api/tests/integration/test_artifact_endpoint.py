"""Integration tests for the artifact serving endpoint."""
import uuid
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.models.tables import (
    Proposal, Execution, ProposalStatus, ExecutionStatus,
)


@pytest_asyncio.fixture
async def artifact_proposal(db_session, active_session):
    p = Proposal(
        session_id=active_session.id,
        action_type="html_artifact",
        title="Mock up login page",
        body="Create a login page with email and password fields",
        confidence=0.9,
        dedupe_key="mockup-login",
        dedupe_hash="xyz789",
        status=ProposalStatus.approved,
        source_text="Let's mock up a login page",
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def artifact_execution(db_session, artifact_proposal):
    e = Execution(
        proposal_id=artifact_proposal.id,
        status=ExecutionStatus.success,
        result={"status": "success", "type": "html_artifact", "title": "Login page"},
        artifact_html="<html><body><h1>Login</h1></body></html>",
    )
    db_session.add(e)
    await db_session.commit()
    await db_session.refresh(e)
    return e


@pytest.mark.asyncio
class TestGetArtifact:

    async def test_wrapper_contains_navbar(self, client, artifact_execution):
        resp = await client.get(f"/api/artifacts/{artifact_execution.id}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "YesChef" in resp.text
        assert "Login page" in resp.text  # title in navbar
        assert "/raw" in resp.text  # iframe src points to raw

    async def test_raw_returns_artifact_html(self, client, artifact_execution):
        resp = await client.get(f"/api/artifacts/{artifact_execution.id}/raw")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "<h1>Login</h1>" in resp.text

    async def test_missing_execution_returns_404(self, client):
        resp = await client.get(f"/api/artifacts/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_raw_missing_returns_404(self, client):
        resp = await client.get(f"/api/artifacts/{uuid.uuid4()}/raw")
        assert resp.status_code == 404

    async def test_no_artifact_html_returns_404(self, client, db_session, artifact_proposal):
        e = Execution(
            proposal_id=artifact_proposal.id,
            status=ExecutionStatus.success,
            result={"status": "success"},
        )
        db_session.add(e)
        await db_session.commit()
        await db_session.refresh(e)

        resp = await client.get(f"/api/artifacts/{e.id}")
        assert resp.status_code == 404
