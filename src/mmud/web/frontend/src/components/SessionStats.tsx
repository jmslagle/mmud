import React from "react";
import { PanelState } from "../panelState";

// Bindings: state.session.hoursElapsed (Time/Online), state.session.stats[...]
// from SessionStatUpdated (Doc 1 supplies: dialed/failed/connected/lost_carrier,
// people_seen/attacked, killed/had_to_run/health_low, sneak_pct/dodge_pct,
// deposited/income_rate). Missing keys render "0"/"-".
export function SessionStats({ state }: { state: PanelState }) {
  const st = state.session.stats;
  const g = (k: string, dflt = "0") => st[k] ?? dflt;
  return (
    <div className="session-stats">
      <h3>Session Statistics</h3>
      <section>
        <h4>Time</h4>
        <div className="stat-row"><span>MegaMud</span><span>{g("megamud_time", "-")}</span></div>
        <div className="stat-row"><span>Online</span><span>{state.session.hoursElapsed.toFixed(2)} h</span></div>
      </section>
      <section>
        <h4>Comms</h4>
        <div className="stat-row"><span>Dialed</span><span>{g("dialed")}</span></div>
        <div className="stat-row"><span>Failed</span><span>{g("failed")}</span></div>
        <div className="stat-row"><span>Connected</span><span>{g("connected")}</span></div>
        <div className="stat-row"><span>Lost carrier</span><span>{g("lost_carrier")}</span></div>
      </section>
      <section>
        <h4>Visitors</h4>
        <div className="stat-row"><span>People seen</span><span>{g("people_seen")}</span></div>
        <div className="stat-row"><span>Attacked</span><span>{g("attacked")}</span></div>
      </section>
      <section>
        <h4>Monsters</h4>
        <div className="stat-row"><span>Killed</span><span>{g("kills")}</span></div>
        <div className="stat-row"><span>Had to run</span><span>{g("had_to_run")}</span></div>
        <div className="stat-row"><span>Health low</span><span>{g("health_low")}</span></div>
      </section>
      <section>
        <h4>Other</h4>
        <div className="stat-row"><span>Sneak%</span><span>{g("sneak_pct", "0%")}</span></div>
        <div className="stat-row"><span>Dodge%</span><span>{g("dodge_pct", "0%")}</span></div>
        <div className="stat-row"><span>Deposited</span><span>{g("deposited")}</span></div>
        <div className="stat-row"><span>Income rate</span><span>{g("income_rate", "0/hr")}</span></div>
      </section>
    </div>
  );
}
