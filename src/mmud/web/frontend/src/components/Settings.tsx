import React, { useEffect, useState } from "react";

// Editor over the ConfigService via GET/PATCH /api/config. Edits item lists
// (auto-pickup / auto-equip) and key toggles; each change PATCHes {section, field,
// value} and is persisted to the character's TOML. 503 -> service unavailable.
type Config = Record<string, any>;

export function Settings() {
  const [config, setConfig] = useState<Config | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/config").then(async (r) => {
      if (r.status === 503) { setUnavailable(true); return; }
      setConfig(await r.json());
    });
  }, []);

  const patchField = async (section: string, field: string, value: any) => {
    setError("");
    const r = await fetch("/api/config", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, field, value }),
    });
    if (r.ok) setConfig(await r.json());
    else setError((await r.json().catch(() => ({})))?.detail ?? `error ${r.status}`);
  };

  if (unavailable)
    return <div className="settings"><h3>Settings</h3><p>Config service not available.</p></div>;
  if (!config)
    return <div className="settings"><h3>Settings</h3><p>Loading…</p></div>;

  const items = config.items ?? {};
  const nav = config.navigation ?? {};

  return (
    <div className="settings">
      <h3>Settings</h3>
      {error && <p className="settings-error">⚠ {error}</p>}

      <ListEditor
        label="Auto-pickup items"
        hint="Picked up on sight (name substring, case-insensitive) even when auto-get is off — e.g. black star key."
        values={items.get_items ?? []}
        onChange={(v) => patchField("items", "get_items", v)}
      />
      <ListEditor
        label="Auto-equip items"
        hint="Equipped when held (empty list = equip anything equippable)."
        values={items.equip_items ?? []}
        onChange={(v) => patchField("items", "equip_items", v)}
      />

      <h4>Toggles</h4>
      <Toggle label="Auto-get all loot" checked={!!items.auto_get}
              onChange={(c) => patchField("items", "auto_get", c)} />
      <Toggle label="Bash doors / gates" checked={!!nav.bash_doors}
              onChange={(c) => patchField("navigation", "bash_doors", c)} />
      <Toggle label="Pick locks" checked={!!nav.can_pick_locks}
              onChange={(c) => patchField("navigation", "can_pick_locks", c)} />

      <details className="settings-raw">
        <summary>Raw config</summary>
        <pre>{JSON.stringify(config, null, 2)}</pre>
      </details>
    </div>
  );
}

function ListEditor({ label, hint, values, onChange }: {
  label: string; hint: string; values: string[]; onChange: (v: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (v && !values.includes(v)) { onChange([...values, v]); setDraft(""); }
  };
  return (
    <div className="list-editor">
      <h4>{label}</h4>
      <p className="hint">{hint}</p>
      <ul>
        {values.map((v) => (
          <li key={v}>
            <span>{v}</span>
            <button title="remove" onClick={() => onChange(values.filter((x) => x !== v))}>✕</button>
          </li>
        ))}
        {values.length === 0 && <li className="empty">(none)</li>}
      </ul>
      <div className="add-row">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") add(); }}
          placeholder="add item name…"
        />
        <button onClick={add}>+ add</button>
      </div>
    </div>
  );
}

function Toggle({ label, checked, onChange }: {
  label: string; checked: boolean; onChange: (c: boolean) => void;
}) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
