import { SIDECAR_ORIGIN } from "./base";

const BASE = (import.meta.env.VITE_RUN_API_URL ?? `${SIDECAR_ORIGIN}/api`).replace(/\/$/, "");

let cachedToken: string | null = null;
let pendingToken: Promise<string> | null = null;

export function setCachedToken(token: string | null): void {
  cachedToken = token;
  pendingToken = null;
}

export async function fetchToken(force = false): Promise<string> {
  if (cachedToken && !force) return cachedToken;
  if (!pendingToken) {
    pendingToken = fetch(`${BASE}/auth/token`, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`token endpoint returned ${response.status}`);
        return response.json() as Promise<{ token: string }>;
      })
      .then((payload) => {
        cachedToken = payload.token;
        return cachedToken;
      })
      .finally(() => {
        pendingToken = null;
      });
  }
  return pendingToken;
}

export async function authHeaders(
  extra: Record<string, string> = {},
): Promise<Record<string, string>> {
  const token = await fetchToken();
  return { ...extra, Authorization: `Bearer ${token}` };
}
