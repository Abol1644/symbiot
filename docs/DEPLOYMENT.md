# symbiot deployment guide

Symbiot runs **natively** — no Docker, no compose stack. Agent nodes execute on
the host via guarded subprocess calls, and persistence is plain SQLite. There
are three ways to run it: the Tauri 2 desktop app, standalone web + sidecar, or
the checkpointed CLI.

## 1. Tauri 2 desktop (recommended)

The desktop shell (`frontend/src-tauri`) supervises the Python sidecar as a
child process and embeds the built web UI.

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm tauri:dev      # dev: Vite on :5173, sidecar on :8100
pnpm tauri:build    # bundles: nsis (Windows), appimage + deb (Linux)
```

How supervision works (`frontend/src-tauri/src/lib.rs`):

- The shell spawns `uv run uvicorn symbiot.sidecar:app --host 127.0.0.1
  --port 8100` (overridable via `SYMBIOT_SIDECAR_CMD` /
  `SYMBIOT_SIDECAR_DIR` env or the `plugins.sidecar` section of
  `tauri.conf.json`) and locates the backend directory automatically.
- The sidecar prints its per-launch API token to stdout; the supervisor
  harvests it and forwards it to the webview over Tauri events
  (`sidecar-token`) — it is never written to `localStorage`.
- A crashed sidecar is restarted up to 3 times; `sidecar_status` reports
  `running | restarting | stopped`. Tauri commands: `launch_sidecar`,
  `stop_sidecar`, `sidecar_status`.
- Provider keys are stored with the OS credential service (`set_provider_key`
  / `provider_key_status`, service `io.symbiot.mission-control`) — never in
  config files or run state.

Packaging notes:

- Windows bundles (NSIS) must be built on Windows; Linux bundles
  (AppImage/deb) need the Tauri GTK/WebKit dev packages. CI builds both on
  tag pushes (`.github/workflows/desktop.yml`).
- The updater plugin is wired but its public key and endpoint are placeholders
  (`plugins.updater` in `tauri.conf.json`). Supply release-signing keys and a
  real endpoint before shipping auto-updates.
- Python must be on `PATH` for the supervised sidecar; it is never bundled.

## 2. Standalone web + sidecar

Serve the production UI from the sidecar itself — when `frontend/dist` exists,
the FastAPI app mounts it at `/`.

```bash
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
cd backend
uv run uvicorn symbiot.sidecar:app --app-dir src --host 127.0.0.1 --port 8100
```

Open `http://127.0.0.1:8100`. For local development with hot reload instead:

```bash
# terminal 1 — sidecar
cd backend && uv run uvicorn symbiot.sidecar:app --app-dir src --host 127.0.0.1 --port 8100 --reload
# terminal 2 — Vite dev server
cd frontend && pnpm dev   # http://localhost:5173
```

Production hosting rules:

- Bind `127.0.0.1` and put the sidecar behind an authentication proxy before
  exposing it beyond localhost.
- The `/api/auth/token` endpoint is localhost-only by design; every other API
  route requires the bearer token.
- CORS allows only `http://localhost:5173`, `http://127.0.0.1:5173`, and
  `tauri://localhost`.

## 3. Checkpointed CLI

```bash
cd backend
uv run python run_loop.py
```

Uses `SqliteSaver` on `backend/checkpoints.db`. Human gates appear as terminal
prompts; re-running resumes from the saved checkpoint.

## Environment reference

| Variable | Default | Purpose |
|---|---|---|
| `SYMBIOT_WORKSPACE_ROOT` | `~/.symbiot/workspace` | Single source of truth for agent workspaces (`config.py: get_workspace_root()`); consumed by `nodes/base.py` and every sidecar workspace endpoint |
| `SYMBIOT_PROJECTS_DIR` | `<repo>/projects` | Root for `source_path` imports in the `base` node |
| `MODEL_PROVIDER` / `MODEL_NAME` | `openai` / `gpt-4o-mini` | Primary LLM (`Settings`) |
| `BASE_URL` / `API_KEY` | — | Generic endpoint override / key for the primary provider |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` / `OPENCODE_API_KEY` | — | Per-provider keys (env fallback; OS keyring preferred on desktop) |
| `FALLBACK_CHAIN` | — | Comma-separated `provider:model` fallback entries |
| `RUN_TIMEOUT_MINUTES` | `30` | Per-run ceiling, hard-capped at 30 min by `guards.py` |
| `SYMBIOT_VAULT_KEY` | — | Master key for the encrypted provider store (managed secret in production) |
| `SYMBIOT_CONFIG_DIR` | `~/.symbiot` | Provider config + vault location |
| `SYMBIOT_DATA_DIR` | `~/.symbiot` | Parent dir for `runs.db` |
| `SYMBIOT_RUNS_DB` | `~/.symbiot/runs.db` | Run/event history database |
| `SYMBIOT_CHECKPOINT_DB` | `<repo>/backend/checkpoints.db` | LangGraph `SqliteSaver` checkpoint database |
| `SYMBIOT_MAX_EVENTS_PER_RUN` | `10000` | In-memory + SQLite event cap per run (oldest pruned) |
| `SYMBIOT_RUN_RETENTION_DAYS` | `30` | Completed-run retention; active runs are never deleted |
| `SYMBIOT_CLEANUP_INTERVAL_SECONDS` | `3600` | Retention sweep interval |
| `SYMBIOT_REDACTION_ENABLED` | `true` | Secret-redaction layer for prompts, events, and stored previews |
| `SYMBIOT_APP_URL` | `http://localhost:5173` | `HTTP-Referer` sent with OpenRouter requests |

Copy `backend/.env.example` to `backend/.env` and fill in your provider. Never
commit real keys.

## SQLite durability & retention

- **Checkpoints** (`SYMBIOT_CHECKPOINT_DB`): full LangGraph state per run —
  resume mid-mission after a crash or restart by reusing the thread id.
- **History** (`SYMBIOT_RUNS_DB`, tables `runs` + `events`): powers the run
  list, status polling, and SSE replay after restart. Interrupted runs are
  marked `interrupted` on boot so the UI can surface them honestly.
- **Retention**: a background loop deletes completed runs older than
  `SYMBIOT_RUN_RETENTION_DAYS`; active/`interrupted` runs are preserved.
- **Backups**: both files are ordinary SQLite databases — snapshot or
  `VACUUM INTO` them on whatever schedule fits. `*.db*` files are gitignored
  and must never be committed.

## Security posture

- **Path containment** — every workspace read/write/git operation resolves
  against `get_workspace_root()` and rejects traversal (including symlinks);
  the programmer node validates every plan target the same way.
- **Command guards** — agent `run_command` steps are shell-split (no shell
  metacharacters path), blocked from `sudo` / destructive `rm`, confined to
  the workspace, and capped at 30 s.
- **SSRF protection** — provider base URLs are validated before any request:
  metadata IPs and private ranges are blocked (local Ollama/vLLM excepted),
  and suspicious hostnames are rejected.
- **Secret redaction** — API keys, bearer tokens, and connection strings are
  stripped from LLM prompts, SSE events, error messages, and persisted run
  previews; API responses carry masked keys only.
- **Auth & transport** — per-launch bearer token, localhost-only token
  endpoint, CORS locked to the dev origin plus `tauri://localhost`.
- **Budgets** — token / call / cost caps plus the run timeout are enforced in
  every LLM-calling node; overruns fail the run instead of the invoice.

## CI

`.github/workflows/ci.yml` runs on every push/PR to `main`: backend
`ruff` + `pytest` (real-provider tests excluded), frontend `lint` + `test` +
`build`, plus `pip-audit` / `pnpm audit` / `cargo audit` security scans.
