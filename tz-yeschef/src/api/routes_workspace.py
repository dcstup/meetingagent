import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models.tables import Workspace
from src.config import settings

router = APIRouter(prefix="/api")


@router.post("/workspace/init")
async def init_workspace(db: AsyncSession = Depends(get_db)):
    """Create or return existing workspace (single-user MVP)."""
    result = await db.execute(select(Workspace).limit(1))
    workspace = result.scalar_one_or_none()

    if workspace:
        return {
            "workspace_id": str(workspace.id),
            "overlay_token": workspace.overlay_token,
            "has_google": workspace.composio_entity_id is not None,
            "has_google_calendar": workspace.has_google_calendar,
        }

    workspace = Workspace(
        overlay_token=secrets.token_urlsafe(32),
        webhook_secret=secrets.token_urlsafe(32),
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)

    # Update global settings
    settings.webhook_secret = workspace.webhook_secret
    settings.overlay_token = workspace.overlay_token

    return {
        "workspace_id": str(workspace.id),
        "overlay_token": workspace.overlay_token,
        "has_google": False,
        "has_google_calendar": False,
    }


@router.get("/workspace/oauth/google")
async def oauth_google(db: AsyncSession = Depends(get_db)):
    """Initiate Google OAuth via Composio."""
    result = await db.execute(select(Workspace).limit(1))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="No workspace found")

    entity_id = str(workspace.id)
    redirect_url = f"{settings.app_public_url}/api/workspace/oauth/callback"

    from src.services.composio_client import initiate_oauth, initiate_gcal_oauth
    try:
        auth_url = initiate_oauth(entity_id, redirect_url)
    except Exception:
        # Gmail already connected, try Calendar
        auth_url = initiate_gcal_oauth(entity_id, redirect_url)

    return {"auth_url": auth_url}


@router.post("/workspace/oauth/google-calendar")
async def oauth_google_calendar(db: AsyncSession = Depends(get_db)):
    """Initiate Google Calendar OAuth via Composio."""
    result = await db.execute(select(Workspace).limit(1))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="No workspace found")
    if not workspace.composio_entity_id:
        raise HTTPException(status_code=400, detail="Connect Google (Gmail) first")

    entity_id = str(workspace.id)
    redirect_url = f"{settings.app_public_url}/api/workspace/oauth/callback"

    from src.services.composio_client import initiate_gcal_oauth
    auth_url = initiate_gcal_oauth(entity_id, redirect_url)
    return {"url": auth_url}


@router.get("/workspace/oauth/callback")
async def oauth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle OAuth callback from Composio."""
    result = await db.execute(select(Workspace).limit(1))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="No workspace found")

    workspace.composio_entity_id = str(workspace.id)
    await db.commit()

    # Also initiate Google Calendar OAuth if Gmail was just connected
    gcal_url = None
    try:
        from src.services.composio_client import initiate_gcal_oauth
        redirect_url = f"{settings.app_public_url}/api/workspace/oauth/callback"
        gcal_url = initiate_gcal_oauth(str(workspace.id), redirect_url)
    except Exception:
        pass

    if gcal_url:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=gcal_url)

    # If we didn't redirect to gcal OAuth, calendar OAuth just completed
    workspace.has_google_calendar = True
    await db.commit()

    return {"status": "connected", "message": "Google account connected successfully"}


@router.post("/meeting/join")
async def join_meeting(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a bot to join a Google Meet URL."""
    from src.adapters import get_adapter
    from src.models.tables import MeetingSession, MeetingStatus

    body = await request.json()
    meet_url = body.get("meet_url", "").strip()
    adapter_type = body.get("adapter_type", "recall")

    if adapter_type == "recall" and (not meet_url or "meet.google.com" not in meet_url):
        raise HTTPException(status_code=400, detail="Invalid Google Meet URL")

    result = await db.execute(select(Workspace).limit(1))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="No workspace found")

    webhook_url = (
        f"{settings.app_public_url}/webhooks/recall/"
        f"{workspace.webhook_secret}/transcript"
    )

    adapter = get_adapter(adapter_type)
    metadata = await adapter.start_session(
        workspace_id=str(workspace.id),
        meeting_url=meet_url,
        webhook_url=webhook_url,
    )

    meeting = MeetingSession(
        workspace_id=workspace.id,
        recall_bot_id=metadata.adapter_session_id if adapter_type == "recall" else None,
        adapter_type=adapter_type,
        adapter_session_id=metadata.adapter_session_id,
        meet_url=meet_url or "",
        status=MeetingStatus.bot_joining if adapter_type == "recall" else MeetingStatus.connecting,
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)

    # Broadcast
    try:
        from src.services.ws_manager import manager
        await manager.broadcast(str(workspace.id), {
            "type": "meeting_status",
            "data": {
                "session_id": str(meeting.id),
                "status": meeting.status.value,
                "meet_url": meet_url,
            },
        })
    except Exception:
        pass

    return {
        "session_id": str(meeting.id),
        "bot_id": metadata.adapter_session_id,
        "status": meeting.status.value,
    }
