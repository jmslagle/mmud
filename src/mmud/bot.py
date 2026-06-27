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
    RawOutput, ScreenUpdated,
)
from mmud.automation.decision import (
    DecisionEngine, QueueDecider, PRIO_QUEUE, PRIO_EMERGENCY, PRIO_CURE, PRIO_FLEE,
    PRIO_SPELLS, PRIO_COMBAT,
    PRIO_BACKSTAB, PRIO_REFRESH, PRIO_ITEMS, PRIO_EQUIP, PRIO_TRAVEL, PRIO_SEARCH,
    PRIO_COMMERCE, PRIO_PARTY, PRIO_LOOK,
)
from mmud.state.tasks import TaskType
from mmud.automation.cures import CureDecider
from mmud.automation.commerce import deposit_copper
from mmud.automation.safety import SafetyMonitor
from mmud.automation.remote import RemoteCommandHandler
from mmud.state.conditions import scan_onset, scan_recovery
from mmud.parser.who_parser import WhoParser
from mmud.parser.conversation_parser import ConversationParser
from mmud.net.connection import MudConnection
from mmud.terminal import TerminalEmulator
from mmud.parser.matcher import PatternMatcher
from mmud.parser.room_parser import RoomParser
from mmud.parser.ansi import render_line, visible_text, line_fg
from mmud.state.game_state import GameState, MonsterSighting
from mmud.navigation.navigator import Navigator
from mmud.combat.combat import CombatEngine, select_attack_target
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
_STAT_MANA_RE = re.compile(r"\bMana(?:/Kai)?:\s*(\d+)/(\d+)")
# Line rendering (cursor replay + colour) lives in mmud.parser.ansi.
# Authoritative combat-state markers (megamud.exe: *Combat Engaged* 0x4b78ac,
# *Combat Off* 0x4b789c, " breaks off combat" 0x4b77f4). *Combat Off* fires
# between rounds mid-fight, so it only toggles the flag — it does NOT clear the
# roster (combat_event_parse @ 0x004176b0).
IDLE_REFRESH_S = 10.0   # idle keepalive: bare Enter every 10s (MegaMud parity)
STALL_TIMEOUT_S = 35.0  # in-game RX silence past this => dead/half-open socket.
                        # Idle refresh (10s) always draws a prompt from a live
                        # server, so ~3 missed prompts means the connection died.
_COMBAT_ENGAGED_RE = re.compile(r"\*Combat Engaged\*", re.IGNORECASE)
_COMBAT_OFF_RE = re.compile(r"\*Combat Off\*|breaks off combat", re.IGNORECASE)
_NAV_FAIL_RE = re.compile(
    # Genuine "can't move that way" replies. NOT "closed"/"locked" — those are
    # door/gate obstacles owned by DoorMonitor (_handle_doors); treating them as
    # nav failures hijacked the move into lost-recovery before we could open/bash.
    r"(?:you can'?t go that way|alas|there is no exit|"
    r"you cannot go that direction|no exit)",
    re.IGNORECASE,
)
# Melee hit: optional adverb (e.g. "critically") before the verb, then "... for N damage".
_PLAYER_HIT_RE = re.compile(
    r"You (?:\w+ )?(?:hit|strike|slash|slice|cut|pierce|bash|smash|backstab|stab|"
    r"crush|maul|cleave|chop|kick|punch)\w* .+? for (\d+) damage", re.IGNORECASE)
# Spell/cast damage: "You fire a magic missile at X for 18 damage!".
_CAST_HIT_RE = re.compile(
    r"You (?:fire|cast|blast|hurl|invoke|channel|conjure|sear|scorch|zap|smite|"
    r"electrocute|incinerate) .+? for (\d+) damage", re.IGNORECASE)
_PLAYER_MISS_RE = re.compile(r"You miss\b", re.IGNORECASE)
# Damage taken (the "Round" range): "The cave worm chomps you for 8 damage!".
_MONSTER_HIT_RE = re.compile(
    r"\w+ you(?: with [\w' ]+)? for (\d+) damage", re.IGNORECASE)
# A round where the monster missed = a dodge (drives Dodge%).
_DODGE_RE = re.compile(r"misses you|miss you\b|You (?:dodge|parry|evade|sidestep)", re.IGNORECASE)
# Who is attacking us: "The <monster> <attack-verb> ... you". Article-prefixed (players
# attack without one). The attacker name (group 1) is added to the roster as a safety
# net so we fight back even if its arrival was missed/cleared and we'd otherwise rest.
_ATTACKER_RE = re.compile(
    r"^(?:A|An|The)\s+(.+?)\s+(?:snaps?|lunges?|claws?|bites?|chomps?|hits?|swings?|"
    r"gores?|mauls?|strikes?|slashes?|tears?|rips?|pounds?|attacks?|stabs?|smashes?|"
    r"slams?|crushes?|kicks?|punches?|spits?|breathes?|blasts?|shoots?|gnaws?|"
    r"thrusts?|jabs?|hacks?|chops?|lashes?)\b.*\byou\b", re.IGNORECASE)
_BACKSTAB_RE = re.compile(r"\bbackstab", re.IGNORECASE)
_CRIT_RE = re.compile(r"critical|devastat|annihilat|massacre|demolish|savage", re.IGNORECASE)
_SNEAK_OK_RE = re.compile(r"move silently|begin to sneak", re.IGNORECASE)
_SNEAK_FAIL_RE = re.compile(r"fail to sneak|make a noise", re.IGNORECASE)

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
        self._terminal = TerminalEmulator()
        self._conn.on_raw = self._feed_raw
        self._config = config or MudConfig()

        if patterns is None and data_dir is not None:
            patterns = load_messages(data_dir / "MESSAGES.MD")
        self._matcher = PatternMatcher(patterns or [])

        if rooms is None and data_dir is not None:
            rooms = load_rooms(data_dir / "ROOMS.MD")
        self._room_parser = RoomParser(rooms or {})
        self._convo_parser = ConversationParser()
        from mmud.parser.player_parser import PlayerExamineParser
        self._examine_parser = PlayerExamineParser()
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
        if self._config.learning.enabled:
            # The store powers live learning (players, exits) and is useful even
            # without the bundled MD files; import_md only runs when data_dir is set.
            from mmud.data.store import GameStore, import_md
            self._store = GameStore(pathlib.Path(self._config.learning.store_path))
        if self._store is not None and data_dir is not None:
            from mmud.data.store import import_md
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
        from mmud.data.classes_races import ClassRaceDB
        # id->name for resolving PLAYERS.MD class_id/race_id (race 7=Dark-Elf,
        # class 10=Gypsy) on spy records.
        self._class_race = ClassRaceDB.from_dir(data_dir)
        # Bundled .MP paths plus optional user dirs of custom paths. extra_paths_dir is
        # a comma-separated list of dirs, loaded in order AFTER the bundled ones, so a
        # later dir's path for the same from->to overrides an earlier one (and new
        # files add new routes). Lets users fix/extend routing without touching the corpus.
        path_dirs = [d for d in (data_dir,) if d]
        path_dirs += [pathlib.Path(d.strip())
                      for d in self._config.navigation.extra_paths_dir.split(",")
                      if d.strip()]
        self._navigator = Navigator.from_directories(path_dirs)
        self._combat = CombatEngine(
            config=self._config.combat,
            sneak_cmd="sneak" if (self._config.stealth.auto_sneak or self._config.stealth.must_sneak) else "",
            must_sneak=self._config.stealth.must_sneak,
        )
        self._spell_engine = SpellEngine(
            self._config.spells,
            monster_priority=self._config.combat.monster_priority,
            attack_order=self._config.combat.attack_order,
            attack_neutral=self._config.combat.attack_neutral,
            mana_attack_pct=self._config.combat.mana_attack_pct,
            bless_durations=self._spell_durations(),
        )
        self._engine = DecisionEngine()
        self._safety = SafetyMonitor(self._config.safety)
        from mmud.session import SessionManager
        self._session = SessionManager(self._config.session)
        from mmud.debug_log import SessionLogger
        self._session_log = SessionLogger(self._config.session.debug_log)
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
            self._item_db,
            enabled=self._config.items.auto_get or bool(self._config.items.equip_items),
            only_items=self._config.items.equip_items,
            on_mark=(lambda n: self._store.add_mark("no_auto_equip", n)) if self._store else None)
        if self._store is not None:
            for n in self._store.marks("ungettable"):
                self._get_decider.mark_ungettable(n)
            for n in self._store.marks("no_auto_equip"):
                self._equip_decider.mark_failed(n)
        self._rooms = rooms or {}
        from mmud.automation.travel import TravelDecider
        self._travel = TravelDecider(self._config.items, self._config.stealth,
                                     self._bus or GameEventBus(), self._config.combat)
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
        from mmud.automation.players import PlayerLookDecider
        self._player_look = PlayerLookDecider(self._config.pvp, self._config.players)
        self._build_engines()
        self._graph = None        # built on first use (corpus parse ~1s)
        self._last_seen_hex = ""
        self._room_block: list[tuple[str, str]] = []   # (display line, fg colour)
        self._title_color = ""             # learned room-title fg colour (one-id hash)
        self._wait_reason = ""             # current intentional-wait status (UI)
        self._objective = ""               # macro status (Looping/Traveling/...)
        self._objective_phase = ""         # objective minus the step, for log throttle
        self._travel_dest = ""             # "FROM->TO" for an active goto
        self._relocate_from = ""           # last hex we re-pathed from (anti-thrash)
        self._pending_move = ""
        self._ready = False          # MegaMud's turn-boundary READY bit: act only at the
                                     # bare "[HP=]:" prompt (set in _process_line), in-game
        self._combat_enabled = True  # MegaMud-style auto-combat toggle ("run" = off)
        self._last_prompt_cmd = ""   # command the server echoed in its last "[HP=]:x"
                                     # prompt — tells us which move a nav-failure is for
        self._last_refresh = 0.0   # last idle-refresh (bare Enter) send
        # True once an "Also here:" line is parsed in the current room display;
        # checked at the "Obvious exits:" terminator to clear a monster-free room.
        self._also_here_seen = False
        # Buffer for a word-wrapped "Also here:" list (server hard-wraps long
        # lines); stitched with the continuation line before parsing.
        self._also_here_pending = ""
        self._stat_requested = False   # send `stat` once per session to learn maxes
        self._in_who = False           # inside a "Current Adventurers" WHO block
        self._who_next = 0.0           # monotonic time of the next periodic `who`
        self._loop_runner = None   # set by toggle_loop()
        self._login_handler = LoginHandler(self._config.login)
        self._who_parser = WhoParser()
        self._last_activity = time.monotonic()
        self._last_rx = time.monotonic()   # last time the server sent us anything
        self._stalled = False              # one-shot guard for the stall watchdog
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
        from mmud.combat.combat import EmergencyDecider
        registry: list[tuple[str, object, int]] = [
            ("queue", QueueDecider(), PRIO_QUEUE),
            # Critical-HP escape: fires even in "run" mode (NOT in the combat-toggle's
            # disabled slots), above everything else.
            ("emergency", EmergencyDecider(self._config.combat), PRIO_EMERGENCY),
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
            ("look", self._player_look, PRIO_LOOK),
            ("travel", self._travel, PRIO_TRAVEL),
            ("search", SearchDecider(self._config.navigation), PRIO_SEARCH),
        ]
        for name, decider, priority in registry:
            self._engine.register(name, decider, priority)

    def _emit(self, event: object) -> None:
        if self._bus is not None:
            self._bus.post(event)

    _DSR_REQUEST = "\x1b[6n"   # Device Status Report: "report cursor position"

    def _dsr_reply(self, data: str) -> str | None:
        """If the server probed our screen size (ESC[6n — usually right after homing
        the cursor to a huge position so it clamps to the grid corner), build the
        cursor-position report ESC[row;colR from the emulator's clamped cursor —
        exactly as MegaMud does (ansi_cursor_pos_report @0x40eb10). This is how the
        full-screen editor learns our real size; without a reply the server assumes
        a default and the editor is laid out off by a line. Cursor is 1-based in
        the report (pyte gives 0-based)."""
        if self._DSR_REQUEST not in data:
            return None
        x, y = self._terminal.cursor()
        return f"\x1b[{y + 1};{x + 1}R"

    def set_terminal_size(self, cols: int, rows: int) -> None:
        """Resize the display grid (to the TUI pane) and report it to the server via
        NAWS, so the full-screen editor formats for our actual screen size."""
        self._terminal.resize(rows, cols)
        if self._conn is not None:
            self._conn.set_size(cols, rows)

    def _feed_raw(self, data: str) -> None:
        """Connection raw-stream tap: drive the terminal emulator (DISPLAY) and
        broadcast the raw chunk to xterm.js. Independent of _process_line, which
        keeps driving SEMANTICS (events/stats/automation) from framed lines.
        """
        self._terminal.feed(data)
        reply = self._dsr_reply(data)   # answer the server's screen-size probe
        if reply is not None:
            self._session_log.event(f"screen-size probe (DSR) -> {reply[2:-1]}")
            try:
                asyncio.create_task(self._conn.send_raw(reply))
            except RuntimeError:
                pass   # no running loop (non-async test / standalone feed)
        self._emit(RawOutput(data=data))
        self._emit(ScreenUpdated())

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
        self._conn.set_size(self._terminal.columns, self._terminal.lines)  # arm NAWS
        self._last_rx = time.monotonic()   # fresh heartbeat; arm the stall watchdog
        self._stalled = False
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
                # MegaMud decides ONCE per turn, gated on the bare-prompt READY bit
                # (network_receive_dispatch @0x45d520 → game_ai_do_something @0x402b20),
                # NOT per line — that coupling caused the double-move / dead-target cast /
                # sneak-spam class. In-game we act only at the prompt; the command QUEUE
                # (login responses, door/loot/user) still drains immediately. Pre-game
                # (login) we respond to every line as before (READY only exists in-game).
                in_game = self._login_handler.in_game
                may_act = (not in_game) or self._ready or bool(self._state._command_queue)
                cmd = self._next_command() if may_act else None
                if cmd:
                    self._session_log.tx(cmd)
                    await self._conn.send(cmd)
                    self._last_activity = time.monotonic()
                    if cmd in ("n", "s", "e", "w", "ne", "nw", "se", "sw", "u", "d"):
                        self._state.move_history.append(cmd)
                        self._pending_move = cmd
        finally:
            ticker_task.cancel()
            await self._conn.close()
            self._session_log.close()

    async def _ticker(self) -> None:
        """1Hz background tick: advances spell cooldowns and checks AFK."""
        while True:
            await asyncio.sleep(1.0)
            self._spell_engine.tick()
            self._check_afk()
            self._check_task_timeout(time.monotonic())
            self._check_session(time.monotonic())
            self._scheduler.tick(time.monotonic())
            self._flush_stats()
            await self._maybe_idle_refresh()
            await self._check_stall(time.monotonic())

    def _flush_stats(self) -> None:
        """Emit the full MegaMud stat set for the Player/Session panes. Runs at
        1Hz so derived/computed values (accuracy ranges, sneak/dodge %, exp rate,
        comms, visitors) stay live without per-line event spam."""
        s, sess = self._state, self._session
        now = time.monotonic()
        acc = s.combat_accuracy()
        out: dict[str, str] = {
            "miss_pct": f"{acc['miss_pct']:.0f}%",
            "sneak_pct": f"{s.sneak_pct:.0f}%",
            "dodge_pct": f"{s.dodge_pct:.0f}%",
            "exp_rate": f"{sess.exp_rate_per_hour()/1000:.0f} k/hr",
            "had_to_run": str(s.ran_away),
            "health_low": str(s.health_low),
            "people_seen": str(sess.people_seen),
            "attacked": str(sess.attacked),
            "dialed": str(sess.dialed),
            "failed": str(sess.dial_failed),
            "connected": str(sess.connected),
            "lost_carrier": str(sess.carrier_lost),
            "deposited": str(sess.deposited),
            "income_rate": f"{sess.income_rate_per_hour(now):.0f}/hr",
        }
        for kind in ("hit", "extra", "crit", "backstab", "cast"):
            row = acc[kind]
            out[f"{kind}_pct"] = f"{row['pct']:.0f}%"
            out[f"{kind}_range"] = row["range"]
            out[f"{kind}_avg"] = str(row["avg"])
        out["round_range"] = acc["round"]["range"]
        out["round_avg"] = str(acc["round"]["avg"])
        if s.exp_needed:
            eta = sess.time_to_level_hours(s.exp_needed)
            out["will_level_in"] = f"{eta:.1f} hr" if eta > 0 else "?"
        for key, value in out.items():
            self._emit(SessionStatUpdated(key=key, value=value))

    async def _maybe_idle_refresh(self) -> None:
        """MegaMud's 10-second room refresh (ai_room_refresh_trigger @ 0x00407e1a):
        when idle in-game it sends a bare Enter so the server re-prints the
        prompt/room and the bot re-syncs (sees wandered-in monsters, gets a fresh
        prompt to act on, recovers from a stalled combat). Our decision loop only
        fires on an incoming line, so without this the bot stalls when the server
        goes quiet. Throttled separately from _last_activity so it doesn't mask
        the AFK timer."""
        if not self._login_handler.in_game:
            return
        now = time.monotonic()
        if (now - self._last_activity >= IDLE_REFRESH_S
                and now - self._last_refresh >= IDLE_REFRESH_S):
            self._last_refresh = now
            self._session_log.tx("(idle refresh)")
            await self._conn.send("")   # bare Enter (\r) — re-print prompt/room
        # Periodic WHO to keep the Players tab fresh as people log in/out.
        iv = self._config.session.who_interval_s
        if iv > 0 and self._stat_requested and now >= self._who_next:
            self._who_next = now + iv
            self._state.enqueue("who")

    async def _check_stall(self, now: float) -> None:
        """Watchdog for a dead/half-open connection. In-game we send an idle
        refresh every 10s and a live server always answers (at least a prompt),
        so prolonged RX silence means the socket died with no TCP RST — the read
        loop would otherwise await forever and the bot looks hung (must be killed).
        Force-close so readlines() ends and run() takes the carrier-loss path
        (redial if configured, else a clean stop instead of an infinite hang)."""
        if self._stalled or not self._login_handler.in_game:
            return
        if now - self._last_rx < STALL_TIMEOUT_S:
            return
        self._stalled = True
        self._session_log.event(
            f"connection stalled: no server data for {now - self._last_rx:.0f}s "
            f"-> closing")
        self._session.on_carrier_lost()
        self._emit(SessionStatUpdated(key="carrier_lost",
                                      value=str(self._session.carrier_lost)))
        await self._conn.close()   # -> readlines() ends -> run() handles recovery

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
        # 15. _parse_room      room detection + roster (Also-here REPLACE / arrival append)
        # 16. _parse_exits     exits -> travel arrival; clears roster for empty rooms
        # 17. _parse_combat_state  *Combat Engaged*/*Combat Off* -> in_combat (no roster clear)
        # 17b. _parse_monster_removal  named death / slay / "you do not see" -> drop monster
        # 18. _parse_combat_stats hit/miss/backstab accounting
        # 19. _handle_doors    open doors when travelling/looping (needs room/exits)
        # 20. _parse_nav_failure  "can't go that way" -> travel/loop failure
        # 21. _parse_conversation tells/says; remote command replies
        # 22. _handle_login    login state machine; auto_start loop on entry
        # 23. _parse_who_and_exp  WHO entries, exp/level, kill counting
        # 24. matcher.match    generic message patterns -> effects / combat flag
        self._last_rx = time.monotonic()   # heartbeat for the stall watchdog
        self._session.on_line(line)   # raw capture before any rendering
        # Replay MajorMud's in-line cursor moves so hotkey/redraw artefacts
        # ("nNorth") resolve. Display keeps colour; parsing uses plain text.
        self._emit(LineReceived(line=render_line(line, color=True)))
        clean = visible_text(line).strip()
        if clean:
            self._session_log.rx(clean)
        # Stitch a word-wrapped "Also here:" list. The server hard-wraps long
        # lines (~79 cols), so a crowded room's monster list arrives split across
        # lines; MegaMud buffers the incomplete also-here and appends the next
        # line (responses-ref §2.3). Without this the list is dropped -> the bot
        # never sees those monsters (combat misses).
        if self._also_here_pending:
            clean = self._also_here_pending + " " + clean
            self._also_here_pending = ""
        if clean.lower().startswith("also here:") and not clean.endswith("."):
            self._also_here_pending = clean
            return
        # WHO block -> Players tab. Consume block lines so they aren't misparsed.
        if self._parse_who(clean):
            return
        # Accumulate display lines so _parse_exits can recover the room title for
        # MegaMud's room-hash lookup. The prompt ("[HP=..]:") is a turn boundary:
        # reset there so the block holds ONLY the current room display (title +
        # items + also-here), not 30 lines of combat/loot/async history — that
        # history produced ~27 garbage candidate hashes that caused false route and
        # wander matches. (Also reset at the exits line that closes the block.)
        # READY = MegaMud's turn boundary (gs+0x53F4 bit0, network_receive_dispatch
        # @0x45d520): we act ONLY at the bare "[HP=...]:" prompt, never mid-stream. Set
        # below for a bare/(Resting) prompt; cleared on every other line.
        self._ready = False
        if clean:
            if "[hp=" in clean.lower():
                self._room_block = []
                # The server echoes the command it just processed after the prompt's
                # "]:". Remember it so a stale nav-failure (the result of a SUPERSEDED
                # move still draining) can be told apart from our current move's — else
                # we'd clear the route and fire a second move on top of the in-flight
                # one (the live double-move). Empty echo (bare prompt) -> leave as-is.
                idx = clean.rfind("]:")
                if idx != -1:
                    after = clean[idx + 2:].strip()
                    self._last_prompt_cmd = after.lower()
                    # Bare prompt (nothing after "]:") OR a "(Resting)"-type status line
                    # = the turn boundary. A command echo ("]:fjet orc") is NOT ready.
                    self._ready = (after == "" or after.startswith("("))
            else:
                # Keep each line's foreground colour so we can pick out the room TITLE
                # by colour (MegaMud identifies it by its display attribute) and hash
                # just that one line instead of the whole block.
                self._room_block.append((clean, line_fg(line)))
                if len(self._room_block) > 30:
                    self._room_block = self._room_block[-30:]
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
        self._spell_engine.on_line(clean)   # buff fade detection -> recast bless
        self._commerce.on_line(clean)
        if (dep := deposit_copper(clean)) is not None:   # live "Deposited" stat
            self._session.on_deposit(dep)
        self._party_parser.feed(clean, self._state)
        self._party_decider.on_line(clean)
        if join_cmd := self._invites.check(clean):
            self._state.enqueue(join_cmd)
        self._loot.process_line(clean, self._state)
        self._parse_get_results(clean)
        self._parse_room(clean)
        self._parse_players(clean)
        self._parse_exits(clean)
        self._parse_combat_state(clean)
        self._parse_monster_removal(clean)
        self._engage_attacker(clean)
        self._parse_combat_stats(clean)
        self._handle_doors(clean)
        self._parse_nav_failure(clean)
        self._parse_conversation(clean)
        self._handle_login(clean)
        self._parse_who_and_exp(clean)
        result = self._matcher.match(clean)
        if result:
            self._state.apply_match(result)
            # NOTE: effect apply/remove only. Combat state is driven by the
            # authoritative *Combat Engaged*/*Combat Off* markers in
            # _parse_combat_state — NOT by any MESSAGES.MD apply-match (which fired
            # for buffs/effects and falsely flagged combat).
            if result.is_apply:
                self._emit(EffectApplied(name=result.pattern.name, flags=result.pattern.flags))
            else:
                self._emit(EffectRemoved(name=result.pattern.name))

    def _parse_vitals(self, line: str) -> None:
        if m := _HP_RE.search(line):
            hp = int(m.group(1))
            # The in-game "[HP=...]" prompt is the reliable "we're in the game"
            # signal (the BBS who-list/pager never shows it). Learn max HP/MA by
            # sending `stat` once here — gating on the login flag sent it too early
            # (during the pager), so max stayed 0 and thresholds never fired.
            if not self._stat_requested:
                self._stat_requested = True
                self._state.enqueue("stat")
                self._state.enqueue("who")   # populate the Players tab on login
                self._who_next = time.monotonic() + self._config.session.who_interval_s
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

    def _build_sighting(self, name: str, count: int) -> MonsterSighting:
        rec = self._monster_db.find(name)
        if rec is None and self._store is not None:
            self._store.learn_monster(name)
        return MonsterSighting(
            name=name, count=count,
            exp_each=rec.exp_value if rec else 0,
            record_id=rec.record_id if rec else -1,
            # MONSTERS.MD kill-type tier (the combat_rating field @ disk 0x25);
            # gates whether the bot will initiate an attack. 0 if unknown.
            kill_type=rec.combat_rating if rec else 0,
        )

    def _parse_room(self, line: str) -> None:
        if code := self._room_parser.detect_room(line):
            prev = self._state.current_room
            prev_hex = self._state.current_hex
            self._state.set_room(code)
            self._state.monsters_present.clear()
            self._also_here_seen = False   # new room display starting
            self._also_here_pending = ""
            self._state.players_present = []
            self._state.ground_items.clear()
            self._state.ground_coins.clear()
            self._backstab.reset()
            self._doors.reset()   # new room: forget door open/bash attempt counts
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
                built = [self._build_sighting(name, count) for name, count in sightings]
                # "Also here:" is the authoritative room roster -> REPLACE (drops
                # stale monsters, like MegaMud's room_entity_classify_all). An
                # arrival ("A rat creeps in") / "X is here" -> append-if-absent.
                if line.lower().startswith("also here:"):
                    self._state.replace_monsters(built)
                    self._also_here_seen = True
                else:
                    for s in built:
                        self._state.add_monster(s)
                    # A wander-in occupies the room: mark it seen so the next exits line
                    # doesn't clear the just-arrived monster as an "empty room".
                    self._also_here_seen = True
                self._session_log.event(
                    "monsters=" + repr([(m.name, getattr(m, "kill_type", 0))
                                        for m in self._state.monsters_present]))
                self._emit(MonstersSeen(monsters=[n for n, _ in sightings]))
            players = self._room_parser.extract_players(line)
            if players:
                # A proper-named entry that's a catalogued monster is an NPC, not a
                # player (mirrors room_entity_classify_all's monster-DB lookup).
                # Track it as a non-attackable sighting; never look/spy it.
                real = []
                for name in players:
                    if self._monster_db.find(name) is not None:
                        self._state.add_monster(self._build_sighting(name, 1))
                    else:
                        real.append(name)
                self._state.players_present = real
                for name in real:
                    self._note_player_seen(name)
                if real and (cmd := self._pvp.check(self._state)):
                    self._state.enqueue(cmd)

    def _note_player_seen(self, name: str, **fields) -> None:
        """Tally a unique visitor and persist to the spy store (merges who-list +
        examine fields)."""
        self._session.on_player_seen(name)
        self._emit(SessionStatUpdated(key="people_seen",
                                      value=str(self._session.people_seen)))
        if self._store is not None:
            self._store.learn_player(name, **fields)

    def _parse_players(self, line: str) -> None:
        from mmud.parser.player_parser import (
            parse_arrival, parse_departure, parse_looking_at)
        # Examine result ("[ Name ]" + "is a <race> <class>") -> learn + finish look.
        if rec := self._examine_parser.feed(line):
            # race/class persist to the spy store + snapshot; don't emit PlayerSeen
            # here (it would clobber the who-list level/rep/gang in Online Players).
            self._note_player_seen(rec["name"], race=rec["race"], **{"class": rec["class"]})
            self._player_look.mark_looked(rec["name"])
            if self._state.task.type is TaskType.LOOKING:
                self._state.complete_task()
            return
        if name := parse_arrival(line):
            if name not in self._state.players_present:
                self._state.players_present.append(name)
            self._note_player_seen(name)
            if cmd := self._pvp.check(self._state):
                self._state.enqueue(cmd)
        elif name := parse_departure(line):
            if name in self._state.players_present:
                self._state.players_present.remove(name)
        elif name := parse_looking_at(line):
            self._session.on_attacked()
            self._emit(SessionStatUpdated(key="attacked",
                                          value=str(self._session.attacked)))

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
            # (max HP/MA is learned via `stat`, triggered on the first in-game
            # "[HP=...]" prompt in _parse_vitals — not here, which fires too early.)
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

    def _parse_who(self, line: str) -> bool:
        """WHO block ("Current Adventurers" / "===" then "[Align ]Name - Title").
        Returns True if the line was consumed as part of the block. Gated by state
        so stray '  -  ' lines elsewhere aren't misread as players."""
        if "Current Adventurers" in line:
            self._in_who = True
            return True
        if not self._in_who:
            return False
        stripped = line.strip()
        if not stripped or set(stripped) <= set("=-"):
            return True   # header underline / blank: stay in the block
        entry = self._who_parser.parse_line(line)
        if entry is None:
            self._in_who = False   # block ended (prompt or other text)
            return False
        self._note_player_seen(entry.name, alignment=entry.alignment, title=entry.title)
        self._emit(PlayerSeen(name=entry.name, alignment=entry.alignment,
                              title=entry.title))
        return True

    def _parse_who_and_exp(self, line: str) -> None:
        # A maxed character that gets no XP still KILLED the monster: MegaMud
        # (combat_event_parse @0x4176b0) runs the same kill epilogue on "You have
        # progressed too far without training". Count the kill + remove the target.
        if "progressed too far without training" in line.lower():
            self._state.add_kill()
            self._emit(SessionStatUpdated(key="kills", value=str(self._state.kills)))
            target = select_attack_target(
                self._state,
                [p.lower() for p in self._config.combat.monster_priority],
                self._config.combat.attack_order,
                self._config.combat.attack_neutral)
            if target and self._state.remove_monster(target):
                self._on_monster_killed(f"killed {target} (maxed)")
            else:
                self._on_monster_killed("kill (maxed)")
            return
        # Per-kill experience: "You gain N experience." This is MegaMud's kill
        # signal (combat_event_parse @ 0x004176b0): accumulate the delta, count
        # the kill, and remove the monster we were fighting (the current target,
        # by position — slot 0 == select_target's pick). The named death/slay
        # lines in _parse_monster_removal handle the by-name cases.
        if (gain := self._who_parser.parse_exp_gain_line(line)) is not None:
            self._session.on_exp_gain(gain, time.monotonic())
            self._state.add_kill()
            self._emit(SessionStatUpdated(key="kills", value=str(self._state.kills)))
            self._emit(SessionStatUpdated(key="exp_gained",
                                          value=str(self._session.exp_gained)))
            # Live exp/level progress from the kill (baseline from the login `stat`),
            # so the Experience pane ticks without re-issuing `exp`/`stat`.
            self._state.set_exp(self._state.exp + gain)
            self._emit(SessionStatUpdated(key="exp", value=str(self._state.exp)))
            if self._state.exp_needed > 0:
                need = max(0, self._state.exp_needed - gain)
                self._state.set_exp_needed(need)
                self._emit(SessionStatUpdated(key="exp_needed", value=str(need)))
                eta = self._session.time_to_level_hours(need)
                self._emit(SessionStatUpdated(
                    key="will_level_in",
                    value=(f"{eta:.1f} hr" if eta > 0 else "?")))
            target = select_attack_target(
                self._state,
                [p.lower() for p in self._config.combat.monster_priority],
                self._config.combat.attack_order,
                self._config.combat.attack_neutral)
            if target and self._state.remove_monster(target):
                self._on_monster_killed(f"killed {target}")
            else:
                self._on_monster_killed("kill")
            return
        # The in-game `exp` command prints all of these on ONE line:
        #   "Exp: 11801 Level: 4 Exp needed for next level: 6349 ...".
        # Parse each independently (no early return) so the absolute Exp and Level
        # aren't swallowed by the exp-needed match.
        if (exp := self._who_parser.parse_exp_line(line)) is not None:
            self._state.set_exp(exp)
            self._emit(SessionStatUpdated(key="exp", value=str(exp)))
        if (need := self._who_parser.parse_exp_needed_line(line)) is not None:
            self._state.set_exp_needed(need)
            self._emit(SessionStatUpdated(key="exp_needed", value=str(need)))
            eta = self._session.time_to_level_hours(need)
            self._emit(SessionStatUpdated(
                key="will_level_in",
                value=(f"{eta:.1f} hr" if eta > 0 else "?")))
        if (lvl := self._who_parser.parse_level_line(line)) is not None:
            if lvl > self._state.level:
                self._stat_requested = False   # leveled up -> re-stat to learn new max
            self._state.set_level(lvl)

    def _room_graph(self):
        if self._graph is None:
            from mmud.navigation.graph import RoomGraph
            paths = list(self._navigator._paths.values())
            self._graph = RoomGraph.from_paths(paths, self._rooms)
            if self._store is not None:
                self._graph.add_learned(self._store.exits())
        return self._graph

    def _parse_exits(self, line: str) -> None:
        from mmud.parser.exits_parser import parse_exits, room_id
        exits = parse_exits(line)
        if exits is None:
            return
        # Resolve the room by MegaMud's room hash (title x exits). The COMPUTED hash
        # of each display line is what the .MP corpus records, so we hash every block
        # line and let travel match the set against the route (works even for rooms
        # absent from ROOMS.MD). detect_room_from_block additionally names the room
        # (ROOMS.MD) for the UI/position. The block is consumed here.
        block = self._room_block          # list[(clean_text, fg_colour)]
        self._room_block = []
        clean_lines = [c for c, _ in block]
        code = self._room_parser.detect_room_from_block(clean_lines, line)
        confident_hex = ""   # hex of a NAME-DETECTED ROOMS.MD room (high confidence)
        if code:
            room = self._rooms.get(code)
            if room and room.hex_id:
                self._state.current_hex = room.hex_id.upper()
                confident_hex = room.hex_id.upper()
            if code != self._state.current_room:
                self._state.set_room(code)
                self._emit(RoomChanged(code=code, name=(room.name if room else code)))
        # Auto-learn the room-TITLE colour from a confidently name-detected room (the
        # line whose hash IS the detected room's id is the title), then prefer the
        # single title-coloured id — MegaMud uses ONE id per room (title x exits), not
        # the whole block. Falls back to the (prompt-trimmed) block set until learned
        # or if no title-coloured line is present.
        if confident_hex:
            for c, col in block:
                if col and room_id(c, line) == confident_hex:
                    self._title_color = col
                    break
        seen_hexes = set()
        if self._title_color:
            seen_hexes = {h for c, col in block
                          if col == self._title_color and (h := room_id(c, line))}
        if not seen_hexes:
            seen_hexes = {h for c, _ in block if (h := room_id(c, line))}
        # Remember the current room's candidate hashes so travel can recognise a
        # departure-room re-display even when current_hex is stale/wrong.
        self._state.last_room_hexes = seen_hexes
        # Keep position fresh by ROOM HASH even when the room isn't in ROOMS.MD (most
        # live "Realm of Legends" rooms aren't, so confident_hex stays empty). When
        # IDLE (not actively traveling — travel.on_arrival owns current_hex while a
        # route runs) and the display resolves to a single id, commit it. Otherwise a
        # manual move through an un-named room leaves current_hex stale and a loop
        # RESTART can't tell we're standing on the loop. (MegaMud: one id per room.)
        if not confident_hex and not self._travel.active and len(seen_hexes) == 1:
            self._state.current_hex = next(iter(seen_hexes))
        # "Obvious exits:" terminates a room display. If this display showed no
        # "Also here:", the room has no monsters -> clear the roster (handles
        # rooms missing from ROOMS.MD, where name-detection can't fire).
        if not self._also_here_seen and self._state.monsters_present:
            self._state.replace_monsters([])
            self._session_log.event("monsters=[] (empty room)")
        self._also_here_seen = False
        self._state.last_exits = exits
        if self._travel.active:
            self._session_log.event(
                f"arrive room={code or '?'} hex={self._state.current_hex or '?'} "
                f"seen={sorted(seen_hexes)}")
        self._travel.on_arrival(self._state, seen_hexes, confident_hex=confident_hex)
        # Surface where we are for the status panel: code+name when ROOMS.MD-known, else
        # the raw room hash (most live rooms aren't in ROOMS.MD).
        loc = ""
        if code:
            r = self._rooms.get(code)
            loc = f"{code} {r.name}".strip() if r and r.name else code
        elif self._state.current_hex:
            loc = self._state.current_hex
        if loc:
            self._emit(SessionStatUpdated(key="location", value=loc))
        self._maybe_relocate(code, confident_hex)
        self._last_seen_hex = ""
        if self._state.task.type is TaskType.SEARCHING:
            self._state.complete_task()

    def _engage_attacker(self, line: str) -> None:
        """Safety net: a monster is hitting us. Ensure it's in the roster so the combat
        engine fights back instead of resting/moving through the beating — covers a
        wander-in the room display cleared, or an arrival we missed entirely. MegaMud
        re-scans the room on combat events; this is our equivalent."""
        from mmud.parser.room_parser import _plausible_monster_name
        m = _ATTACKER_RE.match(line)
        if not m:
            return
        name = m.group(1).strip()
        if not _plausible_monster_name(name):
            return
        if any(s.name.lower() == name.lower() for s in self._state.monsters_present):
            return                              # already tracked -> nothing to do
        self._state.add_monster(self._build_sighting(name, 1))
        self._also_here_seen = True
        self._session_log.event(f"under attack by {name!r} -> re-added to roster")

    def _parse_monster_removal(self, line: str) -> None:
        """Drop a monster from the roster on a named death / slay / "you do not
        see X" line (combat-state-independent). The unnamed "You gain N
        experience" kill is handled in _parse_who_and_exp by target removal."""
        name = self._room_parser.extract_removed_monster(line)
        if name and self._state.remove_monster(name):
            self._on_monster_killed(f"removed {name}")

    def _on_monster_killed(self, reason: str) -> None:
        """Shared cleanup when a monster leaves the roster via death/kill: mark
        loot pending and release the attack-spell pace token so the bot loots and
        moves promptly instead of waiting out the cast cooldown."""
        self._state.inventory_dirty = True   # loot may have dropped
        if self._state.task.type is TaskType.CASTING:
            self._state.abort_task()
        # MegaMud resets the attack cast cap per KILL -> re-cast the next monster instead
        # of meleeing the rest of the room with full mana (the spell->melee "wonky").
        self._spell_engine.on_kill()
        self._session_log.event(
            "monsters=" + repr([m.name for m in self._state.monsters_present])
            + f" ({reason})")

    def _handle_doors(self, line: str) -> None:
        if not (self._travel.active or (self._loop_runner and self._loop_runner.running)):
            return
        door_cmds = self._doors.handle(line, self._pending_move)
        if door_cmds is None:
            return
        if door_cmds:
            for c in door_cmds:
                self._state.enqueue(c)
            # Re-issue just the MOVE after the door clears — NOT retry_current(),
            # which re-runs the whole step including any `[use <key> <dir>]` keyword
            # annotation and burns another key on an already-unlocked door. Travel
            # stays in-flight; the re-issued move's arrival advances the cursor.
            if self._pending_move:
                self._state.enqueue(self._pending_move)
        else:
            self._travel.on_move_failed()  # can't open: normal failure path

    def _parse_nav_failure(self, line: str) -> None:
        if not _NAV_FAIL_RE.search(line):
            return
        # Ignore a STALE failure: if the server's last echoed command isn't the move
        # we're currently awaiting, this "no exit" belongs to a superseded move still
        # draining through the pipeline. Acting on it would clear the route and issue a
        # SECOND move on top of the in-flight one (the live double-move) and falsely
        # declare us lost. Only act when the failure is for our current move (or we
        # have no echo/pending move to compare).
        if (self._last_prompt_cmd and self._pending_move
                and self._last_prompt_cmd != self._pending_move):
            return
        # A bad direction while following a recorded loop means we've desynced
        # (common in hash-colliding areas like the graveyard). Retrying the dead
        # exit is futile -> assume lost and wander to relocate the loop.
        if self._loop_runner and self._loop_runner.running and self._travel.active:
            self._travel.clear(reason="lost")
            msg = self._loop_runner.recover()
            self._session_log.event(f"lost (bad direction) -> {msg}")
        elif self._travel.active:
            self._travel.on_move_failed()   # goto: retry then block

    def _parse_combat_stats(self, line: str) -> None:
        if m := _PLAYER_HIT_RE.search(line):
            dmg = int(m.group(1))
            if _BACKSTAB_RE.search(line):
                self._state.record_hit(dmg, kind="backstab")
                self._state.record_backstab(success=True)
            elif _CRIT_RE.search(line):
                self._state.record_crit(dmg)
            else:
                self._state.record_hit(dmg, kind="hit")
            self._emit(SessionStatUpdated(key="hit_pct", value=f"{self._state.hit_pct:.0f}%"))
        elif m := _CAST_HIT_RE.search(line):
            self._state.record_cast(int(m.group(1)))
        elif _PLAYER_MISS_RE.search(line):
            self._state.record_miss()
        elif _SNEAK_OK_RE.search(line):
            self._state.record_sneak(success=True)
        elif _SNEAK_FAIL_RE.search(line):
            self._state.record_sneak(success=False)
        elif _DODGE_RE.search(line):
            self._state.record_dodge()
        elif m := _MONSTER_HIT_RE.search(line):
            self._state.record_monster_hit(int(m.group(1)))

    def _parse_get_results(self, line: str) -> None:
        from mmud.automation.items import _GET_FAIL_RE, _GOT_RE
        task = self._state.task.type
        low = line.lower()
        if task is TaskType.GETTING:
            if _GET_FAIL_RE.search(line):
                # Scenery / non-gettable (signs, rafts, "Syntax: GET ...") —
                # remember it so we never retry. Coins are transient: a failed
                # coin grab must NOT blacklist the denomination.
                last = self._state.task.payload.get("item")
                if last and not self._state.task.payload.get("coin"):
                    self._get_decider.mark_ungettable(last)
                self._state.abort_task()
            elif _GOT_RE.search(line):
                self._state.complete_task()
                self._state.inventory_dirty = True   # inventory changed -> refresh
        elif task is TaskType.EQUIPPING:
            if low.startswith("you are now wearing") or low.startswith("you are now wielding") \
                    or low.startswith("you are now holding"):
                self._state.complete_task()
            elif "is cursed" in low or "can't remove" in low or "cannot remove" in low:
                if last := self._state.task.payload.get("item"):
                    self._equip_decider.mark_failed(last)
                self._state.abort_task()

    def _parse_combat_state(self, line: str) -> None:
        """Drive in_combat from the authoritative *Combat Engaged*/*Combat Off*
        markers. Does NOT clear the monster roster (handled by death/exp lines and
        room re-displays) — *Combat Off* fires between rounds while the monster is
        still present (combat_event_parse @ 0x004176b0)."""
        if _COMBAT_ENGAGED_RE.search(line):
            if not self._state.in_combat:
                self._state.set_combat(True)
                self._session_log.event("combat=on")
                self._emit(CombatChanged(in_combat=True))
        elif _COMBAT_OFF_RE.search(line):
            if self._state.in_combat:
                self._state.set_combat(False)
                self._session_log.event("combat=off")
                self._emit(CombatChanged(in_combat=False))

    def _next_command(self) -> str | None:
        was_running = self._state.task.type is TaskType.RUNNING
        cmd = self._engine.next_command(self._state)
        if not was_running and self._state.task.type is TaskType.RUNNING:
            self._state.record_ran_away()
            self._emit(SessionStatUpdated(key="ran_away",
                                          value=str(self._state.ran_away)))
        self._update_activity(cmd)
        return cmd

    def _update_activity(self, cmd) -> None:
        """Surface what the bot is doing (or waiting on) so it never looks frozen —
        to the StatsBar, :status, and the session log."""
        from mmud.combat.combat import activity_reason
        s = self._state
        reason = activity_reason(s, cmd, self._config.combat.mana_attack_pct,
                                 self._config.combat.rest_threshold,
                                 self._config.combat.rest_mana_pct)
        if not reason:
            if s.in_combat or s.monsters_present:
                reason = "fighting"
            elif self._travel.active:
                reason = "navigating"
            elif self._loop_runner and self._loop_runner.running:
                reason = "looping"
        if reason != self._wait_reason:
            self._wait_reason = reason
            self._emit(SessionStatUpdated(key="activity", value=reason))
            if reason:
                self._session_log.event(
                    f"status: {reason} (HP={s.hp}/{s.max_hp} MA={s.mana}/{s.max_mana})")
        objective = self._macro_status()
        if objective != self._objective:
            self._objective = objective
            self._emit(SessionStatUpdated(key="objective", value=objective))
            # Log only on a phase/lap change, not every step ("35/68" -> "36/68"),
            # so the loop doesn't spam the session log once per move. The per-step
            # detail lives in a trailing "(...)" — strip it for the phase key.
            phase = re.sub(r"\s*\([^()]*\)\s*$", "", objective)
            if phase != self._objective_phase:
                self._objective_phase = phase
                self._session_log.event(f"objective: {objective}")

    def _code_for_hex(self, hexid: str) -> str:
        """Reverse ROOMS.MD lookup hex->4-letter code (for readable status), or ''."""
        h = (hexid or "").upper()
        if not h:
            return ""
        if getattr(self, "_hex_to_code", None) is None:
            self._hex_to_code = {r.hex_id.upper(): c
                                 for c, r in self._rooms.items() if r.hex_id}
        return self._hex_to_code.get(h, "")

    def _step_detail(self) -> str:
        """' (pos/total: cmd->dest)' for the active route — the current path step,
        for debugging in the status bar. '' when there's no current step."""
        cur = self._travel.current
        if cur is None:
            return ""
        pos, total = self._travel.step
        dest = self._code_for_hex(cur.chosen) or (cur.chosen[:8] if cur.chosen else "?")
        return f" ({pos}/{total}: {cur.command}->{dest})"

    def _macro_status(self) -> str:
        """High-level goal: Looping/Routing/Wandering/Traveling/Idle, with the path
        step (cmd->dest) so travel is debuggable from the status bar."""
        lr = self._loop_runner
        name = self._config.navigation.loop_path
        if lr and lr.running:
            if self._travel.wandering:
                return f"Wandering -> {name}"
            if self._travel.in_approach:
                return f"Routing -> {name}{self._step_detail()}"
            pos, total = self._travel.loop_step
            cur = self._travel.current
            # lap is 0-based internally; display 1-based ("lap 1" on the first pass).
            detail = ""
            if cur is not None:
                dest = self._code_for_hex(cur.chosen) or (cur.chosen[:8] or "?")
                detail = f": {cur.command}->{dest}"
            return f"Looping {name} lap {lr.lap + 1} ({pos}/{total}{detail})"
        if self._travel.active:
            return f"Traveling {self._travel_dest or '?'}{self._step_detail()}"
        return "Idle"

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
        paths = self._navigator.all_paths()
        lr = LoopRunner(self._config.navigation, paths, self._rooms, self._travel,
                        code_route=self._code_route,
                        missing_items=self._code_missing_items,
                        current_code=self._state.current_room,
                        current_hex=self._resolved_current_hex())
        lr.on_lost = self._on_loop_lost
        return lr

    def _on_loop_lost(self, reason: str = "") -> None:
        """The loop stopped before completing. `reason` distinguishes a blocked route
        (e.g. 'need rope and grapple') from a plain lost-wander give-up, so the user
        sees WHY rather than a vague 'Lost' — they can grab the item and retry."""
        name = self._config.navigation.loop_path
        if reason:
            self._session_log.event(f"loop {name} blocked: {reason}")
            self._emit(SessionStatUpdated(key="objective", value=reason))
            return
        self._session_log.event(f"lost — gave up loop {name} (could not relocate); stopped")
        self._emit(SessionStatUpdated(key="objective", value=f"Lost (gave up {name})"))

    def _spell_durations(self) -> dict[str, float]:
        """mnemonic/name -> SPELLS.MD duration (minutes), for auto-timing bless
        re-casts. Sourced from the store (imported SPELLS.MD)."""
        out: dict[str, float] = {}
        try:
            from mmud.data.store import store_spells
            spells = store_spells(self._store) if self._store else []
        except Exception:
            spells = []
        for sp in spells:
            dur = getattr(sp, "duration", 0)
            if dur:
                for key in (getattr(sp, "short_name", ""), getattr(sp, "full_name", "")):
                    if key:
                        out[key.strip().lower()] = float(dur)
        return out

    def _held_items(self) -> set[str]:
        """Items the bot is currently carrying or wearing — used to unlock item-gated
        path legs (a 'rope and grapple' descent, a 'wooden skiff' crossing)."""
        inv = self._state.inventory
        return set(inv.carried) | set(inv.worn)

    def _code_route(self, from_code: str, to_code: str):
        """Walkable route between two room codes by chaining .MP paths (reliable),
        not the collision-prone room-hash BFS. Returns RouteSteps or None. Item-gated
        legs are usable only when we actually carry the required item."""
        from mmud.navigation.code_route import find_code_route
        return find_code_route(from_code, to_code,
                               list(self._navigator._paths.values()), self._rooms,
                               held_items=self._held_items())

    def _code_missing_items(self, from_code: str, to_code: str):
        """Items we'd need (beyond those held) to reach `to_code`; [] if reachable,
        None if unreachable even with every item. Lets us say 'need rope and grapple'
        instead of wandering off lost."""
        from mmud.navigation.code_route import missing_route_items
        return missing_route_items(from_code, to_code,
                                   list(self._navigator._paths.values()),
                                   held_items=self._held_items())

    def _hex_name(self, hexid: str) -> str:
        """A short label for a hex id: 'CODE(Name)' if in ROOMS.MD, else the hex."""
        if not hexid:
            return "?"
        for code, room in self._rooms.items():
            if room.hex_id and room.hex_id.upper() == hexid.upper():
                return f"{code}({room.name})"
        return hexid

    def _log_route(self, label: str, steps) -> None:
        legs = [f"{s.command}->{self._hex_name(s.chosen)}" for s in steps]
        self._session_log.event(f"route {label} ({len(steps)} steps): "
                                + " | ".join(legs))

    def _resolved_current_hex(self) -> str:
        """Best-effort current hex: live position, else the current room's ROOMS.MD
        hex. Empty when position is unknown."""
        h = self._state.current_hex
        if not h and self._state.current_room:
            room = self._rooms.get(self._state.current_room)
            h = room.hex_id.upper() if room and room.hex_id else ""
        return h

    def toggle_loop(self) -> None:
        if self._loop_runner and self._loop_runner.running:
            self._loop_runner.stop()
            return
        self._loop_runner = self._make_loop_runner()
        self._loop_runner.start()

    # Slots that constitute "fighting" — suppressed when combat is toggled off so the
    # bot quick-moves past monsters ("run") instead of stopping to attack.
    _COMBAT_SLOTS = ("backstab", "spells", "combat")

    @property
    def combat_enabled(self) -> bool:
        return self._combat_enabled

    def set_combat_enabled(self, on: bool) -> str:
        """Toggle auto-combat (MegaMud-style). Off -> the attack deciders are skipped
        and travel/loops keep moving through rooms without fighting ("run"); on ->
        restored. Returns a short status message."""
        self._combat_enabled = on
        self._state.combat_enabled = on   # travel reads this: off -> run through monsters
        if on:
            self._engine.disabled_slots.difference_update(self._COMBAT_SLOTS)
        else:
            self._engine.disabled_slots.update(self._COMBAT_SLOTS)
        self._emit(SessionStatUpdated(key="combat", value="on" if on else "off"))
        self._session_log.event(f"combat {'on' if on else 'off'}")
        return f"Combat {'ON' if on else 'OFF — running (no attacks)'}"

    def toggle_combat(self) -> str:
        return self.set_combat_enabled(not self._combat_enabled)

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
        msg = self._loop_runner.start()
        if self._travel.route:
            self._log_route(f"loop {loop_name}", self._travel.route)
        else:
            self._session_log.event(f"loop {loop_name}: {msg}")
        return msg

    def stop_all(self) -> str:
        """Stop loop/travel and clear command queue."""
        if self._loop_runner:
            self._loop_runner.stop()
        self._travel.clear()
        while self._state.dequeue() is not None:
            pass
        return "Stopped."

    def find_rooms(self, query: str, limit: int = 25) -> list[Room]:
        """Search loaded rooms by exact 4-letter code or name substring
        (case-insensitive), sorted by name. For discovering codes to :goto."""
        q = query.strip().lower()
        if not q:
            return []
        matches = [r for code, r in self._rooms.items()
                   if q == code.lower() or q in r.name.lower()]
        matches.sort(key=lambda r: r.name.lower())
        return matches[:limit]

    def _resolve_rooms(self, target: str) -> list[str]:
        """Resolve a goto target to room code(s): an exact 4-letter code, else a
        case-insensitive substring match on room names."""
        t = target.strip()
        if t.upper() in self._rooms:
            return [t.upper()]
        tl = t.lower()
        return [c for c, r in self._rooms.items() if tl and tl in r.name.lower()]

    def _maybe_relocate(self, code: str, hexid: str) -> None:
        """Off-route recovery for ANY active travel (goto OR loop): if we confidently
        detect a KNOWN room (ROOMS.MD) that isn't on the planned route, re-path from
        here to the destination instead of blindly continuing or wandering on. Covers
        the lost-wander case too (a wander has no route, so any known room re-paths)."""
        if not (code and hexid and self._travel.active):
            return
        if any(hexid in s.expect for s in self._travel.route):
            self._relocate_from = ""        # on the route -> reset the thrash guard
            return
        if hexid == self._relocate_from:
            return                          # already re-pathed here; don't thrash
        self._relocate_from = hexid
        if self._loop_runner and self._loop_runner.running:
            msg = self._loop_runner.relocate(code, hexid)
        elif self._travel_dest and "->" in self._travel_dest:
            dest = self._travel_dest.split("->")[-1]
            if dest == code:
                return                      # already at the destination
            msg = self.navigate_to_room(dest)
        else:
            return
        self._session_log.event(f"off-route at {code} -> relocate: {msg}")

    def navigate_to_room(self, target: str) -> str:
        """Multi-hop navigate to a room by 4-letter code OR name substring, by
        chaining recorded .MP paths over the room-code graph."""
        codes = self._resolve_rooms(target)
        if not codes:
            return f"Unknown room: {target}"
        if len(codes) > 1:
            shown = ", ".join(f"{c} ({self._rooms[c].name})" for c in codes[:6])
            more = " …" if len(codes) > 6 else ""
            return f"Ambiguous '{target}' — matches {len(codes)}: {shown}{more}"
        to_code = codes[0].upper()
        from_code = self._state.current_room
        if not from_code:
            return "Current room unknown — move around first to establish position"
        steps = self._code_route(from_code, to_code)
        if steps is None:
            need = self._code_missing_items(from_code, to_code)
            if need:
                return (f"Can't reach {to_code} from {from_code}: "
                        f"need {', '.join(need)}")
            return f"No known route from {from_code} to {to_code}"
        if not steps:
            return f"Already at {to_code}"
        while self._state.dequeue() is not None:
            pass
        self._travel_dest = f"{from_code}->{to_code}"
        self._travel.set_route(steps)
        self._log_route(f"goto {to_code}", steps)
        return f"Navigating to {to_code} ({len(steps)} steps)"

    def list_paths(self) -> list[str]:
        """Return all known loop path names."""
        return self._navigator.list_loop_paths()

    def list_loop_choices(self) -> list[tuple[str, str]]:
        """(identifier, label) for the loop picker — label carries the room name/NPC
        (e.g. 'Cave Worm Area (cavwloop)') so the list isn't a wall of opaque codes."""
        return self._navigator.loop_choices()

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
        wait = f" | {self._wait_reason}" if self._wait_reason else ""
        obj = f" | {self._macro_status()}"
        return f"Room:{room} {hp_str} {mp_str}{loop}{combat}{wait}{obj}"
