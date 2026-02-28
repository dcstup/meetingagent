# Meeting Agent

Meeting Agent is a real-time AI chief of staff for meetings.

It listens to your conversation, captures a live transcript, suggests action items, and executes approved tasks through connected tools.

## What you can do

- Stream live meeting audio and see transcript updates in real time
- Get suggested action items with owner, confidence, and due-date hints
- Approve, edit, or deny each action before execution
- Execute approved actions through Composio-connected apps (for example Gmail, Calendar, Slack, task tools)
- Watch live system checks and API payload debug streams in the right-side panel

## How it works

1. Audio is streamed from your browser microphone.
2. Deepgram converts audio into speaker-labeled transcript lines.
3. OpenAI extracts actionable commitments from transcript context.
4. You approve/edit/deny suggested items.
5. Composio executes approved objectives using the best available tools.
6. Status updates stream live: `suggested -> approved -> executing -> completed/failed`.

## Quick start

1. Install dependencies:

```bash
npm install
```

2. Create env file:

```bash
cp .env.example .env
```

3. Fill required keys in `.env` (at minimum, OpenAI + Deepgram for full real-time flow).

4. Start the app:

```bash
npm run dev
```

5. Open the UI:

- [http://localhost:3000](http://localhost:3000)

## First-time setup checklist

- Open the app and click `Connect`.
- Click `Start mic` and allow microphone access.
- Speak to generate transcript lines.
- Review suggested actions in the Action Items strip.
- Approve one action to test execution.
- Open `Composio settings` to connect toolkits if execution requires auth.

## UI guide

### Header

- Meeting ID input
- Connect/Disconnect
- Start/Stop mic
- Link to Composio settings

### Action Items (top full-width card)

- Fixed-height container with horizontally scrollable action cards
- Each card supports vertical scrolling for longer content
- Controls per item: `Approve`, `Edit`, `Deny`

### Transcript (bottom-left)

- Live interim transcript line
- Finalized transcript history
- Manual transcript injection for demo/testing

### System Checks (bottom-right)

- WebSocket/mic/storage/API diagnostics
- Warning resolution hints
- Live raw payload feeds for:
  - OpenAI input/output
  - Composio input/output

## Composio connections (Settings page)

Use the settings page to authenticate apps outside chat flow.

- Open `/settings` from the dashboard link
- Check current toolkit connection status
- Click connect for required toolkits
- Return to meeting and approve actions again

## Environment variables

Set these in `.env`:

- `PORT` (default `8080`)
- `NEXT_PUBLIC_WS_URL` (default `ws://localhost:8080/ws`)
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (default `gpt-4.1-mini`)
- `DEEPGRAM_API_KEY`
- `COMPOSIO_API_KEY`
- `COMPOSIO_EXEC_MODE` (`mock` | `http` | `python_agents`)
- `COMPOSIO_BASE_URL` (required for `http` mode)
- `COMPOSIO_EXTERNAL_USER_ID` (required for `python_agents` mode)
- `COMPOSIO_PYTHON_BIN` (default `python3`)
- `SUPABASE_URL` (optional but recommended)
- `SUPABASE_SERVICE_ROLE_KEY` (optional but recommended)

## Execution modes

### `mock` mode

- No external side effects
- Best for local UI testing

### `python_agents` mode

- Real Composio + OpenAI Responses tool execution
- Install Python dependencies:

```bash
python3 -m pip install -r /Users/william/ProjectsLocal/LLHackathon/meetingagent/apps/server/scripts/requirements.txt
```

### `http` mode

- Uses configured Composio HTTP endpoint

## Troubleshooting

### No transcript appears

- Confirm microphone permission in browser
- Confirm `DEEPGRAM_API_KEY` is valid
- Check System Checks panel for failures

### Actions are not extracted

- Confirm `OPENAI_API_KEY` is valid
- Speak complete sentences with explicit commitments or tasks
- Use manual transcript inject to test extraction quickly

### Action execution fails

- Open settings and connect required Composio toolkits
- Confirm `COMPOSIO_EXEC_MODE` and related env vars are correct
- Inspect `Live Composio Output Payloads` in System Checks for exact error

### Storage shows warning

- Add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- Run migrations/push schema for persistent storage

## API endpoints

- `GET /health`
- `GET /diagnostics`
- `GET /composio/connections?userId=...`
- `POST /composio/authorize`

## Notes

- All OpenAI prompt text for extraction/execution is centralized in:
  - `/Users/william/ProjectsLocal/LLHackathon/meetingagent/apps/server/src/lib/openai-prompts.ts`
- The app is optimized for fast demo iteration and keeps approval in the loop before external side effects.
