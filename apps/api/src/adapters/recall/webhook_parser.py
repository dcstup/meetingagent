"""Standalone functions to parse Recall.ai webhook payloads into normalized types."""

from src.adapters.base import NormalizedUtterance, AdapterStatus


def parse_transcript_payload(payload: dict) -> tuple[str, list[NormalizedUtterance]]:
    """Parse a Recall transcript webhook payload.

    Returns (bot_id, list_of_normalized_utterances).
    bot_id may be empty string if not found in payload.
    """
    bot_id = (
        payload.get("bot_id")
        or payload.get("data", {}).get("bot_id")
        or payload.get("bot", {}).get("id")
        or ""
    )

    inner_data = payload.get("data", {}).get("data", {})
    words = inner_data.get("words", [])
    participant = inner_data.get("participant", {})

    if words:
        speaker = participant.get("name", "Unknown")
        text = " ".join(
            w.get("text", "") if isinstance(w, dict) else str(w) for w in words
        )
        if isinstance(words[0], dict):
            start_ts = words[0].get("start_timestamp") or {}
            timestamp_ms = int((start_ts.get("relative") or 0) * 1000)
        else:
            timestamp_ms = 0
    else:
        # Fallback for other payload formats
        transcript_data = payload.get("data", {}).get(
            "transcript", payload.get("transcript", {})
        )
        if isinstance(transcript_data, dict):
            speaker = transcript_data.get("speaker", "Unknown")
            text = transcript_data.get("text", "")
            timestamp_ms = int(transcript_data.get("timestamp", 0) * 1000)
        elif isinstance(transcript_data, str):
            speaker = "Unknown"
            text = transcript_data
            timestamp_ms = 0
        else:
            return bot_id, []

    text = text.strip()
    if not text:
        return bot_id, []

    return bot_id, [
        NormalizedUtterance(
            speaker=speaker,
            text=text,
            timestamp_ms=timestamp_ms,
            is_final=True,
        )
    ]


def parse_status_payload(payload: dict) -> tuple[str, AdapterStatus]:
    """Parse a Recall status webhook payload.

    Returns (bot_id, AdapterStatus).
    """
    bot_id = payload.get("bot_id") or payload.get("data", {}).get("bot_id") or ""
    status_code = payload.get("data", {}).get("status", {}).get("code", "")

    if status_code in ("done", "fatal"):
        return bot_id, AdapterStatus.ENDED
    elif status_code == "in_call_recording":
        return bot_id, AdapterStatus.ACTIVE
    else:
        return bot_id, AdapterStatus.CONNECTING
