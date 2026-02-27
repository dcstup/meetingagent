import asyncio
import logging

from src.agent.actions import ActionExecutor
from src.agent.brain import AgentBrain
from src.bot.recall_bot import MeetingBot
from src.config import Settings
from src.transcription.transcript_manager import TranscriptManager

logger = logging.getLogger(__name__)


class MeetingSession:
    """Orchestrates a single meeting: bot lifecycle, transcription, and agent loop."""

    def __init__(self, settings: Settings, meeting_url: str):
        self.settings = settings
        self.meeting_url = meeting_url
        self.transcript_manager = TranscriptManager(settings)
        self.meeting_bot = MeetingBot(settings)
        self.action_executor = ActionExecutor(settings)
        self.agent_brain = AgentBrain(
            settings=settings,
            transcript_manager=self.transcript_manager,
            action_executor=self.action_executor,
            send_chat_fn=self.meeting_bot.send_chat_message,
        )
        self._running = False

    async def start(self, webhook_url: str) -> str:
        """Create bot, join meeting, start agent loop. Returns bot ID."""
        logger.info(f"Starting session for: {self.meeting_url}")

        bot_id = await self.meeting_bot.create_and_join(
            self.meeting_url, webhook_url
        )
        await self.agent_brain.start()
        self._running = True

        logger.info(f"Bot {bot_id} joining meeting, agent listening...")
        return bot_id

    async def poll_until_done(self) -> None:
        """Block until the meeting ends or the bot is removed."""
        while self._running:
            await asyncio.sleep(10)
            if not self._running:
                break
            try:
                data = await self.meeting_bot.get_status()
                status_changes = data.get("status_changes", [])
                if status_changes:
                    latest = status_changes[-1].get("code", "")
                    logger.debug(f"Bot status: {latest}")
                    if latest in ("done", "fatal", "call_ended"):
                        msg = status_changes[-1].get("message", "")
                        logger.info(f"Meeting ended ({latest}): {msg}")
                        break
            except RuntimeError:
                # Client was closed — session is shutting down
                break
            except Exception:
                logger.exception("Error polling bot status")

    async def stop(self) -> None:
        """Clean shutdown. Safe to call multiple times."""
        if not self._running:
            return
        self._running = False
        logger.info("Stopping meeting session...")
        await self.agent_brain.stop()
        try:
            await self.meeting_bot.leave_meeting()
        except Exception as e:
            logger.warning(f"Error leaving meeting: {e}")
        await self.meeting_bot.close()
        logger.info("Session stopped.")

    @property
    def is_running(self) -> bool:
        return self._running
