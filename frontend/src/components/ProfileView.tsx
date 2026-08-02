import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

type Theme = "light" | "dark" | "system";
type Density = "compact" | "comfortable";

interface DockerStatus {
  available: boolean;
  version?: string;
  message: string;
}

function DesktopRuntimePanel() {
  const desktop = "__TAURI_INTERNALS__" in window;
  const [docker, setDocker] = useState<DockerStatus | null>(null);
  const [remoteEndpoint, setRemoteEndpoint] = useState("");
  const [unsafeAcknowledged, setUnsafeAcknowledged] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!desktop) return;
    const timer = window.setTimeout(() => {
      void invoke<DockerStatus>("detect_docker")
        .then(setDocker)
        .catch(() => setMessage("Desktop runtime status is unavailable."));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [desktop]);

  if (!desktop) return null;

  const startSandbox = async () => {
    try {
      const status = await invoke<DockerStatus>("ensure_sandbox");
      setMessage(status.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sandbox could not start.");
    }
  };

  const configureRemote = async () => {
    try {
      const status = await invoke<{ message: string }>("configure_remote_sandbox", { endpoint: remoteEndpoint });
      setMessage(status.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Remote sandbox was rejected.");
    }
  };

  const enableUnsafe = async () => {
    try {
      await invoke("enable_unsafe_local_mode", { acknowledge: unsafeAcknowledged });
      setMessage("Unsafe local mode acknowledged for this explicit session.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unsafe local mode remains disabled.");
    }
  };

  return (
    <div className="panel runtime-panel runtime-desktop">
      <div className="panel-heading"><div><span className="eyebrow">Desktop runtime</span><h2>Sandbox availability</h2></div><span className={`connection-state ${docker?.available ? "connected" : "unconfigured"}`}><i />{docker?.available ? "ready" : "checking"}</span></div>
      <div className="runtime-copy">{docker?.message ?? "Checking the local Docker daemon..."}</div>
      <div className="runtime-actions"><button className="button button-small" disabled={!docker?.available} onClick={() => void startSandbox()}>Start local sandbox</button><span className="runtime-version">{docker?.version ?? ""}</span></div>
      {!docker?.available && <>
        <label htmlFor="remote-sandbox">Remote sandbox endpoint<input id="remote-sandbox" value={remoteEndpoint} placeholder="https://sandbox.example" onChange={event => setRemoteEndpoint(event.target.value)} /></label>
        <button className="button button-secondary runtime-button" onClick={() => void configureRemote()}>Use remote sandbox</button>
        <label className="toggle-row runtime-warning"><span><strong>Unsafe local mode</strong><small>Disabled by default. Only use with explicit acknowledgement.</small></span><input type="checkbox" checked={unsafeAcknowledged} onChange={event => setUnsafeAcknowledged(event.target.checked)} /></label>
        <button className="button button-danger runtime-button" onClick={() => void enableUnsafe()}>Acknowledge unsafe mode</button>
      </>}
      {message && <div className="runtime-message" role="status">{message}</div>}
    </div>
  );
}

export function ProfileView() {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("symbiot.theme") as Theme | null) ?? "dark");
  const [accent, setAccent] = useState(() => localStorage.getItem("symbiot.accent") ?? "#e8a85c");
  const [density, setDensity] = useState<Density>(() => (localStorage.getItem("symbiot.density") as Density | null) ?? "comfortable");
  const [notifications, setNotifications] = useState(() => localStorage.getItem("symbiot.notifications") !== "off");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.density = density;
    document.documentElement.style.setProperty("--accent", accent);
    localStorage.setItem("symbiot.theme", theme);
    localStorage.setItem("symbiot.accent", accent);
    localStorage.setItem("symbiot.density", density);
    localStorage.setItem("symbiot.notifications", notifications ? "on" : "off");
  }, [accent, density, notifications, theme]);

  return (
    <section className="screen profile-screen" aria-labelledby="profile-title">
      <div className="screen-heading"><div><span className="eyebrow">Operator preferences</span><h1 id="profile-title">Profile</h1><p>Shape the control room to the way you make decisions.</p></div></div>
      <div className="profile-grid">
        <div className="panel preference-card"><div className="panel-heading"><div><span className="eyebrow">Atmosphere</span><h2>Display system</h2></div></div>
          <label htmlFor="profile-theme">Theme<select id="profile-theme" value={theme} onChange={event => setTheme(event.target.value as Theme)}><option value="dark">Dark command</option><option value="light">Light command</option><option value="system">System</option></select></label>
          <label>Accent color<div className="accent-options">{["#e8a85c", "#73c7b8", "#9a8cff", "#e67d91"].map(color => <button aria-label={`Set accent ${color}`} className={`accent-swatch ${accent === color ? "selected" : ""}`} style={{ backgroundColor: color }} key={color} onClick={() => setAccent(color)} />)}</div></label>
          <label htmlFor="profile-density">Density<select id="profile-density" value={density} onChange={event => setDensity(event.target.value as Density)}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
        </div>
        <div className="panel preference-card"><div className="panel-heading"><div><span className="eyebrow">Signals</span><h2>Notifications</h2></div></div>
          <label className="toggle-row"><span><strong>Human gate alerts</strong><small>Keep escalation decisions impossible to miss.</small></span><input type="checkbox" checked={notifications} onChange={event => setNotifications(event.target.checked)} /></label>
          <div className="profile-callout"><span className="callout-mark">i</span><p>Provider keys are managed from the Providers surface and never appear in these preferences.</p></div>
        </div>
      </div>
      <DesktopRuntimePanel />
    </section>
  );
}
