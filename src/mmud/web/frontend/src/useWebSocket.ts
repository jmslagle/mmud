import { useEffect, useReducer, useRef } from "react";
import { initialPanelState, panelReducer, PanelEvent } from "./panelState";

/** Forward a RawOutput event's data to a terminal write sink. Pure + testable. */
export function routeRawOutput(
  ev: PanelEvent,
  write: (data: string) => void,
): void {
  if (ev.type === "RawOutput" && typeof ev.data === "string") {
    write(ev.data);
  }
}

export function useWebSocket(url = "/ws") {
  const [state, dispatch] = useReducer(panelReducer, initialPanelState);
  const wsRef = useRef<WebSocket | null>(null);
  // xterm.js holds its own screen buffer; RawOutput bypasses the reducer and
  // is written straight to the terminal via this sink (set by the Terminal).
  const rawSinkRef = useRef<(data: string) => void>(() => {});

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}${url}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data) as PanelEvent;
      routeRawOutput(ev, (data) => rawSinkRef.current(data));
      dispatch(ev);
    };
    return () => ws.close();
  }, [url]);

  return { state, rawSinkRef };
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
