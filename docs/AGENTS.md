# YesChef — Agent Configuration

> All agents: read `CLAUDE.md` at repo root for project rules, runtime config, and behavioral constraints.

## Agent Roles

| Role | Agent Type | When to Use |
|------|-----------|-------------|
| Orchestrator | (you, the lead) | Default mode — decompose, delegate, synthesize |
| Coder | `coder` / `general-purpose` | Implementation tasks, file edits |
| Tester | `tester` | Write tests, run test suites |
| Reviewer | `reviewer` | Code review, security audit |
| Researcher | `Explore` (haiku) | Codebase search, pattern discovery |
| Architect | `Plan` | Design decisions, multi-file planning |

## Swarm Configuration

| Setting | Value |
|---------|-------|
| Topology | `hierarchical` |
| Max Agents | 8 |
| Strategy | `specialized` |
| Consensus | `raft` |

### When to Use Swarms

**Use swarm for:** multi-file changes (3+), new features, cross-module refactoring, API + tests together

**Skip swarm for:** single file edits, 1-2 line fixes, config changes, doc updates

## Claude-Flow Skills (most useful for this project)

| Skill | Use Case |
|-------|----------|
| `/swarm-orchestration` | Multi-agent parallel task execution |
| `/sparc-methodology` | Structured dev workflow (Spec → Pseudo → Arch → Refine → Complete) |
| `/pair-programming` | Interactive TDD, debugging, refactoring sessions |
| `/github:code-review` | PR review with AI agents |
| `/github:pr-manager` | PR lifecycle management |

## Claude-Flow CLI (via MCP)

```bash
# Swarm init
npx @claude-flow/cli@latest swarm init --topology hierarchical --max-agents 8

# Memory
npx @claude-flow/cli@latest memory store --key "key" --value "val" --namespace patterns
npx @claude-flow/cli@latest memory search --query "search terms"

# Hooks
npx @claude-flow/cli@latest hooks pre-task --description "task description"
npx @claude-flow/cli@latest hooks route --task "task description"

# Health
npx @claude-flow/cli@latest doctor --fix
```

## Background Workers

Key workers available via `npx @claude-flow/cli@latest hooks worker dispatch --trigger <name>`:

| Worker | Purpose |
|--------|---------|
| `audit` | Security analysis |
| `testgaps` | Test coverage analysis |
| `optimize` | Performance optimization |
| `map` | Codebase mapping |
