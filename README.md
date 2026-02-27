# Meeting Assistant

Real-time AI agent that joins Zoom meetings, transcribes conversations with speaker attribution, and takes actions autonomously — answering questions, sending emails, and creating tasks.

## How It Works

```
Zoom Meeting
  → Recall.ai bot joins and captures per-participant audio
    → Deepgram transcribes each speaker's stream separately
      → Webhooks deliver transcript entries to our FastAPI server
        → Claude reads the conversation every ~5 seconds
          → Takes action when appropriate (chat reply, email, task)
```

The agent only acts on clear triggers — a question asked, an email requested, or an action item identified. It stays silent during normal conversation.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Runtime | Python 3.12, async |
| Zoom Bot | [Recall.ai](https://recall.ai) — managed bot infrastructure |
| Speech-to-Text | [Deepgram](https://deepgram.com) — real-time streaming with speaker diarization |
| LLM | [Claude](https://anthropic.com) — decides when and how to act |
| Tool Integration | [Composio](https://composio.dev) — Gmail and Linear |
| Web Server | FastAPI + uvicorn |
| Deployment | Docker + ngrok (dev) or any container platform (prod) |

## Features

- **Real-time transcription** with per-speaker attribution (names, not just "Speaker 1")
- **Q&A** — answers questions in the Zoom meeting chat
- **Email** — drafts and sends emails via Gmail when requested
- **Task management** — creates and updates Linear issues for action items
- **Auto-cleanup** — detects when meetings end and shuts down gracefully

## Project Structure

```
src/
├── main.py                  # FastAPI app with /join, /stop, /status endpoints
├── config.py                # Settings loaded from .env
├── bot/
│   └── recall_bot.py        # Recall.ai bot lifecycle (create, join, leave, chat)
├── transcription/
│   ├── models.py            # TranscriptEntry and ParticipantInfo models
│   └── transcript_manager.py # Sliding-window transcript buffer
├── agent/
│   ├── brain.py             # Claude decision loop with tool calling
│   ├── prompts.py           # System prompt and message templates
│   └── actions.py           # Composio executor (Gmail/Linear) + chat tool
├── webhooks/
│   ├── server.py            # Webhook route registration
│   └── handlers.py          # Event handlers for transcript and participant events
└── session/
    └── meeting_session.py   # Orchestrator wiring all components together
```

## Prerequisites

You need accounts and API keys for:

1. **[Recall.ai](https://recall.ai)** — sign up and get an API key
2. **[Deepgram](https://deepgram.com)** — get an API key, then add it in the [Recall.ai transcription dashboard](https://us-west-2.recall.ai/dashboard/transcription)
3. **[Anthropic](https://console.anthropic.com)** — get a Claude API key
4. **[Composio](https://composio.dev)** — sign up, get an API key, and authenticate your Gmail and Linear connections in their dashboard
5. **[ngrok](https://ngrok.com)** — free account for local development tunneling

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your API keys

# 2. Run
docker compose up --build

# 3. Join a meeting (from another terminal)
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{"meeting_url": "https://us02web.zoom.us/j/MEETING_ID?pwd=PASSCODE"}'
```

The bot will appear as "Meeting Assistant" in the Zoom call.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/join` | POST | Join a meeting. Body: `{"meeting_url": "..."}` |
| `/stop` | POST | Leave the current meeting and shut down |
| `/status` | GET | Current session info, participants, and recent transcript |
| `/health` | GET | Health check |
| `/webhooks/recall` | POST | Recall.ai webhook receiver (internal) |

## Cloud Deployment

Deploy the Docker image to any container platform (Railway, Fly.io, AWS ECS):

```bash
# Set WEBHOOK_BASE_URL to your deployed URL (no ngrok needed)
# The app exposes port 8000
```

## Configuration

All settings are in `.env`. See `.env.example` for the full list with defaults.

Key settings:
- `RECALL_REGION` — must match your Recall.ai account region
- `WEBHOOK_BASE_URL` — leave empty for ngrok auto-detection, or set to your deployed URL
- `AGENT_TRIGGER_INTERVAL_SECONDS` — how often Claude checks for new transcript (default: 5s)
- `TRANSCRIPT_BUFFER_MAX_ENTRIES` — sliding window size sent to Claude (default: 50)
