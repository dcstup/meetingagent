# YesChef Specs (approve = "yes chef")

## A) Human action items + info to provide Claude Code

### 1) Accounts, keys, and access (must-have)

* **Recall.ai**

  * API key: `(see .env → RECALL_API_KEY)`
  * Confirm you can create bots for **Google Meet** in your Recall account: Tested and working
  * Bot display name: "YesChef"

* **Composio**

  * API key: `(see .env → COMPOSIO_API_KEY)`
  * Confirm Composio workspace has **Google Calendar + Gmail** tools enabled: confirmed enabled
  * Confirm the **shared app OAuth** flow works for your test Google account: confirmed working
  * If Composio requires “allowed redirect URIs,” provide those / confirm how it’s handled: we're using Composio's default auth provider so that should be handled?

* *embeddings**

  * DeepInfra API key: `(see .env → DEEPINFRA_API_KEY)`
  * Model we want: `Qwen/Qwen3-Embedding-0.6B`
  
* **LLM Extraction Model / Executor Model**
  Provider: Cerebras
  CEREBRAS_API_KEY=`(see .env → CEREBRAS_API_KEY)`
  * Extraction model: `cerebras/gpt-oss-120b` 
  * Executor model (via CrewAI): `cerebras/zai-glm-4.7`

* **Railway**

  * Railway account access (already logged in on CLI) **or** Railway API token: `(see .env → RAILWAY_TOKEN)`
  * backend deployed as: one Railway service
  * If you want Claude Code can deploy via CLI (use Railway skill to figure this out)

### 2) Google Meet + Calendar setup (demo reliability)

* Use a Google Workspace / Google account where:

  * You can create Meet links from Calendar
  * **External participants (the bot)** can join automatically (since you said you control the meeting)
* Create 2–3 test events (Meet links present) with known times.
* Confirm that when a bot joins, it’s admitted automatically (no waiting room / knock). CONFIRMED, with exception that it must be admitted via waiting room. That's fine, we should engineer to account for this case where its entry may be delayed slightly.

### 3) Domain + webhook reachability decisions (Claude, you will handle this part actually)

* Decide the public base URL for the backend (Railway will provide it).
* Confirm inbound webhook traffic is allowed (Railway generally is).

### 4) Secrets I will hand to you, Claude Code

Claude Code, you are given a `.env` file containing:

* `RECALL_API_KEY=...`
* `COMPOSIO_API_KEY=...`
* `DEEPINFRA_API_KEY=...`
* `CEREBRAS_API_KEY=...`
* `RAILWAY_TOKEN=...`
* `APP_PUBLIC_URL=https://<railway-subdomain>.up.railway.app` (let it fill after deploy)
* `BOT_NAME=YesChef`

---

## B) Full plan/spec for Claude Code (end-to-end, real meeting, no replay)

### Goal

When a Google Calendar event containing a Google Meet link starts:

1. backend creates a Recall bot to join the Meet
2. backend receives diarized transcript utterances in real time
3. every few seconds backend proposes **action items** (Gmail draft or generic draft)
4. Chrome extension shows proposals; user approves/dismisses
5. on approve: **executor agent** creates a Gmail draft (via Composio) or generates a generic draft, then shows results in overlay
6. success is visible both in **Gmail Drafts** and in the overlay

### Non-goals (v1)

* Linear/GitHub write actions
* “Open questions / unresolved debates”
* Meeting etiquette safeguards
* Multi-user / multi-tenant

---

## 1) Architecture choices (keep it simple, robust)

### Deployment split

* **Backend API (Railway)**: FastAPI + webhook endpoints + WS endpoints + extraction pipeline
* **Worker (in-process)** for MVP:

  * Use an internal asyncio task queue
  * No separate Redis/Celery needed for demo (unless it becomes flaky)
* **DB**:

  * Easiest: Postgres on Railway
  * Tables for meetings, utterances, proposals, approvals, executions
  * pgvector optional in v1; you can still store embeddings in Postgres if you want, but don’t block MVP on it

### Chrome extension

* Overlay injected into Meet tab
* WebSocket connection to Railway backend
* Minimal UI: transcript feed + proposal cards + result panel

---

## 2) Data model (explicit contracts)

### Entities

**workspace**

* `id`
* `created_at`
* `composio_google_connection_id` (string)
* `overlay_token` (secret)

**calendar_event**

* `id`
* `workspace_id`
* `google_event_id`
* `start_time`, `end_time`
* `meet_url`
* `raw_payload` (json)

**meeting_session**

* `id`
* `workspace_id`
* `calendar_event_id`
* `status`: `scheduled | joining | live | ended | failed`
* `recall_bot_id` (string)
* `started_at`, `ended_at`
* `last_utterance_at`

**utterance**

* `id`
* `meeting_session_id`
* `source_event_id` (id from Recall if available; else hash)
* `speaker` (string)
* `text` (string)
* `ts` (datetime)
* `raw_payload` (json)

**proposal**

* `id` (stable hash: `sha256(meeting_session_id + dedupe_key)`)
* `meeting_session_id`
* `title`
* `rationale`
* `confidence` float
* `action_type`: `gmail_draft | generic_draft`
* `dedupe_key`
* `evidence_snippets` (json array)
* `status`: `proposed | dismissed | approved | executed | failed`
* `created_at`

**execution**

* `id`
* `proposal_id`
* `status`: `running | success | failed`
* `result_type`: `gmail_draft | generic_draft`
* `gmail_draft_id` nullable
* `artifact_text` nullable
* `error` nullable
* `created_at`

---

## 3) Calendar → Meet link detection (v1 rules)

Given a Google Calendar event payload, extract Meet URL from:

1. `hangoutLink` or `conferenceData.entryPoints[].uri` if present
2. else parse first URL in `location`
3. else parse first URL in `description`
   Then validate it contains `meet.google.com/`.

Trigger rule:

* consider events starting within the next **2 minutes** every **30 seconds**
* when `now ∈ [start_time - 60s, start_time + 5m]` and no meeting_session exists → create session + join

Overlap rule:

* create sessions for all overlapping
* if Recall account limits concurrent bots, join earliest and mark others as `failed` with reason `overlap_limit`

---

## 4) Recall integration (webhook-first)

### Endpoints needed

* `POST /webhooks/recall/transcript`

  * receives utterance events (diarized)
  * authenticates via `X-Recall-Signature` if Recall supports signatures, otherwise use a shared secret in URL path (e.g. `/webhooks/recall/<secret>/transcript`)

### Bot creation flow

On session start:

* call Recall “create bot” with:

  * meet URL
  * callback webhook URL
  * “real-time transcription on”
* store `recall_bot_id` in meeting_session
* status → `live` when first utterance arrives (or when Recall confirms join)

---

## 5) Extraction pipeline (your <10s requirement)

Maintain a rolling buffer per meeting_session.

### Windowing

* Keep last **90 seconds** of utterances, speaker-labeled
* Trigger extraction every **5 seconds** IF:

  * new utterances since last extraction AND
  * last extraction was ≥5 seconds ago

### Extraction output schema (strict)

`proposals[]` where each proposal has:

* `title` (<= 80 chars)
* `rationale` (<= 160 chars)
* `confidence` (0..1)
* `action_type` = `gmail_draft` or `generic_draft`
* `dedupe_key` (normalized slug)
* `evidence_snippets` (2–3 short snippets from window)

### Filter rules

* confidence < 0.5 → drop
* 0.5–0.75 → title append “??”
* must include an action verb (simple heuristic on title)

### Dedupe rules

* If `proposal_id` already exists → merge snippets and update confidence if higher
* Additionally compute embedding similarity between new `dedupe_key` and existing open proposals; if cosine > 0.88, merge

---

## 6) Approval + execution semantics (draft-first always)

### Extension actions

* Approve: `POST /api/proposals/{id}/approve`
* Dismiss: `POST /api/proposals/{id}/dismiss`

### Executor behavior

On approve:

* create an `execution` record
* run executor agent with:

  * proposal details
  * evidence snippets
  * optional retrieval tool (fetch last N utterances)
* If `action_type=gmail_draft`:

  * generate: `to`, `subject`, `body`
  * call Composio Gmail tool to **create draft**
  * store returned `gmail_draft_id`
* If `generic_draft`:

  * generate artifact text
  * store in `execution.artifact_text`

Return result to extension via WebSocket event:

* `execution_success` or `execution_failed`

---

## 7) Chrome extension UX (minimum viable, demo-effective)

### UI layout

* Transcript tab:

  * speaker label + text
* Actions tab:

  * proposal cards with Approve / Dismiss
* Results panel:

  * show draft subject/body, plus Gmail draft ID link if possible

### Connectivity

* On load in a Meet tab:

  * connect WS to `wss://<railway>/ws?workspace=<id>`
  * send `overlay_token` for auth

### WS event types

* `meeting_status` { session_id, status }
* `utterance` { speaker, text }
* `proposal_created` { proposal... }
* `proposal_updated` { proposal... }
* `execution_started` { proposal_id }
* `execution_success` { proposal_id, result_type, gmail_draft_id?, artifact_text? }
* `execution_failed` { proposal_id, error }

---

## 8) Test-driven agent development plan (without replay mode)

You said “must actually work,” but you still want TDD. Do this:

### Level 1: unit tests (no external network)

* Meet URL extraction from various event payload fixtures
* Rolling buffer + extraction trigger logic
* Proposal id + dedupe merge logic
* WS event serialization

### Level 2: contract tests (real providers, gated)

* A test script that:

  * uses Composio to list calendar events
  * uses Composio to create a Gmail draft (and asserts draft exists)
  * uses Recall to create a bot for a known Meet URL (smoke only)
    These tests run manually (or CI with secrets).

### Level 3: live e2e “demo test”

A single command:

* deploy backend → open extension → start meeting → speak scripted lines → approve → confirm Gmail draft created

Claude Code should automate as much as possible, but the human will still “speak lines” in the meeting.

---

## 9) Operational concerns (to prevent demo death)

* Add a backend “health” page `/health`
* Add `/debug/sessions` to show sessions + statuses
* Add `/debug/last_webhook` to show last recall event received
* Add timeout handling:

  * if no utterance received within 60s after join attempt → mark failed and surface in UI
* Add basic logging with correlation ids per session

---

## 10) Concrete build sequence for Claude Code (handoff order)

1. **Repo scaffold**

   * FastAPI app, DB models/migrations, config/env loader
2. **Composio onboarding UI**

   * connect Google, store `composio_connection_id`
3. **Calendar watcher**

   * poll events, extract meet URLs, create meeting_session
4. **Recall integration**

   * create bot, webhook receiver, utterance persistence
5. **WebSocket server**

   * push utterances + proposals + execution results
6. **Extractor**

   * rolling window, structured output, dedupe
7. **Approval endpoints**
8. **Executor**

   * gmail draft via Composio + generic drafts
9. **Chrome extension**

   * overlay UI + WS + approve/dismiss calls
10. **Railway deploy**

* env vars, migrations, webhook URL wiring

---
