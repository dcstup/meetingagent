import time
from collections import deque
from dataclasses import dataclass, field
from src.config.constants import (
    ROLLING_BUFFER_WINDOW_S,
    CONFIDENCE_THRESHOLD_DROP,
    CONFIDENCE_THRESHOLD_UNSURE,
)


@dataclass
class BufferEntry:
    speaker: str
    text: str
    timestamp_ms: int
    added_at: float = field(default_factory=time.time)


class RollingBuffer:
    """Maintains a rolling window of transcript utterances."""

    def __init__(self, window_s: int = ROLLING_BUFFER_WINDOW_S):
        self._entries: deque[BufferEntry] = deque()
        self._window_s = window_s

    def add(self, speaker: str, text: str, timestamp_ms: int):
        self._entries.append(
            BufferEntry(speaker=speaker, text=text, timestamp_ms=timestamp_ms)
        )
        self._prune()

    def _prune(self):
        cutoff = time.time() - self._window_s
        while self._entries and self._entries[0].added_at < cutoff:
            self._entries.popleft()

    def get_text(self) -> str:
        self._prune()
        return "\n".join(f"{e.speaker}: {e.text}" for e in self._entries)

    def has_new_content(self, since: float) -> bool:
        return any(e.added_at > since for e in self._entries)

    @property
    def size(self) -> int:
        return len(self._entries)


def filter_proposals(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Apply confidence and action-verb filters to extracted proposals.

    Returns (passed, filtered_out) where filtered_out items include a
    ``filter_reason`` key explaining why they were dropped.
    """
    ACTION_VERBS = {
        "send", "draft", "create", "schedule", "follow", "review", "share",
        "update", "write", "prepare", "submit", "forward", "reply", "set",
        "book", "arrange", "organize", "compile", "complete", "finalize",
        "build", "prototype", "mock", "design", "visualize", "diagram", "wireframe",
    }

    filtered = []
    filtered_out: list[dict] = []
    for item in items:
        confidence = item.get("confidence", 0)

        # Drop low confidence
        if confidence < CONFIDENCE_THRESHOLD_DROP:
            item["filter_reason"] = f"confidence {confidence} < {CONFIDENCE_THRESHOLD_DROP}"
            filtered_out.append(item)
            continue

        # Drop items where readiness < 3 (topic still being debated)
        readiness = item.get("readiness")
        if readiness is not None and readiness < 3:
            item["filter_reason"] = f"readiness {readiness} < 3 (still being debated)"
            filtered_out.append(item)
            continue

        # Check for action verb in title
        title = item.get("title", "").lower()
        has_action_verb = any(verb in title.split() for verb in ACTION_VERBS)

        if not has_action_verb:
            # Also check body first few words
            body_words = item.get("body", "").lower().split()[:5]
            has_action_verb = any(verb in body_words for verb in ACTION_VERBS)

        if not has_action_verb and confidence < CONFIDENCE_THRESHOLD_UNSURE:
            item["filter_reason"] = f"no action verb and confidence {confidence} < {CONFIDENCE_THRESHOLD_UNSURE}"
            filtered_out.append(item)
            continue

        # Mark uncertain ones
        if CONFIDENCE_THRESHOLD_DROP <= confidence < CONFIDENCE_THRESHOLD_UNSURE:
            item["title"] = item.get("title", "") + " ??"

        filtered.append(item)

    return filtered, filtered_out
