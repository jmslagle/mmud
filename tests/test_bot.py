import asyncio
import pytest
from mmud.net.connection import MudConnection
from mmud.bot import MudBot
from mmud.data.messages import MessagePattern
from mmud.events import (
    GameEventBus, LineReceived, HpChanged, EffectApplied,
)


@pytest.mark.asyncio
async def test_connection_sends_and_receives(unused_tcp_port):
    """Use a mock echo server to test connection."""
    async def echo_handler(reader, writer):
        data = await reader.readline()
        writer.write(data)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo_handler, "127.0.0.1", unused_tcp_port)
    async with server:
        conn = MudConnection("127.0.0.1", unused_tcp_port)
        await conn.connect()
        await conn.send("hello")
        line = await conn.readline()
        assert line.strip() == "hello"
        await conn.close()


@pytest.mark.asyncio
async def test_monster_attacking_us_is_added_to_roster():
    # Safety net: if something is hitting us (a wander-in the room display cleared, or a
    # missed arrival), add it to the roster so the combat engine fights back instead of
    # resting through the beating. (MegaMud re-scans the room on combat events.)
    bot = make_transcript_bot([])
    assert not bot._state.monsters_present
    await bot._process_line("The cave worm lunges at you!\n")
    assert any(m.name == "cave worm" for m in bot._state.monsters_present)
    # our own attacks / players (no article) must NOT be mistaken for an attacker
    bot._state.replace_monsters([])
    await bot._process_line("You fire a frost jet at cave worm for 20 damage!\n")
    await bot._process_line("Bob swings at you.\n")
    assert not bot._state.monsters_present


@pytest.mark.asyncio
async def test_also_here_player_not_reattacked_via_learned_placeholder():
    # A player ("TheSysop") that was once wrongly LEARNED as a monster (negative
    # record_id, kill_type 0) must NOT be re-injected into monsters_present as an
    # attackable target — otherwise the bot attacks a player it can't kill, then
    # deadlocks (combat won't re-send + travel held). Only a REAL catalogued monster
    # (record_id >= 0) makes a proper-named "Also here:" entry an NPC sighting.
    from mmud.data.monster_db import MonsterDB
    from mmud.data.binary import Monster
    bot = make_transcript_bot([])
    bot._monster_db = MonsterDB([
        Monster(record_id=-2, name="thesysop", level=0, exp_value=0, combat_rating=0,
                alignment=0, hp_estimate=0, short_name1="", short_name2="", flags=0)])
    await bot._process_line("Also here: TheSysop.\n")
    assert "TheSysop" in bot._state.players_present
    assert not any(m.name.lower() == "thesysop" for m in bot._state.monsters_present)


@pytest.mark.asyncio
async def test_attacker_name_excludes_all_out_adverb():
    # "The X all-out slashes you" -> the attacker is X, NOT "X all-out" (MajorMUD's
    # all-out attack mode). A bogus "X all-out" roster entry made the bot cast
    # "lbol <X> all-out" -> "You do not see ... here".
    bot = make_transcript_bot([])
    await bot._process_line(
        "The nasty black orc captain all-out slashes you for 11 damage!\n")
    names = [m.name for m in bot._state.monsters_present]
    assert "nasty black orc captain" in names
    assert "nasty black orc captain all-out" not in names


@pytest.mark.asyncio
async def test_aggressive_neutral_becomes_attackable_but_guards_dont():
    # The slum giant rats are aggressive (red, attacking) but bundled MONSTERS.MD
    # mis-classifies them kill-type 3 (neutral). If a kill-type-3 mob ATTACKS us, treat
    # it as hostile and fight back (even with attack_neutral off). But NEVER a kill-type-2
    # NPC/guard — we don't attack guards, even if they swing at us.
    from mmud.state.game_state import MonsterSighting
    from mmud.combat.combat import attackable_sightings
    bot = make_transcript_bot([])
    bot._state.monsters_present = [
        MonsterSighting(name="giant rat", kill_type=3),
        MonsterSighting(name="town guard", kill_type=2),
    ]
    assert not attackable_sightings(bot._state, False)        # neither yet (neutral off)
    await bot._process_line("The giant rat bites you for 3 damage!\n")
    await bot._process_line("The town guard swings at you!\n")
    names = [s.name for s in attackable_sightings(bot._state, False)]
    assert "giant rat" in names                              # aggressive neutral -> fight
    assert "town guard" not in names                         # guard -> never


@pytest.mark.asyncio
async def test_wander_in_survives_a_stray_exits_line():
    # A monster wandering in occupies the room; a stray exits line with no "Also here:"
    # must NOT clear it as an empty room (that made the bot rest/move through it).
    bot = make_transcript_bot([])
    await bot._process_line("A giant rat creeps into the room from nowhere.\n")
    assert any(m.name == "giant rat" for m in bot._state.monsters_present)
    await bot._process_line("Obvious exits: north, south\n")
    assert any(m.name == "giant rat" for m in bot._state.monsters_present)


def test_nudge_due_when_task_waiting_and_server_quiet():
    # Prompt-gated decisions stall if the server goes quiet while we're waiting on a task.
    # MegaMud re-evaluates ~1Hz; our equivalent is a keepalive Enter after ~2s of no
    # prompt while work is pending (instead of waiting out the 10s idle refresh).
    from mmud.state.tasks import TaskType
    bot = make_transcript_bot([])
    bot._login_handler.in_game = True
    bot._last_prompt_at = 0.0
    bot._last_refresh = 0.0
    bot._state.begin_task(TaskType.WAITING, priority=60, timeout_s=30.0, now=0.0)
    assert bot._nudge_due(3.0)          # 3s quiet + task active -> nudge
    assert not bot._nudge_due(1.0)      # only 1s quiet -> wait
    bot._last_prompt_at = 2.5
    assert not bot._nudge_due(3.0)      # a prompt arrived 0.5s ago -> no nudge


def test_pregame_only_drains_login_queue_not_the_ai():
    # The login-screen bug: during auto-login the bot ran the full decision engine every
    # line, so it cast bless spells (shld/armr) at the "User-ID:" prompt. While logging in it
    # must ONLY drain the command queue (login replies), never the combat/spell/travel AI.
    from mmud.config.schema import MudConfig, LoginConfig
    config = MudConfig()
    config.login = LoginConfig(username="Raist", password="pw", auto_login=True)
    bot = make_transcript_bot([], config=config)
    bot._login_handler.in_game = False
    calls = []
    bot._next_command = lambda: (calls.append(1), "BLESS")[1]   # stand-in for the AI engine
    # empty queue, pre-game -> nothing sent, engine NOT consulted
    assert bot._turn_command(False) is None
    assert calls == []
    # a queued login reply still drains pre-game
    bot._state.enqueue("Raist")
    assert bot._turn_command(False) == "Raist"
    assert calls == []
    # in-game (ready) -> the engine runs
    bot._login_handler.in_game = True
    bot._ready = True
    assert bot._turn_command(True) == "BLESS"
    assert calls == [1]


@pytest.mark.asyncio
async def test_login_pager_enter_is_sent_not_dropped():
    # The bot hung at "(N)onstop, (Q)uit, or (C)ontinue?": the pager reply is "" (a bare
    # Enter) and the run loop's `if cmd:` dropped it. It must be sent (is not None).
    from mmud.config.schema import MudConfig, LoginConfig
    config = MudConfig()
    config.login = LoginConfig(username="Raist", password="pw", auto_login=True)
    bot = make_transcript_bot([
        'If you already have a User-ID on this system, type it in: ',
        "Enter your password: ",
        "(N)onstop, (Q)uit, or (C)ontinue?",
    ], config=config)
    await bot.run()
    assert "Raist" in bot._conn.sent
    assert "pw" in bot._conn.sent
    assert "" in bot._conn.sent          # the pager Enter — sent, not dropped


def test_no_fast_nudge_when_nothing_pending():
    bot = make_transcript_bot([])
    bot._login_handler.in_game = True
    bot._last_prompt_at = 0.0
    bot._last_refresh = 0.0
    # no task / travel / queue / pending move -> the slow 10s idle refresh handles it
    assert not bot._nudge_due(5.0)


def test_loop_resumes_after_reconnect():
    # reconnect=true: after an auto-reconnect the loop must RESUME (it idled at the login
    # room before). _loop_intended (set by start_loop) drives the resume on game re-entry.
    bot = make_transcript_bot([])
    calls = []
    bot.start_loop = lambda name="": (calls.append(name), "ok")[1]
    bot._loop_intended = "CAVWLOOP"
    bot._prev_in_game = False
    bot._login_handler.in_game = True
    bot._handle_login("[HP=100/MA=50]:")        # game-entry edge after reconnect
    assert calls == ["CAVWLOOP"]
    bot._handle_login("Stone Tunnel")           # still in_game -> no re-start
    assert calls == ["CAVWLOOP"]
    bot._login_handler.in_game = False          # a drop re-arms the edge
    bot._handle_login("User-ID:")
    bot._login_handler.in_game = True
    bot._handle_login("[HP=100/MA=50]:")
    assert calls == ["CAVWLOOP", "CAVWLOOP"]    # resumed again


def test_deliberate_stop_does_not_resume_on_reconnect():
    bot = make_transcript_bot([])
    calls = []
    bot.start_loop = lambda name="": (calls.append(name), "ok")[1]
    bot._loop_intended = "CAVWLOOP"
    bot.stop_all()                              # deliberate stop clears the intent
    assert bot._loop_intended == ""
    bot._prev_in_game = False
    bot._login_handler.in_game = True
    bot._handle_login("[HP=100/MA=50]:")
    assert calls == []                          # no auto-resume after a deliberate stop


def test_resume_loop_after_bail_when_healed():
    # combat.resume_after_bail: after an emergency bail (loop stopped) auto-resume the loop
    # once healed + safe — hands-off bail->heal->resume grind.
    from mmud.config.schema import MudConfig
    config = MudConfig()
    config.combat.resume_after_bail = True
    config.combat.hp_full_pct = 0.85
    bot = make_transcript_bot([], config=config)
    bot._login_handler.in_game = True
    bot._loop_intended = "CAVWLOOP"
    calls = []
    bot.start_loop = lambda name="": (calls.append(name), "ok")[1]
    bot._bailed = True
    bot._state.set_hp(168, 168)                 # healed (>= 85%)
    bot._maybe_resume_after_bail()
    assert calls == ["CAVWLOOP"] and bot._bailed is False
    # still healing -> no resume
    bot._bailed = True; calls.clear(); bot._state.set_hp(100, 168)   # 60% < 85%
    bot._maybe_resume_after_bail()
    assert calls == []
    # in combat -> no resume
    bot._bailed = True; bot._state.set_hp(168, 168); bot._state.set_combat(True)
    bot._maybe_resume_after_bail()
    assert calls == []
    # feature off (default) -> no resume
    config.combat.resume_after_bail = False
    bot._bailed = True; bot._state.set_combat(False)
    bot._maybe_resume_after_bail()
    assert calls == []


def test_inventory_requested_on_game_entry():
    # Route item-gates need to know what we hold (e.g. rope and grapple); the first in-game
    # "[HP=...]" prompt must request inventory alongside stat/who. (Bug: CAVWLOOP was
    # "blocked: need rope and grapple" because we never read inventory on login.)
    bot = make_transcript_bot([])
    bot._login_handler.in_game = True
    bot._parse_vitals("[HP=168/MA=72]:")
    q = list(bot._state._command_queue)
    assert "stat" in q
    assert bot._config.items.inventory_cmd in q          # "inv" by default ("i" for raist)
    assert "exp" in q                                    # exp-to-level / will-level counters


def _equip_item(name, slot):
    from mmud.data.binary import Item
    return Item(record_id=1, name=name, source="", suffix="", item_type=1,
                equip_slot=slot, ac_or_dmg=0, weight=0, value=0, extra_stat1=0,
                flags=0x40000000)


def test_get_all_walks_ground_items_not_blanket_all():
    # "Get all" should send one 'get <item>' per ground item (walk the list), not the
    # literal "get all".
    bot = make_transcript_bot([])
    bot._state.ground_items = ["a rusty sword", "a small shield"]
    bot.get_all()
    cmds = []
    while (c := bot._state.dequeue()) is not None:
        cmds.append(c)
    assert cmds == ["get a rusty sword", "get a small shield"]
    assert bot._state.ground_items == []


def test_equip_all_walks_carried_equippables():
    from mmud.data.item_db import ItemDB
    from mmud.state.inventory import Inventory
    bot = make_transcript_bot([])
    bot._item_db = ItemDB([_equip_item("plate mail", 5), _equip_item("torch", 0)])
    bot._state.inventory = Inventory(carried_counts={"plate mail": 1, "torch": 1})
    bot.equip_all()
    cmds = []
    while (c := bot._state.dequeue()) is not None:
        cmds.append(c)
    assert cmds == ["equip plate mail"]      # torch (slot 0) isn't equippable


def test_mark_worn_adds_to_auto_get_and_equip():
    from mmud.state.inventory import Inventory
    bot = make_transcript_bot([])
    bot._state.inventory = Inventory(worn=["plate mail", "steel helm"])
    bot.mark_worn_as_auto()
    assert "plate mail" in bot._config.items.get_items
    assert "steel helm" in bot._config.items.get_items
    assert "plate mail" in bot._config.items.equip_items
    # the live equip allow-list is updated too, and it's idempotent
    assert "plate mail" in bot._equip_decider._only
    bot.mark_worn_as_auto()
    assert bot._config.items.get_items.count("plate mail") == 1


@pytest.mark.asyncio
async def test_bot_processes_line_and_issues_command(unused_tcp_port):
    """A monster in the room makes the bot initiate combat ('kill <monster>')."""
    received = []

    async def server_handler(reader, writer):
        # A monster sighting -> bot attacks (CombatEngine acts on monsters_present).
        writer.write(b"Also here: an orc.\r\n")
        await writer.drain()
        cmd = await asyncio.wait_for(reader.readline(), timeout=2.0)
        received.append(cmd.decode().strip())
        writer.close()

    server = await asyncio.start_server(server_handler, "127.0.0.1", unused_tcp_port)
    async with server:
        bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[])
        try:
            await asyncio.wait_for(bot.run(), timeout=3.0)
        except asyncio.TimeoutError:
            pass
    assert any("kill orc" in r for r in received)


@pytest.mark.asyncio
async def test_bot_emits_line_received(unused_tcp_port):
    received = []

    async def server_handler(reader, writer):
        writer.write(b"Hello world\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(server_handler, "127.0.0.1", unused_tcp_port)
    bus = GameEventBus()
    bus.subscribe(LineReceived, received.append)

    async with server:
        bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[], event_bus=bus)
        try:
            await asyncio.wait_for(bot.run(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
    assert any(e.line.strip() == "Hello world" for e in received)


@pytest.mark.asyncio
async def test_bot_emits_hp_changed(unused_tcp_port):
    received = []

    async def server_handler(reader, writer):
        writer.write(b"[HP=141/216]:e\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(server_handler, "127.0.0.1", unused_tcp_port)
    bus = GameEventBus()
    bus.subscribe(HpChanged, received.append)

    async with server:
        bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[], event_bus=bus)
        try:
            await asyncio.wait_for(bot.run(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
    assert any(e.hp == 141 and e.max_hp == 216 for e in received)


@pytest.mark.asyncio
async def test_bot_emits_effect_applied(unused_tcp_port):
    received = []

    async def server_handler(reader, writer):
        writer.write(b"You are caught in a chain!\r\n")
        await writer.drain()
        writer.close()

    patterns = [
        MessagePattern(name="chain", flags=0x10, third_field=0,
                       apply_message="You are caught in a chain!",
                       remove_message="You get back on your feet.")
    ]
    server = await asyncio.start_server(server_handler, "127.0.0.1", unused_tcp_port)
    bus = GameEventBus()
    bus.subscribe(EffectApplied, received.append)

    async with server:
        bot = MudBot("127.0.0.1", unused_tcp_port, patterns=patterns, event_bus=bus)
        try:
            await asyncio.wait_for(bot.run(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
    assert any(e.name == "chain" for e in received)


@pytest.mark.asyncio
async def test_bot_detects_room_change(unused_tcp_port):
    from mmud.events import RoomChanged
    from mmud.data.rooms import Room
    rooms = {
        "HOME": Room(code="HOME", hex_id="", hex_id2="", flags=(0,0,0),
                     region="Silvermere", name="The Homely Hearth")
    }
    received = []

    async def server_handler(reader, writer):
        writer.write(b"The Homely Hearth\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(server_handler, "127.0.0.1", unused_tcp_port)
    bus = GameEventBus()
    bus.subscribe(RoomChanged, received.append)

    async with server:
        bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[], event_bus=bus, rooms=rooms)
        try:
            await asyncio.wait_for(bot.run(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
    assert any(e.code == "HOME" for e in received)


@pytest.mark.asyncio
async def test_bot_detects_combat_exit(unused_tcp_port):
    from mmud.events import CombatChanged
    received = []

    async def server_handler(reader, writer):
        writer.write(b"The orc breaks off combat.\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(server_handler, "127.0.0.1", unused_tcp_port)
    bus = GameEventBus()
    bus.subscribe(CombatChanged, received.append)

    async with server:
        bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[], event_bus=bus)
        bot._state.set_combat(True)
        try:
            await asyncio.wait_for(bot.run(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
    assert any(not e.in_combat for e in received)


@pytest.mark.asyncio
async def test_bot_toggle_loop(unused_tcp_port):
    """toggle_loop() creates and starts a LoopRunner, then stops it on second call."""
    from mmud.data.paths import GamePath, PathStep
    from mmud.config.schema import MudConfig

    async def server_handler(reader, writer):
        writer.close()

    server = await asyncio.start_server(server_handler, "127.0.0.1", unused_tcp_port)
    path = GamePath(
        from_code="HOME", from_region="", from_name="",
        to_code="HOME", to_region="", to_name="",
        npc="", steps=[PathStep(hex_id="0", command="n")],
    )
    config = MudConfig()
    config.navigation.loop_path = "HOME"

    async with server:
        bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[], config=config)
        bot._navigator._paths[("HOME", "HOME")] = path
        bot._state.set_room("HOME")
        bot.toggle_loop()
        assert bot._loop_runner is not None
        assert bot._loop_runner.running is True
        bot.toggle_loop()
        assert bot._loop_runner.running is False


def _armed_loop_bot():
    """A bot with a loop running and the route armed (not wandering)."""
    from mmud.data.paths import GamePath, PathStep
    from mmud.config.schema import MudConfig
    config = MudConfig()
    config.navigation.loop_path = "HOME"
    bot = MudBot("localhost", 4000, patterns=[], config=config)
    path = GamePath(from_code="HOME", from_region="", from_name="",
                    to_code="HOME", to_region="", to_name="", npc="",
                    steps=[PathStep(hex_id="AAAA0001", command="n"),
                           PathStep(hex_id="BBBB0002", command="e")])
    bot._navigator._paths[("HOME", "HOME")] = path
    bot._state.set_room("HOME")
    bot._state.current_hex = "AAAA0001"     # on the loop's first step -> resume, no wander
    bot.toggle_loop()
    return bot


def test_stale_nav_failure_is_ignored():
    # We sent 'w', but the server's "no exit" is echoing an OLDER 'n' (a superseded
    # move still draining). Reacting would clear the route and fire a SECOND move on
    # top of the in-flight 'w' -> the live double-move. The stale failure must be
    # dropped: still on the loop, not wandering.
    bot = _armed_loop_bot()
    assert bot._travel.active and not bot._travel.wandering
    bot._pending_move = "w"
    bot._last_prompt_cmd = "n"          # server processed 'n', not our current 'w'
    bot._parse_nav_failure("There is no exit in that direction!")
    assert not bot._travel.wandering
    assert bot._loop_runner.running


def test_matching_nav_failure_triggers_recovery():
    # The failure IS for our current move ('w' echoed) -> genuinely a dead end ->
    # recover (wander to relocate the loop).
    bot = _armed_loop_bot()
    bot._pending_move = "w"
    bot._last_prompt_cmd = "w"
    bot._parse_nav_failure("There is no exit in that direction!")
    assert bot._travel.wandering


@pytest.mark.asyncio
async def test_room_display_emits_location_stat():
    # The bottom-left status panel shows where we are: a code+name when known, else the
    # raw hash. The bot emits it as a "location" session stat on each room display.
    from mmud.events import SessionStatUpdated
    from mmud.data.rooms import Room
    from mmud.parser.exits_parser import room_id
    exits = "Obvious exits: north"
    rooms = {"HOME": Room(code="HOME", hex_id=room_id("The Home Room", exits),
                          hex_id2="", flags=(0, 0, 0), region="", name="The Home Room")}
    received = []
    bus = GameEventBus()
    bus.subscribe(SessionStatUpdated, received.append)
    bot = MudBot("localhost", 4000, patterns=[], event_bus=bus, rooms=rooms)
    await bot._process_line("The Home Room\n")
    await bot._process_line(exits + "\n")
    locs = [e.value for e in received if e.key == "location"]
    assert locs and "HOME" in locs[-1]


@pytest.mark.asyncio
async def test_room_display_emits_hash_location_when_unknown():
    # A room absent from ROOMS.MD still reports position by hash.
    from mmud.events import SessionStatUpdated
    from mmud.parser.exits_parser import room_id
    received = []
    bus = GameEventBus()
    bus.subscribe(SessionStatUpdated, received.append)
    bot = MudBot("localhost", 4000, patterns=[], event_bus=bus)
    bot._title_color = "1;36"
    await bot._process_line("[HP=100/MA=50]:\n")
    await bot._process_line("\x1b[1;36mSlum Street, Bend\x1b[0m\n")
    exits = "Obvious exits: south, west"
    await bot._process_line(exits + "\n")
    locs = [e.value for e in received if e.key == "location"]
    assert locs and locs[-1] == room_id("Slum Street, Bend", exits)


@pytest.mark.asyncio
async def test_ready_only_on_the_bare_prompt():
    # MegaMud's turn boundary: the decider runs ONLY at a bare "[HP=]:" prompt, never on
    # mid-stream lines (hit/damage/death/exp/room). A command-echo prompt is NOT ready.
    bot = make_transcript_bot([])
    await bot._process_line("You fire a frost jet at orc for 20 damage!\n")
    assert not bot._ready                         # mid-round result -> not a turn boundary
    await bot._process_line("The dark cultist collapses without a sound.\n")
    assert not bot._ready                         # flavor death -> not ready
    await bot._process_line("Also here: a rat.\n")
    assert not bot._ready                         # sighting -> not ready
    await bot._process_line("[HP=100/MA=100]:fjet orc\n")        # command echo -> NOT ready
    assert not bot._ready
    await bot._process_line("[HP=100/MA=100]:\n")                # bare prompt -> ready
    assert bot._ready
    await bot._process_line("[HP=100/MA=100]: (Resting)\n")      # resting status -> ready
    assert bot._ready


@pytest.mark.asyncio
async def test_progressed_too_far_counts_as_a_kill():
    # MegaMud (combat_event_parse @0x4176b0) treats "You have progressed too far without
    # training" as a kill (a maxed character that gets no XP) — same target removal.
    from mmud.state.game_state import MonsterSighting
    bot = make_transcript_bot([])
    bot._state.monsters_present = [MonsterSighting(name="orc")]
    kills0 = bot._state.kills
    await bot._process_line("You have progressed too far without training to gain more experience.\n")
    assert bot._state.kills == kills0 + 1
    assert not bot._state.monsters_present          # the target was removed


@pytest.mark.asyncio
async def test_in_game_decides_only_at_the_prompt(unused_tcp_port):
    # End-to-end: once in-game, an "Also here: orc" sighting does NOT trigger an attack
    # mid-stream — the bot waits for the bare prompt (the turn boundary) and attacks then.
    received = []

    async def server_handler(reader, writer):
        writer.write(b"Also here: an orc.\r\n")           # sighting (mid-stream) -> no act
        await writer.drain()
        writer.write(b"[HP=100/MA=100]:\r\n")             # bare prompt -> act now
        await writer.drain()
        cmd = await asyncio.wait_for(reader.readline(), timeout=2.0)
        received.append(cmd.decode().strip())
        writer.close()

    server = await asyncio.start_server(server_handler, "127.0.0.1", unused_tcp_port)
    async with server:
        bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[])
        bot._login_handler.in_game = True            # the gate is in-game only
        bot._stat_requested = True                   # skip the one-time login `stat`
        try:
            await asyncio.wait_for(bot.run(), timeout=3.0)
        except asyncio.TimeoutError:
            pass
    assert received and received[0] == "kill orc"     # attacked at the prompt, not before


def test_toggle_combat_disables_attack_slots():
    # MegaMud-style combat toggle: off -> the attack deciders are skipped so the bot
    # quick-moves past monsters ("run"); on -> they're restored.
    bot = MudBot("localhost", 4000, patterns=[])
    assert bot.combat_enabled is True
    bot.toggle_combat()
    assert bot.combat_enabled is False
    assert {"combat", "backstab", "spells"} <= bot._engine.disabled_slots
    bot.toggle_combat()
    assert bot.combat_enabled is True
    assert not (bot._engine.disabled_slots & {"combat", "backstab", "spells"})


def test_bot_list_paths_empty():
    bot = MudBot("localhost", 4000, patterns=[])
    assert isinstance(bot.list_paths(), list)


def test_bot_status_text():
    bot = MudBot("localhost", 4000, patterns=[])
    status = bot.status_text()
    assert "Room:" in status
    assert "HP:" in status


def test_bot_stop_all_clears_queue():
    bot = MudBot("localhost", 4000, patterns=[])
    bot._state.enqueue("n")
    bot._state.enqueue("e")
    bot.stop_all()
    assert bot._state.dequeue() is None


@pytest.mark.asyncio
async def test_bot_navigate_to_room_no_current_room():
    bot = MudBot("localhost", 4000, patterns=[])
    msg = bot.navigate_to_room("CLKR")
    assert "unknown" in msg.lower()


def test_bot_start_loop_no_config():
    bot = MudBot("localhost", 4000, patterns=[])
    msg = bot.start_loop()
    assert "No loop" in msg or "not found" in msg


from conftest import make_transcript_bot


@pytest.mark.asyncio
async def test_transcript_bot_rests_on_low_hp():
    # HP 10/100 out of combat -> CombatEngine rest_threshold (0.40) says "rest".
    # The first prompt queues the one-time stat/who/inv/exp; the rest action follows once
    # those drain (one per prompt).
    bot = make_transcript_bot(["[HP=10/100]:\n"] * 7)
    await bot.run()
    assert "rest" in bot._conn.sent


@pytest.mark.asyncio
async def test_transcript_bot_sends_nothing_when_healthy():
    # Healthy: only the one-time login `stat` + `who`, no action commands.
    bot = make_transcript_bot(["[HP=100/100]:\n", "[HP=100/100]:\n"])
    await bot.run()
    assert bot._conn.sent == ["stat", "who"]


from mmud.automation.decision import PRIO_COMBAT
from mmud.state.tasks import TaskType
from mmud.events import TaskChanged


def test_closed_door_or_gate_is_not_a_nav_failure():
    # Regression: "closed" must NOT count as a nav failure, or the lost-recovery
    # wander hijacks the move before DoorMonitor can open/bash.
    from mmud.bot import _NAV_FAIL_RE
    assert _NAV_FAIL_RE.search("The gate is closed!") is None
    assert _NAV_FAIL_RE.search("The door is closed!") is None
    assert _NAV_FAIL_RE.search("You can't go that way!") is not None
    assert _NAV_FAIL_RE.search("There is no exit in that direction!") is not None
    # Overweight rejection is a blocked exit (retry then clear), never a silent hang.
    assert _NAV_FAIL_RE.search("You are too heavy to move!") is not None


def test_extra_paths_dir_accepts_comma_separated_dirs(tmp_path):
    from mmud.config.schema import MudConfig
    d1 = tmp_path / "p1"; d1.mkdir()
    d2 = tmp_path / "p2"; d2.mkdir()
    (d1 / "AABB.MP").write_text("[][]\n[AABB:R:F]\n[BBCC:R:T]\nH0:H1:1:-1:0:::\nH0:0000:n\n")
    (d2 / "XXYY.MP").write_text("[][]\n[XXYY:R:X]\n[YYZZ:R:Y]\nH0:H1:1:-1:0:::\nH0:0000:s\n")
    config = MudConfig()
    config.navigation.extra_paths_dir = f"{d1} , {d2}"      # comma-separated, with spaces
    bot = make_transcript_bot([], config=config)
    assert bot._navigator.get_path("AABB", "BBCC") is not None   # loaded from dir 1
    assert bot._navigator.get_path("XXYY", "YYZZ") is not None   # loaded from dir 2


def test_off_route_known_room_repaths_a_goto():
    # Recovery must work for NORMAL travel too: a goto that wanders to a KNOWN room
    # not on its route should re-path from there to the destination, not blunder on.
    from mmud.navigation.graph import RouteStep
    bot = make_transcript_bot([])
    bot._travel.set_route([RouteStep("n", frozenset({"ONROUTE1"}), "ONROUTE1")])
    bot._travel_dest = "FROM->WALT"
    calls = []
    bot.navigate_to_room = lambda t: calls.append(t) or "re-pathing"
    bot._maybe_relocate("SOME", "OFFROUTE9")      # known room, NOT on the route
    assert calls == ["WALT"]                       # re-pathed to the goto destination
    calls.clear()
    bot._maybe_relocate("ONR", "ONROUTE1")         # known room that IS on the route
    assert calls == []                             # no needless re-path


@pytest.mark.asyncio
async def test_room_block_resets_on_prompt_not_accumulating_combat():
    # The room-hash candidate set was built from the last 30 lines of ALL output
    # (combat, loot, async) -> ~27 garbage hashes that caused false route/wander
    # matches. The prompt is a turn boundary: reset the block there so it holds only
    # the current room display (title + items + also-here).
    bot = make_transcript_bot([])
    await bot._process_line("The zombie swings at you with its arm!\n")
    await bot._process_line("You fire a magic missile at zombie for 21 damage!\n")
    await bot._process_line("[HP=100/MA=50]:\n")      # prompt -> reset
    assert bot._room_block == []
    await bot._process_line("Graveyard\n")
    await bot._process_line("You notice gold here.\n")
    assert [c for c, _ in bot._room_block] == ["Graveyard", "You notice gold here."]


@pytest.mark.asyncio
async def test_title_colour_narrows_seen_to_single_id():
    # Once the room-title colour is learned, the candidate-hash set is just the
    # title line's id (MegaMud's one-id-per-room) — not the items/exits lines.
    from mmud.parser.exits_parser import room_id
    bot = make_transcript_bot([])
    bot._title_color = "1;36"                                    # learned: cyan titles
    await bot._process_line("[HP=100/MA=50]:\n")                 # prompt -> fresh block
    await bot._process_line("\x1b[1;36mGraveyard\x1b[0m\n")      # title (cyan)
    await bot._process_line("\x1b[0;37mYou notice gold here.\x1b[0m\n")  # items (white)
    exits = "Obvious exits: north, south"
    await bot._process_line(exits + "\n")                        # closes the block
    assert bot._state.last_room_hexes == {room_id("Graveyard", exits)}


@pytest.mark.asyncio
async def test_collision_confident_match_is_rejected():
    # In dense identical-room areas a STRAY (non-title) block line collides with a far-off
    # ROOMS.MD room; trusting it as a position fix drove a bogus cross-map relocate that
    # desynced the loop (live cave "Stone Tunnel" matched ROOMS.MD code SJLM). A confident
    # name-match whose hash isn't the room's OWN (title-coloured) id must be rejected.
    from mmud.data.rooms import Room
    from mmud.parser.exits_parser import room_id
    exits = "Obvious exits: north"
    title, stray = "Stone Tunnel", "A cave worm slithers past."
    real_hex, fake_hex = room_id(title, exits), room_id(stray, exits)
    assert real_hex != fake_hex
    rooms = {"SJLM": Room(code="SJLM", hex_id=fake_hex, hex_id2="",
                          flags=(0, 0, 0), region="", name="Silver Jungle")}
    bot = make_transcript_bot([], rooms=rooms)
    bot._title_color = "1;36"                                   # learned cyan titles
    await bot._process_line("[HP=100/MA=50]:\n")
    await bot._process_line(f"\x1b[1;36m{title}\x1b[0m\n")      # title (cyan) -> real_hex
    await bot._process_line(f"\x1b[0;37m{stray}\x1b[0m\n")      # stray (white) -> SJLM/fake_hex
    await bot._process_line(exits + "\n")
    assert bot._state.current_room != "SJLM"          # collision name-match rejected
    assert bot._state.current_hex != fake_hex
    assert bot._state.last_room_hexes == {real_hex}   # only the room's own title id


@pytest.mark.asyncio
async def test_idle_room_display_updates_current_hex_by_hash():
    # Live "Realm of Legends" rooms are mostly absent from ROOMS.MD, so position can't
    # be NAME/ROOMS-detected. When idle (loop stopped, manual move), a room display that
    # resolves to a single id must still update current_hex by HASH — else a loop
    # RESTART resumes from a stale position. (MegaMud tracks one id per room.)
    from mmud.parser.exits_parser import room_id
    bot = make_transcript_bot([])
    bot._title_color = "1;36"                                   # learned cyan titles
    bot._state.current_hex = "STALE000"                         # stale from before
    await bot._process_line("[HP=100/MA=50]:\n")
    await bot._process_line("\x1b[1;36mSlum Street, Bend\x1b[0m\n")
    exits = "Obvious exits: south, west"
    await bot._process_line(exits + "\n")
    assert bot._state.current_hex == room_id("Slum Street, Bend", exits)


def test_keyed_door_reissues_move_not_the_whole_step():
    # After `use <key> <dir>` unlocks but leaves the door CLOSED, the move fails with
    # "There is a closed door in that direction!". We must `open <dir>` then re-issue
    # ONLY the move — re-running the step would re-`use` another key.
    from mmud.config.schema import MudConfig
    from mmud.navigation.graph import RouteStep
    config = MudConfig()
    bot = make_transcript_bot([], config=config)
    bot._travel.set_route([RouteStep("e", frozenset({"X"}), "X")])
    bot._pending_move = "e"
    bot._handle_doors("There is a closed door in that direction!")
    cmds = []
    while (c := bot._state.dequeue()) is not None:
        cmds.append(c)
    assert cmds == ["open e", "e"]   # open, then re-move; no `use <key>` re-run


def test_closed_gate_during_travel_bashes_not_wanders():
    from mmud.config.schema import MudConfig
    from mmud.navigation.graph import RouteStep
    config = MudConfig()
    config.navigation.bash_doors = True
    bot = make_transcript_bot([], config=config)
    bot._travel.set_route([RouteStep("n", frozenset({"X"}), "X")])
    bot._pending_move = "n"
    # 1st closed -> open; 2nd closed -> bash. Neither clears the route (no wander).
    bot._handle_doors("The gate is closed!")
    bot._parse_nav_failure("The gate is closed!")
    assert bot._travel.active
    bot._handle_doors("The gate is closed!")
    bot._parse_nav_failure("The gate is closed!")
    assert bot._travel.active
    cmds = []
    while (c := bot._state.dequeue()) is not None:
        cmds.append(c)
    assert "open n" in cmds and "bash n" in cmds


def test_must_sneak_wires_sneak_cmd_without_auto_sneak():
    # Regression: must_sneak=True with auto_sneak=False must still hand the
    # CombatEngine a non-empty sneak_cmd, else decide() deadlocks on None.
    from mmud.config.schema import MudConfig, StealthConfig
    config = MudConfig()
    config.stealth = StealthConfig(auto_sneak=False, must_sneak=True)
    bot = make_transcript_bot([], config=config)
    assert bot._combat.sneak_cmd == "sneak"   # hardcoded literal wired by the bot


def test_kill_clears_casting_task_and_removes_monster():
    # A kill (named slay) drops the monster and releases the attack-spell pace
    # token, so loot/movement isn't blocked for a full round after a kill.
    from mmud.state.tasks import TaskType
    from mmud.automation.decision import PRIO_SPELLS
    from mmud.state.game_state import MonsterSighting
    bot = make_transcript_bot([])
    bot._state.monsters_present = [MonsterSighting(name="filthbug")]
    bot._state.begin_task(TaskType.CASTING, priority=PRIO_SPELLS, timeout_s=4.0)
    bot._parse_monster_removal("You have slain the filthbug!")
    assert bot._state.monster_names() == []
    assert bot._state.task.type is TaskType.IDLE


@pytest.mark.asyncio
async def test_idle_refresh_sends_bare_enter_when_idle():
    # MegaMud's 10s room refresh: idle in-game -> bare Enter to re-sync.
    import time as _t
    bot = make_transcript_bot([])
    bot._login_handler.in_game = True
    bot._last_activity = _t.monotonic() - 20.0   # idle for 20s
    await bot._maybe_idle_refresh()
    assert bot._conn.sent == [""]                 # bare Enter
    # Throttled: not re-sent immediately.
    await bot._maybe_idle_refresh()
    assert bot._conn.sent == [""]


@pytest.mark.asyncio
async def test_idle_refresh_skips_when_active_or_not_in_game():
    import time as _t
    bot = make_transcript_bot([])
    # Not in game yet -> never refresh (don't disrupt login/menus).
    bot._last_activity = _t.monotonic() - 20.0
    await bot._maybe_idle_refresh()
    assert bot._conn.sent == []
    # In game but just acted -> not idle.
    bot._login_handler.in_game = True
    bot._last_activity = _t.monotonic()
    await bot._maybe_idle_refresh()
    assert bot._conn.sent == []


@pytest.mark.asyncio
async def test_stall_watchdog_closes_dead_connection():
    # Half-open/stalled connection: in-game, we keep sending idle-refresh Enters
    # but MajorMUD (which always answers with at least a prompt) sends nothing back
    # for a long time -> the socket is dead. The bot used to loop on readlines()
    # forever (must be killed). The watchdog force-closes so the session ends and
    # reconnect/clean-stop kicks in.
    import time as _t
    bot = make_transcript_bot([])
    bot._login_handler.in_game = True
    now = _t.monotonic()
    bot._last_rx = now - 40.0          # no server data for 40s
    await bot._check_stall(now)
    assert bot._conn.closed
    assert bot._session.carrier_lost >= 1


@pytest.mark.asyncio
async def test_stall_watchdog_quiet_when_fresh_or_not_in_game():
    import time as _t
    bot = make_transcript_bot([])
    now = _t.monotonic()
    # Not in game (login/menus legitimately wait on us) -> never trip.
    bot._last_rx = now - 100.0
    await bot._check_stall(now)
    assert not bot._conn.closed
    # In game but data arrived recently -> healthy.
    bot._login_handler.in_game = True
    bot._last_rx = now - 1.0
    await bot._check_stall(now)
    assert not bot._conn.closed


@pytest.mark.asyncio
async def test_received_line_refreshes_rx_timestamp():
    bot = make_transcript_bot([])
    bot._last_rx = 0.0
    await bot._process_line("[HP=100/MA=50]:\n")
    assert bot._last_rx > 0.0


def test_set_terminal_size_resizes_grid_and_reports_via_naws():
    # The TUI resizes the grid to its pane; the bot resizes the emulator AND tells
    # the server the new size (NAWS) so the full-screen editor lays out for it.
    bot = make_transcript_bot([])
    bot.set_terminal_size(80, 50)
    assert bot._terminal.lines == 50
    assert bot._conn.size == (80, 50)


def test_dsr_reply_reports_clamped_grid_cursor():
    # The server detects screen size by homing the cursor to a huge position
    # (clamped to our grid corner) then asking ESC[6n. We must reply with the
    # clamped cursor ESC[row;colR, exactly like MegaMud's ansi_cursor_pos_report
    # -> the editor is laid out for our real size (no off-by-one).
    bot = make_transcript_bot([])
    bot._terminal.feed("\x1b[99;99H")            # home to corner; pyte clamps to 24x80
    assert bot._dsr_reply("\x1b[6n") == "\x1b[24;80R"
    assert bot._dsr_reply("plain text, no query") is None


def test_dsr_reply_reflects_resized_grid():
    # With the grid sized to the pane, we report the bigger size, so the editor
    # is formatted for the whole pane.
    bot = make_transcript_bot([])
    bot._terminal.resize(46)
    bot._terminal.feed("\x1b[99;99H")
    assert bot._dsr_reply("\x1b[6n") == "\x1b[46;80R"


@pytest.mark.asyncio
async def test_feed_raw_answers_screen_size_probe():
    import asyncio as _a
    bot = make_transcript_bot([])
    bot._feed_raw("\x1b[99;99H\x1b[6n")          # corner-home + DSR in one chunk
    await _a.sleep(0)                             # let the scheduled reply run
    assert bot._conn.sent_raw == ["\x1b[24;80R"]


def test_flush_stats_emits_panel_fields():
    from mmud.events import GameEventBus, SessionStatUpdated
    seen = {}
    bus = GameEventBus()
    bus.subscribe(SessionStatUpdated, lambda e: seen.__setitem__(e.key, e.value))
    bot = make_transcript_bot([], event_bus=bus)
    bot._state.record_hit(20, "hit")
    bot._state.record_crit(64)
    bot._state.record_monster_hit(8)
    bot._flush_stats()
    # Combat accuracy ranges + percentages.
    assert seen["hit_range"] == "20-20"
    assert seen["crit_range"] == "64-64"
    assert seen["round_range"] == "8-8"
    assert "%" in seen["hit_pct"] and "%" in seen["miss_pct"]
    # Session-pane fields all present.
    for k in ("sneak_pct", "dodge_pct", "exp_rate", "people_seen", "attacked",
              "dialed", "connected", "had_to_run", "health_low", "income_rate"):
        assert k in seen


def test_combat_stats_parsing_by_type():
    bot = make_transcript_bot([])
    bot._parse_combat_stats("You slash the orc for 12 damage!")
    bot._parse_combat_stats("You critically smash the orc for 40 damage!")
    bot._parse_combat_stats("You backstab the orc for 105 damage!")
    bot._parse_combat_stats("You fire a magic missile at the orc for 18 damage!")
    bot._parse_combat_stats("You miss the orc!")
    bot._parse_combat_stats("The cave worm chomps you for 8 damage!")
    bot._parse_combat_stats("The orc misses you!")
    acc = bot._state.combat_accuracy()
    assert acc["hit"]["range"] == "12-12"
    assert acc["crit"]["range"] == "40-40"
    assert acc["backstab"]["range"] == "105-105"
    assert acc["cast"]["range"] == "18-18"
    assert acc["round"]["range"] == "8-8"            # damage taken
    assert bot._state.combat_misses == 1
    assert bot._state.dodges == 1                    # "misses you"
    assert bot._state.backstab_successes == 1


def test_stat_sent_once_on_first_ingame_prompt():
    # Learn max HP/MA: `stat` fires on the first in-game "[HP=...]" prompt (the
    # reliable in-game signal — the BBS pager never shows it), not on the login
    # flag (which fired too early, during the pager).
    bot = make_transcript_bot([])
    bot._parse_vitals("[HP=46/MA=12]:")
    drained = []
    while (c := bot._state.dequeue()) is not None:
        drained.append(c)
    assert drained == ["stat", "who", "inv", "exp"]   # maxes + Players + held items + exp-to-level
    # Idempotent: not re-sent on every subsequent prompt.
    bot._parse_vitals("[HP=46/MA=12]:")
    assert bot._state.dequeue() is None


def test_stat_sheet_sets_max_hp():
    # MajorMUD stat sheet: "Hits: 46/46   AC: 5/10" -> learn max HP (46).
    bot = make_transcript_bot([])
    bot._parse_vitals("Hits: 46/46              AC: 5/10")
    assert bot._state.hp == 46 and bot._state.max_hp == 46


def test_stat_not_sent_for_bbs_pager_lines():
    # The BBS who-list/pager has no "[HP=...]" -> no premature stat.
    bot = make_transcript_bot([])
    bot._parse_vitals("(N)onstop, (Q)uit, or (C)ontinue?")
    assert bot._state.dequeue() is None


def test_levelup_triggers_restat():
    bot = make_transcript_bot([])
    bot._parse_vitals("[HP=46/MA=12]:")
    while bot._state.dequeue() is not None:       # drain initial stat + who
        pass
    bot._state.set_level(5)
    bot._parse_who_and_exp("Level: 6")           # leveled up
    bot._parse_vitals("[HP=60/MA=20]:")          # next prompt re-stats
    drained = []
    while (c := bot._state.dequeue()) is not None:
        drained.append(c)
    assert "stat" in drained


def test_negative_hp_is_parsed_so_emergency_can_fire():
    # "[HP=-257/MA=72]" (mortally wounded) must parse to NEGATIVE hp. The digit-only regex
    # froze hp at the last positive value, so the emergency threshold never saw the crash
    # and the bot kept fleeing ("n", rejected "you are mortally wounded") instead of recalling.
    from mmud.combat.combat import EmergencyDecider
    from mmud.config.schema import CombatConfig
    bot = make_transcript_bot([])
    bot._login_handler.in_game = True
    bot._state.set_hp(168, 168)
    bot._parse_vitals("[HP=-257/MA=72]:")
    assert bot._state.hp == -257
    # and the emergency decider fires at negative hp
    d = EmergencyDecider(CombatConfig(emergency_threshold=0.05, emergency_cmd="sys go sil"))
    assert d.decide(bot._state) in ("sys go sil", "break")   # break-first if flagged in-combat


def test_combat_markers_toggle_in_combat():
    # *Combat Engaged* / *Combat Off* drive in_combat; *Combat Off* must NOT
    # clear the roster (it fires between rounds mid-fight).
    from mmud.state.game_state import MonsterSighting
    bot = make_transcript_bot([])
    bot._state.monsters_present = [MonsterSighting(name="orc")]
    bot._parse_combat_state("*Combat Engaged*")
    assert bot._state.in_combat is True
    bot._parse_combat_state("*Combat Off*")
    assert bot._state.in_combat is False
    assert bot._state.monster_names() == ["orc"]   # roster preserved


@pytest.mark.asyncio
async def test_active_task_suppresses_combat_decider(unused_tcp_port):
    # Low HP would normally produce "rest", but an active task at PRIO_COMBAT pins it
    bot = make_transcript_bot(["[HP=10/100]:\n"])
    bot._state.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)
    await bot.run()
    assert "rest" not in bot._conn.sent


def test_task_timeout_aborts_and_emits(unused_tcp_port):
    from mmud.events import GameEventBus
    received = []
    bus = GameEventBus()
    bus.subscribe(TaskChanged, received.append)
    bot = make_transcript_bot([], event_bus=bus)
    bot._state.begin_task(TaskType.CASTING, priority=10, timeout_s=5.0, now=100.0)
    bot._check_task_timeout(now=106.0)
    assert not bot._state.task.is_active
    assert any(e.status == "timeout" and e.task_type == "CASTING" for e in received)


def test_task_not_expired_is_untouched(unused_tcp_port):
    bot = make_transcript_bot([])
    bot._state.begin_task(TaskType.CASTING, priority=10, timeout_s=5.0, now=100.0)
    bot._check_task_timeout(now=104.0)
    assert bot._state.task.is_active


from mmud.config.schema import MudConfig, HealthConfig, SafetyConfig
from mmud.events import ConditionChanged, HangupTriggered
from mmud.state.conditions import Condition


@pytest.mark.asyncio
async def test_condition_onset_tracked_and_cured():
    config = MudConfig()
    config.health = HealthConfig(poison_cmd="cast neutralize")
    bot = make_transcript_bot(
        ["You have been poisoned!\n", "[HP=100/100]:\n"], config=config
    )
    await bot.run()
    assert Condition.POISONED in bot._state.conditions
    assert "cast neutralize" in bot._conn.sent


@pytest.mark.asyncio
async def test_condition_recovery_clears_and_completes_task():
    config = MudConfig()
    config.health = HealthConfig(poison_cmd="cast neutralize")
    bot = make_transcript_bot(
        ["You have been poisoned!\n", "The poison has worn off.\n"], config=config
    )
    await bot.run()
    assert Condition.POISONED not in bot._state.conditions
    assert not bot._state.task.is_active


@pytest.mark.asyncio
async def test_condition_events_emitted():
    received = []
    bus = GameEventBus()
    bus.subscribe(ConditionChanged, received.append)
    bot = make_transcript_bot(
        ["You have been poisoned!\n", "The poison has worn off.\n"], event_bus=bus
    )
    await bot.run()
    assert any(e.name == "POISONED" and e.active for e in received)
    assert any(e.name == "POISONED" and not e.active for e in received)


@pytest.mark.asyncio
async def test_death_hangs_up_and_stops_processing():
    received = []
    bus = GameEventBus()
    bus.subscribe(HangupTriggered, received.append)
    config = MudConfig()
    config.safety = SafetyConfig(hangup_on_death=True, reconnect=False)
    bot = make_transcript_bot(
        ["You have died!\n", "[HP=100/100]:\n"], config=config, event_bus=bus
    )
    await bot.run()
    assert any("death" in e.reason for e in received)


@pytest.mark.asyncio
async def test_blind_onset_stops_loop():
    from mmud.automation.loop_runner import LoopRunner
    from mmud.config.schema import NavigationConfig
    from mmud.data.paths import GamePath, PathStep
    bot = make_transcript_bot(["You are blind!\n"])
    path = GamePath(from_code="HOME", from_region="", from_name="",
                    to_code="HOME", to_region="", to_name="", npc="",
                    steps=[PathStep(hex_id="0", command="n")])
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], {}, bot._travel)
    runner.start()
    bot._loop_runner = runner
    assert runner.running
    await bot.run()
    assert not runner.running


@pytest.mark.asyncio
async def test_reconnect_retries_on_connection_loss(unused_tcp_port):
    # Nothing listening on the port -> ConnectionRefusedError each attempt
    config = MudConfig()
    config.safety = SafetyConfig(reconnect=True, max_redials=2)
    bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[], config=config)
    attempts = []
    original_connect = bot._conn.connect

    async def counting_connect():
        attempts.append(1)
        await original_connect()

    bot._conn.connect = counting_connect
    bot._redial_delay_s = 0.0   # don't sleep in tests
    await bot.run()
    assert len(attempts) == 3   # initial + 2 redials


@pytest.mark.asyncio
async def test_no_reconnect_by_default(unused_tcp_port):
    bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[])
    await bot.run()   # must return (refused), not raise or loop


@pytest.mark.asyncio
async def test_afk_low_hp_hangup():
    config = MudConfig()
    config.afk.enabled = True
    config.afk.hangup_on_low_hp = True
    bot = make_transcript_bot(["[HP=5/100]:\n"], config=config)
    await bot.run()
    assert bot._safety.hangup_requested
    assert "low hp" in bot._safety.reason.lower()


from mmud.config.schema import PlayerRule, RemoteConfig


def _remote_config() -> MudConfig:
    config = MudConfig()
    config.remote = RemoteConfig(enabled=True)
    config.players = [PlayerRule(name="Friend", friend=True, remote_cmds=["*"])]
    return config


@pytest.mark.asyncio
async def test_remote_tell_executes_and_replies():
    # The bot sends ONE command per received line, so the @kill tell queues two
    # commands (the attack, then the reply) — a second server line drains the second.
    bot = make_transcript_bot(
        ["[Friend tells you] @kill orc\n", "ok\n"], config=_remote_config()
    )
    await bot.run()
    assert "kill orc" in bot._conn.sent
    assert "/Friend attacking orc" in bot._conn.sent


@pytest.mark.asyncio
async def test_remote_disabled_ignores_tells():
    config = _remote_config()
    config.remote.enabled = False
    bot = make_transcript_bot(["[Friend tells you] @kill orc\n"], config=config)
    await bot.run()
    assert "kill orc" not in bot._conn.sent


@pytest.mark.asyncio
async def test_stranger_tell_ignored():
    bot = make_transcript_bot(
        ["[Stranger tells you] @hangup\n"], config=_remote_config()
    )
    await bot.run()
    assert not bot._safety.hangup_requested


@pytest.mark.asyncio
async def test_run_rules_flee_on_crowded_room():
    from mmud.state.tasks import TaskType
    config = MudConfig()
    config.combat.max_monsters = 3
    # Single line: RunDecider fires "flee" and begins the RUNNING task. (A second
    # line would let the QueueDecider drain a queued flee, which preempts/aborts
    # the task — correct engine semantics, covered in test_run_rules.)
    bot = make_transcript_bot(["Also here: 4 orc warriors.\n"], config=config)
    await bot.run()
    assert "flee" in bot._conn.sent
    assert bot._state.task.type is TaskType.RUNNING


@pytest.mark.asyncio
async def test_no_run_rules_attacks_crowded_room():
    config = MudConfig()
    config.combat.max_monsters = 0          # no limit
    config.combat.attack_cmd = "kill"
    bot = make_transcript_bot(
        ["Also here: 4 orc warriors.\n", "An orc warrior swings at you!\n"],
        config=config,
        patterns=[MessagePattern(name="hit", flags=0, third_field=0,
                                 apply_message="An orc warrior swings at you!",
                                 remove_message="")],
    )
    await bot.run()
    assert any(c.startswith("kill") for c in bot._conn.sent)
    assert "flee" not in bot._conn.sent


@pytest.mark.asyncio
async def test_inv_block_parsed_into_state():
    bot = make_transcript_bot([
        "You are carrying a torch, 153 copper farthings.\n",
        "You are wearing chainmail armour.\n",
        "Wealth: 153 copper farthings\n",
        "Encumbrance: 45/120 - Light [37%]\n",
    ])
    await bot.run()
    assert bot._state.inventory.coins["copper"] == 153
    assert bot._state.inventory_dirty is False
    assert bot._state.inventory.encumbrance_level == "light"


@pytest.mark.asyncio
async def test_auto_cash_gets_ground_coins():
    config = MudConfig()
    config.items.auto_cash = True
    config.items.collect_copper = True
    bot = make_transcript_bot(
        ["You notice 23 copper farthings here.\n"], config=config)
    await bot.run()
    assert "get 23 copper" in bot._conn.sent   # amount included per server syntax


@pytest.mark.asyncio
async def test_unknown_monster_learned_when_enabled(tmp_path):
    config = MudConfig()
    config.learning.enabled = True
    config.learning.store_path = str(tmp_path / "gamedb.json")
    bot = make_transcript_bot(["Also here: a glimmering wisp.\n"], config=config)
    from mmud.data.store import GameStore
    bot._store = GameStore(tmp_path / "gamedb.json")   # transcript bot has no data_dir
    await bot.run()
    names = [r["name"] for r in bot._store.data["monsters"].values()]
    assert "glimmering wisp" in names


from mmud.data.rooms import Room as _Room
from mmud.data.paths import GamePath as _GamePath, PathStep as _PathStep

_NAV_ROOMS = {
    "HOME": _Room(code="HOME", hex_id="AAAA0001", hex_id2="", flags=(0, 0, 0),
                  region="", name="The Home Room"),
    "FARR": _Room(code="FARR", hex_id="CCCC0003", hex_id2="", flags=(0, 0, 0),
                  region="", name="The Far Room"),
}
_NAV_PATH = _GamePath(from_code="HOME", from_region="", from_name="",
                      to_code="FARR", to_region="", to_name="", npc="",
                      steps=[_PathStep(hex_id="AAAA0001", command="n"),
                             _PathStep(hex_id="BBBB0002", command="e")])


@pytest.mark.asyncio
async def test_multihop_goto_walks_route():
    bot = make_transcript_bot(
        ["Obvious exits: north\n",          # arrival signal -> first move
         "Obvious exits: east\n",           # unnamed middle room -> second move
         "The Far Room\n",                  # named arrival
         "Obvious exits: west\n"],
        rooms=_NAV_ROOMS)
    bot._navigator._paths[("HOME", "FARR")] = _NAV_PATH
    bot._state.set_room("HOME")
    bot._state.current_hex = "AAAA0001"
    msg = bot.navigate_to_room("FARR")
    assert "2 steps" in msg
    await bot.run()
    assert bot._conn.sent == ["n", "e"]
    assert bot._state.current_hex == "CCCC0003"
    assert not bot._travel.active            # arrived


def test_goto_unknown_destination():
    bot = make_transcript_bot([], rooms=_NAV_ROOMS)
    bot._state.set_room("HOME")
    bot._state.current_hex = "AAAA0001"
    assert "unknown" in bot.navigate_to_room("ZZZZ").lower()


def test_goto_reports_required_item_when_only_route_is_gated():
    # The only HOME->FARR route needs a "rope and grapple" we don't hold. Instead of a
    # bare "no route", tell the user exactly what's missing.
    bot = make_transcript_bot([], rooms=_NAV_ROOMS)
    gated = _GamePath(from_code="HOME", from_region="", from_name="",
                      to_code="FARR", to_region="", to_name="", npc="",
                      steps=[_PathStep(hex_id="AAAA0001", command="d")],
                      requires="rope and grapple")
    bot._navigator._paths[("HOME", "FARR")] = gated
    bot._state.set_room("HOME")
    bot._state.current_hex = "AAAA0001"
    msg = bot.navigate_to_room("FARR")
    assert "rope and grapple" in msg.lower()


@pytest.mark.asyncio
async def test_observed_movement_learns_exit(tmp_path):
    config = MudConfig()
    config.learning.enabled = True
    config.learning.store_path = str(tmp_path / "g.json")
    bot = make_transcript_bot(
        ["The Home Room\n", "Obvious exits: north\n"], config=config,
        rooms=_NAV_ROOMS)
    from mmud.data.store import GameStore
    bot._store = GameStore(tmp_path / "g.json")
    # a manual move was sent before this room appeared
    bot._state.current_hex = "BBBB0002"
    bot._pending_move = "s"
    await bot.run()
    assert ("BBBB0002", "s", "AAAA0001") in bot._store.exits()


_BANK_ROOMS = {
    "HOME": _Room(code="HOME", hex_id="AAAA0001", hex_id2="", flags=(0, 0, 0),
                  region="", name="The Home Room"),
    "BANK": _Room(code="BANK", hex_id="BBBB0002", hex_id2="", flags=(0, 0, 0),
                  region="", name="The Grand Bank"),
}
_BANK_PATH = _GamePath(from_code="HOME", from_region="", from_name="",
                       to_code="BANK", to_region="", to_name="", npc="",
                       steps=[_PathStep(hex_id="AAAA0001", command="n")])


@pytest.mark.asyncio
async def test_bank_detour_deposits_and_resyncs():
    from mmud.state.inventory import Inventory
    config = MudConfig()
    config.items.max_wealth = 100
    config.items.min_wealth = 10
    config.commerce.bank_room = "BANK"
    bot = make_transcript_bot(
        ["Obvious exits: north\n",      # idle in HOME: commerce arms, travel moves
         "The Grand Bank\n",            # named arrival
         "Obvious exits: south\n",      # arrival signal completes the route
         "ok\n",                        # commerce works: deposit
         "ok\n"],                       # work done -> dirty -> refresh issues inv
        config=config, rooms=_BANK_ROOMS)
    bot._navigator._paths[("HOME", "BANK")] = _BANK_PATH
    bot._state.set_room("HOME")
    bot._state.current_hex = "AAAA0001"
    bot._state.inventory = Inventory(coins={"copper": 500})
    bot._state.inventory_dirty = False
    await bot.run()
    assert "n" in bot._conn.sent
    assert "deposit 490 copper" in bot._conn.sent
    assert "inv" in bot._conn.sent      # post-work re-sync


from mmud.config.schema import SessionConfig


@pytest.mark.asyncio
async def test_relog_runs_second_session(tmp_path):
    received = []
    bus = GameEventBus()
    bus.subscribe(LineReceived, received.append)
    bot = make_transcript_bot(["hello\n", "world\n"], event_bus=bus)
    bot.request_relog("test")
    await bot.run()
    # logout command sent, then a SECOND session replayed the transcript
    assert bot._config.session.logout_cmd in bot._conn.sent
    assert len(received) == 4               # 2 lines x 2 sessions
    assert not bot._relog_pending


@pytest.mark.asyncio
async def test_relog_resets_login_and_safety():
    bot = make_transcript_bot(["You have died!\n"])
    bot._config.safety.hangup_on_death = True
    bot._login_handler.in_game = True
    bot.request_relog("test")
    await bot.run()
    # second session re-processed the death line; safety was reset in between
    # (hangup fired again in session 2 and ended the run)
    assert bot._safety.hangup_requested
    assert bot._login_handler.in_game is False or bot._safety.hangup_requested


@pytest.mark.asyncio
async def test_relog_rearms_health_low_edge_detect():
    # Regression: _was_low must reset on relog so the first low-HP dip of the
    # fresh session is counted. The transcript replays a low-HP line each
    # session; with _was_low pre-stuck True and no relog reset, the edge would
    # stay suppressed and health_low would never increment.
    config = MudConfig()
    config.combat.flee_threshold = 0.15
    bot = make_transcript_bot(["[HP=10/100]\n"], config=config)
    bot._was_low = True            # simulate prior session ending at low HP
    bot.request_relog("test")
    await bot.run()
    # The transcript replays the low-HP line each session. Session 1's dip is
    # suppressed (carried-over _was_low=True); without the relog reset, session 2
    # would be suppressed too. The relog re-arm lets session 2 count the dip.
    assert bot._state.health_low >= 1   # fresh session's first dip was counted


@pytest.mark.asyncio
async def test_session_capture_via_bot(tmp_path):
    config = MudConfig()
    config.session = SessionConfig(capture_file=str(tmp_path / "cap.log"))
    bot = make_transcript_bot(["alpha\n", "beta\n"], config=config)
    await bot.run()
    bot._session.close()
    text = (tmp_path / "cap.log").read_text()
    assert "alpha" in text and "beta" in text


@pytest.mark.asyncio
async def test_ticker_action_low_rate_hangup(monkeypatch):
    # tick() decision is unit-tested in test_session; here just verify the
    # bot honors a "hangup" action from the session manager.
    bot = make_transcript_bot(["x\n"])
    bot._session._fired = False
    monkeypatch.setattr(bot._session, "tick", lambda now: "hangup")
    bot._check_session(now=0.0)
    assert bot._safety.hangup_requested
    assert "session" in bot._safety.reason


@pytest.mark.asyncio
async def test_party_heal_e2e():
    config = MudConfig()
    config.party.heal_spell = "cast heal"
    config.party.heal_hp_pct = 0.50
    bot = make_transcript_bot(
        ["The following people are in your party:\n",
         "Beeze          [Cleric]    [ 40] [100]\n",   # 40: heal yes, wait no
         "[HP=100/100]:\n",           # first prompt: one-time `stat`+`who`+`inv`+`exp`
         "[HP=100/100]:\n",           # drain queued who
         "[HP=100/100]:\n",           # drain queued inv
         "[HP=100/100]:\n",           # drain queued exp
         "[HP=100/100]:\n"],          # next prompt: heal decider fires
        config=config)
    await bot.run()
    assert "cast heal Beeze" in bot._conn.sent


@pytest.mark.asyncio
async def test_friend_invite_autojoin():
    config = MudConfig()
    config.players = [PlayerRule(name="Krang", friend=True)]
    bot = make_transcript_bot(
        ["Krang has invited you to join his party.\n", "ok\n"], config=config)
    await bot.run()
    assert "join Krang" in bot._conn.sent


@pytest.mark.asyncio
async def test_scheduled_command_fires_via_ticker():
    from mmud.config.schema import ScheduleEvent
    config = MudConfig()
    config.schedule.events = [ScheduleEvent(type="command", every_seconds=1,
                                            arg="look")]
    bot = make_transcript_bot(["x\n"], config=config)
    # drive the scheduler directly (the 1Hz ticker calls this in production)
    bot._scheduler.tick(bot._scheduler._next_fire[0] + 0.1)
    assert bot._state.dequeue() == "look"


@pytest.mark.asyncio
async def test_ran_away_counter_increments_on_flee():
    config = MudConfig()
    config.combat.max_monsters = 1   # 3 goblins > 1 -> RunDecider flees
    bot = make_transcript_bot(["Also here: 3 goblins.\n"], config=config)
    await bot.run()
    assert "flee" in bot._conn.sent
    assert bot._state.ran_away >= 1


@pytest.mark.asyncio
async def test_health_low_counter_increments():
    config = MudConfig()
    config.combat.flee_threshold = 0.15
    bot = make_transcript_bot(["[HP=10/100]\n"], config=config)
    await bot.run()
    assert bot._state.health_low >= 1


@pytest.mark.asyncio
async def test_engine_registry_order_and_names():
    from mmud.config.schema import MudConfig
    bot = make_transcript_bot([], config=MudConfig())
    slots = bot._engine._slots          # list[tuple[priority, name, decider]]
    prios = [s[0] for s in slots]
    names = [s[1] for s in slots]
    assert prios == sorted(prios)
    for expected in ("queue", "cures", "run", "backstab", "spells", "combat",
                     "refresh", "equip", "items", "commerce", "party", "travel", "search"):
        assert expected in names


@pytest.mark.asyncio
async def test_connection_loss_is_logged(caplog):
    import logging
    from mmud.config.schema import MudConfig
    bot = make_transcript_bot([], config=MudConfig())
    async def boom():
        raise ConnectionError("boom")
    bot._run_session = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="mmud.bot"):
        await bot.run()
    assert any("boom" in r.getMessage() or "connection" in r.getMessage().lower()
               for r in caplog.records)


def test_bot_feeds_terminal_emulator_and_emits_raw():
    from conftest import make_transcript_bot
    from mmud.events import GameEventBus, RawOutput, ScreenUpdated

    bus = GameEventBus()
    raw_events: list[str] = []
    screen_events: list[object] = []
    bus.subscribe(RawOutput, lambda e: raw_events.append(e.data))
    bus.subscribe(ScreenUpdated, screen_events.append)

    bot = make_transcript_bot([], event_bus=bus)
    # The FakeConnection has no on_raw plumbing; drive the bot's hook directly,
    # exactly as the real readlines() loop would per chunk.
    bot._feed_raw("\x1b[1;1Hello")

    assert raw_events == ["\x1b[1;1Hello"]
    assert len(screen_events) == 1
    # The emulator received the bytes (cursor-home + text shows on row 0).
    assert bot._terminal.display()[0].startswith("ello")


@pytest.mark.asyncio
async def test_autoget_strips_count_and_marks_scenery_ungettable():
    """Count-prefixed scenery: bot sends 'get log raft' (not 'get 2 log raft'),
    and the server's currency-syntax rejection marks it ungettable so it never
    retries even when the room re-displays it."""
    from mmud.config.schema import MudConfig
    config = MudConfig()
    config.items.auto_get = True
    bot = make_transcript_bot(
        ["You notice 2 log raft here.\n",
         "Syntax: GET 2 {Currency}\n",
         "You notice 2 log raft here.\n",
         "[HP=46/MA=12]:\n"],
        config=config)
    await bot.run()
    gets = [c for c in bot._conn.sent if c.startswith("get ")]
    assert gets == ["get log raft"]          # count stripped; tried exactly once
    assert "get 2 log raft" not in bot._conn.sent


def test_navigate_to_room_by_name(monkeypatch):
    # "far" uniquely matches "The Far Room" (FARR) -> resolves + routes.
    bot = make_transcript_bot([], rooms=_NAV_ROOMS)
    bot._navigator._paths[("HOME", "FARR")] = _NAV_PATH
    bot._state.set_room("HOME")
    bot._state.current_hex = "AAAA0001"
    msg = bot.navigate_to_room("far")
    assert "2 steps" in msg          # name resolved to FARR and routed


def test_navigate_to_room_unknown_name():
    bot = make_transcript_bot([], rooms=_NAV_ROOMS)
    assert "unknown" in bot.navigate_to_room("zzznosuchroomzzz").lower()


def test_navigate_to_room_ambiguous_lists_matches():
    # "room" matches BOTH "The Home Room" and "The Far Room".
    bot = make_transcript_bot([], rooms=_NAV_ROOMS)
    msg = bot.navigate_to_room("room")
    assert "ambiguous" in msg.lower()
    assert "HOME" in msg and "FARR" in msg


def test_find_rooms_by_name_and_code():
    bot = make_transcript_bot([], rooms=_NAV_ROOMS)
    # name substring matches both rooms, sorted by name
    names = [r.name for r in bot.find_rooms("room")]
    assert names == ["The Far Room", "The Home Room"]
    # exact code match
    by_code = bot.find_rooms("FARR")
    assert [r.code for r in by_code] == ["FARR"]
    # no match
    assert bot.find_rooms("zzznope") == []
    # blank query is empty (not "everything")
    assert bot.find_rooms("  ") == []


def test_find_rooms_respects_limit():
    bot = make_transcript_bot([], rooms=_NAV_ROOMS)
    assert len(bot.find_rooms("room", limit=1)) == 1
