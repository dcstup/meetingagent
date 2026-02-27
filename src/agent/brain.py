import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import anthropic

from src.agent.actions import ActionExecutor, SEND_CHAT_MESSAGE_TOOL
from src.agent.prompts import SYSTEM_PROMPT, build_user_message
from src.config import Settings
from src.transcription.transcript_manager import TranscriptManager

logger = logging.getLogger(__name__)


class AgentBrain:
    """Claude-based decision loop that reads transcript and takes actions."""

    def __init__(
        self,
        settings: Settings,
        transcript_manager: TranscriptManager,
        action_executor: ActionExecutor,
        send_chat_fn: Callable[[str], Coroutine[Any, Any, None]],
    ):
        self.settings = settings
        self.transcript_manager = transcript_manager
        self.action_executor = action_executor
        self.send_chat_fn = send_chat_fn
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._running = False
        self._last_processed_count = 0
        self._task: asyncio.Task | None = None
        self._tools: list | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._agent_loop())
        logger.info("Agent brain started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Agent brain stopped")

    def _get_tools(self) -> list:
        """Get tools, with graceful fallback if Composio fails."""
        if self._tools is not None:
            return self._tools

        try:
            composio_tools = self.action_executor.get_tools()
            self._tools = composio_tools + [SEND_CHAT_MESSAGE_TOOL]
            logger.info(f"Loaded {len(self._tools)} tools ({len(composio_tools)} Composio + send_chat_message)")
        except Exception:
            logger.exception("Failed to load Composio tools — using chat-only mode")
            self._tools = [SEND_CHAT_MESSAGE_TOOL]

        return self._tools

    async def _agent_loop(self) -> None:
        """Wait for new transcript entries, then invoke Claude."""
        logger.info("Agent loop running, waiting for transcript...")
        while self._running:
            await self.transcript_manager.wait_for_new_entry(
                timeout=self.settings.agent_trigger_interval_seconds
            )

            if not self._running:
                break

            current_count = self.transcript_manager.entry_count
            if current_count <= self._last_processed_count:
                continue

            self._last_processed_count = current_count
            logger.info(f"Processing {current_count} transcript entries...")

            try:
                await self._invoke_claude()
            except Exception:
                logger.exception("Agent loop error")

    async def _invoke_claude(self) -> None:
        """Send recent transcript to Claude and handle tool calls."""
        transcript_text = await self.transcript_manager.get_formatted_transcript()
        participants = await self.transcript_manager.get_participants()
        participants_text = "\n".join(
            f"- {p.name} (host: {p.is_host})" for p in participants
        ) or "- No participants detected yet"

        user_message = build_user_message(transcript_text, participants_text)
        tools = self._get_tools()
        messages: list[dict] = [{"role": "user", "content": user_message}]

        logger.info(f"Calling Claude with {len(tools)} tools...")

        # Tool-use loop
        while True:
            response = await self._client.messages.create(
                model=self.settings.claude_model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )

            logger.info(f"Claude response: stop_reason={response.stop_reason}")

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = await self._handle_tool_call(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            }
                        )

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                for block in response.content:
                    if hasattr(block, "text"):
                        logger.info(f"Agent decided: {block.text[:200]}")
                break

    async def _handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        logger.info(f"Tool call: {tool_name}({tool_input})")

        if tool_name == "send_chat_message":
            try:
                await self.send_chat_fn(tool_input["message"])
                return "Message sent to meeting chat."
            except Exception as e:
                logger.error(f"Failed to send chat message: {e}")
                return f"Failed to send chat message: {e}"
        else:
            return await self.action_executor.execute_tool_call(tool_name, tool_input)
