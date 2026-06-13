from __future__ import annotations
import asyncio
import logging
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
    ConditionChanged, HangupTriggered, DbImported, DbCollision,
)
from mmud.automation.decision import (
    DecisionEngine, QueueDecider, PRIO_QUEUE, PRIO_CURE, PRIO_FLEE, PRIO_SPELLS, PRIO_COMBAT,
    PRIO_BACKSTAB, PRIO_REFRESH, PRIO_ITEMS, PRIO_EQUIP, PRIO_TRAVEL, PRIO_SEARCH,
    PRIO_COMMERCE, PRIO_PARTY,
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
from mmud.parser.ansi import render_line, visible_text
from mmud.state.game_state import GameState, MonsterSighting
from mmud.navigation.navigator import Navigator
from mmud.combat.combat import CombatEngine
from mmud.automation.login import LoginHandler
from mmud.automation.spells import SpellEngine

# Prompt vitals. MajorMud prompts vary by player config: "[HP=141/216]",
# "[HP=49 /MA=20 ]" (current-only, mana as MA), "[HP=49/216 MA=20/45]", etc.
# Capture current and an OPTIONAL max for each; mana is MA or MP.
_HP_RE = re.compile(r"\bHP=(\d+)(?:/(\d+))?")
_MP_RE = re.compile(r"\b(?:MA|MP)=(\d+)(?:/(\d+))?")
# The `stat`/`health` command reports current AND max — learn the max here so a
# minimal prompt (current-only) still drives flee/rest thresholds. RECONSTRUCTED
# wording; tune against the live server (docs/testing-plan.md).
_STAT_HITS_RE = re.compile(r"\b(?:Hits|Hit Points|HP):\s*(\d+)/(\d+)")
_STAT_MANA_RE = re.compile(r"\bMana:\s*(\d+)/(\d+)")
# Line rendering (cursor replay + colour) lives in mmud.parser.ansi.
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

_log = logging.getLogger(__name__)


class MudBot:
    """Top-level bot: reads MUD lines, updates GameState, decides next command.

    Data flow per line: the connection yields a raw line, which _process_line
    runs through an ordered pipeline of parser/monitor hooks that mutate
    self._state (and emit events on self._bus). After each line the
    DecisionEngine (self._engine) is consulted via _next_command() to pick the
    single next command to send.

    Lifecycle:
      * __init__ builds the parsers, line-monitors, deciders, and the decision
        registry (the decider table is assembled in _build_engines()).
      * run() drives the reconnect/relog loop, calling _run_session() per
        connection and handling carrier loss / redial / hangup.
      * _run_session() owns one connection's read -> _process_line -> decide ->
        send loop, plus a 1Hz background _ticker() (cooldowns, AFK, timeouts,
        session limits, scheduler).
    """

    def __init__(
        self,
        host: str,
        port: int,
        patterns: list[MessagePattern] | None = None,
        data_dir: pathlib.Path | None = None,
        event_bus: GameEventBus | None = None,
        rooms: dict[str, Room] | None = None,
        config: MudConfig | None = None,
        config_path: pathlib.Path | None = None,
        config_service=None,
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
        self._bus = event_bus   # assigned early so DB import can emit events

        from mmud.config.runtime import ConfigService
        self._config_service = config_service or ConfigService(
            self._config,
            bus=self._bus or GameEventBus(),
            path=config_path,
        )
        self._web_server = None

        from mmud.data.monster_db import MonsterDB
        from mmud.data.item_db import ItemDB
        self._store = None
        if self._config.learning.enabled and data_dir is not None:
            from mmud.data.store import GameStore, import_md
            self._store = GameStore(pathlib.Path(self._config.learning.store_path))
            report = import_md(self._store, data_dir)
            self._monster_db = MonsterDB.from_store(self._store)
            self._item_db = ItemDB.from_store(self._store)
            self._emit(DbImported(
                added=sum(report.added.values()),
                updated=sum(report.updated.values()),
                collisions=report.collisions))
            for c in self._store.data["collisions"][-report.collisions:] if report.collisions else []:
                self._emit(DbCollision(db=c["db"], record_id=c["record_id"]))
        else:
            monsters_md = (data_dir / "MONSTERS.MD") if data_dir else None
            self._monster_db = (MonsterDB.from_file(monsters_md)
                                if monsters_md and monsters_md.exists() else MonsterDB([]))
            items_md = (data_dir / "ITEMS.MD") if data_dir else None
            self._item_db = (ItemDB.from_file(items_md)
                             if items_md and items_md.exists() else ItemDB([]))

        self._state = GameState()
        self._navigator = Navigator.from_directory(data_dir) if data_dir else Navigator([])
        self._combat = CombatEngine(
            config=self._config.combat,
            sneak_cmd=self._config.stealth.sneak_cmd if (self._config.stealth.auto_sneak or self._config.stealth.must_sneak) else "",
            must_sneak=self._config.stealth.must_sneak,
        )
        self._spell_engine = SpellEngine(self._config.spells)
        self._engine = DecisionEngine()
        self._safety = SafetyMonitor(self._config.safety)
        from mmud.session import SessionManager
        self._session = SessionManager(self._config.session)
        self._relog_pending = False
        from mmud.automation.scheduler import Scheduler
        self._scheduler = Scheduler(
            self._config.schedule,
            send=self._state.enqueue,
            goto=self.navigate_to_room,
            start_loop=self.start_loop,
            relog=lambda: self.request_relog("scheduled relog"),
            logoff=self._scheduled_logoff,
            variables=self._template_vars,
        )
        self._remote = RemoteCommandHandler(self)
        from mmud.combat.pvp import PvpEngine
        self._pvp = PvpEngine(self._config.pvp, self._config.players, self._safety)
        from mmud.combat.backstab import BackstabEngine
        self._backstab = BackstabEngine(self._config.combat, self._config.stealth)
        from mmud.parser.inventory_parser import InventoryParser
        self._inv_parser = InventoryParser()
        from mmud.automation.items import LootMonitor, GetDecider
        self._loot = LootMonitor(
            is_monster=lambda name: self._monster_db.find(name) is not None)
        self._get_decider = GetDecider(
            self._config.items,
            on_mark=(lambda n: self._store.add_mark("ungettable", n)) if self._store else None)
        from mmud.automation.equip import EquipDecider
        self._equip_decider = EquipDecider(
            self._item_db, enabled=self._config.items.auto_get,
            on_mark=(lambda n: self._store.add_mark("no_auto_equip", n)) if self._store else None)
        if self._store is not None:
            for n in self._store.marks("ungettable"):
                self._get_decider.mark_ungettable(n)
            for n in self._store.marks("no_auto_equip"):
                self._equip_decider.mark_failed(n)
        self._rooms = rooms or {}
        from mmud.automation.travel import TravelDecider
        self._travel = TravelDecider(self._config.items, self._config.stealth,
                                     self._bus or GameEventBus())
        from mmud.automation.doors import DoorMonitor
        self._doors = DoorMonitor(self._config.navigation)
        from mmud.automation.commerce import CommerceEngine
        self._commerce = CommerceEngine(
            self._config.commerce, self._config.items,
            navigate=self.navigate_to_room,
            resume_loop=lambda: self.start_loop(),
            loop_running=lambda: bool(self._loop_runner and self._loop_runner.running),
            travel_active=lambda: self._travel.active,
        )
        from mmud.parser.party_parser import PartyParser
        from mmud.automation.party import PartyDecider, InviteMonitor
        self._party_parser = PartyParser()
        self._invites = InviteMonitor(self._config.players)
        self._party_decider = PartyDecider(self._config.party, self._config.players)
        self._build_engines()
        self._graph = None        # built on first use (corpus parse ~1s)
        self._last_seen_hex = ""
        self._pending_move = ""
        self._loop_runner = None   # set by toggle_loop()
        self._login_handler = LoginHandler(self._config.login)
        self._who_parser = WhoParser()
        self._last_activity = time.monotonic()
        self._auto_started = False
        self._redial_delay_s = 5.0
        self._was_low = False   # edge-detect for health_low stat

    def _build_engines(self) -> None:
        """Register every decider into self._engine in one ordered table.

        All dependencies (self._spell_engine, self._combat, self._backstab,
        self._get_decider, self._equip_decider, self._travel, self._commerce,
        self._party_decider) are constructed in __init__ BEFORE this runs.
        The table is the single source of truth for slot names + priorities;
        DecisionEngine.register sorts by priority, so list order here is just
        for readability. Same names/priorities/instances as before => no
        behavior change.
        """
        from mmud.automation.run_rules import RunDecider
        from mmud.state.inventory import RefreshDecider
        from mmud.automation.search import SearchDecider
        registry: list[tuple[str, object, int]] = [
            ("queue", QueueDecider(), PRIO_QUEUE),
            ("cures", CureDecider(self._config.health), PRIO_CURE),
            ("run", RunDecider(self._config.combat, self._config.navigation), PRIO_FLEE),
            ("backstab", self._backstab, PRIO_BACKSTAB),
            ("spells", self._spell_engine, PRIO_SPELLS),
            ("combat", self._combat, PRIO_COMBAT),
            ("refresh", RefreshDecider(self._config.items.inventory_cmd), PRIO_REFRESH),
            ("equip", self._equip_decider, PRIO_EQUIP),
            ("items", self._get_decider, PRIO_ITEMS),
            ("commerce", self._commerce, PRIO_COMMERCE),
            ("party", self._party_decider, PRIO_PARTY),
            ("travel", self._travel, PRIO_TRAVEL),
            ("search", SearchDecider(self._config.navigation), PRIO_SEARCH),
        ]
        for name, decider, priority in registry:
            self._engine.register(name, decider, priority)

    def _emit(self, event: object) -> None:
        if self._bus is not None:
            self._bus.post(event)

    async def run(self) -> None:
        redials = 0
        while True:
            try:
                await self._run_session()
            except (ConnectionError, OSError) as exc:
                _log.warning("connection lost: %s", exc)
                self._session.on_carrier_lost()
                self._emit(SessionStatUpdated(key="carrier_lost",
                                              value=str(self._session.carrier_lost)))
            if self._relog_pending:
                # deliberate logout-and-return: one fresh session, not a redial
                self._relog_pending = False
                self._login_handler.reset()
                self._safety.reset()
                self._state.abort_task()
                self._session.reset(time.monotonic())
                self._was_low = False   # fresh session: re-arm health_low edge-detect
                continue
            if self._safety.hangup_requested:
                break   # deliberate disconnect — never auto-reconnect past it
            if (not self._config.safety.reconnect
                    or redials >= self._config.safety.max_redials):
                break
            redials += 1
            self._session.on_dial()
            self._emit(SessionStatUpdated(key="dialed",
                                          value=str(self._session.dialed)))
            await asyncio.sleep(self._redial_delay_s)

    async def _run_session(self) -> None:
        await self._conn.connect()
        self._session.on_connect()
        self._emit(SessionStatUpdated(key="connected",
                                      value=str(self._session.connected)))
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
                        self._pending_move = cmd
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
            self._check_session(time.monotonic())
            self._scheduler.tick(time.monotonic())

    def _check_afk(self) -> None:
        cfg = self._config.afk
        if not cfg.enabled or self._state.in_combat:
            return
        idle = time.monotonic() - self._last_activity
        if idle >= cfg.timeout_minutes * 60:
            self._state.enqueue(cfg.reply)
            self._last_activity = time.monotonic()  # reset to avoid spam

    async def _process_line(self, line: str) -> None:
        # Hook pipeline, in order. Each step mutates self._state and/or emits
        # events; ordering matters where a later hook depends on state a prior
        # hook set. After this method, _next_command() decides what to send.
        #
        #  1. session.on_line   raw line captured BEFORE ANSI strip (transcript)
        #  2. emit LineReceived raw line broadcast to the UI/event bus
        #     --- ANSI stripped into `clean`; all hooks below see `clean` ---
        #  3. _parse_vitals     HP/MP -> state, health_low edge, AFK low-HP hangup
        #  4. inv_parser.feed   inventory snapshot; completes a WAITING task
        #  5. _parse_conditions condition onset/recovery; aborts/completes tasks
        #  6. safety.process    panic/hangup triggers on dangerous lines
        #  7. backstab.on_line  feed stealth/backstab state machine
        #  8. combat.on_line    feed combat engine (sneak/attack bookkeeping)
        #  9. commerce.on_line  bank/shop/train dialogue progress
        # 10. party_parser.feed party roster -> state
        # 11. party_decider.on_line  party heal/wait/share bookkeeping
        # 12. invites.check    auto-accept party invites -> enqueue join
        # 13. loot.process     remember dropped loot for the get decider
        # 14. _parse_get_results  GETTING/EQUIPPING task success/failure
        # 15. _parse_room      room detection: resets per-room state, learns exits
        # 16. _parse_exits     exit list -> travel arrival, completes SEARCHING
        # 17. _parse_combat_exit  combat end -> clear monsters, mark inv dirty
        # 18. _parse_combat_stats hit/miss/backstab accounting
        # 19. _handle_doors    open doors when travelling/looping (needs room/exits)
        # 20. _parse_nav_failure  "can't go that way" -> travel/loop failure
        # 21. _parse_conversation tells/says; remote command replies
        # 22. _handle_login    login state machine; auto_start loop on entry
        # 23. _parse_who_and_exp  WHO entries, exp/level, kill counting
        # 24. matcher.match    generic message patterns -> effects / combat flag
        self._session.on_line(line)   # raw capture before any rendering
        # Replay MajorMud's in-line cursor moves so hotkey/redraw artefacts
        # ("nNorth") resolve. Display keeps colour; parsing uses plain text.
        self._emit(LineReceived(line=render_line(line, color=True)))
        clean = visible_text(line).strip()
        self._parse_vitals(clean)
        if inv := self._inv_parser.feed(clean):
            self._state.inventory = inv
            self._state.inventory_dirty = False
            if self._state.task.type is TaskType.WAITING:
                self._state.complete_task()
        self._parse_conditions(clean)
        self._safety.process_line(clean)
        self._backstab.on_line(clean)
        self._combat.on_line(clean)
        self._commerce.on_line(clean)
        self._party_parser.feed(clean, self._state)
        self._party_decider.on_line(clean)
        if join_cmd := self._invites.check(clean):
            self._state.enqueue(join_cmd)
        self._loot.process_line(clean, self._state)
        self._parse_get_results(clean)
        self._parse_room(clean)
        self._parse_exits(clean)
        self._parse_combat_exit(clean)
        self._parse_combat_stats(clean)
        self._handle_doors(clean)
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
            hp = int(m.group(1))
            # Prompts without a max (e.g. "[HP=49 /MA=20 ]") keep the last known
            # max — learned from a previous full prompt or the `stat` line.
            max_hp = int(m.group(2)) if m.group(2) else self._state.max_hp
            self._state.set_hp(hp, max_hp)
            self._emit(HpChanged(hp=hp, max_hp=max_hp))
            is_low = max_hp > 0 and hp / max_hp <= self._config.combat.flee_threshold
            if is_low and not self._was_low:
                self._state.record_health_low()
                self._emit(SessionStatUpdated(key="health_low",
                                              value=str(self._state.health_low)))
            self._was_low = is_low
            if (self._config.afk.enabled and self._config.afk.hangup_on_low_hp
                    and max_hp > 0 and hp / max_hp <= self._config.combat.flee_threshold):
                self._safety.request_hangup(f"low HP while AFK ({hp}/{max_hp})")
        if m := _MP_RE.search(line):
            mp = int(m.group(1))
            max_mp = int(m.group(2)) if m.group(2) else self._state.max_mana
            self._state.set_mana(mp, max_mp)
            self._emit(MpChanged(mp=mp, max_mp=max_mp))
        # `stat` output carries the maxes a current-only prompt omits.
        if m := _STAT_HITS_RE.search(line):
            hp, max_hp = int(m.group(1)), int(m.group(2))
            self._state.set_hp(hp, max_hp)
            self._emit(HpChanged(hp=hp, max_hp=max_hp))
        if m := _STAT_MANA_RE.search(line):
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
            prev_hex = self._state.current_hex
            self._state.set_room(code)
            self._state.monsters_present.clear()
            self._state.players_present = []
            self._state.ground_items.clear()
            self._state.ground_coins.clear()
            self._backstab.reset()
            if self._state.task.type is TaskType.RUNNING:
                self._state.complete_task()
            room = self._rooms.get(code)
            self._last_seen_hex = room.hex_id.upper() if room and room.hex_id else ""
            if self._last_seen_hex:
                self._state.current_hex = self._last_seen_hex
            # Learn the exit a manual move just traversed.
            if (self._store is not None and self._pending_move
                    and self._state.current_hex and prev_hex
                    and prev_hex != self._state.current_hex):
                self._store.add_exit(prev_hex, self._pending_move,
                                     self._state.current_hex)
            self._pending_move = ""
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
                    if rec is None and self._store is not None:
                        self._store.learn_monster(name)
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
            self._session.on_exp(exp, time.monotonic())
            self._emit(SessionStatUpdated(key="exp", value=str(exp)))
        if (lvl := self._who_parser.parse_level_line(line)) is not None:
            self._state.set_level(lvl)
        # Kill detection: "You have slain the X" (already in combat exit)
        if "have slain" in line.lower() or "have killed" in line.lower():
            self._state.add_kill()
            self._emit(SessionStatUpdated(key="kills", value=str(self._state.kills)))

    def _room_graph(self):
        if self._graph is None:
            from mmud.navigation.graph import RoomGraph
            paths = list(self._navigator._paths.values())
            self._graph = RoomGraph.from_paths(paths, self._rooms)
            if self._store is not None:
                self._graph.add_learned(self._store.exits())
        return self._graph

    def _parse_exits(self, line: str) -> None:
        from mmud.parser.exits_parser import parse_exits
        exits = parse_exits(line)
        if exits is None:
            return
        self._state.last_exits = exits
        self._travel.on_arrival(self._state, self._last_seen_hex)
        self._last_seen_hex = ""
        if self._state.task.type is TaskType.SEARCHING:
            self._state.complete_task()

    def _handle_doors(self, line: str) -> None:
        if not (self._travel.active or (self._loop_runner and self._loop_runner.running)):
            return
        door_cmds = self._doors.handle(line, self._pending_move)
        if door_cmds is None:
            return
        for c in door_cmds:
            self._state.enqueue(c)
        if door_cmds:
            self._travel.retry_current()   # re-send the move after opening
        else:
            self._travel.on_move_failed()  # can't open: normal failure path

    def _parse_nav_failure(self, line: str) -> None:
        if _NAV_FAIL_RE.search(line):
            if self._travel.active:
                self._travel.on_move_failed()
            elif self._loop_runner and self._loop_runner.running:
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

    def _parse_get_results(self, line: str) -> None:
        from mmud.automation.items import _CANT_GET_RE
        task = self._state.task.type
        low = line.lower()
        if task is TaskType.GETTING:
            if _CANT_GET_RE.search(line):
                if last := self._state.task.payload.get("item"):
                    self._get_decider.mark_ungettable(last)
                self._state.abort_task()
            elif low.startswith("you took") or low.startswith("you get"):
                self._state.complete_task()
        elif task is TaskType.EQUIPPING:
            if low.startswith("you are now wearing") or low.startswith("you are now wielding") \
                    or low.startswith("you are now holding"):
                self._state.complete_task()
            elif "is cursed" in low or "can't remove" in low or "cannot remove" in low:
                if last := self._state.task.payload.get("item"):
                    self._equip_decider.mark_failed(last)
                self._state.abort_task()

    def _parse_combat_exit(self, line: str) -> None:
        if self._state.in_combat and _COMBAT_EXIT_RE.search(line):
            self._state.set_combat(False)
            self._state.monsters_present.clear()
            self._state.inventory_dirty = True   # loot may have dropped
            self._emit(CombatChanged(in_combat=False))

    def _next_command(self) -> str | None:
        was_running = self._state.task.type is TaskType.RUNNING
        cmd = self._engine.next_command(self._state)
        if not was_running and self._state.task.type is TaskType.RUNNING:
            self._state.record_ran_away()
            self._emit(SessionStatUpdated(key="ran_away",
                                          value=str(self._state.ran_away)))
        return cmd

    def _check_task_timeout(self, now: float) -> None:
        if self._state.task.expired(now):
            task_name = self._state.task.type.name
            self._state.abort_task()
            self._emit(TaskChanged(task_type=task_name, status="timeout"))

    def _check_session(self, now: float) -> None:
        action = self._session.tick(now)
        if action == "hangup":
            self._safety.request_hangup("session limit reached")
        elif action == "relog":
            self.request_relog("exp rate below minimum")

    def _scheduled_logoff(self) -> None:
        self._state.enqueue(self._config.session.logout_cmd)
        self._safety.request_hangup("scheduled logoff")

    def _template_vars(self) -> dict:
        names = self._state.monster_names()
        return {
            "userid": self._config.login.username,
            "pswd": self._config.login.password,
            "target": names[0] if names else "",
            "source": "",   # populated when live testing identifies the source line
            "dmg": str(self._state.combat_dmg_sum),
        }

    def request_relog(self, reason: str) -> None:
        """Log out cleanly and start one fresh session (login from scratch)."""
        if self._relog_pending:
            return
        self._relog_pending = True
        self._state.begin_task(TaskType.RELOGGING, priority=1, timeout_s=30.0,
                               now=time.monotonic())
        self._state.enqueue(self._config.session.logout_cmd)

    def _make_loop_runner(self):
        from mmud.automation.loop_runner import LoopRunner
        paths = list(self._navigator._paths.values())
        return LoopRunner(self._config.navigation, paths, self._rooms, self._travel)

    def toggle_loop(self) -> None:
        if self._loop_runner and self._loop_runner.running:
            self._loop_runner.stop()
            return
        self._loop_runner = self._make_loop_runner()
        self._loop_runner.start()

    def maybe_build_web_server(self):
        """Construct the web control-panel server iff [web] config is enabled.

        Lazy import so the `web` extra (fastapi/uvicorn) is only required when
        the panel is actually on. Idempotent; returns None when disabled.
        """
        if not self._config.web.enabled:
            return None
        if self._web_server is not None:
            return self._web_server
        from mmud.web.server import WebPanelServer
        self._web_server = WebPanelServer(self)
        return self._web_server

    def start_loop(self, name: str = "") -> str:
        """Start a named loop path. Returns status message."""
        if name:
            self._config.navigation.loop_path = name.upper()
        loop_name = self._config.navigation.loop_path
        if not loop_name:
            return "No loop path configured. Use :loop NAME"
        if self._loop_runner and self._loop_runner.running:
            self._loop_runner.stop()
        self._loop_runner = self._make_loop_runner()
        if self._loop_runner._path is None:
            return f"Loop path '{loop_name}' not found in loaded paths"
        self._loop_runner.start()
        return f"Loop started: {loop_name}"

    def stop_all(self) -> str:
        """Stop loop/travel and clear command queue."""
        if self._loop_runner:
            self._loop_runner.stop()
        self._travel.clear()
        while self._state.dequeue() is not None:
            pass
        return "Stopped."

    def navigate_to_room(self, to_code: str) -> str:
        """Multi-hop navigate to a 4-letter room code via the room graph."""
        from mmud.navigation.graph import NavStatus
        dest = self._rooms.get(to_code.upper())
        if dest is None or not dest.hex_id:
            return f"Unknown destination room: {to_code.upper()}"
        src_hex = self._state.current_hex
        if not src_hex and self._state.current_room:
            room = self._rooms.get(self._state.current_room)
            src_hex = room.hex_id.upper() if room and room.hex_id else ""
        if not src_hex:
            return "Current room unknown — move around first to establish position"
        result = self._room_graph().find_path(src_hex, dest.hex_id)
        if result.status is NavStatus.UNKNOWN_START:
            return f"Current room {src_hex} not in the path corpus"
        if result.status is NavStatus.UNKNOWN_DEST:
            return f"Unknown destination room: {to_code.upper()}"
        if result.status is NavStatus.NO_PATH:
            return f"No known route to {to_code.upper()}"
        while self._state.dequeue() is not None:
            pass
        self._travel.set_route(result.steps)
        return f"Navigating to {to_code.upper()} ({len(result.steps)} steps)"

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
