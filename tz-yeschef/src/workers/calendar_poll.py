import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.config.constants import CALENDAR_POLL_INTERVAL_S, CALENDAR_LOOKAHEAD_S
from src.db.engine import async_session
from src.models.tables import Workspace, CalendarEvent, MeetingSession, MeetingStatus
from src.services.calendar_watcher import extract_meet_url
from src.services.recall import create_bot

logger = logging.getLogger(__name__)


async def poll_calendar_events():
    """Poll for upcoming calendar events and create bots for meetings starting soon."""
    while True:
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(Workspace).where(Workspace.composio_entity_id.isnot(None))
                )
                workspaces = result.scalars().all()

            # Process each workspace with its own session to isolate failures
            for workspace in workspaces:
                try:
                    async with async_session() as ws_db:
                        await _check_workspace_events(ws_db, workspace)
                except Exception as e:
                    logger.error(f"Error checking workspace {workspace.id}: {e}")
        except Exception as e:
            logger.error(f"Calendar poll error: {e}")

        await asyncio.sleep(CALENDAR_POLL_INTERVAL_S)


async def _check_workspace_events(db: AsyncSession, workspace):
    """Check a workspace's calendar for imminent meetings."""
    try:
        from composio import Composio

        sdk = Composio(api_key=settings.composio_api_key)

        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(seconds=CALENDAR_LOOKAHEAD_S)).isoformat()

        # Use Composio to fetch calendar events
        response = sdk.tools.execute(
            slug="GOOGLECALENDAR_FIND_EVENT",
            arguments={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": True,
                "orderBy": "startTime",
            },
            user_id=workspace.composio_entity_id,
            dangerously_skip_version_check=True,
        )

        resp_data = response if isinstance(response, dict) else getattr(response, 'data', {})
        if isinstance(resp_data, dict):
            events = resp_data.get("items", resp_data.get("data", {}).get("items", []))
        elif isinstance(resp_data, list):
            events = resp_data
        else:
            events = []

        for event in events:
            meet_url = extract_meet_url(event)
            if not meet_url:
                continue

            google_event_id = event.get("id", "")

            # Check if already tracked
            existing = await db.execute(
                select(CalendarEvent).where(CalendarEvent.google_event_id == google_event_id)
            )
            if existing.scalar_one_or_none():
                continue

            # Create calendar event record
            cal_event = CalendarEvent(
                workspace_id=workspace.id,
                google_event_id=google_event_id,
                title=event.get("summary", "Untitled"),
                meet_url=meet_url,
                start_time=datetime.fromisoformat(
                    event["start"].get("dateTime", event["start"].get("date"))
                ),
                end_time=datetime.fromisoformat(
                    event["end"].get("dateTime", event["end"].get("date"))
                ),
            )
            db.add(cal_event)
            await db.flush()

            # Create meeting session
            webhook_url = (
                f"{settings.app_public_url}/webhooks/recall/"
                f"{workspace.webhook_secret}/transcript"
            )
            bot_resp = await create_bot(meet_url, webhook_url)
            bot_id = bot_resp.get("id")
            if not bot_id:
                logger.error(f"Recall.ai returned no bot id for {meet_url}: {bot_resp}")
                continue

            meeting = MeetingSession(
                workspace_id=workspace.id,
                calendar_event_id=cal_event.id,
                recall_bot_id=bot_id,
                meet_url=meet_url,
                status=MeetingStatus.bot_joining,
            )
            db.add(meeting)
            await db.commit()

            logger.info(f"Created bot for meeting: {cal_event.title} ({meet_url})")

            # Broadcast meeting status
            try:
                from src.services.ws_manager import manager
                await manager.broadcast(str(workspace.id), {
                    "type": "meeting_status",
                    "data": {
                        "session_id": str(meeting.id),
                        "status": meeting.status.value,
                        "title": cal_event.title,
                        "meet_url": meet_url,
                    },
                })
            except Exception:
                pass
    except ImportError as e:
        logger.warning(f"Composio not available ({e}), skipping calendar poll")
    except Exception as e:
        logger.error(f"Error fetching calendar for workspace {workspace.id}: {e}")
