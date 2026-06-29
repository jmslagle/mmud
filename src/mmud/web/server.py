from __future__ import annotations
import dataclasses
import pathlib
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import mmud.events as ev
from mmud.web.serialize import serialize_event

_EVENT_TYPES: tuple[type, ...] = (
    ev.LineReceived, ev.HpChanged, ev.MpChanged, ev.RoomChanged,
    ev.EffectApplied, ev.EffectRemoved, ev.CombatChanged,
    ev.ConversationReceived, ev.PlayerSeen, ev.PathStarted, ev.PathStepped,
    ev.SessionStatUpdated, ev.MonstersSeen, ev.TaskChanged,
    ev.ConditionChanged, ev.HangupTriggered, ev.DbImported, ev.DbCollision,
    ev.TravelResynced, ev.TravelEnded, ev.TravelLost, ev.RawOutput,
    # ScreenUpdated is intentionally NOT broadcast — it's a TUI re-render signal;
    # the web frontend redraws from the RawOutput byte stream via xterm.js.
)

_QUICKTOOL: dict[str, str] = {
    "n": "n", "ne": "ne", "e": "e", "se": "se",
    "s": "s", "sw": "sw", "w": "w", "nw": "nw", "u": "u", "d": "d",
    # get-all / equip-all / mark-worn are handled by post_quicktool via the bot (they
    # walk the inventory one item at a time, not a blanket "get all"/"wear all").
    "drop-all": "drop all", "deposit": "deposit all", "search": "search", "afk": "afk",
}

_FRONTEND_DIST = pathlib.Path(__file__).parent / "frontend" / "dist"


def quicktool_command(action: str) -> str | None:
    return _QUICKTOOL.get(action)


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: list[Any] = []

    def add(self, ws: Any) -> None:
        self._clients.append(ws)

    def remove(self, ws: Any) -> None:
        if ws in self._clients:
            self._clients.remove(ws)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(ws)


class CommandBody(BaseModel):
    cmd: str


class QuickToolBody(BaseModel):
    action: str


class LoopBody(BaseModel):
    name: str = ""        # loop path name (e.g. "CAVWLOOP"); "" -> the configured loop_path
    action: str = "start"  # "start" | "stop"


class GotoBody(BaseModel):
    target: str           # 4-letter room code OR name substring (resolved by navigate_to_room)


class WebPanelServer:
    def __init__(self, bot: Any) -> None:
        self._bot = bot
        self._manager = ConnectionManager()
        self._loop = None
        self.app = self._build_app()
        self._subscribe_all()

    def _subscribe_all(self) -> None:
        bus = self._bot._bus
        if bus is None:
            return
        for event_type in _EVENT_TYPES:
            bus.subscribe(event_type, self._on_event)

    def _on_event(self, event: object) -> None:
        message = serialize_event(event)
        import asyncio
        coro = self._manager.broadcast(message)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        loop = self._loop
        if running is not None and (loop is None or loop is running):
            # Same thread as the server loop: schedule directly.
            running.create_task(coro)
            return
        if loop is not None:
            # Posted from another thread (e.g. the bot's I/O thread or a
            # synchronous test driver): hand off to the server loop safely.
            asyncio.run_coroutine_threadsafe(coro, loop)
            return
        # No server loop known and no running loop: nothing we can do.
        coro.close()

    def snapshot(self) -> dict:
        import time
        s = self._bot._state
        sess = self._bot._session
        now = time.monotonic()
        return {
            "room": {"code": s.current_room, "hex": s.current_hex},
            "vitals": {"hp": s.hp, "max_hp": s.max_hp, "mana": s.mana,
                       "max_mana": s.max_mana, "in_combat": s.in_combat},
            "progress": {"level": s.level, "exp": s.exp, "kills": s.kills,
                         "exp_needed": s.exp_needed},
            "combat": {"hits": s.combat_hits, "misses": s.combat_misses,
                       "special": s.combat_special, "dmg_sum": s.combat_dmg_sum,
                       "monster_hits": s.monster_hits, "monster_misses": s.monster_misses,
                       "backstab_attempts": s.backstab_attempts,
                       "backstab_successes": s.backstab_successes,
                       "hit_pct": s.hit_pct, "avg_damage": s.avg_damage,
                       "accuracy": s.combat_accuracy()},
            "session": {"hours_elapsed": sess.hours_elapsed(now),
                        "exp_rate_per_hour": sess.exp_rate_per_hour(),
                        "people_seen": sess.people_seen, "attacked": sess.attacked,
                        "dialed": sess.dialed, "dial_failed": sess.dial_failed,
                        "connected": sess.connected, "carrier_lost": sess.carrier_lost,
                        "deposited": sess.deposited,
                        "income_rate": sess.income_rate_per_hour(now),
                        "sneak_pct": s.sneak_pct, "dodge_pct": s.dodge_pct,
                        "ran_away": s.ran_away, "health_low": s.health_low},
            "monsters": [{"name": m.name, "count": m.count, "exp_each": m.exp_each}
                         for m in s.monsters_present],
            "players": list(s.players_present),
            "player_records": (store.players()
                               if (store := getattr(self._bot, "_store", None)) else {}),
        }

    def _config_service(self):
        return getattr(self._bot, "_config_service", None)

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="mmud control panel")
        bot = self._bot
        manager = self._manager

        @app.get("/api/state")
        async def get_state():
            return self.snapshot()

        @app.post("/api/command")
        async def post_command(body: CommandBody):
            cmd = body.cmd.strip()
            if not cmd:
                return JSONResponse({"detail": "empty command"}, status_code=400)
            await bot._conn.send(cmd)
            return {"ok": True, "sent": cmd}

        @app.post("/api/quicktool")
        async def post_quicktool(body: QuickToolBody):
            action = body.action.strip().lower()
            # Walk-the-list actions go through the bot (one command per item), not a
            # blanket "get all"/"wear all".
            if action == "get-all":
                return {"ok": True, "action": action, "sent": bot.get_all()}
            if action == "equip-all":
                return {"ok": True, "action": action, "sent": bot.equip_all()}
            if action == "mark-worn":
                return {"ok": True, "action": action, "sent": bot.mark_worn_as_auto()}
            cmd = quicktool_command(action)
            if cmd is None:
                return JSONResponse({"detail": f"unknown action: {action}"}, status_code=400)
            await bot._conn.send(cmd)
            return {"ok": True, "action": action, "sent": cmd}

        @app.post("/api/loop")
        async def post_loop(body: LoopBody):
            # Start/stop a navigation loop by name (the configured loop_path when blank).
            # Routes to the bot's own loop runner — NOT a raw server command — so it works
            # the same as the TUI ":loop NAME".
            action = (body.action or "start").strip().lower()
            if action == "stop":
                return {"ok": True, "action": "stop", "result": bot.stop_all()}
            name = body.name.strip()
            return {"ok": True, "action": "start", "name": name,
                    "result": bot.start_loop(name)}

        @app.post("/api/goto")
        async def post_goto(body: GotoBody):
            # Multi-hop navigate to a room by 4-letter code or name substring — routes to the
            # bot's own travel graph (navigate_to_room), the same as the TUI ":goto CODE".
            target = body.target.strip()
            if not target:
                return JSONResponse({"detail": "empty target"}, status_code=400)
            return {"ok": True, "target": target,
                    "result": bot.navigate_to_room(target)}

        @app.get("/api/config")
        async def get_config():
            svc = self._config_service()
            if svc is None:
                return JSONResponse({"detail": "config service unavailable"}, status_code=503)
            return dataclasses.asdict(svc.config)

        @app.patch("/api/config")
        async def patch_config(patch: dict):
            svc = self._config_service()
            if svc is None:
                return JSONResponse({"detail": "config service unavailable"}, status_code=503)
            try:
                svc.patch(patch["section"], patch["field"], patch["value"],
                          persist=svc.can_persist)
            except KeyError as exc:
                return JSONResponse({"detail": f"unknown field: {exc}"}, status_code=400)
            except ValueError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            return dataclasses.asdict(svc.config)

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            import asyncio
            if self._loop is None:
                self._loop = asyncio.get_running_loop()
            await ws.accept()
            manager.add(ws)
            try:
                await ws.send_json({"type": "Snapshot", **self.snapshot()})
                while True:
                    await ws.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                manager.remove(ws)

        if _FRONTEND_DIST.is_dir():
            app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")
        return app

    async def serve(self) -> None:
        import asyncio
        import uvicorn
        self._loop = asyncio.get_running_loop()
        cfg = self._bot._config.web
        config = uvicorn.Config(self.app, host=cfg.host, port=cfg.port, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()
