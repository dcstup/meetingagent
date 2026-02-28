from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class AdapterType(str, Enum):
    RECALL = "recall"
    DEEPGRAM = "deepgram"


@dataclass
class NormalizedUtterance:
    speaker: str
    text: str
    timestamp_ms: int
    is_final: bool = True


@dataclass
class SessionMetadata:
    adapter_session_id: str
    meeting_url: Optional[str] = None
    title: Optional[str] = None
    platform: Optional[str] = None


class AdapterStatus(str, Enum):
    CONNECTING = "connecting"
    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"


class TranscriptAdapter(ABC):
    adapter_type: AdapterType

    @abstractmethod
    async def start_session(
        self, workspace_id: str, meeting_url: str, **kwargs
    ) -> SessionMetadata:
        ...

    @abstractmethod
    async def stop_session(self, adapter_session_id: str) -> None:
        ...

    @abstractmethod
    async def get_status(self, adapter_session_id: str) -> AdapterStatus:
        ...

    def parse_webhook(self, payload: dict) -> tuple[str, list[NormalizedUtterance]]:
        """Parse an incoming webhook payload. Returns (adapter_session_id, utterances).
        Not all adapters use webhooks; override only if applicable."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support webhook parsing"
        )

    def parse_status_webhook(self, payload: dict) -> tuple[str, AdapterStatus]:
        """Parse a status webhook payload. Returns (adapter_session_id, status).
        Not all adapters use webhooks; override only if applicable."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support status webhook parsing"
        )
