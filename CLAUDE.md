# YesChef — Claude Code Configuration

## Role: Orchestrator First

- **Default mode: orchestrator.** Break tasks into subtasks, delegate to subagents (coder, tester, reviewer, researcher, etc.), synthesize results. Only write code directly when explicitly asked or for trivial edits.
- When given a multi-step task, create a plan, spawn parallel agents, and coordinate — don't do everything sequentially yourself.
- Use claude-flow skills proactively for complex work (see MCP & Hooks section below).
- For simple single-file changes, just do them directly — don't over-orchestrate.

## Behavioral Rules (Always Enforced)

- Do what has been asked; nothing more, nothing less
- NEVER create files unless they're absolutely necessary for achieving your goal
- ALWAYS prefer editing an existing file to creating a new one
- NEVER proactively create documentation files (*.md) or README files unless explicitly requested
- NEVER save working files, text/mds, or tests to the root folder
- Never continuously check status after spawning a swarm — wait for results
- ALWAYS read a file before editing it
- NEVER commit secrets, credentials, or .env files
- When uncertain about scope or approach, ASK before doing — a 10-second clarification beats a 10-minute redo

## Architecture & Specs

- See `docs/SPECS.md` for full architectural decisions, API contracts, and feature specs
- See `docs/AGENTS.md` for agent roles and coordination patterns

## Python Runtime

- ALWAYS use `uv` for Python — never bare `python` or `pip`
- Run tests: `cd apps/api && uv run pytest -q`
- Add deps: `cd apps/api && uv add <package>`
- Run scripts: `uv run python script.py`
- The project uses `pyproject.toml` with hatchling, not setup.py/requirements.txt

## Monorepo Layout

```
meetingagent/                  # repo root
├── apps/api/                  # FastAPI backend (Python, uv)
│   ├── src/                   # All backend source code
│   ├── tests/                 # All backend tests (unit/, integration/, contract/)
│   ├── pyproject.toml         # Python deps & config
│   └── railway.toml           # Railway deployment config
├── apps/extension/            # Chrome MV3 extension
├── apps/dashboard/            # Vite+React dashboard (stub)
├── apps/web/                  # Landing site (stub)
├── apps/mobile/               # React Native (stub)
├── packages/api-types/        # Shared OpenAPI types (stub)
├── docs/                      # Documentation, specs, assets
├── turbo.json                 # Turborepo config
└── package.json               # Root workspace config
```

- Backend code goes in `apps/api/src/`, tests in `apps/api/tests/`
- NEVER put Python files in the repo root
- Extension code goes in `apps/extension/`
- Docs go in `docs/`

## Build & Test

```bash
# Backend tests (from repo root)
cd apps/api && uv run pytest -q

# Backend tests (specific)
cd apps/api && uv run pytest tests/unit/ -q
cd apps/api && uv run pytest tests/integration/ -q
```

- ALWAYS run tests after making code changes
- ALWAYS verify tests pass before committing
- **ALWAYS run tests (unit, integration, etc.) in subagents, NEVER in the main session** — use `Agent` tool with `subagent_type: "tester"` to run tests so the main context stays clean for orchestration

## Code Standards

- Keep files under 500 lines
- Type hints on public Python functions, async by default
- Prefer TDD mock-first for new code
- Validate input at system boundaries
- Use parameterized queries for SQL, sanitize output to prevent XSS
- Sanitize all file paths — prevent directory traversal

### Commit Messages

```
<type>(<scope>): <description>

Co-Authored-By: claude-flow <ruv@ruv.net>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

## Security Rules

- NEVER hardcode API keys, secrets, or credentials in source files
- NEVER commit .env files or any file containing secrets
- Always validate user input at system boundaries
- Always sanitize file paths to prevent directory traversal

## Concurrency

- Batch independent tool calls in a single message (parallel reads, parallel agents, etc.)
- Use `run_in_background: true` for agent Task calls
- After spawning agents, STOP — wait for results, don't poll

## Agent Delegation

Use the Agent tool with specialized `subagent_type` for delegation:

| Task | Agent Type | Model |
|------|-----------|-------|
| Code implementation | `coder` or `general-purpose` | sonnet |
| Code review | `reviewer` | sonnet |
| Test writing/running | `tester` | sonnet |
| Research/exploration | `Explore` | haiku |
| Architecture planning | `Plan` | sonnet |
| Quick searches | `Explore` | haiku |

- Spawn multiple agents in parallel when tasks are independent
- Use `isolation: "worktree"` for agents that write code, to avoid conflicts
- Use `model: "haiku"` for simple/fast tasks to save cost

## MCP Integration & Hooks

Claude Flow exposes tools via MCP. Key tools:

| Tool | Purpose |
|------|---------|
| `swarm_init` | Initialize swarm coordination |
| `agent_spawn` | Spawn new agents |
| `memory_store` / `memory_search` | AgentDB pattern storage and semantic search |
| `task_orchestrate` | Task coordination |

### Hooks (lifecycle automation)

| Hook | Trigger | Purpose |
|------|---------|---------|
| `pre-task` | Before task starts | Load context and patterns |
| `post-task` | After task completes | Record completion, train |
| `pre-edit` / `post-edit` | Around file changes | Validate, backup, verify |
| `session-start` / `session-end` | Session lifecycle | Init context / export metrics |
| `route` | Task routing | Route to appropriate agent type |

### Memory System

```bash
# Store a pattern
npx @claude-flow/cli@latest memory store --key "pattern-name" --value "description" --namespace patterns

# Search patterns
npx @claude-flow/cli@latest memory search --query "search terms" --namespace patterns
```

## Deployment (Railway) — CRITICAL

**There is NO automatic deployment. Git pushes do NOT trigger builds.** Railway is not connected to GitHub for this project. Deployment is manual via `railway up`.

**YOU (the Claude agent) are responsible for deploying after code changes that need to go live.** Do not assume pushing to git deploys anything. After committing and pushing:

1. Load the `/use-railway` skill
2. Run `cd apps/api && railway up` to deploy
3. Verify the deploy succeeded (check logs, health endpoint)
4. Confirm alembic migrations ran if schema changed

```bash
# Deploy from apps/api/ directory (the Railway service root)
cd apps/api && railway up

# Check deploy status
railway status

# View logs
railway logs --tail 50
```

- **Start command** (in `railway.toml`): `alembic upgrade head && uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-8000}`
- Alembic migrations run automatically on every deploy via the start command
- All migrations must be idempotent (`IF NOT EXISTS`, `IF NOT EXISTS`) because prod schema may already have columns from manual SQL
- Railway project: `yeschef` in `Meshi Trial` workspace

## Autonomous Operation Guidelines

To minimize human intervention:
- **Auto-fix on test failure**: If tests fail after a change, read the error, fix it, re-run — don't ask the human unless stuck after 2 attempts
- **Auto-run tests**: Always run `cd apps/api && uv run pytest -q` after code changes without being asked
- **Git workflow**: Stage specific files, write clear commit messages, but NEVER push without explicit permission
- **Dependency changes**: Adding a Python dep via `uv add` is fine; notify the human but don't block on approval
- **Ambiguous scope**: When a request could be interpreted multiple ways, ask ONE clarifying question rather than guessing wrong
- **Session handoff**: At the end of a session, summarize what was done, what's pending, and what the next session should start with

## Tech Stack Quick Reference

| Layer | Tech | Notes |
|-------|------|-------|
| Backend | FastAPI + SQLAlchemy async | Python 3.12+, uv managed |
| AI Extraction | Cerebras (zai-glm-4.7) | 30s intervals, 45s buffer |
| Gate Scoring | Cerebras (zai-glm-4.7) | 7-dim rubric, avg>3.8 + readiness>=4 |
| Execution | CrewAI + Composio | Gmail, Calendar, generic drafts |
| Transcription | Recall.ai (bot) + DeepGram (stub) | Adapter pattern |
| Database | PostgreSQL + asyncpg | Alembic migrations |
| Extension | Chrome MV3 | Content script → iframe overlay |
| Deployment | Railway (Nixpacks) | **MANUAL deploy only — see Deployment section below** |
| Monorepo | Turborepo | Workspaces in apps/ + packages/ |

## Key File Map (relative to apps/api/)

- `src/services/gate.py` — Gate scoring
- `src/services/cerebras.py` — Extraction prompt
- `src/services/executor.py` — CrewAI execution
- `src/workers/extraction_loop.py` — Main pipeline
- `src/adapters/` — Transcript adapter registry
- `src/api/routes_workspace.py` — OAuth endpoints
- `src/models/tables.py` — All DB models
