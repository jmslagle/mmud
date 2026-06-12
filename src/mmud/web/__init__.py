"""Web control panel: FastAPI + WebSocket UI driven by GameEventBus.

`WebPanelServer` (server.py) registers one subscriber per event dataclass,
serialises each event to JSON, and broadcasts it to all /ws clients. REST
endpoints read GameState/SessionManager and drive the live MudBot. The whole
package is optional — only imported when [web] config is enabled (see
MudBot.maybe_build_web_server).
"""
