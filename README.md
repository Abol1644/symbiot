# Symbiot — Programmer Loop Agent

A closed-loop, multi-agent system that turns a locked-format `PROJECT.md` into working, tested, deployed software with minimal human intervention.

## How it works

Four agents form a supervisor-free cycle orchestrated by LangGraph's conditional edges:

```
Intake (Base) ──> Planner ──> Programmer ──> Tester
                                              │
                    ┌─────────────────────────┤
                    │ passed                   │ failed
                    ▼                          ▼
             More milestones?            attempts left?
             ├─ yes ──> Planner           ├─ yes ──> Planner (debug mode)
             └─ no ──> Done               └─ no ──> Human review (interrupt)
```

| Agent | Role |
|---|---|
| **Base / Intake** | Parses `PROJECT.md` into a structured spec: scope, milestones, definition of "done." |
| **Planner** | Turns the spec into an execution plan (build → maintain → develop → fix → deploy) for the current milestone. In `debug` mode, writes a plan informed by the Tester's failure report. |
| **Programmer** | Executes the plan inside an isolated sandbox. |
| **Tester** | Verifies the milestone: static checks → existing test suite → EARS acceptance criteria. Pass advances the loop; failure routes back to the Planner with a structured report. |

Each milestone gets `max_attempts` (default 3). On exhaustion the graph pauses via `interrupt()` and waits for human guidance — never fails silently.

## Repository layout

```
backend/     Python + LangGraph agent graph (FastAPI streaming layer planned)
  src/
    graph.py      LangGraph state graph
    state.py      LoopState contract
    schemas.py    Milestone / spec schemas
    nodes/        Agent node implementations
    sandbox/      Sandboxed execution (Docker)
    config.py     Settings
frontend/    Vite + TypeScript + React (React Flow canvas planned)
projects/    PROJECT.md files — one per project the loop works on
```

## Project spec format

Each project lives in `projects/<name>/PROJECT.md` with YAML frontmatter for deterministic parsing and prose for human nuance. Acceptance criteria use **EARS notation** (`WHEN … THE SYSTEM SHALL …`) so they map ~1:1 onto test cases for the Tester agent.

```markdown
---
project: my-app
version: 1
end_goal: >
  One unambiguous paragraph describing what "done" means for the whole project.
constraints:
  - "TypeScript strict mode"
out_of_scope:
  - "Mobile app — web only for v1"
---

## Milestones

### M1: Project scaffold
acceptance_criteria:
  - WHEN the app is started THE SYSTEM SHALL serve a homepage on localhost
  - WHEN `npm run build` is run THE SYSTEM SHALL produce a dist/ folder with no errors
depends_on: []
```

## Key design decisions

- **Typed shared state** — every agent reads/writes one `LoopState` object (milestones, plan, diff, test report, attempt counter, `mode: build|debug`) instead of re-parsing prose. No information loss at handoffs.
- **No supervisor agent** — the graph's conditional edges *are* the orchestration. Four agents, no more.
- **Sandboxed execution** — Programmer/Tester run inside a local Docker container mounted to a throwaway clone of the repo. Nothing autonomous touches the host.
- **Git convention** — one branch per milestone (`milestone/m1-scaffold`), one commit per attempt, milestone id in commit messages; merged to `main` on Tester pass.
- **Deterministic verification** — the LLM in the Tester only interprets ambiguous failures and writes the report; lint, typecheck, and test runs do the actual judging.
- **Deploy as a milestone type** — `type: deploy` milestones run through the same Planner → Programmer → Tester cycle as any other (Tester checks the health endpoint). No fifth agent.
- **Cost-tuned models** — expensive model only where reasoning matters (Planner); cheap models for parsing and verification (Base, Tester).

## Roadmap

- **Phase 0** — Finalize `PROJECT.md` and `LoopState` schemas (spec only, no code).
- **Phase 1** — MVP loop: Base → Planner → Programmer, SQLite checkpointer, no Tester/frontend.
- **Phase 2** — Tester node + retry loop with `max_attempts` and `mode: debug`.
- **Phase 3** — Move execution into local Docker sandboxing.
- **Phase 4** — Visualization: FastAPI streaming (SSE/WebSocket) + React Flow canvas with live node highlighting and state diffs.
- **Phase 5** *(optional)* — Human-in-the-loop gates: `interrupt()` before merge and on attempt exhaustion.
- **Phase 6** *(optional)* — Deploy milestone type.
- **Phase 7** *(optional)* — Hardening: managed sandbox (E2B/Daytona), Postgres checkpointer, PR-based merges.

Phases 5–7 are on-demand hardening — everything after Phase 4 completes the idea as specified.

## Getting started

*Skeleton in progress* — the backend graph, state contract, and frontend canvas are being scaffolded per the roadmap above.

## Sources / further reading

- LangGraph human-in-the-loop & `interrupt()`: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph multi-agent patterns (supervisor vs. swarm): https://focused.io/lab/multi-agent-orchestration-in-langgraph-supervisor-vs-swarm-tradeoffs-and-architecture
- Spec-driven development, 2026 field guide (Spec Kit, EARS notation): https://dev.to/krlz/spec-driven-development-in-2026-what-it-is-the-tooling-and-how-teams-actually-use-it-2fk2
- Spec-driven development guide: https://www.thebcms.com/blog/spec-driven-development/
- LangGraph.js vs. Python parity: https://www.crewship.dev/learn/langgraph-vs-langgraphjs
- Sandbox comparison (E2B vs. Daytona vs. Modal): https://particula.tech/blog/modal-vs-e2b-vs-daytona-vs-vercel-sandbox-ai-code-execution
- React-based LangGraph visualizer example: https://github.com/Coding-Crashkurse/LangGraph-Visualizer
