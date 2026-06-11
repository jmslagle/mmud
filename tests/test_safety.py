from mmud.automation.safety import SafetyMonitor
from mmud.config.schema import SafetyConfig


def test_death_triggers_hangup():
    m = SafetyMonitor(SafetyConfig(hangup_on_death=True))
    m.process_line("You have died!")
    assert m.hangup_requested
    assert "death" in m.reason


def test_death_hangup_can_be_disabled():
    m = SafetyMonitor(SafetyConfig(hangup_on_death=False))
    m.process_line("You have died!")
    assert not m.hangup_requested


def test_hangup_player_seen_in_room():
    m = SafetyMonitor(SafetyConfig(hangup_players=["BadGuy"]))
    m.process_line("Also here: BadGuy, an orc warrior.")
    assert m.hangup_requested
    assert "BadGuy" in m.reason


def test_hangup_player_in_conversation_is_ignored():
    # Only room-presence lines count — a tell mentioning the name must not hang up
    m = SafetyMonitor(SafetyConfig(hangup_players=["BadGuy"]))
    m.process_line("[Friend tells you] watch out for BadGuy")
    assert not m.hangup_requested


def test_normal_lines_do_nothing():
    m = SafetyMonitor(SafetyConfig())
    m.process_line("You notice 2 orcs here.")
    m.process_line("[HP=100/100]:")
    assert not m.hangup_requested


def test_manual_request():
    m = SafetyMonitor(SafetyConfig())
    m.request_hangup("remote @hangup from Friend")
    assert m.hangup_requested
    assert m.reason == "remote @hangup from Friend"
