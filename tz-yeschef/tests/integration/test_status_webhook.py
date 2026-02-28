"""Integration tests for the Recall status webhook."""
import pytest
from unittest.mock import patch, AsyncMock

from src.models.tables import MeetingStatus


@pytest.mark.asyncio
class TestStatusWebhook:

    async def test_done_status_ends_session(self, client, workspace, active_session, db_session):
        active_session.status = MeetingStatus.active
        await db_session.commit()

        resp = await client.post(
            f"/webhooks/recall/{workspace.webhook_secret}/status",
            json={
                "bot_id": active_session.recall_bot_id,
                "data": {"status": {"code": "done"}},
            },
        )
        assert resp.status_code == 200
        await db_session.refresh(active_session)
        assert active_session.status == MeetingStatus.ended
        assert active_session.ended_at is not None

    async def test_fatal_status_ends_session(self, client, workspace, active_session, db_session):
        resp = await client.post(
            f"/webhooks/recall/{workspace.webhook_secret}/status",
            json={
                "bot_id": active_session.recall_bot_id,
                "data": {"status": {"code": "fatal"}},
            },
        )
        assert resp.status_code == 200
        await db_session.refresh(active_session)
        assert active_session.status == MeetingStatus.ended

    async def test_in_call_recording_activates_session(self, client, workspace, active_session, db_session):
        resp = await client.post(
            f"/webhooks/recall/{workspace.webhook_secret}/status",
            json={
                "bot_id": active_session.recall_bot_id,
                "data": {"status": {"code": "in_call_recording"}},
            },
        )
        assert resp.status_code == 200
        await db_session.refresh(active_session)
        assert active_session.status == MeetingStatus.active
        assert active_session.started_at is not None

    async def test_status_broadcasts_via_ws(self, client, workspace, active_session):
        broadcast_calls = []

        async def mock_broadcast(ws_id, msg):
            broadcast_calls.append(msg)

        with patch("src.services.ws_manager.manager.broadcast", side_effect=mock_broadcast):
            await client.post(
                f"/webhooks/recall/{workspace.webhook_secret}/status",
                json={
                    "bot_id": active_session.recall_bot_id,
                    "data": {"status": {"code": "done"}},
                },
            )

        assert any(c["type"] == "meeting_status" for c in broadcast_calls)

    async def test_invalid_bot_id_returns_404(self, client, workspace):
        resp = await client.post(
            f"/webhooks/recall/{workspace.webhook_secret}/status",
            json={
                "bot_id": "nonexistent-bot",
                "data": {"status": {"code": "done"}},
            },
        )
        assert resp.status_code == 404
