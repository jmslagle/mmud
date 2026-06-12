import { useEffect, useReducer, useRef } from "react";
import { initialPanelState, panelReducer, PanelEvent } from "./panelState";

export function useWebSocket(url = "/ws") {
  const [state, dispatch] = useReducer(panelReducer, initialPanelState);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}${url}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data) as PanelEvent;
      dispatch(ev);
    };
    return () => ws.close();
  }, [url]);

  return state;
}

export async function sendCommand(cmd: string): Promise<void> {
  await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cmd }),
  });
}

export async function quickTool(action: string): Promise<void> {
  await fetch("/api/quicktool", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}
