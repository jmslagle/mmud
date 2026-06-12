import React, { useState } from "react";
import "./App.css";
import { useWebSocket, sendCommand } from "./useWebSocket";
import { Terminal } from "./components/Terminal";
import { Conversations } from "./components/Conversations";
import { OnlinePlayers } from "./components/OnlinePlayers";
import { SessionStats } from "./components/SessionStats";
import { PlayerStats } from "./components/PlayerStats";
import { QuickTools } from "./components/QuickTools";
import { Settings } from "./components/Settings";

export function App() {
  const state = useWebSocket();
  const [cmd, setCmd] = useState("");
  const [showSettings, setShowSettings] = useState(false);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (cmd.trim()) { void sendCommand(cmd); setCmd(""); }
  };

  return (
    <div className="app">
      <header>
        <span>mmud control panel</span>
        <button onClick={() => setShowSettings((v) => !v)}>
          {showSettings ? "Panels" : "Settings"}
        </button>
      </header>
      {showSettings ? (
        <Settings />
      ) : (
        <div className="grid">
          <div className="main-col">
            <Terminal state={state} />
            <form className="command-bar" onSubmit={submit}>
              <input
                value={cmd}
                onChange={(e) => setCmd(e.target.value)}
                placeholder="Type a command…"
                autoFocus
              />
              <button type="submit">Send</button>
            </form>
            <Conversations state={state} />
          </div>
          <div className="side-col">
            <PlayerStats state={state} />
            <SessionStats state={state} />
            <OnlinePlayers state={state} />
            <QuickTools state={state} />
          </div>
        </div>
      )}
    </div>
  );
}
