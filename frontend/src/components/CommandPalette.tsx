import { useEffect, useMemo, useRef, useState } from "react";

export interface PaletteAction {
  id: string;
  label: string;
  detail: string;
  shortcut?: string;
  run: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  actions: PaletteAction[];
  onClose: () => void;
}

export function CommandPalette({ open, actions, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const filtered = useMemo(() => {
    const needle = query.toLowerCase().trim();
    return needle ? actions.filter(action => `${action.label} ${action.detail}`.toLowerCase().includes(needle)) : actions;
  }, [actions, query]);

  useEffect(() => {
    if (open) {
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Enter" && filtered[0]) {
        filtered[0].run();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [filtered, onClose, open]);

  if (!open) return null;
  return (
    <div className="palette-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="command-palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="palette-input-row">
          <span className="palette-symbol">/</span>
          <input ref={inputRef} value={query} onChange={event => setQuery(event.target.value)} placeholder="Jump to a mission action..." />
          <kbd>esc</kbd>
        </div>
        <div className="palette-list">
          {filtered.map(action => (
            <button key={action.id} className="palette-action" onClick={() => { action.run(); onClose(); }}>
              <span><strong>{action.label}</strong><small>{action.detail}</small></span>
              {action.shortcut && <kbd>{action.shortcut}</kbd>}
            </button>
          ))}
          {filtered.length === 0 && <div className="palette-empty">No matching actions.</div>}
        </div>
        <div className="palette-footer"><span>Navigate by search</span><span><kbd>enter</kbd> select</span></div>
      </div>
    </div>
  );
}
