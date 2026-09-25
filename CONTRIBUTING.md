# Contributing to TalentFlow

Thanks for helping out! Here's how to get productive quickly.

## Setup

Follow **Local development** in the [README](README.md). You don't need an API key: without one, the agents run in offline mode with deterministic heuristics, and so do the tests.

## Project layout

```
backend/app/
  agents/         one module per agent: prompt, Pydantic output schema, offline heuristic
  api/            FastAPI routers
  llm/            Claude client + offline mode
  orchestrator.py pipeline state machine; the only place stages change
  embeddings.py   fastembed / Voyage / hash embedders
  models.py       SQLAlchemy models
frontend/src/
  pages/          one file per route
  components/     shared UI
```

## Adding an agent

1. Create `backend/app/agents/<name>.py` with a Pydantic output model, a system prompt, and an offline `heuristic`.
2. Call it through `run_structured(...)` so it works in both Claude and offline modes.
3. Add a stage to `Stage` in `models.py` and wire the transition in `orchestrator.py` (`TRANSITIONS` and `run_agent_step`).
4. Add a test in `backend/tests/`.

## Before opening a PR

```bash
cd backend && ruff check app tests && pytest
cd frontend && npm run build
```

Keep PRs focused. For larger changes, open an issue first so we can agree on the approach.
