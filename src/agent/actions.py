import logging

from composio import Composio

from src.config import Settings

logger = logging.getLogger(__name__)

SEND_CHAT_MESSAGE_TOOL = {
    "name": "send_chat_message",
    "description": (
        "Send a message to the meeting chat. Use this to answer questions "
        "asked during the meeting or share information with participants."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to send to the meeting chat.",
            }
        },
        "required": ["message"],
    },
}


def _to_anthropic_tool(tool: dict) -> dict:
    """Convert an OpenAI-format tool to Anthropic format."""
    # OpenAI format: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    # Anthropic format: {"name": ..., "description": ..., "input_schema": ...}
    if "function" in tool:
        func = tool["function"]
        return {
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
        }
    # Already in Anthropic format or close to it
    if "input_schema" in tool:
        return tool
    # Has "parameters" but no "function" wrapper
    if "parameters" in tool:
        return {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "input_schema": tool["parameters"],
        }
    return tool


class ActionExecutor:
    """Manages Composio tools (Gmail + Linear) and the custom chat tool."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._composio = Composio(api_key=settings.composio_api_key)
        self._tools: list | None = None

    def get_tools(self) -> list:
        """Return Anthropic-formatted tool definitions for Gmail + Linear."""
        if self._tools is None:
            raw_tools = self._composio.tools.get(
                user_id=self.settings.composio_user_id,
                toolkits=["gmail", "linear"],
            )
            self._tools = [_to_anthropic_tool(t) for t in raw_tools]
            logger.info(
                f"Loaded {len(self._tools)} Composio tools: "
                f"{[t['name'] for t in self._tools[:5]]}..."
            )
        return self._tools

    async def execute_tool_call(self, tool_name: str, tool_input: dict) -> str:
        """Execute a Composio tool call (Gmail or Linear)."""
        try:
            result = self._composio.provider.handle_tool_call(
                tool_name=tool_name,
                tool_input=tool_input,
                user_id=self.settings.composio_user_id,
            )
            logger.info(f"Tool {tool_name} executed successfully")
            return str(result)
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name} - {e}")
            return f"Error executing {tool_name}: {e}"
