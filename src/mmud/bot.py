from __future__ import annotations
import pathlib
import re
from mmud.data.messages import MessagePattern, load_messages
from mmud.events import (
    GameEventBus, LineReceived, HpChanged, MpChanged,
    EffectApplied, EffectRemoved, CombatChanged,
)
from mmud.net.connection import MudConnection
from mmud.parser.matcher import PatternMatcher
from mmud.state.game_state import GameState
from mmud.navigation.navigator import Navigator
from mmud.combat.combat import CombatEngine

_HP_RE = re.compile(r"\[HP=(\d+)/(\d+)\]")
_MP_RE = re.compile(r"\[MP=(\d+)/(\d+)\]")


class MudBot:
    def __init__(
        self,
        host: str,
        port: int,
        patterns: list[MessagePattern] | None = None,
        data_dir: pathlib.Path | None = None,
        event_bus: GameEventBus | None = None,
    ) -> None:
        self._conn = MudConnection(host, port)
        if patterns is None and data_dir is not None:
            patterns = load_messages(data_dir / "MESSAGES.MD")
        self._matcher = PatternMatcher(patterns or [])
        self._state = GameState()
        self._navigator = Navigator.from_directory(data_dir) if data_dir else Navigator([])
        self._combat = CombatEngine()
        self._bus = event_bus

    def _emit(self, event: object) -> None:
        if self._bus is not None:
            self._bus.post(event)

    async def run(self) -> None:
        await self._conn.connect()
        try:
            while True:
                line = await self._conn.readline()
                if not line:
                    break
                await self._process_line(line)
                cmd = self._next_command()
                if cmd:
                    await self._conn.send(cmd)
        finally:
            await self._conn.close()

    async def _process_line(self, line: str) -> None:
        self._emit(LineReceived(line=line))
        self._parse_vitals(line)
        result = self._matcher.match(line)
        if result:
            self._state.apply_match(result)
            if result.is_apply:
                self._emit(EffectApplied(name=result.pattern.name, flags=result.pattern.flags))
                prev = self._state.in_combat
                self._state.set_combat(True)
                if not prev:
                    self._emit(CombatChanged(in_combat=True))
            else:
                self._emit(EffectRemoved(name=result.pattern.name))

    def _parse_vitals(self, line: str) -> None:
        if m := _HP_RE.search(line):
            hp, max_hp = int(m.group(1)), int(m.group(2))
            self._state.set_hp(hp, max_hp)
            self._emit(HpChanged(hp=hp, max_hp=max_hp))
        if m := _MP_RE.search(line):
            mp, max_mp = int(m.group(1)), int(m.group(2))
            self._state.set_mana(mp, max_mp)
            self._emit(MpChanged(mp=mp, max_mp=max_mp))

    def _next_command(self) -> str | None:
        queued = self._state.dequeue()
        if queued:
            return queued
        return self._combat.decide(self._state)
