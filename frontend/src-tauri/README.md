# symbiot desktop

The Tauri shell uses the same React build as the web app. Rust owns local
Docker detection, the `symbiot-sandbox` container lifecycle, and provider keys
through the operating-system credential vault.

## Development

```bash
pnpm tauri dev
```

If Docker is unavailable, the desktop command surface can be pointed at a
remote sandbox. Unsafe local execution is disabled unless both the explicit
UI acknowledgement and `SYMBIOT_ALLOW_UNSAFE_LOCAL=1` are present.

## Bundles

```bash
pnpm tauri build --bundles nsis
pnpm tauri build --bundles appimage,deb
```

The configuration requests Windows NSIS, Linux AppImage, and Debian packages.
Updater endpoints and the signing public key are intentionally placeholders;
replace them before publishing. Builds without signing keys are unsigned and
must be labeled as such in release notes.
