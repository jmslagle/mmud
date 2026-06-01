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
