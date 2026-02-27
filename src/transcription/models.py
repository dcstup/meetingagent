from datetime import datetime

from pydantic import BaseModel


class TranscriptEntry(BaseModel):
    """A single utterance in the meeting transcript."""

    speaker_name: str
    speaker_id: int
    text: str
    timestamp_relative: float  # seconds from meeting start
    received_at: datetime

    def format_for_llm(self) -> str:
        minutes = int(self.timestamp_relative // 60)
        seconds = int(self.timestamp_relative % 60)
        return f"[{minutes:02d}:{seconds:02d}] {self.speaker_name}: {self.text}"


class ParticipantInfo(BaseModel):
    """Tracks a meeting participant."""

    id: int
    name: str
    is_host: bool = False
    email: str | None = None
    joined_at: datetime | None = None
    left_at: datetime | None = None
