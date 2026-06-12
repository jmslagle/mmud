import React, { useEffect, useState } from "react";

// Uses Doc 2 ConfigService via GET/PATCH /api/config. When the service is
// absent the API returns 503 and we show a banner instead of the editor.
export function Settings() {
  const [config, setConfig] = useState<Record<string, any> | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    fetch("/api/config").then(async (r) => {
      if (r.status === 503) { setUnavailable(true); return; }
      setConfig(await r.json());
    });
  }, []);

  if (unavailable) {
    return <div className="settings"><h3>Settings</h3><p>Config service not available.</p></div>;
  }
  if (!config) return <div className="settings"><h3>Settings</h3><p>Loading…</p></div>;

  const save = async (patch: Record<string, any>) => {
    const r = await fetch("/api/config", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (r.ok) setConfig(await r.json());
  };

  return (
    <div className="settings">
      <h3>Settings</h3>
      <pre>{JSON.stringify(config, null, 2)}</pre>
      <button onClick={() => save({})}>Reload</button>
    </div>
  );
}
