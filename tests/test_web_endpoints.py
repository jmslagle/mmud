from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from mmud.events import GameEventBus, HpChanged
from mmud.state.game_state import GameState
from mmud.session import SessionManager
from mmud.config.schema import MudConfig
from mmud.config.runtime import ConfigService
from mmud.web.server import WebPanelServer


class FakeConn:
    def __init__(self):
        self.sent = []
    async def send(self, command):
        self.sent.append(command)


class FakeBot:
    def __init__(self, with_config_service=False):
        self._bus = GameEventBus()
        self._state = GameState()
        self._config = MudConfig()
        self._session = SessionManager(self._config.session, now=lambda: 0.0)
        self._conn = FakeConn()
        if with_config_service:
            self._config_service = ConfigService(self._config, bus=self._bus, path=None)


@pytest.fixture
def fake_bot():
    return FakeBot()


@pytest.fixture
def client(fake_bot):
    return TestClient(WebPanelServer(fake_bot).app)


def test_state_returns_snapshot(client, fake_bot):
    fake_bot._state.set_hp(30, 90)
    fake_bot._state.set_level(12)
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["vitals"]["hp"] == 30
    assert body["vitals"]["max_hp"] == 90
    assert body["progress"]["level"] == 12


def test_command_reaches_send_stub(client, fake_bot):
    r = client.post("/api/command", json={"cmd": "look"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "sent": "look"}
    assert fake_bot._conn.sent == ["look"]


def test_empty_command_rejected(client):
    assert client.post("/api/command", json={"cmd": "   "}).status_code == 400


def test_quicktool_compass(client, fake_bot):
    assert client.post("/api/quicktool", json={"action": "ne"}).status_code == 200
    assert fake_bot._conn.sent == ["ne"]


def test_quicktool_action_button(client, fake_bot):
    assert client.post("/api/quicktool", json={"action": "deposit"}).status_code == 200
    assert fake_bot._conn.sent == ["deposit all"]


def test_quicktool_unknown_400(client):
    assert client.post("/api/quicktool", json={"action": "frobnicate"}).status_code == 400


def test_config_503_when_bot_has_no_service(client):
    # FakeBot() has no _config_service -> 503
    assert client.get("/api/config").status_code == 503


def test_config_get_and_patch_with_service():
    bot = FakeBot(with_config_service=True)
    client = TestClient(WebPanelServer(bot).app)
    got = client.get("/api/config")
    assert got.status_code == 200
    assert got.json()["combat"]["attack_cmd"] == "kill"   # default
    r = client.patch("/api/config", json={"section": "combat", "field": "attack_cmd", "value": "bash"})
    assert r.status_code == 200
    assert bot._config.combat.attack_cmd == "bash"
    assert r.json()["combat"]["attack_cmd"] == "bash"


def test_config_patch_unknown_field_400():
    bot = FakeBot(with_config_service=True)
    client = TestClient(WebPanelServer(bot).app)
    r = client.patch("/api/config", json={"section": "combat", "field": "nope", "value": "x"})
    assert r.status_code == 400


def test_ws_broadcasts_posted_event(client, fake_bot):
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "Snapshot"
        fake_bot._bus.post(HpChanged(hp=5, max_hp=40))
        msg = ws.receive_json()
        assert msg == {"type": "HpChanged", "hp": 5, "max_hp": 40}


def test_ws_broadcasts_raw_output(client, fake_bot):
    from mmud.events import RawOutput

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "Snapshot"
        fake_bot._bus.post(RawOutput(data="\x1b[2J"))
        msg = ws.receive_json()
        assert msg == {"type": "RawOutput", "data": "\x1b[2J"}
