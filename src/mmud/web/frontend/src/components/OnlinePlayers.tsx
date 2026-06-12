import React from "react";
import { PanelState } from "../panelState";

// Binding: state.players (PlayerSeen: name/level/rep/gang).
export function OnlinePlayers({ state }: { state: PanelState }) {
  const players = Object.values(state.players);
  return (
    <div className="online-players">
      <h3>Online Players</h3>
      <table>
        <thead>
          <tr><th>Name</th><th>Level</th><th>Rep</th><th>Gang</th></tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <tr key={p.name}>
              <td>{p.name}</td><td>{p.level}</td><td>{p.rep}</td><td>{p.gang}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
