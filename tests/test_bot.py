import asyncio
import pytest
from mmud.net.connection import MudConnection
from mmud.bot import MudBot
from mmud.data.messages import MessagePattern


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
    assert any("attack" in r for r in received)
