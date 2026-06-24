import re
from mmud.debug_log import SessionLogger

_TS = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} ")


def test_logs_rx_tx_event_with_tags(tmp_path):
    p = tmp_path / "session.log"
    log = SessionLogger(str(p))
    log.rx("Also here: giant rat, kobold thief.")
    log.tx("mmis giant rat")
    log.event("combat=on target=giant rat")
    log.close()
    lines = p.read_text().splitlines()
    assert _TS.match(lines[0]) and lines[0].endswith("RX  Also here: giant rat, kobold thief.")
    assert _TS.match(lines[1]) and lines[1].endswith("TX  mmis giant rat")
    assert _TS.match(lines[2]) and lines[2].endswith("EVT combat=on target=giant rat")


def test_rx_strips_trailing_newline(tmp_path):
    p = tmp_path / "s.log"
    log = SessionLogger(str(p))
    log.rx("a line\n")
    log.close()
    assert p.read_text().splitlines()[0].endswith("RX  a line")


def test_creates_parent_directory(tmp_path):
    # A configured path like "logs/session.log" must not crash when the dir is
    # missing — the logger creates it.
    p = tmp_path / "logs" / "session.log"
    log = SessionLogger(str(p))
    log.rx("hello")
    log.close()
    assert p.exists() and p.read_text().strip().endswith("RX  hello")


def test_disabled_when_no_path(tmp_path):
    # Empty path = off: no file created, calls are no-ops, no error.
    log = SessionLogger("")
    assert not log.enabled
    log.rx("x"); log.tx("y"); log.event("z"); log.close()
    assert list(tmp_path.iterdir()) == []
