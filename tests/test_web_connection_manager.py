from __future__ import annotations
from mmud.web.server import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent = []
    async def send_json(self, data):
        self.sent.append(data)


async def test_broadcast_reaches_all_clients():
    mgr = ConnectionManager()
    a, b = FakeWS(), FakeWS()
    mgr.add(a); mgr.add(b)
    await mgr.broadcast({"type": "HpChanged", "hp": 10, "max_hp": 20})
    assert a.sent == [{"type": "HpChanged", "hp": 10, "max_hp": 20}]
    assert b.sent == [{"type": "HpChanged", "hp": 10, "max_hp": 20}]


async def test_remove_stops_delivery():
    mgr = ConnectionManager()
    a = FakeWS(); mgr.add(a); mgr.remove(a)
    await mgr.broadcast({"type": "x"})
    assert a.sent == []


async def test_dead_client_is_dropped_not_raised():
    class Dead(FakeWS):
        async def send_json(self, data):
            raise RuntimeError("closed")
    mgr = ConnectionManager()
    dead, ok = Dead(), FakeWS()
    mgr.add(dead); mgr.add(ok)
    await mgr.broadcast({"type": "x"})
    assert ok.sent == [{"type": "x"}]
    assert dead not in mgr._clients
