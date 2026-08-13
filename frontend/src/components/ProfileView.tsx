import { useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";
type Density = "compact" | "comfortable";

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
    </section>
  );
}
