import React, { useMemo, useRef, useEffect } from "react";
import Convert from "ansi-to-html";
import { PanelState } from "../panelState";

// Bindings: state.terminal (LineReceived), state.room (RoomChanged),
// state.vitals.hp/maxHp/mana/maxMana (HpChanged/MpChanged), inCombat (CombatChanged).
export function Terminal({ state }: { state: PanelState }) {
  const convert = useMemo(() => new Convert({ newline: true }), []);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo(0, ref.current.scrollHeight); }, [state.terminal]);
  const html = useMemo(
    () => state.terminal.map((l) => convert.toHtml(l)).join("<br/>"),
    [state.terminal, convert],
  );
  const v = state.vitals;
  return (
    <div className="terminal">
      <div className="room-header">
        {state.room.name || state.room.code} {state.vitals.inCombat ? "[COMBAT]" : ""}
      </div>
      <div className="terminal-body" ref={ref} dangerouslySetInnerHTML={{ __html: html }} />
      <div className="prompt">
        [HP={v.hp}/{v.maxHp}] [MP={v.mana}/{v.maxMana}]
      </div>
    </div>
  );
}
