import asyncio
import logging
from collections import deque
from datetime import UTC, datetime

from src.config import Settings
from src.transcription.models import ParticipantInfo, TranscriptEntry

logger = logging.getLogger(__name__)


class TranscriptManager:
    """Accumulates transcript entries and participant info with a sliding window buffer."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._entries: deque[TranscriptEntry] = deque(
            maxlen=settings.transcript_buffer_max_entries
        )
        self._all_entries: list[TranscriptEntry] = []
        self._participants: dict[int, ParticipantInfo] = {}
        self._lock = asyncio.Lock()
        self._new_entry_event = asyncio.Event()

    async def add_transcript(
        self,
        speaker_id: int,
        speaker_name: str,
        text: str,
        timestamp_relative: float,
    ) -> None:
        entry = TranscriptEntry(
            speaker_name=speaker_name or f"Speaker {speaker_id}",
            speaker_id=speaker_id,
            text=text,
            timestamp_relative=timestamp_relative,
            received_at=datetime.now(UTC),
        )
        async with self._lock:
            self._entries.append(entry)
            self._all_entries.append(entry)
        self._new_entry_event.set()

    async def add_participant(
        self,
        participant_id: int,
        name: str,
        is_host: bool = False,
        email: str | None = None,
    ) -> None:
        async with self._lock:
            self._participants[participant_id] = ParticipantInfo(
                id=participant_id,
                name=name,
                is_host=is_host,
                email=email,
                joined_at=datetime.now(UTC),
            )

    async def remove_participant(self, participant_id: int) -> None:
        async with self._lock:
            if participant_id in self._participants:
                self._participants[participant_id].left_at = datetime.now(UTC)

    async def get_recent_transcript(self) -> list[TranscriptEntry]:
        async with self._lock:
            return list(self._entries)

    async def get_formatted_transcript(self) -> str:
        entries = await self.get_recent_transcript()
        return "\n".join(e.format_for_llm() for e in entries)

    async def get_participants(self) -> list[ParticipantInfo]:
        async with self._lock:
            return [p for p in self._participants.values() if p.left_at is None]

    async def get_full_transcript(self) -> list[TranscriptEntry]:
        async with self._lock:
            return list(self._all_entries)

    async def wait_for_new_entry(self, timeout: float = 5.0) -> bool:
        """Block until a new entry arrives or timeout. Returns True if new entry."""
        self._new_entry_event.clear()
        try:
            await asyncio.wait_for(self._new_entry_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def entry_count(self) -> int:
        return len(self._all_entries)
