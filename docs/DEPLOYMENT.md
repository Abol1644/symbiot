# symbiot deployment

## Web

Build the React shell and launch the API plus the sandbox image:

```bash
pnpm --dir frontend install
pnpm --dir frontend build
docker compose up --build
```

Open `http://localhost:8100`. The FastAPI process serves the built shell,
provider management, checkpointed runs, and SSE events. Generated code is
still executed by `symbiot-sandbox`; the API container is not a code runner.

The Compose backend does **not** mount the Docker socket by default. Generated
code is still executed by `symbiot-sandbox`; when running the API outside of
Compose (local dev), the backend talks to the local Docker daemon directly and
creates hardened sandbox containers on demand.

Compose shares `${PWD}/.symbiot` at the same absolute path inside the API
container and the Docker daemon. On Docker Desktop, add the
repository/workspace path to Docker's shared folders before running a mission.
If `${PWD}` is not available in your shell, set
`SYMBIOT_HOST_WORKSPACE` to an absolute shared path. Do not replace the
sandbox with host execution.

## Sandbox hardening

Every sandbox container runs with an immutable security posture:

- Non-root user (`sandbox`) inside the image; `python`, `pip`, `pytest`,
  `node`, and `npm` are available to it (a writable `/opt/venv` is provided)
- `--memory=512m --cpus=1 --pids-limit=100`
- `--cap-drop=ALL --security-opt=no-new-privileges:true`
- `--read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m`
- Workspace bind-mounted read-write only at `/workspace`; no other mounts
- `--network=none` by default — never `--privileged`, never the Docker socket

Network policy is controlled by `SYMBIOT_SANDBOX_NETWORK`:

| value        | behavior                                                              |
|--------------|-----------------------------------------------------------------------|
| `none`       | (default) no network                                                  |
| `restricted` | user-defined bridge plus best-effort egress blocks for metadata IPs (169.254.169.254, fd00:ec2::254) and private ranges |
| `bridge`     | default Docker bridge (full egress — use only when you trust the task) |

`restricted` applies `iptables`/`ip6tables` DOCKER-USER DROP rules and needs
host privileges; if the rules cannot be applied it logs a warning and falls
back to `none`. Use `bridge` if a task legitimately needs to reach local
services such as Ollama (`http://localhost:11434`).

Commands inside the sandbox are validated: the first token must be on the
allowlist (`SYMBIOT_ALLOWED_COMMANDS`, comma-separated; defaults to
python/pip/pytest/node/npm/npx/pnpm/cargo/gcc/make/git and friends) and shell
metacharacters (`;`, `|`, `&&`, `||`, `$()`, backticks, `>`, `<`) are rejected
unless opted out via `SYMBIOT_SHELL_META_ALLOW`. Commands execute directly
without `/bin/sh -c`.

## Deploy mode

`SYMBIOT_DEPLOY_MODE` controls the deployer node:

| value    | behavior                                                     |
|----------|--------------------------------------------------------------|
| `none`   | (default) deployer disabled — the graph reports success with `deploy_result.smoke_test_passed: false` |
| `socket` | explicit opt-in; requires the Docker socket to be reachable  |
| `remote` | remote Docker daemon via `SYMBIOT_DOCKER_HOST` (e.g. `tcp://host:2375`) |

To use `socket` mode with the Compose backend, re-add the mount:

```yaml
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

## Secret redaction

`SYMBIOT_REDACTION_ENABLED` (default `true`) gates a redaction layer that
strips API keys, bearer tokens, private keys, and connection strings before
file contents enter LLM prompts or provider configuration leaves the API.
Run history is persisted to `localStorage` as preview + SHA-256 hash only —
never the raw PROJECT.md.


Run history can use the optional Postgres profile. Set a deployment-specific
`POSTGRES_PASSWORD` first:

```bash
export POSTGRES_PASSWORD='use-a-secret-manager-value'
docker compose --profile history up --build
```

## Desktop

The Tauri project is in `frontend/src-tauri` and wraps the same `frontend/dist`:

```bash
pnpm --dir frontend tauri:dev
pnpm --dir frontend tauri:build -- --bundles appimage,deb
```

The configuration also requests the Windows NSIS target:

```bash
pnpm --dir frontend tauri:build -- --bundles nsis
```

Windows artifacts must be built on Windows or a configured Windows CI runner.
Linux artifacts require the Tauri GTK/WebKit development packages. Signing and
the updater endpoint are placeholders until release credentials are supplied.

### Sidecar supervision

The shell spawns the Python sidecar (`uv run uvicorn symbiot.sidecar:app` by
default) as a child process, reads the per-launch API token from the startup
log, and forwards it to the webview via Tauri events (never localStorage). A
crashed sidecar is restarted up to 3 times; `sidecar_status` reports
`running | stopped | restarting`. Overrides: `SYMBIOT_SIDECAR_URL`,
`SYMBIOT_SIDECAR_CMD`, `SYMBIOT_SIDECAR_DIR`, or `plugins.sidecar` in
`frontend/src-tauri/tauri.conf.json`. Python must be on `PATH`; it is never
bundled.

### Sandbox controls and remote endpoints

The Tauri shell has no Docker socket access. Sandbox controls are Tauri IPC
commands that proxy the sidecar API (`/api/sandbox/status`, `/stop`,
`/restart`). A remote Docker endpoint can be configured from the Profile
screen: the sidecar SSRF-validates the URL (blocking metadata/private ranges),
probes it, and persists it to `~/.symbiot/config.json` (0600). When set, the
sandbox client uses the remote daemon instead of local Docker — for the
shared container and for run sandboxes alike.
