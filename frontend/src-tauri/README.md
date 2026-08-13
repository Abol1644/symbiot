# symbiot desktop

The Tauri shell is a thin supervisor around the Python sidecar. It spawns
`uv run uvicorn symbiot.sidecar:app` as a child process, harvests the
per-launch API token from the sidecar's startup log, and forwards it to the
webview through Tauri events — the token never touches localStorage. The
shell restarts a crashed sidecar up to 3 times, then reports `stopped`.

The shell never talks to Docker directly. Sandbox lifecycle commands are
Tauri IPC commands that proxy the sidecar HTTP API (`GET /api/sandbox/status`,
`POST /api/sandbox/stop`, `POST /api/sandbox/restart`); the remote sandbox
endpoint is validated by the sidecar's SSRF gate and persisted in
`~/.symbiot/config.json`.

## Sidecar configuration

`tauri.conf.json` → `plugins.sidecar`:

```json
"sidecar": {
  "url": "http://127.0.0.1:8100",
  "command": "uv run uvicorn symbiot.sidecar:app --host 127.0.0.1 --port 8100"
}
```

Environment overrides (highest precedence): `SYMBIOT_SIDECAR_URL`,
`SYMBIOT_SIDECAR_CMD`, `SYMBIOT_SIDECAR_DIR`. The working directory falls
back to auto-detection (walking up from the process CWD to find
`src/symbiot/sidecar.py`). Python is expected on `PATH` — it is never bundled.

## Development

```bash
pnpm tauri dev
```

`beforeDevCommand` runs `pnpm dev` and `beforeBuildCommand` runs `pnpm build`
from the `frontend/` directory (the Tauri CLI preserves the invoking CWD).

## Bundles

```bash
pnpm tauri build --bundles nsis
pnpm tauri build --bundles appimage,deb
```

The configuration requests Windows NSIS, Linux AppImage, and Debian packages.
Updater endpoints and the signing public key are intentionally placeholders;
replace them before publishing. Builds without signing keys are unsigned and
must be labeled as such in release notes.
