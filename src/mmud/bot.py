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
    ConversationReceived, PlayerSeen, SessionStatUpdated, TaskChanged,
    ConditionChanged, HangupTriggered,
)
from mmud.automation.decision import (
    DecisionEngine, QueueDecider, PRIO_QUEUE, PRIO_CURE, PRIO_FLEE, PRIO_SPELLS, PRIO_COMBAT,
)
from mmud.state.tasks import TaskType
from mmud.automation.cures import CureDecider
from mmud.automation.safety import SafetyMonitor
from mmud.automation.remote import RemoteCommandHandler
from mmud.state.conditions import scan_onset, scan_recovery
from mmud.parser.who_parser import WhoParser
from mmud.parser.conversation_parser import ConversationParser
from mmud.net.connection import MudConnection
from mmud.parser.matcher import PatternMatcher
from mmud.parser.room_parser import RoomParser
from mmud.state.game_state import GameState, MonsterSighting
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
_PLAYER_HIT_RE = re.compile(r"You (?:hit|strike|slash|pierce|bash|backstab)\w* \w.+? for (\d+) damage", re.IGNORECASE)
_PLAYER_MISS_RE = re.compile(r"You miss\b", re.IGNORECASE)
_MONSTER_HIT_RE = re.compile(r"(?:hits?|strikes?|slashes?|bashes?|pierces?) you for (\d+) damage", re.IGNORECASE)
_BACKSTAB_RE = re.compile(r"You backstab", re.IGNORECASE)


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

        from mmud.data.monster_db import MonsterDB
        monsters_md = (data_dir / "MONSTERS.MD") if data_dir else None
        self._monster_db = (MonsterDB.from_file(monsters_md)
                            if monsters_md and monsters_md.exists() else MonsterDB([]))

        self._state = GameState()
        self._navigator = Navigator.from_directory(data_dir) if data_dir else Navigator([])
        self._combat = CombatEngine(
            config=self._config.combat,
            sneak_cmd=self._config.stealth.sneak_cmd if self._config.stealth.auto_sneak else "",
        )
        self._spell_engine = SpellEngine(self._config.spells)
        self._engine = DecisionEngine()
        self._engine.register("queue", QueueDecider(), PRIO_QUEUE)
        self._engine.register("spells", self._spell_engine, PRIO_SPELLS)
        self._engine.register("combat", self._combat, PRIO_COMBAT)
        self._safety = SafetyMonitor(self._config.safety)
        self._remote = RemoteCommandHandler(self)
        from mmud.combat.pvp import PvpEngine
        self._pvp = PvpEngine(self._config.pvp, self._config.players, self._safety)
        self._engine.register("cures", CureDecider(self._config.health), PRIO_CURE)
        from mmud.automation.run_rules import RunDecider
        self._engine.register("run", RunDecider(self._config.combat,
                                                self._config.navigation), PRIO_FLEE)
        from mmud.combat.backstab import BackstabEngine
        self._backstab = BackstabEngine(self._config.combat, self._config.stealth)
        self._engine.register("backstab", self._backstab, PRIO_COMBAT - 1)
        self._bus = event_bus
        self._loop_runner = None   # set by toggle_loop()
        self._login_handler = LoginHandler(self._config.login)
        self._who_parser = WhoParser()
        self._last_activity = time.monotonic()
        self._auto_started = False
        self._redial_delay_s = 5.0

    def _emit(self, event: object) -> None:
        if self._bus is not None:
            self._bus.post(event)

    async def run(self) -> None:
        redials = 0
        while True:
            try:
                await self._run_session()
            except (ConnectionError, OSError):
                pass
            if self._safety.hangup_requested:
                break   # deliberate disconnect — never auto-reconnect past it
            if (not self._config.safety.reconnect
                    or redials >= self._config.safety.max_redials):
                break
            redials += 1
            await asyncio.sleep(self._redial_delay_s)

    async def _run_session(self) -> None:
        await self._conn.connect()
        ticker_task = asyncio.create_task(self._ticker())
        try:
            async for line in self._conn.readlines():
                await self._process_line(line)
                if self._safety.hangup_requested:
                    self._emit(HangupTriggered(reason=self._safety.reason))
                    break
                cmd = self._next_command()
                if cmd:
                    await self._conn.send(cmd)
                    self._last_activity = time.monotonic()
                    if cmd in ("n", "s", "e", "w", "ne", "nw", "se", "sw", "u", "d"):
                        self._state.move_history.append(cmd)
        finally:
            ticker_task.cancel()
            await self._conn.close()

    async def _ticker(self) -> None:
        """1Hz background tick: advances spell cooldowns and checks AFK."""
        while True:
            await asyncio.sleep(1.0)
            self._spell_engine.tick()
            self._check_afk()
            self._check_task_timeout(time.monotonic())

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
        self._parse_conditions(clean)
        self._safety.process_line(clean)
        self._backstab.on_line(clean)
        self._parse_room(clean)
        self._parse_combat_exit(clean)
        self._parse_combat_stats(clean)
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
            if (self._config.afk.enabled and self._config.afk.hangup_on_low_hp
                    and max_hp > 0 and hp / max_hp <= self._config.combat.flee_threshold):
                self._safety.request_hangup(f"low HP while AFK ({hp}/{max_hp})")
        if m := _MP_RE.search(line):
            mp, max_mp = int(m.group(1)), int(m.group(2))
            self._state.set_mana(mp, max_mp)
            self._emit(MpChanged(mp=mp, max_mp=max_mp))

    def _parse_conditions(self, line: str) -> None:
        if cond := scan_onset(line):
            if cond not in self._state.conditions:
                self._state.conditions.add(cond)
                self._emit(ConditionChanged(name=cond.name, active=True))
                # Conditions interrupt whatever the bot was doing
                if self._state.task.is_active:
                    self._state.abort_task()
                # Blind blocks movement: stop any running loop
                if cond.name == "BLIND" and self._loop_runner and self._loop_runner.running:
                    self.stop_all()
        if cond := scan_recovery(line):
            self._state.conditions.discard(cond)
            self._emit(ConditionChanged(name=cond.name, active=False))
            # Complete the pending cure task for this condition
            if (self._state.task.is_active
                    and self._state.task.payload.get("condition") == cond.name):
                self._state.complete_task()

    def _parse_room(self, line: str) -> None:
        if code := self._room_parser.detect_room(line):
            prev = self._state.current_room
            self._state.set_room(code)
            self._state.monsters_present.clear()
            self._state.players_present = []
            self._backstab.reset()
            if self._state.task.type is TaskType.RUNNING:
                self._state.complete_task()
            if code != prev:
                self._emit(RoomChanged(code=code, name=line.strip()))
        else:
            sightings = self._room_parser.extract_sightings(line)
            if sightings:
                for name, count in sightings:
                    rec = self._monster_db.find(name)
                    self._state.monsters_present.append(MonsterSighting(
                        name=name, count=count,
                        exp_each=rec.exp_value if rec else 0,
                        record_id=rec.record_id if rec else -1,
                    ))
                self._emit(MonstersSeen(monsters=[n for n, _ in sightings]))
            players = self._room_parser.extract_players(line)
            if players:
                self._state.players_present = players
                if cmd := self._pvp.check(self._state):
                    self._state.enqueue(cmd)

    def _parse_conversation(self, line: str) -> None:
        msg = self._convo_parser.parse(line)
        if msg is None:
            return
        self._emit(ConversationReceived(
            channel=msg.channel,
            sender=msg.sender,
            text=msg.text,
        ))
        if self._config.remote.enabled and msg.channel == "tell":
            reply = self._remote.handle(msg.sender, msg.text)
            if reply:
                self._state.enqueue(
                    self._config.remote.tell_format.format(name=msg.sender, text=reply)
                )

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

    def _parse_combat_stats(self, line: str) -> None:
        if m := _PLAYER_HIT_RE.search(line):
            dmg = int(m.group(1))
            is_bs = bool(_BACKSTAB_RE.search(line))
            self._state.record_hit(dmg)
            if is_bs:
                self._state.record_backstab(success=True)
            self._emit(SessionStatUpdated(key="hit_pct", value=f"{self._state.hit_pct:.0f}%"))
        elif _PLAYER_MISS_RE.search(line):
            self._state.record_miss()
        elif m := _MONSTER_HIT_RE.search(line):
            self._state.record_monster_hit()

    def _parse_combat_exit(self, line: str) -> None:
        if self._state.in_combat and _COMBAT_EXIT_RE.search(line):
            self._state.set_combat(False)
            self._state.monsters_present.clear()
            self._emit(CombatChanged(in_combat=False))

    def _next_command(self) -> str | None:
        return self._engine.next_command(self._state)

    def _check_task_timeout(self, now: float) -> None:
        if self._state.task.expired(now):
            task_name = self._state.task.type.name
            self._state.abort_task()
            self._emit(TaskChanged(task_type=task_name, status="timeout"))

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

    def start_loop(self, name: str = "") -> str:
        """Start a named loop path. Returns status message."""
        from mmud.automation.loop_runner import LoopRunner
        if name:
            self._config.navigation.loop_path = name.upper()
        loop_name = self._config.navigation.loop_path
        if not loop_name:
            return "No loop path configured. Use :loop NAME"
        if self._loop_runner and self._loop_runner.running:
            self._loop_runner.stop()
        paths = list(self._navigator._paths.values())
        self._loop_runner = LoopRunner(
            nav_config=self._config.navigation,
            stealth_config=self._config.stealth,
            paths=paths,
            state=self._state,
            bus=self._bus or __import__("mmud.events", fromlist=["GameEventBus"]).GameEventBus(),
        )
        self._loop_runner.start()
        if self._loop_runner._path is None:
            return f"Loop path '{loop_name}' not found in loaded paths"
        return f"Loop started: {loop_name}"

    def stop_all(self) -> str:
        """Stop loop and clear command queue."""
        if self._loop_runner:
            self._loop_runner.stop()
        while self._state.dequeue() is not None:
            pass
        return "Stopped."

    def navigate_to_room(self, to_code: str) -> str:
        """Navigate from current room to to_code using a loaded path."""
        from_code = self._state.current_room
        if not from_code:
            return "Current room unknown — move around first to establish position"
        path = self._navigator.navigate_to(from_code, to_code.upper())
        if path is None:
            return f"No direct path from {from_code} to {to_code.upper()}"
        # Clear queue and enqueue the path
        while self._state.dequeue() is not None:
            pass
        self._navigator.execute_path(path, self._state)
        return f"Navigating: {from_code} → {to_code.upper()} ({len(path.steps)} steps)"

    def list_paths(self) -> list[str]:
        """Return all known loop path names."""
        return self._navigator.list_loop_paths()

    def status_text(self) -> str:
        """Return a brief status string."""
        s = self._state
        hp_str = f"HP:{s.hp}/{s.max_hp}" if s.max_hp else "HP:?"
        mp_str = f"MP:{s.mana}/{s.max_mana}" if s.max_mana else "MP:?"
        room = s.current_room or "?"
        loop = ""
        if self._loop_runner and self._loop_runner.running:
            name = self._config.navigation.loop_path
            loop = f" | Loop:{name} lap:{self._loop_runner.lap}"
        combat = " | IN COMBAT" if s.in_combat else ""
        return f"Room:{room} {hp_str} {mp_str}{loop}{combat}"
