from mmud.automation.scheduler import Scheduler
from mmud.config.schema import ScheduleConfig, ScheduleEvent


class _Harness:
    def __init__(self):
        self.sent, self.gotos, self.loops = [], [], []
        self.relogs = 0
        self.logoffs = 0

    def make(self, *events, t=0.0):
        self.t = t
        return Scheduler(
            ScheduleConfig(events=list(events)),
            send=self.sent.append,
            goto=self.gotos.append,
            start_loop=self.loops.append,
            relog=lambda: setattr(self, "relogs", self.relogs + 1),
            logoff=lambda: setattr(self, "logoffs", self.logoffs + 1),
            now=lambda: self.t,
        )


def test_command_fires_on_interval_with_expansion():
    h = _Harness()
    s = h.make(ScheduleEvent(type="command", every_seconds=60,
                             arg="say hi^M"), t=0.0)
    s.tick(59.0)
    assert h.sent == []
    s.tick(60.0)
    assert h.sent == ["say hi"]              # expanded, trailing CR stripped
    s.tick(61.0)
    assert h.sent == ["say hi"]              # not again until next interval
    s.tick(120.0)
    assert h.sent == ["say hi", "say hi"]


def test_count_limits_fires():
    h = _Harness()
    s = h.make(ScheduleEvent(type="relog", every_seconds=10, count=2), t=0.0)
    s.tick(10.0); s.tick(20.0); s.tick(30.0); s.tick(40.0)
    assert h.relogs == 2                     # count exhausted


def test_goto_loop_logoff_dispatch():
    h = _Harness()
    s = h.make(ScheduleEvent(type="goto", every_seconds=5, arg="BANK"),
               ScheduleEvent(type="loop", every_seconds=7, arg="ORCS"),
               ScheduleEvent(type="logoff", every_seconds=11), t=0.0)
    s.tick(11.0)
    assert h.gotos == ["BANK"]
    assert h.loops == ["ORCS"]
    assert h.logoffs == 1


def test_disabled_event_never_fires():
    h = _Harness()
    s = h.make(ScheduleEvent(type="command", every_seconds=0, arg="x"), t=0.0)
    s.tick(99999.0)
    assert h.sent == []


def test_logon_is_noop_while_connected():
    h = _Harness()
    s = h.make(ScheduleEvent(type="logon", every_seconds=5), t=0.0)
    s.tick(10.0)                             # must not raise or dispatch
    assert h.sent == [] and h.relogs == 0
