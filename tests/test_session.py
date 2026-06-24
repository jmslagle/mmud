from mmud.config.schema import SessionConfig
from mmud.session import SessionManager


def _mgr(start=0.0, **cfg):
    return SessionManager(SessionConfig(**cfg), now=lambda: start)


def test_exp_rate_needs_two_samples():
    m = _mgr()
    assert m.exp_rate_per_hour() == 0.0
    m.on_exp(1000, now=0.0)
    assert m.exp_rate_per_hour() == 0.0


def test_exp_rate_per_hour():
    m = _mgr()
    m.on_exp(1000, now=0.0)
    m.on_exp(3000, now=1800.0)          # +2000 exp in 30 min
    assert m.exp_rate_per_hour() == 4000.0


def test_on_exp_gain_accumulates_and_rates():
    m = _mgr()
    m.on_exp_gain(26, now=0.0)           # first kill seeds baseline
    assert m.exp_gained == 26
    assert m.exp_rate_per_hour() == 0.0  # one time point -> no rate yet
    m.on_exp_gain(34, now=1800.0)        # +34 -> total 60 over 30 min
    assert m.exp_gained == 60
    assert m.exp_rate_per_hour() == 120.0  # 60 exp / 0.5h


def test_hours_elapsed():
    m = _mgr(start=0.0)
    assert m.hours_elapsed(7200.0) == 2.0


def test_tick_max_hours_hangup():
    m = _mgr(start=0.0, max_hours_per_day=2)
    assert m.tick(7199.0) is None
    assert m.tick(7200.0) == "hangup"
    assert m.tick(7300.0) is None       # latched: fires once


def test_tick_low_rate_after_grace():
    m = _mgr(start=0.0, min_exp_rate=5000, grace_minutes=15,
             low_rate_action="relog")
    m.on_exp(0, now=0.0)
    m.on_exp(100, now=1800.0)           # 200/hr, well under 5000
    assert m.tick(899.0) is None        # still inside grace (15 min)
    assert m.tick(1800.0) == "relog"
    assert m.tick(1900.0) is None       # latched


def test_tick_rate_ok_no_action():
    m = _mgr(start=0.0, min_exp_rate=1000, grace_minutes=0)
    m.on_exp(0, now=0.0)
    m.on_exp(5000, now=3600.0)          # 5000/hr
    assert m.tick(3600.0) is None


def test_tick_disabled_by_default():
    m = _mgr(start=0.0)
    m.on_exp(0, now=0.0)
    m.on_exp(1, now=36000.0)
    assert m.tick(36000.0) is None


def test_capture_appends_raw_lines(tmp_path):
    cap = tmp_path / "session.log"
    m = SessionManager(SessionConfig(capture_file=str(cap)), now=lambda: 0.0)
    m.on_line("[HP=100/100]:\n")
    m.on_line("An orc swings at you!")     # newline added if missing
    m.close()
    assert cap.read_text() == "[HP=100/100]:\nAn orc swings at you!\n"


def test_no_capture_when_unset(tmp_path):
    m = SessionManager(SessionConfig(), now=lambda: 0.0)
    m.on_line("hello\n")                   # must not crash or create files
    m.close()
    assert list(tmp_path.iterdir()) == []


def test_comms_counters_increment():
    from mmud.config.schema import SessionConfig
    from mmud.session import SessionManager
    m = SessionManager(SessionConfig(), now=lambda: 0.0)
    assert m.dialed == 0
    m.on_dial(); m.on_dial(); m.on_connect(); m.on_dial_failed(); m.on_carrier_lost()
    assert (m.dialed, m.connected, m.dial_failed, m.carrier_lost) == (2, 1, 1, 1)


def test_time_to_level_eta_hours():
    from mmud.config.schema import SessionConfig
    from mmud.session import SessionManager
    m = SessionManager(SessionConfig(), now=lambda: 0.0)
    m.on_exp(0, now=0.0)
    m.on_exp(1000, now=3600.0)
    assert m.time_to_level_hours(exp_to_next=2500) == 2.5


def test_time_to_level_eta_zero_rate():
    from mmud.config.schema import SessionConfig
    from mmud.session import SessionManager
    m = SessionManager(SessionConfig(), now=lambda: 0.0)
    assert m.time_to_level_hours(exp_to_next=2500) == 0.0
