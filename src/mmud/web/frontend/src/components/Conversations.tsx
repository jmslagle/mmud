import React from "react";
import { PanelState } from "../panelState";

// Binding: state.conversations[] (ConversationReceived: channel/sender/text).
export function Conversations({ state }: { state: PanelState }) {
  return (
    <div className="conversations">
      <h3>Conversations</h3>
      <div className="convo-body">
        {state.conversations.map((m, i) => (
          <div className={`convo-line channel-${m.channel}`} key={i}>
            <span className="convo-channel">[{m.channel}]</span>{" "}
            <span className="convo-sender">{m.sender}:</span>{" "}
            <span className="convo-text">{m.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
