---
name: yeschef-adapters
description: "YesChef transcript adapter architecture, registry, and ingestion patterns"
trigger: when working on adapters, transcript ingestion, Recall, DeepGram, or adding new transcript sources
---

# YesChef Transcript Adapter Architecture

## Overview

The adapter system abstracts transcript sources behind a single `TranscriptAdapter` ABC. The pipeline is:

```
Transcript Source (Recall bot / DeepGram / future)
  → Adapter (normalizes to NormalizedUtterance)
    → Utterance stored in DB
      → Extraction loop triggered
        → Gate scoring → CrewAI execution
```

Two ingestion patterns exist:
- **Webhook pattern** (Recall): the external service posts events to `POST /webhooks/recall/{secret}/transcript`. The route calls `adapter.parse_webhook(payload)` then stores/broadcasts.
- **Direct push pattern** (DeepGram / future): the client (browser extension) posts pre-parsed utterances directly to `POST /api/ingest/utterance`. No adapter parsing needed on the server side.

---

## File Map

All paths relative to `apps/api/`:

| File | Purpose |
|------|---------|
| `src/adapters/base.py` | ABC, enums, dataclasses |
| `src/adapters/__init__.py` | Registry (`_registry` dict, `register()`, `get_adapter()`) |
| `src/adapters/recall/__init__.py` | Recall self-registration |
| `src/adapters/recall/adapter.py` | RecallAdapter implementation |
| `src/adapters/recall/client.py` | Recall.ai HTTP client (`create_bot`, `get_bot_status`) |
| `src/adapters/recall/webhook_parser.py` | Recall payload parsing (pure functions) |
| `src/adapters/deepgram/__init__.py` | DeepGram self-registration |
| `src/adapters/deepgram/adapter.py` | DeepgramAdapter stub |
| `src/api/routes_webhooks.py` | Recall webhook HTTP routes |
| `src/api/routes_ingest.py` | Generic utterance ingest endpoint |
| `src/models/tables.py` | MeetingSession adapter columns |

---

## Core Types (`src/adapters/base.py`)

### `AdapterType` (str enum)
```python
class AdapterType(str, Enum):
    RECALL = "recall"
    DEEPGRAM = "deepgram"
```

### `NormalizedUtterance` (dataclass)
```python
@dataclass
class NormalizedUtterance:
    speaker: str        # Display name of the speaker, e.g. "Alice Smith"
    text: str           # Full utterance text (already joined from words)
    timestamp_ms: int   # Milliseconds from meeting start (relative, not epoch)
    is_final: bool = True  # Always True currently; future: handle interim results
```

### `SessionMetadata` (dataclass)
```python
@dataclass
class SessionMetadata:
    adapter_session_id: str        # Opaque ID from the adapter (e.g. Recall bot_id)
    meeting_url: Optional[str] = None
    title: Optional[str] = None
    platform: Optional[str] = None  # e.g. "recall"
```

### `AdapterStatus` (str enum)
```python
class AdapterStatus(str, Enum):
    CONNECTING = "connecting"
    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"
```

### `TranscriptAdapter` (ABC)
```python
class TranscriptAdapter(ABC):
    adapter_type: AdapterType  # Class-level attribute, set by each subclass

    @abstractmethod
    async def start_session(
        self, workspace_id: str, meeting_url: str, **kwargs
    ) -> SessionMetadata: ...
    # Creates a new meeting session (e.g. spawns a bot). Returns metadata
    # including the adapter_session_id to store in MeetingSession.adapter_session_id.

    @abstractmethod
    async def stop_session(self, adapter_session_id: str) -> None: ...
    # Tears down the session (e.g. removes bot). May be a no-op for some adapters.

    @abstractmethod
    async def get_status(self, adapter_session_id: str) -> AdapterStatus: ...
    # Polls external service for current status. Used for health checks.

    def parse_webhook(self, payload: dict) -> tuple[str, list[NormalizedUtterance]]:
        # Optional — override if the adapter uses webhooks.
        # Returns (adapter_session_id, utterances).
        # Default raises NotImplementedError.
        ...

    def parse_status_webhook(self, payload: dict) -> tuple[str, AdapterStatus]:
        # Optional — override if the adapter uses status webhooks.
        # Returns (adapter_session_id, status).
        # Default raises NotImplementedError.
        ...
```

**Rule**: If your adapter uses webhooks, override both `parse_webhook` and `parse_status_webhook`. If it uses direct push (like DeepGram), leave both unimplemented.

---

## Adapter Registry (`src/adapters/__init__.py`)

```python
_registry: dict[str, type[TranscriptAdapter]] = {}

def register(name: str, cls: type[TranscriptAdapter]) -> None:
    _registry[name] = cls

def get_adapter(name: str, **config) -> TranscriptAdapter:
    # Instantiates the adapter class with **config kwargs.
    # Raises KeyError if name is not registered.
    if name not in _registry:
        raise KeyError(f"Unknown adapter: {name!r}. Registered: {list(_registry)}")
    return _registry[name](**config)
```

**Registration is static (not dynamic)**. On module import, `_auto_register()` runs:
```python
def _auto_register() -> None:
    from src.adapters.recall import RecallAdapter  # noqa: F401
    from src.adapters.deepgram import DeepgramAdapter  # noqa: F401
```

Each adapter's `__init__.py` calls `register()` when imported:
```python
# src/adapters/recall/__init__.py
from src.adapters.recall.adapter import RecallAdapter
import src.adapters as _registry_mod
_registry_mod.register("recall", RecallAdapter)
```

**To add a new adapter**: create `src/adapters/myadapter/__init__.py` that calls `register("myadapter", MyAdapter)`, then add its import to `_auto_register()` in `src/adapters/__init__.py`.

---

## Recall Adapter (`src/adapters/recall/`)

### RecallAdapter

```python
class RecallAdapter(TranscriptAdapter):
    adapter_type = AdapterType.RECALL

    def __init__(self, webhook_url_template: str = "", **kwargs):
        # webhook_url_template may contain {secret} or other format placeholders.
        self._webhook_url_template = webhook_url_template

    async def start_session(
        self, workspace_id: str, meeting_url: str, **kwargs
    ) -> SessionMetadata:
        # kwargs may include webhook_url (fully formed) or keys for template formatting.
        # Calls create_bot(meet_url, webhook_url) → returns {"id": "<bot_id>", ...}
        # Returns SessionMetadata(adapter_session_id=bot_id, meeting_url=..., platform="recall")

    async def stop_session(self, adapter_session_id: str) -> None:
        pass  # No-op — bots leave when meeting ends

    async def get_status(self, adapter_session_id: str) -> AdapterStatus:
        # Calls get_bot_status(bot_id) → {"status": {"code": "..."}, ...}
        # Recall status codes → AdapterStatus mapping:
        #   "done" | "fatal"        → ENDED
        #   "in_call_recording"     → ACTIVE
        #   anything else           → CONNECTING

    def parse_webhook(self, payload: dict) -> tuple[str, list[NormalizedUtterance]]:
        return parse_transcript_payload(payload)

    def parse_status_webhook(self, payload: dict) -> tuple[str, AdapterStatus]:
        return parse_status_payload(payload)
```

### Recall HTTP Client (`src/adapters/recall/client.py`)

Base URL: `https://us-west-2.recall.ai/api/v1`
Auth: `Authorization: Token {settings.recall_api_key}`

**`create_bot(meet_url, webhook_url) -> dict`**
```
POST /bot
{
  "meeting_url": meet_url,
  "bot_name": settings.bot_name,
  "recording_config": {
    "transcript": {
      "provider": {"meeting_captions": {}}
    },
    "realtime_endpoints": [
      {
        "type": "webhook",
        "url": webhook_url,
        "events": ["transcript.data"]
      }
    ]
  }
}
```
Returns the full bot object; `bot_id = resp["id"]`.

**`get_bot_status(bot_id) -> dict`**
```
GET /bot/{bot_id}
```
Returns bot object with `status.code` field.

### Recall Webhook Payload Parsing (`src/adapters/recall/webhook_parser.py`)

#### Transcript webhook (`transcript.data` event)

The parser handles two payload shapes:

**Shape A — words array (primary)**:
```json
{
  "bot_id": "<bot_id>",
  "data": {
    "bot_id": "<bot_id>",
    "data": {
      "words": [
        {
          "text": "Hello",
          "start_timestamp": {"relative": 1.23}
        }
      ],
      "participant": {
        "name": "Alice Smith"
      }
    }
  }
}
```
- `speaker` = `data.data.participant.name` (fallback: "Unknown")
- `text` = words joined by space
- `timestamp_ms` = `words[0].start_timestamp.relative * 1000` (integer)

**Shape B — transcript dict (fallback)**:
```json
{
  "bot_id": "<bot_id>",
  "data": {
    "transcript": {
      "speaker": "Alice Smith",
      "text": "Hello world",
      "timestamp": 1.23
    }
  }
}
```
- `timestamp_ms` = `transcript.timestamp * 1000`

**bot_id extraction** tries in order: `payload.bot_id` → `payload.data.bot_id` → `payload.bot.id`

Returns `(bot_id: str, [NormalizedUtterance])`. Returns `(bot_id, [])` if text is empty.

#### Status webhook

```json
{
  "bot_id": "<bot_id>",
  "data": {
    "bot_id": "<bot_id>",
    "status": {
      "code": "in_call_recording"
    }
  }
}
```
Returns `(bot_id, AdapterStatus)`.

---

## DeepGram Adapter (`src/adapters/deepgram/adapter.py`)

**Status: stub — all methods raise `NotImplementedError`.**

```python
class DeepgramAdapter(TranscriptAdapter):
    adapter_type = AdapterType.DEEPGRAM

    async def start_session(...) -> SessionMetadata:
        raise NotImplementedError(...)

    async def stop_session(...) -> None:
        raise NotImplementedError(...)

    async def get_status(...) -> AdapterStatus:
        raise NotImplementedError(...)

    # parse_webhook and parse_status_webhook intentionally NOT overridden.
    # DeepGram uses direct push, not webhooks.
```

**Intended future flow**:
1. User clicks "Start Local Meeting" in the browser extension.
2. Extension captures mic via `getUserMedia()`.
3. Audio streamed to DeepGram real-time WebSocket API; DeepGram returns diarized transcript chunks.
4. Extension posts each utterance to `POST /api/ingest/utterance` (no server-side adapter parsing needed).
5. Server stores and broadcasts — same pipeline as Recall.

When implementing: `start_session` should create a DeepGram streaming session and return an `adapter_session_id` the extension stores and sends with each `ingest/utterance` call.

---

## Webhook Routes (`src/api/routes_webhooks.py`)

Router prefix: `/webhooks`

### `POST /webhooks/recall/{secret}/transcript`

- Authenticates workspace via `webhook_secret` path param.
- Gets adapter: `get_adapter("recall")` (no config kwargs).
- Calls `adapter.parse_webhook(payload)` → `(bot_id, utterances)`.
- Finds `MeetingSession` by `recall_bot_id == bot_id AND workspace_id == workspace.id`.
- **Fallback**: if no match, picks most recent `bot_joining | connecting | active` session for the workspace.
- Calls `_store_and_broadcast()` with first utterance.
- Returns `{"status": "ok"}` or `{"status": "ignored"}`.

**Webhook URL format** (used when creating a bot):
```
https://<host>/webhooks/recall/{workspace.webhook_secret}/transcript
```

### `POST /webhooks/recall/{secret}/status`

- Authenticates workspace via `webhook_secret`.
- Calls `adapter.parse_status_webhook(payload)` → `(bot_id, adapter_status)`.
- Finds session by `recall_bot_id == bot_id`.
- Maps `AdapterStatus.ENDED` → `MeetingStatus.ended` + sets `ended_at`.
- Maps `AdapterStatus.ACTIVE` → `MeetingStatus.active` + sets `started_at` if not set.
- Broadcasts `meeting_status` event via WebSocket.

### `_store_and_broadcast()` (shared helper)

Called by both the webhook route and the ingest route (separate copies with same logic):
1. If `session.status` is `bot_joining` or `connecting`, set to `active`.
2. Create `Utterance` row, `db.add()`, `await db.commit()`.
3. If status changed, broadcast `{"type": "meeting_status", ...}` to `workspace_id` channel.
4. If session is now `active`, call `start_extraction(session_id)` (idempotent).
5. Broadcast `{"type": "utterance", "data": {id, speaker, text, timestamp_ms}}`.

---

## Generic Ingest Endpoint (`src/api/routes_ingest.py`)

Router prefix: `/api`

### `POST /api/ingest/utterance`

No adapter-specific parsing — expects pre-normalized data.

**Request body** (`IngestUtteranceRequest`):
```json
{
  "session_id": "uuid-string",
  "speaker": "Alice Smith",
  "text": "Hello world",
  "timestamp_ms": 1230
}
```

**Behavior**:
- Validates `session_id` is a valid UUID; 400 if not.
- Looks up `MeetingSession` by `id`; 404 if not found. No workspace scoping — caller must know the session UUID.
- Empty `text` (after strip) returns `{"status": "ignored"}`.
- Same activate-store-broadcast-extract logic as webhook route.

**Use cases**: DeepGram browser flow, tests, any adapter that pushes utterances directly from client code.

---

## DB Model (`src/models/tables.py`)

### `MeetingSession` adapter-relevant columns

```python
class MeetingSession(Base):
    __tablename__ = "meeting_sessions"

    # Legacy Recall-specific column (keep for backwards compat)
    recall_bot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Adapter-agnostic columns (added in adapter architecture migration)
    adapter_type: Mapped[str | None] = mapped_column(
        String(32), default="recall", nullable=True
    )
    adapter_session_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # Status uses adapter-agnostic aliases
    status: Mapped[MeetingStatus]  # bot_joining == connecting (both valid)
```

### `MeetingStatus` enum
```python
class MeetingStatus(str, enum.Enum):
    pending = "pending"
    bot_joining = "bot_joining"
    connecting = "connecting"  # adapter-agnostic alias for bot_joining
    active = "active"
    ended = "ended"
    failed = "failed"
```

**Migration notes**:
- `recall_bot_id` is kept for backwards compatibility; Recall webhook routes still look up by `recall_bot_id`.
- New adapters should use `adapter_session_id` for lookup and set `adapter_type`.
- Default value of `adapter_type` is `"recall"` to avoid breaking existing rows.

### Indexes
```python
Index("ix_meeting_sessions_workspace_status", "workspace_id", "status")
Index("ix_meeting_sessions_recall_bot_id", "recall_bot_id")
```
No index on `adapter_session_id` yet — add one when implementing a new adapter that queries by it.

---

## How to Add a New Adapter

### Step 1: Add to `AdapterType` enum
In `src/adapters/base.py`:
```python
class AdapterType(str, Enum):
    RECALL = "recall"
    DEEPGRAM = "deepgram"
    MYADAPTER = "myadapter"  # add this
```

### Step 2: Create the adapter package
```
src/adapters/myadapter/
  __init__.py
  adapter.py
  client.py          # if you need an HTTP/WebSocket client
  webhook_parser.py  # if you use webhooks
```

### Step 3: Implement `adapter.py`
```python
from src.adapters.base import (
    AdapterStatus, AdapterType, NormalizedUtterance, SessionMetadata, TranscriptAdapter
)

class MyAdapter(TranscriptAdapter):
    adapter_type = AdapterType.MYADAPTER

    def __init__(self, **kwargs):
        # Accept config kwargs passed from get_adapter("myadapter", key=val)
        ...

    async def start_session(
        self, workspace_id: str, meeting_url: str, **kwargs
    ) -> SessionMetadata:
        # Call your service's API to start a session.
        # Return SessionMetadata(adapter_session_id=<your_id>, ...)
        ...

    async def stop_session(self, adapter_session_id: str) -> None:
        # Tear down the session, or pass if not applicable.
        ...

    async def get_status(self, adapter_session_id: str) -> AdapterStatus:
        # Poll your service for current status.
        # Map to AdapterStatus.CONNECTING / ACTIVE / ENDED / FAILED
        ...

    # IF using webhooks, also implement:
    def parse_webhook(self, payload: dict) -> tuple[str, list[NormalizedUtterance]]:
        # Parse payload, return (adapter_session_id, utterances)
        ...

    def parse_status_webhook(self, payload: dict) -> tuple[str, AdapterStatus]:
        # Parse status payload, return (adapter_session_id, status)
        ...
```

### Step 4: Register in `__init__.py`
```python
# src/adapters/myadapter/__init__.py
from src.adapters.myadapter.adapter import MyAdapter
import src.adapters as _registry_mod

_registry_mod.register("myadapter", MyAdapter)

__all__ = ["MyAdapter"]
```

### Step 5: Add to auto-registration
In `src/adapters/__init__.py`, add to `_auto_register()`:
```python
def _auto_register() -> None:
    from src.adapters.recall import RecallAdapter    # noqa: F401
    from src.adapters.deepgram import DeepgramAdapter  # noqa: F401
    from src.adapters.myadapter import MyAdapter      # noqa: F401  ← add this
```

### Step 6: Choose ingestion pattern

**Webhook pattern** (external service posts to your server):
- Add routes to `src/api/routes_webhooks.py` (or a new `routes_myadapter.py`).
- Route URL should include `{workspace.webhook_secret}` for authentication.
- Call `get_adapter("myadapter")` and `adapter.parse_webhook(payload)`.
- Use `_store_and_broadcast()` to store/broadcast utterances.
- Register the route in `src/api/app.py`.

**Direct push pattern** (client posts utterances directly):
- Reuse `POST /api/ingest/utterance` — no new routes needed.
- Client must know the `session_id` UUID.
- `start_session` must create the `MeetingSession` row and return its UUID as `adapter_session_id`.

### Step 7: Database
If you need to look up sessions by `adapter_session_id` in webhooks, add a DB index:
```python
# In src/models/tables.py MeetingSession.__table_args__:
Index("ix_meeting_sessions_adapter_session_id", "adapter_type", "adapter_session_id")
```
Create a migration: `cd apps/api && uv run alembic revision --autogenerate -m "add adapter_session_id index"`.

Set `adapter_type` and `adapter_session_id` when creating `MeetingSession` rows.

---

## Webhook vs Direct Push — Decision Guide

| Criterion | Webhook | Direct Push |
|-----------|---------|-------------|
| Who has the transcript? | External service (Recall, Zoom, Teams) | Client app (browser extension, mobile) |
| Transport | External service → your server HTTP POST | Client → `POST /api/ingest/utterance` |
| Auth | `webhook_secret` in URL path | Must know `session_id` UUID |
| Parsing | Implement `parse_webhook()` | Not needed — client sends normalized data |
| Realtime latency | Depends on external service pipeline | Lower (direct from audio capture) |
| Example | Recall.ai | DeepGram browser mic |

---

## WebSocket Broadcasts

After any utterance is stored, the pipeline broadcasts two event types to the workspace's WebSocket channel (channel key = `workspace_id` UUID string):

```json
{"type": "meeting_status", "data": {"session_id": "...", "status": "active"}}
{"type": "utterance", "data": {"id": "...", "speaker": "...", "text": "...", "timestamp_ms": 0}}
```

The broadcast manager is `src/services/ws_manager.manager` — a singleton. Call:
```python
await manager.broadcast(str(session.workspace_id), payload_dict)
```

---

## Config Dependencies

Recall adapter requires these settings (from `src/config.py`):
- `settings.recall_api_key` — Recall.ai API token
- `settings.bot_name` — Display name for the bot in meetings

These are read from environment variables. Never hardcode them.
