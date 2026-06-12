import React from "react";
import { quickTool } from "../useWebSocket";
import { PanelState } from "../panelState";

const COMPASS: (string | null)[][] = [
  ["nw", "n", "ne"],
  ["w", null, "e"],
  ["sw", "s", "se"],
];

const ACTIONS: { id: string; label: string }[] = [
  { id: "get-all", label: "Get-All" },
  { id: "drop-all", label: "Drop-All" },
  { id: "equip-all", label: "Equip-All" },
  { id: "deposit", label: "Deposit" },
  { id: "search", label: "Search" },
  { id: "afk", label: "AFK" },
];

export function QuickTools({ state }: { state: PanelState }) {
  const fire = (action: string) => () => { void quickTool(action); };
  const income = state.session.stats["income_rate"] ?? "0/hr";

  return (
    <div className="quick-tools">
      <h3>Quick Tools</h3>
      <div className="compass">
        {COMPASS.map((row, r) => (
          <div className="compass-row" key={r}>
            {row.map((dir, c) =>
              dir ? (
                <button key={c} className="compass-btn" onClick={fire(dir)}>
                  {dir.toUpperCase()}
                </button>
              ) : (
                <div key={c} className="compass-center">
                  <button className="ud-btn" onClick={fire("u")}>U</button>
                  <button className="ud-btn" onClick={fire("d")}>D</button>
                </div>
              ),
            )}
          </div>
        ))}
      </div>
      <div className="action-buttons">
        {ACTIONS.map((a) => (
          <button key={a.id} className="action-btn" onClick={fire(a.id)}>
            {a.label}
          </button>
        ))}
      </div>
      <div className="income">Income: {income}</div>
    </div>
  );
}
