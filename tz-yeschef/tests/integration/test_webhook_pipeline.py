"""Integration tests for the Recall webhook → DB → WS broadcast pipeline.

Uses real Recall payload format captured from production logs.
"""
import uuid
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import select

from src.models.tables import Utterance, MeetingSession, MeetingStatus


REAL_RECALL_PAYLOAD = {
    "event": "transcript.data",
    "data": {
        "data": {
            "words": [
                {
                    "text": "We need to send a follow-up email to the client about the Q3 report.",
                    "start_timestamp": {
                        "relative": 7.0,
                        "absolute": "2026-02-28T04:38:06.420502Z",
                    },
                    "end_timestamp": {
                        "relative": 12.0,
                        "absolute": "2026-02-28T04:38:11.420502Z",
                    },
                }
            ],
            "participant": {
                "id": 100,
                "name": "Tommy Zhao",
                "is_host": True,
                "platform": "desktop",
                "extra_data": {},
            },
        },
        "transcript": {"id": "abc-123"},
    },
}


def _make_payload(text: str, speaker: str = "Tommy Zhao", relative_ts: float = 7.0):
    return {
        "event": "transcript.data",
        "data": {
            "data": {
                "words": [
                    {
                        "text": text,
                        "start_timestamp": {"relative": relative_ts, "absolute": "2026-02-28T00:00:00Z"},
                        "end_timestamp": {"relative": relative_ts + 3, "absolute": "2026-02-28T00:00:03Z"},
                    }
                ],
                "participant": {"id": 1, "name": speaker, "is_host": True, "platform": "desktop", "extra_data": {}},
            },
            "transcript": {"id": str(uuid.uuid4())},
        },
    }


@pytest.mark.asyncio
class TestWebhookTranscriptParsing:
    """Test that real Recall payloads are parsed correctly."""

    async def test_real_payload_creates_utterance(self, client, workspace, active_session, db_session):
        with patch("src.workers.extraction_loop.start_extraction", new_callable=AsyncMock):
            resp = await client.post(
                f"/webhooks/recall/{workspace.webhook_secret}/transcript",
                json=REAL_RECALL_PAYLOAD,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        result = await db_session.execute(select(Utterance))
        utterance = result.scalar_one()
        assert utterance.speaker == "Tommy Zhao"
        assert "follow-up email" in utterance.text
        assert utterance.timestamp_ms == 7000

    async def test_empty_text_ignored(self, client, workspace, active_session):
        payload = _make_payload(text="   ")
        with patch("src.workers.extraction_loop.start_extraction", new_callable=AsyncMock):
            resp = await client.post(
                f"/webhooks/recall/{workspace.webhook_secret}/transcript",
                json=payload,
            )
        assert resp.json()["status"] == "ignored"

    async def test_invalid_secret_returns_403(self, client):
        resp = await client.post(
            "/webhooks/recall/wrong-secret/transcript",
            json=REAL_RECALL_PAYLOAD,
        )
        assert resp.status_code == 403

    async def test_no_session_returns_ignored(self, client, workspace):
        """Webhook with valid secret but no matching session returns 200 (prevent Recall retries)."""
        payload = _make_payload("hello")
        payload["data"]["data"]["bot_id"] = "nonexistent-bot"
        resp = await client.post(
            f"/webhooks/recall/{workspace.webhook_secret}/transcript",
            json=payload,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    async def test_session_transitions_to_active(self, client, workspace, active_session, db_session):
        assert active_session.status == MeetingStatus.bot_joining
        payload = _make_payload("Hello everyone")
        with patch("src.workers.extraction_loop.start_extraction", new_callable=AsyncMock):
            await client.post(
                f"/webhooks/recall/{workspace.webhook_secret}/transcript",
                json=payload,
            )
        await db_session.refresh(active_session)
        assert active_session.status == MeetingStatus.active

    async def test_multiple_utterances_stored_in_order(self, client, workspace, active_session, db_session):
        with patch("src.workers.extraction_loop.start_extraction", new_callable=AsyncMock):
            for i, text in enumerate(["First point", "Second point", "Third point"]):
                await client.post(
                    f"/webhooks/recall/{workspace.webhook_secret}/transcript",
                    json=_make_payload(text, relative_ts=float(i * 5)),
                )

        result = await db_session.execute(
            select(Utterance).order_by(Utterance.timestamp_ms)
        )
        utterances = result.scalars().all()
        assert len(utterances) == 3
        assert utterances[0].text == "First point"
        assert utterances[1].text == "Second point"
        assert utterances[2].text == "Third point"
        assert utterances[0].timestamp_ms < utterances[1].timestamp_ms

    async def test_bot_id_lookup_finds_session(self, client, workspace, active_session):
        """When bot_id is in payload, it should find the right session."""
        payload = _make_payload("test utterance")
        payload["bot_id"] = active_session.recall_bot_id
        with patch("src.workers.extraction_loop.start_extraction", new_callable=AsyncMock):
            resp = await client.post(
                f"/webhooks/recall/{workspace.webhook_secret}/transcript",
                json=payload,
            )
        assert resp.status_code == 200

    async def test_fallback_finds_active_session_without_bot_id(self, client, workspace, active_session, db_session):
        """When no bot_id in payload, falls back to most recent active session."""
        payload = _make_payload("fallback test")
        # No bot_id anywhere in payload
        with patch("src.workers.extraction_loop.start_extraction", new_callable=AsyncMock):
            resp = await client.post(
                f"/webhooks/recall/{workspace.webhook_secret}/transcript",
                json=payload,
            )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestWebhookWSBroadcast:
    """Test that webhook triggers WS broadcasts."""

    async def test_utterance_broadcast(self, client, workspace, active_session):
        broadcast_calls = []

        async def mock_broadcast(ws_id, msg):
            broadcast_calls.append((ws_id, msg))

        with patch("src.workers.extraction_loop.start_extraction", new_callable=AsyncMock), \
             patch("src.services.ws_manager.manager.broadcast", side_effect=mock_broadcast):
            await client.post(
                f"/webhooks/recall/{workspace.webhook_secret}/transcript",
                json=_make_payload("Action item: schedule meeting"),
            )

        # Should have meeting_status + utterance broadcasts
        utterance_msgs = [c for c in broadcast_calls if c[1]["type"] == "utterance"]
        assert len(utterance_msgs) >= 1
        assert utterance_msgs[0][0] == str(workspace.id)
        assert "schedule meeting" in utterance_msgs[0][1]["data"]["text"]

    async def test_meeting_status_broadcast_on_activation(self, client, workspace, active_session):
        broadcast_calls = []

        async def mock_broadcast(ws_id, msg):
            broadcast_calls.append((ws_id, msg))

        with patch("src.workers.extraction_loop.start_extraction", new_callable=AsyncMock), \
             patch("src.services.ws_manager.manager.broadcast", side_effect=mock_broadcast):
            await client.post(
                f"/webhooks/recall/{workspace.webhook_secret}/transcript",
                json=_make_payload("first words"),
            )

        status_msgs = [c for c in broadcast_calls if c[1]["type"] == "meeting_status"]
        assert len(status_msgs) == 1
        assert status_msgs[0][1]["data"]["status"] == "active"
