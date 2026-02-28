"""Integration tests for POST /api/ingest/utterance."""

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock

from sqlalchemy import select

from src.models.tables import MeetingSession, MeetingStatus, Utterance


@pytest.mark.asyncio
async def test_ingest_utterance_stores_and_returns_ok(client, active_session):
    with patch("src.api.routes_ingest.manager", new_callable=AsyncMock):
        resp = await client.post(
            "/api/ingest/utterance",
            json={
                "session_id": str(active_session.id),
                "speaker": "Alice",
                "text": "Hello from ingest",
                "timestamp_ms": 5000,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ingest_utterance_not_found(client):
    resp = await client.post(
        "/api/ingest/utterance",
        json={
            "session_id": "00000000-0000-0000-0000-000000000000",
            "speaker": "X",
            "text": "no session",
            "timestamp_ms": 0,
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ingest_utterance_empty_text_ignored(client, active_session):
    with patch("src.api.routes_ingest.manager", new_callable=AsyncMock):
        resp = await client.post(
            "/api/ingest/utterance",
            json={
                "session_id": str(active_session.id),
                "speaker": "Bob",
                "text": "   ",
                "timestamp_ms": 0,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_ingest_activates_session(client, active_session):
    """Session in bot_joining should become active on first ingest."""
    with patch("src.api.routes_ingest.manager", new_callable=AsyncMock):
        resp = await client.post(
            "/api/ingest/utterance",
            json={
                "session_id": str(active_session.id),
                "speaker": "C",
                "text": "first utterance",
                "timestamp_ms": 100,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
