from __future__ import annotations
import asyncio
import pathlib
from mmud.data.messages import MessagePattern, load_messages
from mmud.net.connection import MudConnection
from mmud.parser.matcher import PatternMatcher
from mmud.state.game_state import GameState
from mmud.navigation.navigator import Navigator
from mmud.combat.combat import CombatEngine


class MudBot:
    def __init__(
        self,
        host: str,
        port: int,
        patterns: list[MessagePattern] | None = None,
        data_dir: pathlib.Path | None = None,
    ) -> None:
        self._conn = MudConnection(host, port)
        if patterns is None and data_dir is not None:
            patterns = load_messages(data_dir / "MESSAGES.MD")
        self._matcher = PatternMatcher(patterns or [])
        self._state = GameState()
        self._navigator = Navigator.from_directory(data_dir) if data_dir else Navigator([])
        self._combat = CombatEngine()

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
        result = self._matcher.match(line)
        if result:
            self._state.apply_match(result)
            # Any apply match means we're being affected — treat as in combat
            if result.is_apply:
                self._state.set_combat(True)

    def _next_command(self) -> str | None:
        queued = self._state.dequeue()
        if queued:
            return queued
        return self._combat.decide(self._state)
