import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections per workspace."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, workspace_id: str, websocket: WebSocket):
        await websocket.accept()
        if workspace_id not in self._connections:
            self._connections[workspace_id] = []
        self._connections[workspace_id].append(websocket)
        logger.info(
            f"WS connected: workspace={workspace_id}, "
            f"total={len(self._connections[workspace_id])}"
        )

    def disconnect(self, workspace_id: str, websocket: WebSocket):
        if workspace_id in self._connections:
            self._connections[workspace_id] = [
                ws for ws in self._connections[workspace_id] if ws != websocket
            ]
            if not self._connections[workspace_id]:
                del self._connections[workspace_id]
        logger.info(f"WS disconnected: workspace={workspace_id}")

    async def broadcast(self, workspace_id: str, message: dict[str, Any]):
        if workspace_id not in self._connections:
            return
        dead: list[WebSocket] = []
        for ws in self._connections[workspace_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(workspace_id, ws)

    async def send_personal(self, websocket: WebSocket, message: dict[str, Any]):
        try:
            await websocket.send_json(message)
        except Exception:
            pass


manager = ConnectionManager()
