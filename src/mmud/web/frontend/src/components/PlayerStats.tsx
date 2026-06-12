import React from "react";
import { PanelState } from "../panelState";

function pct(n: number, d: number): string {
  return d > 0 ? `${Math.round((n / d) * 100)}%` : "0%";
}

export function PlayerStats({ state }: { state: PanelState }) {
  const c = state.combat;
  const attacks = c.hits + c.misses + c.special;
  const monsterAttacks = c.monsterHits + c.monsterMisses;
  const s = state.session;

  // Combat Accuracy rows. R: = latest round (Doc 1 fills; mirrors A: for now).
  const rows: { label: string; a: string; r: string }[] = [
    { label: "Miss", a: pct(c.misses, attacks), r: pct(c.misses, attacks) },
    { label: "Hit", a: pct(c.hits, attacks), r: pct(c.hits, attacks) },
    { label: "Extra", a: pct(c.special, attacks), r: pct(c.special, attacks) },
    { label: "Crit", a: s.stats["crit_pct"] ?? "0%", r: s.stats["crit_pct"] ?? "0%" },
    {
      label: "BS",
      a: pct(c.backstabSuccesses, c.backstabAttempts),
      r: pct(c.backstabSuccesses, c.backstabAttempts),
    },
    { label: "Cast", a: s.stats["cast_pct"] ?? "0%", r: s.stats["cast_pct"] ?? "0%" },
    {
      label: "Round",
      a: pct(c.monsterMisses, monsterAttacks),
      r: pct(c.monsterMisses, monsterAttacks),
    },
  ];

  const expNeeded = s.stats["exp_needed"] ?? "?";
  const willLevelIn = s.stats["will_level_in"] ?? "?";

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
            <span className="col-label">{row.label}</span>
            <span className="col-r">{row.r}</span>
            <span className="col-a">{row.a}</span>
          </div>
        ))}
      </section>
    </div>
  );
}
