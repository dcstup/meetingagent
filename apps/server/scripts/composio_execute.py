#!/usr/bin/env python3
import json
import os
import sys
from typing import Any


def _fail(message: str) -> None:
    print(json.dumps({"ok": False, "message": message}))
    sys.exit(1)


def _load_input() -> dict[str, Any]:
    if len(sys.argv) < 2:
        _fail("Missing payload argument")

    try:
        return json.loads(sys.argv[1])
    except Exception as exc:
        _fail(f"Invalid JSON payload: {exc}")


def _run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from composio import Composio
        from composio_openai import OpenAIResponsesProvider
        from openai import OpenAI
    except Exception as exc:
        return {
            "ok": False,
            "message": (
                "Missing Python dependencies. Install "
                "apps/server/scripts/requirements.txt first. "
                f"Import error: {exc}"
            ),
        }

    api_key = os.environ.get("COMPOSIO_API_KEY", "").strip()
    openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    external_user_id = os.environ.get("COMPOSIO_EXTERNAL_USER_ID", "").strip()
    model = os.environ.get("OPENAI_MODEL", "gpt-5.2").strip()

    if not api_key:
        return {"ok": False, "message": "COMPOSIO_API_KEY is required for python_agents mode"}

    if not openai_api_key:
        return {"ok": False, "message": "OPENAI_API_KEY is required for python_agents mode"}

    if not external_user_id:
        return {
            "ok": False,
            "message": "COMPOSIO_EXTERNAL_USER_ID is required for python_agents mode"
        }

    probe = bool(payload.get("probe"))
    prompt = payload.get("prompt")

    composio = Composio(api_key=api_key, provider=OpenAIResponsesProvider())

    try:
        # Disable in-chat auth prompts; auth should be handled in app settings UI.
        session = composio.create(user_id=external_user_id, manage_connections=False)
        tools = session.tools()
    except Exception as exc:
        return {"ok": False, "message": f"Failed to create Composio session/tools: {exc}"}

    if probe:
        return {
            "ok": True,
            "message": f"Composio session ready ({len(tools)} tools, Responses API mode)"
        }

    if not isinstance(prompt, str) or not prompt.strip():
        return {"ok": False, "message": "Execution prompt is missing"}

    try:
        client = OpenAI(api_key=openai_api_key)

        response = client.responses.create(
            model=model,
            tools=tools,
            input=[{"role": "user", "content": prompt}],
        )

        # Agentic loop: execute tool calls until the model returns only text.
        while True:
            tool_calls = [item for item in response.output if item.type == "function_call"]
            if not tool_calls:
                break

            results = composio.provider.handle_tool_calls(response=response, user_id=external_user_id)

            response = client.responses.create(
                model=model,
                tools=tools,
                previous_response_id=response.id,
                input=[
                    {
                        "type": "function_call_output",
                        "call_id": tool_calls[i].call_id,
                        "output": json.dumps(result),
                    }
                    for i, result in enumerate(results)
                ],
            )

    except Exception as exc:
        return {"ok": False, "message": f"Composio Responses execution failed: {exc}"}

    for item in response.output:
        if item.type == "message":
            # responses SDK returns content blocks; first output_text block is enough for demo.
            for block in item.content:
                if getattr(block, "type", None) in ("output_text", "text") and hasattr(block, "text"):
                    return {"ok": True, "message": str(block.text)}

    return {"ok": True, "message": "Composio execution completed"}


def main() -> None:
    payload = _load_input()
    result = _run(payload)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
