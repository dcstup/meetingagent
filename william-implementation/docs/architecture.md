# Architecture

## Product intent

Meeting Agent is a real-time AI chief of staff:

`Audio -> Transcript -> OpenAI extraction -> Human approval -> Composio execution -> Status updates`

## Design principles

- AI-first decisioning over rigid deterministic routing
- Flexible/extensible payload contracts
- Approval gate before side effects
- Fast demo iteration (inline orchestration, no queue infra yet)

## System components

- Web: Next.js app in `apps/web`
- Server: Fastify + WebSocket in `apps/server`
- ASR: Deepgram streaming adapter
- Extraction: OpenAI Responses API
- Execution: Composio adapter (`mock` / `http` / `python_agents`)
- Storage: Supabase if configured; memory fallback otherwise

## Runtime flow

1. `meeting:start` initializes state and streaming session.
2. `audio:chunk` is forwarded to Deepgram.
3. Transcript lines are upserted to meeting state and broadcast.
4. Final lines trigger orchestrator extraction queue.
5. OpenAI extraction suggests actions.
6. User approves/edits/denies actions.
7. Approved action is transformed into `ComposioExecutionRequest`.
8. Composio executes objective and action status is streamed.

## Execution contract

`ComposioExecutionRequest` currently includes:

- `objective`
- `meeting.id`
- approved `action`
- `transcriptContext` (full meeting transcript from meeting store)
- `supabaseContext` hints

### Missing-field policy (prompt-driven)

1. infer from full transcript context
2. query Supabase using available tools
3. ask user only if unresolved

## Prompt source of truth

All OpenAI prompt/snippet text is centralized in:

- `apps/server/src/lib/openai-prompts.ts`

Includes extraction and execution prompts/policies.

## UI structure (current)

- Header controls at top
- Full-width fixed-height `Action Items` card under header
- Horizontally scrollable action sub-cards
- Vertical scroll inside each action card for long content
- `Transcript` and `System Checks` panels below
- Right panel includes live debug payload feeds:
  - OpenAI input/output
  - Composio input/output

## Key files

- Server entry: `apps/server/src/index.ts`
- Orchestration: `apps/server/src/services/orchestrator.ts`
- Extraction: `apps/server/src/services/openai-adapter.ts`
- Composio adapter: `apps/server/src/services/composio-adapter.ts`
- Python execution runner: `apps/server/scripts/composio_execute.py`
- Prompt definitions: `apps/server/src/lib/openai-prompts.ts`
- Shared types: `apps/server/src/types.ts`
- Dashboard UI: `apps/web/app/page.tsx`
- Settings UI: `apps/web/app/settings/page.tsx`
- Supabase schema: `supabase/schema.sql` and `supabase/migrations/`

