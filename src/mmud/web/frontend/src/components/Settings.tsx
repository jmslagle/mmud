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
  const combat = config.combat ?? {};

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

      <h4>Combat &amp; Rest</h4>
      <PercentField
        label="Rest below HP %"
        hint="Out of combat, rest and recover when HP drops under this."
        value={combat.rest_threshold ?? 0}
        onChange={(v) => patchField("combat", "rest_threshold", v)}
      />
      <PercentField
        label="Rest below Mana %"
        hint="Out of combat, rest to recover mana under this (0 = off). Good for casters."
        value={combat.rest_mana_pct ?? 0}
        onChange={(v) => patchField("combat", "rest_mana_pct", v)}
      />
      <PercentField
        label="Flee below HP %"
        hint="In combat, flee when HP drops under this."
        value={combat.flee_threshold ?? 0}
        onChange={(v) => patchField("combat", "flee_threshold", v)}
      />
      <PercentField
        label="Cast above Mana %"
        hint="Only cast the attack spell when mana is above this; below it, melee."
        value={combat.mana_attack_pct ?? 0}
        onChange={(v) => patchField("combat", "mana_attack_pct", v)}
      />

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

function PercentField({ label, hint, value, onChange }: {
  label: string; hint: string; value: number; onChange: (v: number) => void;
}) {
  // Stored as a 0..1 fraction; shown/edited as a 0..100 percentage.
  const [draft, setDraft] = useState(Math.round((value ?? 0) * 100).toString());
  useEffect(() => { setDraft(Math.round((value ?? 0) * 100).toString()); }, [value]);
  const commit = () => {
    const pct = Math.max(0, Math.min(100, parseInt(draft, 10) || 0));
    onChange(pct / 100);
  };
  return (
    <div className="num-field">
      <label>
        {label}
        <input
          type="number" min={0} max={100} value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") commit(); }}
        />
        <span className="unit">%</span>
      </label>
      <p className="hint">{hint}</p>
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
