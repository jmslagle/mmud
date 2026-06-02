from __future__ import annotations
import asyncio
import pathlib
import re
import time
from mmud.config.schema import MudConfig
from mmud.data.messages import MessagePattern, load_messages
from mmud.data.rooms import Room, load_rooms
from mmud.events import (
    GameEventBus, LineReceived, HpChanged, MpChanged,
    EffectApplied, EffectRemoved, CombatChanged, RoomChanged, MonstersSeen,
    ConversationReceived, PlayerSeen, SessionStatUpdated,
)
from mmud.parser.who_parser import WhoParser
from mmud.parser.conversation_parser import ConversationParser
from mmud.net.connection import MudConnection
from mmud.parser.matcher import PatternMatcher
from mmud.parser.room_parser import RoomParser
from mmud.state.game_state import GameState
from mmud.navigation.navigator import Navigator
from mmud.combat.combat import CombatEngine
from mmud.automation.login import LoginHandler
from mmud.automation.spells import SpellEngine

_HP_RE = re.compile(r"\[HP=(\d+)/(\d+)\]")
_MP_RE = re.compile(r"\[MP=(\d+)/(\d+)\]")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_COMBAT_EXIT_RE = re.compile(
    r"breaks off combat|Combat Engaged:\s*Off|"
    r"You have (?:slain|killed)|falls? to the ground|"
    r"(?:is|are) dead\b",
    re.IGNORECASE,
)
_NAV_FAIL_RE = re.compile(
    r"(?:you can'?t go that way|alas|there is no exit|"
    r"you cannot go that direction|no exit|blocked|closed)",
    re.IGNORECASE,
)


class MudBot:
    def __init__(
        self,
        host: str,
        port: int,
        patterns: list[MessagePattern] | None = None,
        data_dir: pathlib.Path | None = None,
        event_bus: GameEventBus | None = None,
        rooms: dict[str, Room] | None = None,
        config: MudConfig | None = None,
    ) -> None:
        self._conn = MudConnection(host, port)
        self._config = config or MudConfig()

        if patterns is None and data_dir is not None:
            patterns = load_messages(data_dir / "MESSAGES.MD")
        self._matcher = PatternMatcher(patterns or [])

        if rooms is None and data_dir is not None:
            rooms = load_rooms(data_dir / "ROOMS.MD")
        self._room_parser = RoomParser(rooms or {})
        self._convo_parser = ConversationParser()

        self._state = GameState()
        self._navigator = Navigator.from_directory(data_dir) if data_dir else Navigator([])
        self._combat = CombatEngine(
            config=self._config.combat,
            sneak_cmd=self._config.stealth.sneak_cmd if self._config.stealth.auto_sneak else "",
        )
        self._spell_engine = SpellEngine(self._config.spells)
        self._bus = event_bus
        self._loop_runner = None   # set by toggle_loop()
        self._login_handler = LoginHandler(self._config.login)
        self._who_parser = WhoParser()
        self._last_activity = time.monotonic()
        self._auto_started = False

    def _emit(self, event: object) -> None:
        if self._bus is not None:
            self._bus.post(event)

    async def run(self) -> None:
        await self._conn.connect()
        ticker_task = asyncio.create_task(self._ticker())
        try:
            while True:
                line = await self._conn.readline()
                if not line:
                    break
                await self._process_line(line)
                cmd = self._next_command()
                if cmd:
                    await self._conn.send(cmd)
                    self._last_activity = time.monotonic()
        finally:
            ticker_task.cancel()
            await self._conn.close()

    async def _ticker(self) -> None:
        """1Hz background tick: advances spell cooldowns and checks AFK."""
        while True:
            await asyncio.sleep(1.0)
            self._spell_engine.tick()
            self._check_afk()

    def _check_afk(self) -> None:
        cfg = self._config.afk
        if not cfg.enabled or self._state.in_combat:
            return
        idle = time.monotonic() - self._last_activity
        if idle >= cfg.timeout_minutes * 60:
            self._state.enqueue(cfg.reply)
            self._last_activity = time.monotonic()  # reset to avoid spam

    async def _process_line(self, line: str) -> None:
        self._emit(LineReceived(line=line))
        clean = _ANSI_RE.sub("", line).strip()
        self._parse_vitals(clean)
        self._parse_room(clean)
        self._parse_combat_exit(clean)
        self._parse_nav_failure(clean)
        self._parse_conversation(clean)
        self._handle_login(clean)
        self._parse_who_and_exp(clean)
        result = self._matcher.match(clean)
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

    def _parse_room(self, line: str) -> None:
        if code := self._room_parser.detect_room(line):
            prev = self._state.current_room
            self._state.set_room(code)
            self._state.monsters_present.clear()
            if code != prev:
                self._emit(RoomChanged(code=code, name=line.strip()))
        else:
            monsters = self._room_parser.extract_monsters(line)
            if monsters:
                self._state.monsters_present.extend(monsters)
                self._emit(MonstersSeen(monsters=monsters))

    def _parse_conversation(self, line: str) -> None:
        msg = self._convo_parser.parse(line)
        if msg:
            self._emit(ConversationReceived(
                channel=msg.channel,
                sender=msg.sender,
                text=msg.text,
            ))

    def _handle_login(self, line: str) -> None:
        if self._login_handler.in_game:
            # Check auto_start on first game entry
            if (not self._auto_started
                    and self._config.navigation.auto_start):
                self._auto_started = True
                self.toggle_loop()
            return
        if self._state.in_combat:
            return
        cmd = self._login_handler.process_line(line)
        if cmd is not None:
            self._state.enqueue(cmd)

    def _parse_who_and_exp(self, line: str) -> None:
        # WHO list entry
        entry = self._who_parser.parse_line(line)
        if entry:
            self._emit(PlayerSeen(name=entry.name, level=entry.level,
                                  rep=entry.rep, gang=entry.gang))
            return
        # XP tracking
        if (exp := self._who_parser.parse_exp_line(line)) is not None:
            self._state.set_exp(exp)
            self._emit(SessionStatUpdated(key="exp", value=str(exp)))
        if (lvl := self._who_parser.parse_level_line(line)) is not None:
            self._state.set_level(lvl)
        # Kill detection: "You have slain the X" (already in combat exit)
        if "have slain" in line.lower() or "have killed" in line.lower():
            self._state.add_kill()
            self._emit(SessionStatUpdated(key="kills", value=str(self._state.kills)))

    def _parse_nav_failure(self, line: str) -> None:
        if _NAV_FAIL_RE.search(line):
            if self._loop_runner and self._loop_runner.running:
                self._loop_runner.on_nav_failure()

    def _parse_combat_exit(self, line: str) -> None:
        if self._state.in_combat and _COMBAT_EXIT_RE.search(line):
            self._state.set_combat(False)
            self._state.monsters_present.clear()
            self._emit(CombatChanged(in_combat=False))

    def _next_command(self) -> str | None:
        queued = self._state.dequeue()
        if queued:
            return queued
        # Spell decisions first (heal, pre-attack, bless, mana heal)
        if cmd := self._spell_engine.decide(self._state):
            return cmd
        return self._combat.decide(self._state)

    def toggle_loop(self) -> None:
        from mmud.automation.loop_runner import LoopRunner
        if self._loop_runner and self._loop_runner.running:
            self._loop_runner.stop()
            return
        paths = list(self._navigator._paths.values())
        self._loop_runner = LoopRunner(
            nav_config=self._config.navigation,
            stealth_config=self._config.stealth,
            paths=paths,
            state=self._state,
            bus=self._bus or GameEventBus(),
        )
        self._loop_runner.start()
