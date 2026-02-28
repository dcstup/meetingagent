import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

from src.db.engine import async_session
from src.models.tables import Workspace
from src.services.ws_manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    workspace: str = Query(...),
):
    """WebSocket endpoint for real-time updates.

    First message must be: {"type": "auth", "token": "<overlay_token>"}
    """
    await websocket.accept()

    # Wait for auth message
    try:
        raw = await websocket.receive_text()
        msg = json.loads(raw)
        if msg.get("type") != "auth":
            await websocket.send_json({"type": "error", "data": {"message": "Unauthorized"}})
            await websocket.close(code=4001)
            return

        # Validate token against workspace record
        async with async_session() as db:
            result = await db.execute(
                select(Workspace).where(Workspace.id == uuid.UUID(workspace))
            )
            ws_record = result.scalar_one_or_none()
            if not ws_record or msg.get("token") != ws_record.overlay_token:
                await websocket.send_json({"type": "error", "data": {"message": "Unauthorized"}})
                await websocket.close(code=4001)
                return
    except Exception:
        await websocket.close(code=4001)
        return

    # Register connection (already accepted above)
    if workspace not in manager._connections:
        manager._connections[workspace] = []
    manager._connections[workspace].append(websocket)

    await websocket.send_json({"type": "auth_ok", "data": {}})

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong", "data": {}})
    except WebSocketDisconnect:
        manager.disconnect(workspace, websocket)
    except Exception:
        manager.disconnect(workspace, websocket)
