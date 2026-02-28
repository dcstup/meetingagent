#!/usr/bin/env python3
import json
import os
import sys
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def _fail(message: str) -> None:
    _emit({"ok": False, "message": message})
    sys.exit(1)


def _load_input() -> dict[str, Any]:
    if len(sys.argv) < 2:
        _fail("Missing payload argument")

    try:
        return json.loads(sys.argv[1])
    except Exception as exc:
        _fail(f"Invalid JSON payload: {exc}")


def _serialize_toolkits(toolkits_response: Any) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []

    for toolkit in getattr(toolkits_response, "items", []) or []:
        slug = getattr(toolkit, "slug", "")
        name = getattr(toolkit, "name", slug)
        connection = getattr(toolkit, "connection", None)

        # SDK field naming may vary across versions.
        connected_account = None
        if connection is not None:
            connected_account = getattr(connection, "connected_account", None) or getattr(
                connection, "connectedAccount", None
            )

        connected_account_id = getattr(connected_account, "id", None)
        status = getattr(connection, "status", None) if connection is not None else None
        is_active = bool(connected_account_id)

        serialized.append(
            {
                "slug": slug,
                "name": name,
                "isActive": is_active,
                "connectedAccountId": connected_account_id,
                "status": status,
            }
        )

    serialized.sort(key=lambda x: (not x.get("isActive", False), str(x.get("slug", ""))))
    return serialized


def _run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from composio import Composio
    except Exception as exc:
        return {
            "ok": False,
            "message": (
                "Missing Python dependencies for Composio. "
                "Install apps/server/scripts/requirements.txt first. "
                f"Import error: {exc}"
            ),
        }

    api_key = os.environ.get("COMPOSIO_API_KEY", "").strip()
    default_user_id = os.environ.get("COMPOSIO_EXTERNAL_USER_ID", "").strip()

    user_id = str(payload.get("user_id") or default_user_id).strip()
    mode = str(payload.get("mode") or "").strip()

    if not api_key:
        return {"ok": False, "message": "COMPOSIO_API_KEY is required"}

    if not user_id:
        return {
            "ok": False,
            "message": "user_id is required (or set COMPOSIO_EXTERNAL_USER_ID)"
        }

    composio = Composio(api_key=api_key)

    try:
        # Menu-auth flow: disable in-chat connection management tool.
        session = composio.create(user_id=user_id, manage_connections=False)
    except Exception as exc:
        return {"ok": False, "message": f"Failed to create Composio session: {exc}"}

    if mode == "status":
        try:
            toolkits = session.toolkits()
            return {
                "ok": True,
                "user_id": user_id,
                "toolkits": _serialize_toolkits(toolkits),
            }
        except Exception as exc:
            return {"ok": False, "message": f"Failed to list toolkit statuses: {exc}"}

    if mode == "authorize":
        toolkit = str(payload.get("toolkit") or "").strip()
        callback_url = payload.get("callback_url")

        if not toolkit:
            return {"ok": False, "message": "toolkit is required for authorize mode"}

        try:
            if isinstance(callback_url, str) and callback_url.strip():
                request = session.authorize(toolkit, callback_url=callback_url.strip())
            else:
                request = session.authorize(toolkit)

            redirect_url = getattr(request, "redirect_url", None) or getattr(request, "redirectUrl", None)
            if not redirect_url:
                return {
                    "ok": False,
                    "message": "Composio authorize returned no redirect URL",
                }

            return {
                "ok": True,
                "user_id": user_id,
                "toolkit": toolkit,
                "redirect_url": redirect_url,
            }
        except Exception as exc:
            return {"ok": False, "message": f"Failed to authorize toolkit '{toolkit}': {exc}"}

    return {"ok": False, "message": f"Unsupported mode: {mode}"}


def main() -> None:
    payload = _load_input()
    result = _run(payload)
    _emit(result)


if __name__ == "__main__":
    main()
