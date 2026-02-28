"""Unit tests for the WebSocket connection manager."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.services.ws_manager import ConnectionManager


@pytest.mark.asyncio
class TestConnectionManager:

    async def test_connect_and_disconnect(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect("ws-1", ws)
        assert "ws-1" in mgr._connections
        assert len(mgr._connections["ws-1"]) == 1

        mgr.disconnect("ws-1", ws)
        assert "ws-1" not in mgr._connections

    async def test_broadcast_sends_to_all(self):
        mgr = ConnectionManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect("ws-1", ws1)
        await mgr.connect("ws-1", ws2)

        await mgr.broadcast("ws-1", {"type": "test"})
        ws1.send_json.assert_called_once_with({"type": "test"})
        ws2.send_json.assert_called_once_with({"type": "test"})

    async def test_broadcast_removes_dead_connections(self):
        mgr = ConnectionManager()
        ws_good = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_json.side_effect = RuntimeError("closed")

        await mgr.connect("ws-1", ws_good)
        await mgr.connect("ws-1", ws_dead)
        assert len(mgr._connections["ws-1"]) == 2

        await mgr.broadcast("ws-1", {"type": "test"})
        assert len(mgr._connections["ws-1"]) == 1
        assert mgr._connections["ws-1"][0] is ws_good

    async def test_broadcast_no_op_for_unknown_workspace(self):
        mgr = ConnectionManager()
        await mgr.broadcast("nonexistent", {"type": "test"})  # should not raise

    async def test_disconnect_unknown_workspace(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        mgr.disconnect("nonexistent", ws)  # should not raise

    async def test_send_personal_success(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.send_personal(ws, {"type": "hello"})
        ws.send_json.assert_called_once_with({"type": "hello"})

    async def test_send_personal_error_swallowed(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.send_json.side_effect = RuntimeError("closed")
        await mgr.send_personal(ws, {"type": "hello"})  # should not raise
