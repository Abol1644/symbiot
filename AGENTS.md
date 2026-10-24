# AGENTS.md — symbiot contributor context

## What this is
Autonomous multi-agent software engineering platform: a `PROJECT.md` spec goes
in, verified milestone-driven code comes out, streamed live to mission control.
- `backend/` — Python 3.12+ FastAPI sidecar + LangGraph engine + SQLite
  checkpoints (`checkpoints.db`) and run history (`runs.db`).
- `frontend/` — React 19 + TypeScript + Vite + React Flow mission-control UI.
- `frontend/src-tauri/` — Tauri 2 Rust desktop shell supervising the sidecar.

## Dev & test (Windows PowerShell)
`uv` lives at `C:\Users\Aryan\AppData\Roaming\Python\Python314\Scripts\uv.exe`
when it is not on `PATH`. Setup: `uv sync --project backend` and
`pnpm --dir frontend install --frozen-lockfile`.
```powershell
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest backend/tests -m "not real_provider"
```
```powershell
cd frontend
pnpm tsc -b
pnpm lint
pnpm test --run
pnpm build
```

## Core invariants
- Native execution only: nodes run via host subprocess, there is no Docker
  sandbox and no compose stack. Do not reintroduce container references.
- `get_workspace_root()` in `backend/src/symbiot/config.py` is the single
  source of truth for workspace paths (`~/.symbiot/workspace` by default,
  overridable via `SYMBIOT_WORKSPACE_ROOT`). `nodes/base.py` and every
  `sidecar.py` workspace endpoint must resolve through it per call.
- Safety is load-bearing: path containment, command guards, SSRF-gated
  provider URLs, automatic secret redaction, token-authenticated sidecar,
  CORS locked to localhost + Tauri.
- Budgets are enforced per node: token / LLM-call / cost caps plus a
  30-minute-max run timeout (`guards.py`).
- Never commit `*.db`, `*.db-shm`, `*.db-wal`, or `*.egg-info/` — gitignored
  and untracked. Keep `uv.lock` / `pnpm-lock.yaml` in sync with manifests.

## Architecture pointers
- Graph (`backend/src/symbiot/graph.py`): `validator` → `base` → `planner` →
  `programmer` → `tester`, then `advance` / `escalation` (human gate) /
  `deploy_gate` → `deployer` → `cleanup`. `router.py` owns test/advance
  transitions (pass + confidence ≥ 0.7 advances).
- Runs (`run_manager.py`): SQLite `runs`/`events`, `SqliteSaver`
  checkpoints, SSE stream + replay, cancellation, 30-day retention.
- LLM (`providers.py`, `llm.py`): OpenAI / Anthropic / OpenRouter / OpenCode /
  generic OpenAI-compatible router with fallback chains; structured-JSON
  invocation with validation retries counted against budgets.
- UI (`frontend/src`): `MissionConsole`, `GraphCanvas`, `EscalationCenter`,
  `ProvidersView`, `HistoryView`, `useLangGraphStream` SSE hook.
- Desktop (`frontend/src-tauri/src/lib.rs`): sidecar supervision with
  auto-restart, IPC token handshake, OS-keyring provider vault.

## Docs
`README.md` is the product showcase, `docs/DEPLOYMENT.md` the deployment /
env / security reference. Every feature claim must be traceable to code.
