"""DeepgramAdapter — stub for future browser-based mic capture via DeepGram.

Flow (future implementation):
1. User clicks "Start Local Meeting" in the browser extension.
2. Extension captures mic audio via getUserMedia().
3. Audio is streamed to the DeepGram real-time API (WebSocket) which returns
   diarized transcript chunks.
4. Extension pushes each utterance to POST /api/ingest/utterance, which stores
   it and broadcasts via WS -- the same pipeline as Recall utterances.

Because there is no meeting bot and no meeting URL, start_session creates a
"virtual" session and returns a unique adapter_session_id.
"""

from src.adapters.base import (
    AdapterStatus,
    AdapterType,
    NormalizedUtterance,
    SessionMetadata,
    TranscriptAdapter,
)


class DeepgramAdapter(TranscriptAdapter):
    adapter_type = AdapterType.DEEPGRAM

    async def start_session(
        self, workspace_id: str, meeting_url: str, **kwargs
    ) -> SessionMetadata:
        # Future: initialize a DeepGram streaming session, return its id.
        raise NotImplementedError(
            "DeepgramAdapter.start_session is not yet implemented. "
            "This adapter will create a DeepGram streaming session and return "
            "an adapter_session_id that the browser extension uses to push utterances."
        )

    async def stop_session(self, adapter_session_id: str) -> None:
        # Future: close the DeepGram WebSocket session.
        raise NotImplementedError(
            "DeepgramAdapter.stop_session is not yet implemented."
        )

    async def get_status(self, adapter_session_id: str) -> AdapterStatus:
        # Future: check whether the DeepGram stream is still open.
        raise NotImplementedError(
            "DeepgramAdapter.get_status is not yet implemented."
        )

    # DeepGram does not use webhooks -- utterances arrive via POST /api/ingest/utterance.
    # parse_webhook and parse_status_webhook intentionally remain unimplemented.
