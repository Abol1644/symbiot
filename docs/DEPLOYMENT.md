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

The Compose backend uses the local Docker socket so it can create the existing
sandbox containers. Compose shares `${PWD}/.symbiot` at the same absolute path
inside the API container and the Docker daemon. On Docker Desktop, add the
repository/workspace path to Docker's shared folders before running a mission.
If `${PWD}` is not available in your shell, set
`SYMBIOT_HOST_WORKSPACE` to an absolute shared path. Do not replace the
sandbox with host execution.

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

If Docker is missing, the desktop shell exposes a remote sandbox mode. Unsafe
local execution is never selected automatically and requires both explicit UI
acknowledgement and `SYMBIOT_ALLOW_UNSAFE_LOCAL=1`.
