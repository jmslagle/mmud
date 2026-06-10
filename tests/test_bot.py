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
