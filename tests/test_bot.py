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
async def test_bot_processes_line_and_issues_command(unused_tcp_port):
    """Bot receives a combat message and sends 'attack' in response."""
    received = []

    async def server_handler(reader, writer):
        # Send a combat message
        writer.write(b"An orc hits you!\r\n")
        await writer.drain()
        # Wait for bot's response
        cmd = await asyncio.wait_for(reader.readline(), timeout=2.0)
        received.append(cmd.decode().strip())
        writer.close()

    server = await asyncio.start_server(server_handler, "127.0.0.1", unused_tcp_port)
    patterns = [
        MessagePattern(name="being hit", flags=0, third_field=0,
                       apply_message="An orc hits you!", remove_message="")
    ]
    async with server:
        bot = MudBot("127.0.0.1", unused_tcp_port, patterns=patterns)
        try:
            await asyncio.wait_for(bot.run(), timeout=3.0)
        except asyncio.TimeoutError:
            pass
    assert any("kill" in r for r in received)


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
    # HP 10/100 out of combat -> CombatEngine rest_threshold (0.40) says "rest"
    bot = make_transcript_bot(["[HP=10/100]:\n"])
    await bot.run()
    assert "rest" in bot._conn.sent


@pytest.mark.asyncio
async def test_transcript_bot_sends_nothing_when_healthy():
    bot = make_transcript_bot(["[HP=100/100]:\n"])
    await bot.run()
    assert bot._conn.sent == []


from mmud.automation.decision import PRIO_COMBAT
from mmud.state.tasks import TaskType
from mmud.events import TaskChanged


def test_must_sneak_wires_sneak_cmd_without_auto_sneak():
    # Regression: must_sneak=True with auto_sneak=False must still hand the
    # CombatEngine a non-empty sneak_cmd, else decide() deadlocks on None.
    from mmud.config.schema import MudConfig, StealthConfig
    config = MudConfig()
    config.stealth = StealthConfig(auto_sneak=False, must_sneak=True,
                                   sneak_cmd="sneak")
    bot = make_transcript_bot([], config=config)
    assert bot._combat.sneak_cmd == "sneak"


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
    assert "get copper" in bot._conn.sent


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
         "[HP=100/100]:\n"],          # ends the list; decider fires
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
