export const isDesktop =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export const SIDECAR_ORIGIN = isDesktop ? "http://127.0.0.1:8100" : "";
