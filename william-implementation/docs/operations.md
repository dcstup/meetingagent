# Operations and Debugging

## Composio auth model

Use menu/settings auth (not in-chat auth prompts):

- Session is created with `manage_connections=false` in Python runner
- Settings page handles toolkit connection lifecycle
- Endpoints:
  - `GET /composio/connections`
  - `POST /composio/authorize`

## Execution modes

- `COMPOSIO_EXEC_MODE=mock`: no side effects; best for UI/dev flow
- `COMPOSIO_EXEC_MODE=python_agents`: Composio Native Tools + OpenAI Responses loop
- `COMPOSIO_EXEC_MODE=http`: sends to configured Composio HTTP endpoint

For `python_agents` mode, install:

```bash
python3 -m pip install -r apps/server/scripts/requirements.txt
```

## Diagnostics endpoints

- `GET /health`: basic service flags and mode checks
- `GET /diagnostics`: detailed checks for storage/OpenAI/Deepgram/Composio

## UI diagnostics panel

`System Checks` panel includes:

- service readiness checks
- warning resolution hints
- server debug snapshot
- live payload feeds:
  - OpenAI input/output
  - Composio input/output

## Action flicker mitigation

Suggested action IDs are deterministic (hash of normalized `title|owner|dueDate`) to reduce remount flicker while transcript evolves.

## Common failure areas

### No transcript

- Missing mic permission
- Invalid/missing `DEEPGRAM_API_KEY`
- WebSocket connection issues

### No action extraction

- Missing/invalid `OPENAI_API_KEY`
- Insufficient final transcript lines for extraction

### Composio execution failure

- Missing toolkit connection for chosen action
- Invalid Composio env settings
- Python dependency issues in `python_agents` mode

