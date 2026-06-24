import React from "react";
import { PanelState } from "../panelState";

function pct(n: number, d: number): string {
  return d > 0 ? `${Math.round((n / d) * 100)}%` : "0%";
}

export function PlayerStats({ state }: { state: PanelState }) {
  const s = state.session;
  const stat = (k: string, d = "0%") => s.stats[k] ?? d;

  // Combat Accuracy: "<label> <pct>  R:<min-max>  A:<avg>" (matches MegaMud).
  const rows: { label: string; pct: string; r: string; a: string }[] = [
    { label: "Miss", pct: stat("miss_pct"), r: "", a: "" },
    { label: "Hit", pct: stat("hit_pct"), r: stat("hit_range", "0-0"), a: stat("hit_avg", "0") },
    { label: "Extra", pct: stat("extra_pct"), r: stat("extra_range", "0-0"), a: stat("extra_avg", "0") },
    { label: "Crit", pct: stat("crit_pct"), r: stat("crit_range", "0-0"), a: stat("crit_avg", "0") },
    { label: "BS", pct: stat("backstab_pct"), r: stat("backstab_range", "0-0"), a: stat("backstab_avg", "0") },
    { label: "Cast", pct: stat("cast_pct"), r: stat("cast_range", "0-0"), a: stat("cast_avg", "0") },
    { label: "Round", pct: "", r: stat("round_range", "0-0"), a: stat("round_avg", "0") },
  ];

  const expNeeded = s.stats["exp_needed"] ?? "?";
  const willLevelIn = s.stats["will_level_in"] ?? "?";
  void pct;  // (legacy helper retained for compatibility)

  return (
    <div className="player-stats">
      <h3>Player Statistics</h3>

      <section className="experience">
        <h4>Experience</h4>
        <div className="stat-row"><span>Duration</span><span>{s.hoursElapsed.toFixed(2)} h</span></div>
        <div className="stat-row"><span>Exp made</span><span>{state.progress.exp}</span></div>
        <div className="stat-row"><span>Exp needed</span><span>{expNeeded}</span></div>
        <div className="stat-row"><span>Exp rate</span><span>{Math.round(s.expRatePerHour)}/hr</span></div>
        <div className="stat-row"><span>Will level in</span><span>{willLevelIn}</span></div>
      </section>

      <section className="combat-accuracy">
        <h4>Combat Accuracy</h4>
        <div className="accuracy-header">
          <span className="col-label"></span>
          <span className="col-r">R:</span>
          <span className="col-a">A:</span>
        </div>
        {rows.map((row) => (
          <div className="accuracy-row" key={row.label}>
            <span className="col-label">{row.label} {row.pct}</span>
            <span className="col-r">{row.r}</span>
            <span className="col-a">{row.a}</span>
          </div>
        ))}
      </section>
    </div>
  );
}
