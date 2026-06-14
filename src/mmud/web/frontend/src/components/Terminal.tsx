import React, { useEffect, useRef } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { PanelState } from "../panelState";

// DISPLAY comes from the raw server stream (RawOutput) written straight into
// xterm.js, which owns its own screen buffer + scrollback. The room header /
// prompt below still read SEMANTICS from PanelState (HpChanged/RoomChanged/etc).
export function Terminal({
  state,
  rawSinkRef,
}: {
  state: PanelState;
  rawSinkRef: React.MutableRefObject<(data: string) => void>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const term = new XTerm({
      cols: 80,
      rows: 24,
      convertEol: true,
      fontFamily: "monospace",
      theme: { background: "#000000", foreground: "#c0c0c0" },
    });
    term.open(containerRef.current);
    termRef.current = term;
    // Point the WS hook's raw sink at this terminal's write().
    rawSinkRef.current = (data: string) => term.write(data);
    return () => {
      rawSinkRef.current = () => {};
      term.dispose();
      termRef.current = null;
    };
  }, [rawSinkRef]);

  const v = state.vitals;
  return (
    <div className="terminal">
      <div className="room-header">
        {state.room.name || state.room.code} {state.vitals.inCombat ? "[COMBAT]" : ""}
      </div>
      <div className="terminal-body" ref={containerRef} />
      <div className="prompt">
        [HP={v.hp}/{v.maxHp}] [MP={v.mana}/{v.maxMana}]
      </div>
    </div>
  );
}
