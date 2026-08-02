# symbiot

Multi-agent loop that turns a PROJECT.md spec into a tested, deployed project — fully autonomous, sandboxed, with human-in-the-loop gates and live streaming to a React visualizer.

```
PROJECT.md -> validator -> base -> planner -> programmer -> tester
                                   ^         |              |
                                   |    +----+              |
                                   |    |retry       pass   |
                                   |    v              v    |
                                   +- escalation   advance  |
                                        |              |    |
                                     abort       +----+    |
                                        |         |next     |
                                        v         v         |
                                     cleanup <- planner ----
                                        ^
                                fail/budget exceeded
                                        |
                                 +------+
                                 |      done
                                 v
                            deploy_gate
                                 |
                         +-------+-------+
                         | approve       | skip
                         v               v
                      deployer       cleanup -> END
                         |               ^
                         v               |
                      cleanup -----------+

```

## Agent roles

| Node | Role |
|------|------|
| Validator | Parses PROJECT.md, extracts spec metadata, milestones, and budget |
| Base | Creates workspace, initializes git repo, starts Docker sandbox container |
| Planner | LLM-driven: generates a Plan (create/edit/delete/run steps) for the current milestone |
| Programmer | Executes the plan: writes files, edits via LLM, runs commands in sandbox |
| Tester | Runs pytest, checks syntax, LLM-evaluates acceptance criteria -> TestReport |
| Escalation | HITL interrupt when max_attempts exhausted -- human chooses retry or abort |
| Deployer | Builds Docker image from workspace and smoke-tests it |

## Setup

### Prerequisites
- Docker with the daemon running
- Python 3.12+ with uv installed
- Node.js 22+ with pnpm installed

### Backend

```bash
cd backend
uv sync

# Build the sandbox image (used for running untrusted code)
docker build -t symbiot-sandbox backend/sandbox/

# Configure .env with your model provider
cp .env.example .env
# Edit .env: MODEL_PROVIDER, MODEL_NAME, BASE_URL, API_KEY
# Optionally add LangSmith keys for tracing:
#   LANGCHAIN_TRACING_V2=true
#   LANGCHAIN_API_KEY=lsv2_pt_...
#   LANGCHAIN_PROJECT=symbiot
```

### Frontend

```bash
cd frontend
pnpm install
```

## How to run

### 1. CLI (checkpointed, resumable)

```bash
cd backend
uv run python run_loop.py
```

Uses SqliteSaver for checkpointing. Interrupts appear as terminal prompts. Resume by re-running -- it picks up from the checkpoint.

### 2. Web mission control

```bash
 cd frontend && pnpm build
 cd ..
 uv run uvicorn symbiot.sidecar:app --app-dir backend/src --host 127.0.0.1 --port 8100
```

Open http://localhost:8100. The FastAPI service serves the React build, starts
checkpointed graph runs, exposes SSE agent events, and keeps human decisions
inside the graph interrupt gates.

### 3. Local development visualizer

```bash
cd backend && uv run uvicorn symbiot.sidecar:app --host 127.0.0.1 --port 8100
# second terminal
cd frontend && pnpm dev
```

Open http://localhost:5173. Paste a PROJECT.md, hit Launch mission. Watch the
factory stream nodes and Docker stdout in real time.

### 4. Web and desktop packaging

```bash
pnpm --dir frontend install
pnpm --dir frontend build
docker compose up --build
```

See `docs/DEPLOYMENT.md` for Postgres history, Tauri bundles, remote sandbox
mode, and signing/updater release requirements.

## PROJECT.md spec

```markdown
## META
name: my-project | stack: python 3.12 | runtime: cli | entrypoint: main.py | smoke_command: --help

## OBJECTIVE
One-line description of what this project does.

## END_CRITERIA
- Criterion 1
- Criterion 2

## MILESTONES
- {id: m1, title: first feature, acceptance_criteria: ["criterion 1"], max_attempts: 3}
- {id: m2, title: second feature, acceptance_criteria: ["criterion 2"], max_attempts: 3}

## BUDGET
token_cap: 500000
llm_call_cap: 50

## OUT_OF_SCOPE
no database, no web UI
```

| Field | Required | Default |
|-------|----------|---------|
| name | yes | -- |
| stack | yes | -- |
| runtime | yes | -- |
| entrypoint | no | first .py file in workspace |
| smoke_command | no | --help |
| token_cap | no | 2,000,000 |
| llm_call_cap | no | 100 |
| max_attempts | no | 3 |

## Safety model

- **Sandbox**: All untrusted code runs in an ephemeral Docker container. File writes happen on the host workspace (git-tracked), but command execution (pytest, pip, user scripts) runs inside the container.
- **Budget governor**: Hard caps on total tokens (token_cap), LLM invocations (llm_call_cap), and optional cost. Provider retries and fallback calls are counted before they execute, with per-provider usage retained in checkpointed run state.
- **Run timeout**: Each LLM-calling node checks elapsed time against a configurable limit (default 30 minutes). Exceeding it kills the run.
- **HITL gates**: Escalation on milestone failure -- human decides retry or abort. Deploy gate after all milestones pass -- human decides whether to build the Docker image. Both use LangGraph interrupt().
- **max_attempts**: Per-milestone retry limit. After exhausting, goes to escalation instead of silently looping.
- **Command safety**: Programmer filters commands -- no sudo, no rm -rf /, no paths outside workspace.

## Production notes

- Swap SqliteSaver -> PostgresSaver for production persistence.
- Put the FastAPI service behind an auth proxy before exposing it outside localhost.
- Add authentication middleware (OAuth, API keys) to the LangGraph API.
- Configure Docker resource limits on sandbox containers (memory, CPU).
- The deployer builds on the **host** (not inside the sandbox) -- it's a trusted packaging step.
