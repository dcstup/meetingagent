"""RecallAdapter — wraps the Recall.ai client behind the TranscriptAdapter interface."""

from src.adapters.base import (
    AdapterStatus,
    AdapterType,
    NormalizedUtterance,
    SessionMetadata,
    TranscriptAdapter,
)
from src.adapters.recall.client import create_bot, get_bot_status
from src.adapters.recall.webhook_parser import parse_transcript_payload, parse_status_payload


class RecallAdapter(TranscriptAdapter):
    adapter_type = AdapterType.RECALL

    def __init__(self, webhook_url_template: str = "", **kwargs):
        # webhook_url_template can contain {secret} placeholder
        self._webhook_url_template = webhook_url_template

    async def start_session(
        self, workspace_id: str, meeting_url: str, **kwargs
    ) -> SessionMetadata:
        webhook_url = kwargs.get("webhook_url", "")
        if not webhook_url and self._webhook_url_template:
            webhook_url = self._webhook_url_template.format(**kwargs)

        bot_resp = await create_bot(meeting_url, webhook_url)
        bot_id = bot_resp.get("id", "")

        return SessionMetadata(
            adapter_session_id=bot_id,
            meeting_url=meeting_url,
            platform="recall",
        )

    async def stop_session(self, adapter_session_id: str) -> None:
        # Recall bots leave when the meeting ends or can be stopped via API.
        # For now this is a no-op; a future iteration could call the
        # Recall "remove bot" endpoint.
        pass

    async def get_status(self, adapter_session_id: str) -> AdapterStatus:
        data = await get_bot_status(adapter_session_id)
        status_code = data.get("status", {}).get("code", "")
        if status_code in ("done", "fatal"):
            return AdapterStatus.ENDED
        elif status_code == "in_call_recording":
            return AdapterStatus.ACTIVE
        else:
            return AdapterStatus.CONNECTING

    def parse_webhook(self, payload: dict) -> tuple[str, list[NormalizedUtterance]]:
        return parse_transcript_payload(payload)

    def parse_status_webhook(self, payload: dict) -> tuple[str, AdapterStatus]:
        return parse_status_payload(payload)
