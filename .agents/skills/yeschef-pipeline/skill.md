---
name: yeschef-pipeline
description: "YesChef extraction→gate→execution pipeline internals"
trigger: when working on extraction_loop, gate scoring, executor, action items, or the AI pipeline
---

# YesChef AI Pipeline — Reference Documentation

This document is the complete reference for the YesChef meeting intelligence pipeline. A subagent working on any part of the pipeline can rely on this document without reading source files.

---

## Pipeline Overview

```
Transcript Utterance (webhook or POST /api/ingest/utterance)
    │
    ▼
Utterance stored in DB (session_id, speaker, text, timestamp_ms)
    │
    ▼ (every 30s)
RollingBuffer (45s window) — accumulates new utterances
    │
    ▼
extract_action_items(transcript_text) — Cerebras gpt-oss-120b
    │  Returns: [{action_type, title, body, recipient, confidence, readiness, dedupe_key}]
    ▼
filter_proposals(raw_items) — confidence/readiness/verb filter
    │  Drops: confidence < 0.5, readiness < 3, no action verb (unless confidence >= 0.75)
    ▼
is_duplicate(session_id, dedupe_key, text, existing_proposals) — hash + cosine
    │  Threshold: cosine similarity > 0.88
    ▼
_get_rag_context(session_id, query_text, top_k=5) — semantic search over utterances
    │
    ▼
gate.evaluate_action(candidate, transcript_window, rag_context_chunks, meeting_context)
    │  Model: Cerebras zai-glm-4.7 — 7-dimension rubric
    │  Pass condition: avg_score > 3.8 AND readiness >= 4
    │  Fails open on any error
    ▼
Proposal written to DB
    │  gate_passed=True  → status=ProposalStatus.pending, broadcast "proposal_created"
    │  gate_passed=False → status=ProposalStatus.dropped, broadcast "proposal_dropped"
    ▼
(on user approval) execute_*() — CrewAI + Composio
    │  gmail_draft  → execute_gmail_draft()
    │  html_artifact → execute_artifact()
    │  generic_draft → execute_generic_draft()
    ▼
Execution record written to DB (executions table)
```

---

## Constants (`src/config/constants.py`)

```python
EXTRACTION_INTERVAL_S = 30          # How often the extraction loop fires
ROLLING_BUFFER_WINDOW_S = 45        # Seconds of transcript the buffer retains
CONFIDENCE_THRESHOLD_DROP = 0.5     # Items below this are dropped immediately
CONFIDENCE_THRESHOLD_UNSURE = 0.75  # Items below this need an action verb
COSINE_DEDUPE_THRESHOLD = 0.88      # Cosine similarity above this = duplicate

EXTRACTION_MODEL = "gpt-oss-120b"                    # Cerebras extraction model
GATE_MODEL = "zai-glm-4.7"                           # Cerebras gate scoring model
EXECUTOR_MODEL = "gemini/gemini-3-pro-preview"        # CrewAI execution model
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"         # DeepInfra embeddings

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

GATE_AVG_THRESHOLD = 3.8            # Minimum average score across all 7 dimensions
GATE_READINESS_THRESHOLD = 4        # Minimum readiness score (separate from avg)
```

---

## Data Models (`src/models/tables.py`)

### Enums

```python
class MeetingStatus(str, enum.Enum):
    pending = "pending"
    bot_joining = "bot_joining"
    connecting = "connecting"   # adapter-agnostic alias for bot_joining
    active = "active"
    ended = "ended"
    failed = "failed"

class ProposalStatus(str, enum.Enum):
    pending = "pending"     # Passed gate, awaiting user approval
    approved = "approved"   # User approved, execution triggered
    dismissed = "dismissed" # User dismissed
    dropped = "dropped"     # Failed gate

class ExecutionStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
```

### MeetingSession

```python
class MeetingSession(Base):
    __tablename__ = "meeting_sessions"
    id: UUID (PK)
    workspace_id: UUID (FK workspaces.id)
    calendar_event_id: UUID | None (FK calendar_events.id)
    recall_bot_id: str | None        # Legacy Recall.ai bot ID
    adapter_type: str | None         # "recall" or "deepgram" (default: "recall")
    adapter_session_id: str | None   # Adapter-specific session identifier
    meet_url: str
    status: MeetingStatus
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
```

Indexes: `(workspace_id, status)`, `(recall_bot_id)`

### Utterance

```python
class Utterance(Base):
    __tablename__ = "utterances"
    id: UUID (PK)
    session_id: UUID (FK meeting_sessions.id)
    speaker: str
    text: str
    timestamp_ms: int  # BigInteger
    created_at: datetime
```

Index: `(session_id, created_at)`

### Proposal

```python
class Proposal(Base):
    __tablename__ = "proposals"
    id: UUID (PK)
    session_id: UUID (FK meeting_sessions.id)
    action_type: str           # "gmail_draft" | "html_artifact" | "generic_draft"
    title: str
    body: str
    recipient: str | None      # Only for gmail_draft
    confidence: float
    dedupe_key: str
    dedupe_hash: str | None    # SHA-256 of "session_id:dedupe_key"
    embedding: list | None     # JSONB — vector for cosine dedup
    status: ProposalStatus
    source_text: str           # First 2000 chars of transcript window used
    gate_scores: dict | None   # JSONB — {explicitness, value, ..., readiness}
    gate_avg_score: float | None
    gate_readiness: int | None
    gate_evidence_quote: str | None
    gate_missing_info: list | None  # JSONB — list of missing info strings
    gate_passed: bool | None
    created_at: datetime
```

Index: `(session_id, status)`

### Execution

```python
class Execution(Base):
    __tablename__ = "executions"
    id: UUID (PK)
    proposal_id: UUID (FK proposals.id)
    status: ExecutionStatus
    result: dict | None      # JSONB — executor return value
    error: str | None
    artifact_html: str | None  # For html_artifact executions
    created_at: datetime
    completed_at: datetime | None
```

### Workspace

```python
class Workspace(Base):
    __tablename__ = "workspaces"
    id: UUID (PK)
    composio_entity_id: str | None   # Composio user entity for tool access
    has_google_calendar: bool         # Gates calendar watcher activation
    overlay_token: str
    webhook_secret: str
    created_at: datetime
```

---

## Ingestion Endpoint (`src/api/routes_ingest.py`)

```
POST /api/ingest/utterance
```

Request model:
```python
class IngestUtteranceRequest(BaseModel):
    session_id: str
    speaker: str
    text: str
    timestamp_ms: int
```

Behavior:
1. Validates `session_id` as UUID; 404 if session not found; ignores empty `text`.
2. Auto-activates session: if `status` is `bot_joining` or `connecting`, transitions to `active` and broadcasts `meeting_status` event.
3. Writes `Utterance` to DB.
4. Calls `start_extraction(session_id)` if session is `active` (idempotent — ignores if already running).
5. Broadcasts `utterance` event over WebSocket to workspace room.

WebSocket broadcast shape on utterance:
```json
{
  "type": "utterance",
  "data": {
    "id": "<uuid>",
    "speaker": "<name>",
    "text": "<text>",
    "timestamp_ms": 12345
  }
}
```

---

## Extraction Loop (`src/workers/extraction_loop.py`)

### Lifecycle

```python
async def start_extraction(session_id: str)
```
- Idempotent. If session already has an active task in `_active_sessions`, returns immediately.
- Creates `asyncio.Task` running `_extraction_loop(session_id)`.

```python
async def stop_extraction(session_id: str)
```
- Cancels the task and removes from `_active_sessions`.

### Main Loop

```python
async def _extraction_loop(session_id: str)
```
- Creates a `RollingBuffer()` instance (private to the loop).
- Tracks `last_utterance_id: uuid.UUID | None` as a cursor.
- Every `EXTRACTION_INTERVAL_S` (30s): calls `_run_extraction_cycle()`.
- Terminates on `_SessionEnded` (session status `ended` or `failed`).
- Silently catches and logs other exceptions, continues running.
- Cleans up `_active_sessions` in `finally`.

### Extraction Cycle

```python
async def _run_extraction_cycle(
    session_id: str,
    buffer: RollingBuffer,
    last_utterance_id: uuid.UUID | None,
) -> uuid.UUID | None
```

Steps:
1. Fetch session; raise `_SessionEnded` if missing or status is `ended`/`failed`.
2. Query only NEW utterances (created after `last_utterance_id`'s timestamp).
3. Add each new utterance to `buffer` via `buffer.add(speaker, text, timestamp_ms)`.
4. Get `transcript_text = buffer.get_text()` — last 45s of utterances as `"Speaker: text\n..."`.
5. Truncate to 12000 chars (~3000 tokens) if necessary (takes trailing end).
6. Call `extract_action_items(transcript_text)` — Cerebras.
7. Call `filter_proposals(raw_items)` — confidence/readiness/verb filter.
8. For each filtered item:
   a. Call `is_duplicate(session_id, dedupe_key, text, existing_dicts)`.
   b. Compute embedding via `get_embedding(body or title)`.
   c. Retrieve RAG context: `_get_rag_context(session_id, f"{title} {body}", top_k=5)`.
   d. Collect unique speakers from `buffer._entries` as `participants`.
   e. Call `gate.evaluate_action(candidate, transcript_text, rag_chunks, meeting_ctx)`.
   f. Create `Proposal` with `status=pending` (gate passed) or `status=dropped` (gate failed).
9. Commit all proposals atomically.
10. Broadcast each proposal as `proposal_created` or `proposal_dropped` over WebSocket.

### RAG Context Helper

```python
async def _get_rag_context(
    session_id: str,
    query_text: str,
    top_k: int = 5,
) -> list[dict]
```
- Returns list of `{"time_offset": "<timestamp_ms>", "text": "<Speaker>: <text>"}`.
- Embeds `query_text`, scores all session utterances by cosine similarity, returns top-k sorted chronologically.
- Returns `[]` on any error.

---

## Extraction Service (`src/services/cerebras.py`)

### Client

```python
def get_client() -> Cerebras
```
- Singleton. Initialized with `settings.cerebras_api_key`.
- Shared between extraction and gate services.

### Extraction

```python
async def extract_action_items(transcript_text: str) -> list[dict]
```
- Model: `EXTRACTION_MODEL = "gpt-oss-120b"` (Cerebras).
- Temperature: `0.1`, max_tokens: `2048`.
- Runs in thread pool via `loop.run_in_executor(None, _call_cerebras)` (Cerebras SDK is sync).
- Retry: if `response_format={"type": "json_object"}` fails, retries without `response_format` and appends `"IMPORTANT: Return ONLY valid JSON"` to system prompt.

**System Prompt (verbatim):**
```
You are an action-item extractor for meeting transcripts.
Extract actionable items that someone needs to do after the meeting.

For each action item, determine:
- action_type: "gmail_draft" if it involves sending an email, "html_artifact" if it involves building/prototyping/mocking up/designing/visualizing something (UI, diagram, flowchart, wireframe, dashboard, landing page, prototype, SVG, etc.), otherwise "generic_draft"
- title: short title (max 80 chars)
- body: the full action item description
- recipient: email recipient if gmail_draft, null otherwise
- confidence: 0.0-1.0 how confident this is a real action item
- readiness: 1-5 scale assessing whether the conversation topic has resolved. 5=fully resolved/moved on, 1=still actively debating. Only mark 4-5 if the group has clearly agreed or moved past the topic.
- dedupe_key: a short canonical key for deduplication (e.g. "email-bob-proposal")

Return a JSON array of action items. If none found, return [].
Only extract items with clear action verbs (send, create, schedule, follow up, draft, review, etc.).
```

**User message:** `"Transcript:\n{transcript_text}"`

**Returned field schema per item:**
```json
{
  "action_type": "gmail_draft | html_artifact | generic_draft",
  "title": "string (max 80 chars)",
  "body": "string",
  "recipient": "email string or null",
  "confidence": 0.0,
  "readiness": 1,
  "dedupe_key": "short-canonical-key"
}
```

### JSON Parsing (`_parse_items`)

Tries in order:
1. Direct `json.loads(content)`.
2. Extract from markdown code block ` ```json ... ``` `.
3. Regex search for `[...]` or `{...}` in raw text.
4. Returns `[]` on all failures.

Handles both list and dict responses (extracts first list value from dict).

---

## Filtering (`src/services/extractor.py`)

### RollingBuffer

```python
class RollingBuffer:
    def __init__(self, window_s: int = ROLLING_BUFFER_WINDOW_S)  # 45s default
    def add(self, speaker: str, text: str, timestamp_ms: int)
    def get_text(self) -> str   # "Speaker: text\n..." for all entries in window
    def has_new_content(self, since: float) -> bool
    @property size: int

@dataclass
class BufferEntry:
    speaker: str
    text: str
    timestamp_ms: int
    added_at: float  # wall clock time (time.time())
```

Pruning: on each `add()` and `get_text()`, entries older than `window_s` seconds by wall clock are evicted from the front of the deque.

### filter_proposals

```python
def filter_proposals(items: list[dict]) -> list[dict]
```

Rules applied in order:
1. Drop if `confidence < 0.5` (`CONFIDENCE_THRESHOLD_DROP`).
2. Drop if `readiness` is present and `readiness < 3`.
3. Check for action verb in title (word-boundary match against `title.lower().split()`).
4. If no action verb in title, check first 5 words of body.
5. Drop if no action verb found AND `confidence < 0.75` (`CONFIDENCE_THRESHOLD_UNSURE`).
6. Append `" ??"` to title for items with `0.5 <= confidence < 0.75` (uncertainty marker).

Action verb set:
```python
ACTION_VERBS = {
    "send", "draft", "create", "schedule", "follow", "review", "share",
    "update", "write", "prepare", "submit", "forward", "reply", "set",
    "book", "arrange", "organize", "compile", "complete", "finalize",
    "build", "prototype", "mock", "design", "visualize", "diagram", "wireframe",
}
```

---

## Deduplication (`src/services/deduper.py`)

```python
def compute_dedupe_hash(session_id: str, dedupe_key: str) -> str
```
- `sha256(f"{session_id}:{dedupe_key}")` as hex digest.

```python
async def is_duplicate(
    session_id: str,
    dedupe_key: str,
    text: str,
    existing_proposals: list[dict],  # [{"dedupe_hash": str, "embedding": list | None}]
) -> bool
```

Check order:
1. Exact hash match against all `existing_proposals[*].dedupe_hash`.
2. Cosine similarity of new item's embedding against all existing embeddings.
   - Threshold: `> 0.88` (`COSINE_DEDUPE_THRESHOLD`).
   - Falls back to hash-only if embedding fails.

---

## Gate Scoring (`src/services/gate.py`)

### Entrypoint

```python
async def evaluate_action(
    candidate: dict,             # {title, action_type, body, recipient}
    transcript_window: str,      # Recent transcript text (up to 12000 chars)
    rag_context_chunks: list[dict],  # [{time_offset, text}] — historical context
    meeting_context: dict,       # {title, participants: [str]}
) -> dict
```

Returns:
```python
{
    "scores": {
        "explicitness": float,
        "value": float,
        "specificity": float,
        "urgency": float,
        "feasibility": float,
        "evidence_strength": float,
        "readiness": float,
    },
    "avg_score": float,           # mean of all 7 dimension scores
    "passed": bool,               # avg_score > 3.8 AND readiness >= 4
    "verbatim_evidence_quote": str | None,
    "missing_critical_info": list[str],
}
```

On any error, returns fail-open result:
```python
{
    "scores": {},
    "avg_score": 0.0,
    "passed": True,
    "verbatim_evidence_quote": None,
    "missing_critical_info": [],
    "error": "<reason>",
}
```

### Gate Scoring Dimensions (1–5 scale, 1=worst, 5=best)

| Dimension | 1 (Low) | 5 (High) |
|---|---|---|
| `explicitness` | Vague suggestion or passing thought | Clear, explicit verbal commitment or direct request with owner in live window |
| `value` | Trivial, administrative, or low-impact | High-impact, critical-path action directly driving project forward |
| `specificity` | Too abstract to understand without guessing | "Who, what, and how" perfectly clear (RAG context allowed) |
| `urgency` | "Someday" or backlog item | Must be completed immediately or shortly after meeting |
| `feasibility` | Cannot draft a valid artifact with current context | All required fields (recipient, topic, core ask) present to generate draft now |
| `evidence_strength` | Based on vibes, assumptions, or implicit context | Directly supported by verbatim, unambiguous quote in transcript_window |
| `readiness` | Active debate ongoing | Fully resolved; conversation has definitively moved on, commitment stands unchallenged |

**Critical rule**: The explicit commitment MUST occur in `transcript_window`. RAG chunks (`rag_context_chunks`) are only allowed to inform Specificity and Feasibility, not to establish that a commitment was made.

### Pass Condition

```python
passed = avg_score > GATE_AVG_THRESHOLD and scores["readiness"] >= GATE_READINESS_THRESHOLD
# i.e.: avg > 3.8 AND readiness >= 4
```

### Gate System Prompt (verbatim)

```
You are the Action Item Judge for a live meeting assistant. Your sole responsibility is to evaluate a candidate action item against the provided transcript data using a strict 1-5 rubric.

You will receive two types of transcript data:
1. rag_context_chunks: Historical snippets from earlier in the meeting, provided ONLY to resolve ambiguities (e.g., who "he" is, or what "the project" refers to).
2. transcript_window: The recent conversation window. This includes the moment the action was allegedly triggered, plus the immediate trailing conversation to evaluate if the topic has resolved.

CRITICAL RULE: The explicit commitment or request MUST occur within the `transcript_window`. Do not approve actions where the commitment only exists in the `rag_context_chunks`. RAG chunks are strictly for filling in missing details to improve Specificity and Feasibility.

SCORING RUBRIC (1 = Lowest/Worst, 5 = Highest/Best):
1. Explicitness: 1 = Vague suggestion or passing thought. 5 = Clear, explicit verbal commitment or direct request with a designated owner in the live window.
2. Value: 1 = Trivial, administrative, or low-impact task. 5 = High-impact, critical-path action that directly drives the project forward.
3. Specificity: 1 = Too abstract to understand without guessing key facts. 5 = Highly concrete; the "who, what, and how" are perfectly clear (using RAG context if needed).
4. Urgency: 1 = A "someday" or backlog item. 5 = Must be completed immediately or shortly after this meeting.
5. Feasibility: 1 = Impossible to draft a valid artifact (ticket, email) with the current context. 5 = All required fields (recipient, topic, core ask) are present (using RAG context if needed) to generate a perfect draft right now.
6. Evidence Strength: 1 = Based on vibes, assumptions, or implicit context. 5 = Directly supported by a verbatim, unambiguous quote in the `transcript_window`.
7. Readiness: 1 = Active debate ongoing. The participants are still actively discussing, modifying, or debating the specifics of this action. 3 = A commitment was made, but the conversation is lingering on closely related details or minor clarifications. 5 = Fully resolved. The conversation has definitively moved on to a completely different topic, and the original commitment stands unchallenged.

EXTRACTION RULES:
- verbatim_evidence_quote: You must extract the exact, continuous string of text from the `transcript_window` that proves this action was committed to. Do not pull this from RAG chunks. If none exists, output null.
- missing_critical_info: List 1-2 bullet points of what is required to execute this action but remains missing even after reviewing both the window and RAG chunks. If nothing is missing, output an empty array [].

OUTPUT FORMAT:
You must respond ONLY with a valid JSON object with keys: scores (object with explicitness, value, specificity, urgency, feasibility, evidence_strength, readiness), verbatim_evidence_quote (string or null), missing_critical_info (array of strings).
```

### Gate User Payload (JSON-serialized)

```json
{
  "meeting_context": {"title": "...", "participants": ["Alice", "Bob"]},
  "rag_context_chunks": [{"time_offset": "12345", "text": "Alice: blah"}],
  "transcript_window": "Alice: ...\nBob: ...",
  "candidate_action": {
    "title": "...",
    "action_type": "gmail_draft",
    "body": "...",
    "recipient": "bob@example.com"
  }
}
```

### Gate Model Call

```python
client.chat.completions.create(
    model="zai-glm-4.7",
    messages=[
        {"role": "system", "content": GATE_SYSTEM_PROMPT},
        {"role": "user", "content": user_payload},  # JSON string
    ],
    response_format={"type": "json_object"},
    max_tokens=1024,
    temperature=0.1,
)
```

Retry: if `response_format` fails, retries without it (same pattern as extraction).

### JSON Parsing (`_parse_gate_response`)

Tries in order:
1. Direct `json.loads(content)`.
2. Extract from markdown code block.
3. Regex search for `{...}` object.
4. Returns `None` → triggers `_fail_open`.

---

## Execution Service (`src/services/executor.py`)

All three executor functions follow the same pattern:
1. Optionally call `_get_conversation_context(session_id, query)` for RAG grounding.
2. Create a `CrewAI` `Agent` + `Task` + `Crew`.
3. Run `crew.kickoff()` in thread pool.
4. Return standardized result dict.

### Gmail Draft

```python
async def execute_gmail_draft(
    entity_id: str,   # Composio entity ID (from workspace.composio_entity_id)
    recipient: str,
    subject: str,
    body: str,
    session_id: str | None = None,
) -> dict
```

Returns on success:
```python
{"status": "success", "type": "gmail_draft", "recipient": ..., "subject": ..., "result": str(crew_output)}
```

Returns on failure:
```python
{"status": "failed", "type": "gmail_draft", "error": str(e)}
```

Agent definition:
```python
Agent(
    role="Email Assistant",
    goal="Create Gmail drafts informed by meeting context",
    backstory="You are a professional email assistant. You use meeting transcript context to write accurate, well-informed email drafts.",
    tools=gmail_tools,   # from Composio toolkit "gmail"
    llm=EXECUTOR_MODEL,  # "gemini/gemini-3-pro-preview"
    verbose=False,
)
```

Task description template:
```
Create a Gmail draft with:
To: {recipient}
Subject: {subject}
Body: {body}

Relevant meeting context (use to inform tone and details):
---
{context}
---

Use the meeting context to make the email specific and grounded. Do not fabricate details not present in the context.
```

### HTML Artifact

```python
async def execute_artifact(
    title: str,
    body: str,
    session_id: str | None = None,
) -> dict
```

Returns on success:
```python
{"status": "success", "type": "html_artifact", "artifact_html": str, "title": str}
```

Agent definition:
```python
Agent(
    role="Visual Artifact Generator",
    goal="Create self-contained HTML artifacts: pages, Mermaid diagrams, or SVG graphics",
    backstory="You are an expert frontend developer and data visualization specialist. You create beautiful, self-contained HTML documents. You decide the best format: a full HTML page with inline CSS/JS, a Mermaid diagram, or an SVG graphic.",
    tools=[],
    llm=EXECUTOR_MODEL,
    verbose=False,
)
```

Format selection in task description (three options):
1. Full HTML page — for UI mockups, dashboards, landing pages. Use inline CSS and JS.
2. Mermaid diagram — wrap in HTML with `<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js">` and a `<pre class="mermaid">` block.
3. SVG — wrap in HTML with inline `<svg>`.

Post-processing: strips leading ` ``` ` and trailing ` ``` ` fences if present.

### Generic Draft

```python
async def execute_generic_draft(
    title: str,
    body: str,
    session_id: str | None = None,
) -> dict
```

Returns on success:
```python
{"status": "success", "type": "generic_draft", "title": str, "result": str(crew_output)}
```

Agent definition:
```python
Agent(
    role="Writing Assistant",
    goal="Create polished, professional drafts informed by meeting context",
    backstory="You are a skilled writer. You use meeting transcript context to create accurate, grounded professional documents.",
    tools=[],
    llm=EXECUTOR_MODEL,
    verbose=False,
)
```

### CrewAI Setup (shared across all three)

```python
Crew(agents=[agent], tasks=[task], verbose=False, tracing=True)
# crew.kickoff() is called via loop.run_in_executor(None, crew.kickoff)
```

`tracing=True` enables CrewAI telemetry (controlled by `CREWAI_TRACING_ENABLED` env var).

### Composio Tool Retrieval

```python
async def _get_gmail_tools(entity_id: str) -> list
```
- Creates `Composio(provider=CrewAIProvider(), api_key=settings.composio_api_key)`.
- Calls `sdk.tools.get(user_id=entity_id, toolkits=["gmail"])`.
- Returns empty list on failure → `execute_gmail_draft` returns `{"status": "failed", "error": "No Gmail tools available..."}`.

### RAG Context in Executor

```python
async def _get_conversation_context(session_id: str, query_text: str, top_k: int = 5) -> str
```
- Same embedding + cosine similarity approach as `_get_rag_context` in extraction_loop.
- Returns `"\n".join(f"{u.speaker}: {u.text}" for ...)` (plain text, not dicts).
- Falls back to `_get_recent_context(session_id, limit=10)` if embedding fails.

---

## WebSocket Broadcast Events

All broadcasts use `manager.broadcast(workspace_id, payload)`.

| Event type | Trigger | Payload fields |
|---|---|---|
| `utterance` | Utterance stored | `id, speaker, text, timestamp_ms` |
| `meeting_status` | Session activated | `session_id, status` |
| `proposal_created` | Gate passed | `id, action_type, title, body, recipient, confidence, gate_passed, gate_scores, gate_avg_score, gate_evidence_quote, gate_missing_info` |
| `proposal_dropped` | Gate failed | same fields as proposal_created |

---

## Error Handling Summary

| Location | Error | Behavior |
|---|---|---|
| `gate.evaluate_action()` | Any exception | `_fail_open()` — returns `passed=True`, logs warning |
| `gate.evaluate_action()` | Missing score dimension | `_fail_open()` |
| `gate.evaluate_action()` | Unparseable JSON | `_fail_open()` |
| `_extraction_loop()` | Extraction cycle error | Log + continue loop |
| `_extraction_loop()` | `_SessionEnded` | Graceful exit |
| `is_duplicate()` | Embedding failure | Falls back to hash-only |
| `_get_rag_context()` | Any error | Returns `[]` |
| `execute_*()` | Any exception | Returns `{"status": "failed", "error": str(e)}` |
| `_get_gmail_tools()` | No tools returned | `execute_gmail_draft` returns failed status |
| Cerebras `response_format` | Not supported | Retry without it, append JSON instruction to prompt |
| Broadcast failures | Any exception | Silently suppressed (pipeline continues) |

---

## Key File Paths (relative to `apps/api/`)

```
src/workers/extraction_loop.py   — Main pipeline loop, RAG for gate, proposal creation
src/services/cerebras.py         — Extraction LLM client + extract_action_items()
src/services/gate.py             — Gate scoring, 7-dim rubric, evaluate_action()
src/services/executor.py         — CrewAI gmail_draft, html_artifact, generic_draft
src/services/extractor.py        — RollingBuffer, filter_proposals()
src/services/deduper.py          — compute_dedupe_hash(), is_duplicate()
src/services/embeddings.py       — get_embedding(), cosine_similarity()
src/services/ws_manager.py       — WebSocket manager.broadcast()
src/api/routes_ingest.py         — POST /api/ingest/utterance
src/models/tables.py             — All DB models and enums
src/config/constants.py          — All tunable constants and model names
```
