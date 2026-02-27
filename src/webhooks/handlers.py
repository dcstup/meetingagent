import logging

from src.transcription.transcript_manager import TranscriptManager

logger = logging.getLogger(__name__)


async def handle_transcript_data(
    payload: dict, transcript_manager: TranscriptManager
) -> None:
    """Handle transcript.data events — extract speaker and text, add to buffer."""
    inner_data = payload.get("data", {}).get("data", {})
    words = inner_data.get("words", [])
    participant = inner_data.get("participant", {})

    if not words:
        return

    text = " ".join(w.get("text", "") for w in words).strip()
    if not text:
        return

    timestamp = words[0].get("start_timestamp", {}).get("relative", 0.0)
    speaker_id = participant.get("id", 0)
    speaker_name = participant.get("name") or f"Speaker {speaker_id}"

    await transcript_manager.add_transcript(
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        text=text,
        timestamp_relative=timestamp,
    )
    logger.info(f"[{timestamp:.1f}s] {speaker_name}: {text}")


async def handle_participant_join(
    payload: dict, transcript_manager: TranscriptManager
) -> None:
    participant = payload.get("data", {}).get("data", {}).get("participant", {})
    name = participant.get("name", "Unknown")
    await transcript_manager.add_participant(
        participant_id=participant.get("id", 0),
        name=name,
        is_host=participant.get("is_host", False),
        email=participant.get("email"),
    )
    logger.info(f"Participant joined: {name}")


async def handle_participant_leave(
    payload: dict, transcript_manager: TranscriptManager
) -> None:
    participant = payload.get("data", {}).get("data", {}).get("participant", {})
    await transcript_manager.remove_participant(participant.get("id", 0))
    logger.info(f"Participant left: {participant.get('name')}")


async def handle_bot_status(payload: dict) -> None:
    event = payload.get("event", "unknown")
    logger.info(f"Bot status: {event}")
