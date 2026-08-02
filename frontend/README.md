# symbiot mission control

The React/Vite shell is the web surface and the Tauri desktop surface. It
connects to the FastAPI run API through `/api` and to the local provider/fs
sidecar through `/fs`.

```bash
pnpm install
pnpm run dev
pnpm run test
pnpm run lint
pnpm run build
```

For desktop development, use `pnpm run tauri:dev`. Release bundle targets are
configured in `src-tauri/tauri.conf.json` for NSIS, AppImage, and Debian.
