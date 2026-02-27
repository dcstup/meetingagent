import httpx
import logging

from src.config import Settings

logger = logging.getLogger(__name__)


class MeetingBot:
    """Manages a Recall.ai bot that joins a Zoom meeting with Deepgram transcription."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = f"https://{settings.recall_region}.recall.ai/api/v1"
        self.headers = {
            "Authorization": f"Token {settings.recall_api_key}",
            "Content-Type": "application/json",
        }
        self.bot_id: str | None = None
        self._client = httpx.AsyncClient(headers=self.headers, timeout=30.0)

    async def create_and_join(self, meeting_url: str, webhook_url: str) -> str:
        """Create a bot that joins the meeting with real-time transcription webhooks."""
        payload = {
            "meeting_url": meeting_url,
            "bot_name": self.settings.bot_name,
            "recording_config": {
                "transcript": {
                    "provider": {"deepgram_streaming": {}},
                    "diarization": {
                        "use_separate_streams_when_available": True,
                    },
                },
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": webhook_url,
                        "events": [
                            "transcript.data",
                            "transcript.partial_data",
                            "participant_events.join",
                            "participant_events.leave",
                        ],
                    }
                ],
            },
        }

        response = await self._client.post(f"{self.base_url}/bot/", json=payload)
        if response.status_code >= 400:
            logger.error(f"Recall.ai API error {response.status_code}: {response.text}")
        response.raise_for_status()
        data = response.json()
        self.bot_id = data["id"]
        logger.info(f"Bot created: {self.bot_id}")
        return self.bot_id

    async def get_status(self) -> dict:
        """Check the bot's current status."""
        response = await self._client.get(f"{self.base_url}/bot/{self.bot_id}/")
        response.raise_for_status()
        return response.json()

    async def leave_meeting(self) -> None:
        """Remove the bot from the meeting."""
        if self.bot_id:
            response = await self._client.post(
                f"{self.base_url}/bot/{self.bot_id}/leave_call/"
            )
            response.raise_for_status()
            logger.info(f"Bot {self.bot_id} left meeting")

    async def send_chat_message(self, message: str) -> None:
        """Send a message to the meeting chat."""
        if self.bot_id:
            response = await self._client.post(
                f"{self.base_url}/bot/{self.bot_id}/send_chat_message/",
                json={"message": message},
            )
            response.raise_for_status()
            logger.info(f"Chat message sent: {message[:80]}...")

    async def close(self) -> None:
        await self._client.aclose()
