"""Recall.ai HTTP client — canonical location.

This module contains the actual Recall API interaction logic.
src/services/recall.py re-exports from here for backwards compatibility.
"""

import httpx

from src.config import settings

RECALL_BASE = "https://us-west-2.recall.ai/api/v1"


async def create_bot(meet_url: str, webhook_url: str) -> dict:
    """Create a Recall.ai bot to join a Google Meet."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RECALL_BASE}/bot",
            headers={"Authorization": f"Token {settings.recall_api_key}"},
            json={
                "meeting_url": meet_url,
                "bot_name": settings.bot_name,
                "recording_config": {
                    "transcript": {
                        "provider": {"meeting_captions": {}},
                    },
                    "realtime_endpoints": [
                        {
                            "type": "webhook",
                            "url": webhook_url,
                            "events": ["transcript.data"],
                        }
                    ],
                },
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()


async def get_bot_status(bot_id: str) -> dict:
    """Get the status of a Recall.ai bot."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RECALL_BASE}/bot/{bot_id}",
            headers={"Authorization": f"Token {settings.recall_api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()
