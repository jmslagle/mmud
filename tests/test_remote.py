import pytest
from mmud.automation.remote import RemoteCommandHandler
from mmud.bot import MudBot
from mmud.config.schema import MudConfig, PlayerRule


def _bot(rules: list[PlayerRule]) -> MudBot:
    config = MudConfig()
    config.players = rules
    bot = MudBot("test", 0, patterns=[], config=config)
    return bot


def _handler(rules: list[PlayerRule]) -> RemoteCommandHandler:
    return RemoteCommandHandler(_bot(rules))


WILDCARD = [PlayerRule(name="Friend", friend=True, remote_cmds=["*"])]


def test_unknown_sender_denied_silently():
    h = _handler(WILDCARD)
    assert h.handle("Stranger", "@status") is None


def test_known_sender_without_verb_gets_denied_reply():
    h = _handler([PlayerRule(name="Friend", remote_cmds=["status"])])
    assert h.handle("Friend", "@stop") == "permission denied"


def test_wildcard_allows_everything():
    h = _handler(WILDCARD)
    reply = h.handle("Friend", "@status")
    assert reply is not None and reply != "permission denied"


def test_sender_match_is_case_insensitive():
    h = _handler(WILDCARD)
    assert h.handle("fRiEnD", "@status") is not None


def test_non_at_text_ignored():
    h = _handler(WILDCARD)
    assert h.handle("Friend", "hello there") is None


def test_unknown_verb_ignored():
    h = _handler(WILDCARD)
    assert h.handle("Friend", "@frobnicate") is None


def test_health_reports_vitals():
    bot = _bot(WILDCARD)
    bot._state.set_hp(50, 100)
    bot._state.set_mana(20, 40)
    h = RemoteCommandHandler(bot)
    assert h.handle("Friend", "@health") == "HP 50/100 MP 20/40"


def test_kill_enqueues_attack():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@kill orc warrior")
    assert reply == "attacking orc warrior"
    assert bot._state.dequeue() == "kill orc warrior"


def test_kill_without_target_returns_usage():
    h = _handler(WILDCARD)
    assert "usage" in h.handle("Friend", "@kill").lower()


def test_stop_calls_stop_all():
    bot = _bot(WILDCARD)
    bot._state.enqueue("n")
    h = RemoteCommandHandler(bot)
    h.handle("Friend", "@stop")
    assert bot._state.dequeue() is None   # queue cleared


def test_hangup_requests_safety_hangup():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    assert h.handle("Friend", "@hangup") == "hanging up"
    assert bot._safety.hangup_requested
    assert "Friend" in bot._safety.reason


def test_panic_sends_panic_cmd_then_hangs_up():
    bot = _bot(WILDCARD)
    bot._config.safety.panic_cmd = "recall"
    h = RemoteCommandHandler(bot)
    h.handle("Friend", "@panic!")
    assert bot._state.dequeue() == "recall"
    assert bot._safety.hangup_requested


def test_auto_sneak_toggle():
    bot = _bot(WILDCARD)
    assert bot._config.stealth.auto_sneak is False
    h = RemoteCommandHandler(bot)
    assert h.handle("Friend", "@auto-sneak") == "auto_sneak on"
    assert bot._config.stealth.auto_sneak is True
    assert h.handle("Friend", "@auto-sneak off") == "auto_sneak off"
    assert bot._config.stealth.auto_sneak is False


def test_custom_verb_registration():
    h = _handler(WILDCARD)
    h.register("wealth", lambda sender, arg: "1234 copper")
    assert h.handle("Friend", "@wealth") == "1234 copper"


def test_wealth_verb():
    from mmud.state.inventory import Inventory
    bot = _bot(WILDCARD)
    bot._state.inventory = Inventory(coins={"gold": 3, "copper": 7})
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@wealth")
    assert "307" in reply        # 3*100 + 7 copper-equivalent


def test_db_verb_reports_store_stats():
    bot = _bot(WILDCARD)
    from mmud.data.store import GameStore
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        bot._store = GameStore(pathlib.Path(td) / "g.json")
        bot._store.data["monsters"]["1"] = {"record_id": 1, "name": "rat", "origin": "md"}
        bot._store.data["collisions"].append({"db": "monsters", "record_id": 1})
        h = RemoteCommandHandler(bot)
        reply = h.handle("Friend", "@db")
        assert "1 monsters" in reply and "1 collisions" in reply


def test_db_verb_without_store():
    bot = _bot(WILDCARD)
    bot._store = None
    h = RemoteCommandHandler(bot)
    assert "disabled" in h.handle("Friend", "@db").lower()


def test_relog_verb():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@relog")
    assert "relog" in reply.lower()
    assert bot._relog_pending
    assert bot._state.dequeue() == bot._config.session.logout_cmd


def test_rate_verb():
    bot = _bot(WILDCARD)
    bot._session.on_exp(0, now=0.0)
    bot._session.on_exp(2500, now=1800.0)
    h = RemoteCommandHandler(bot)
    assert "5000" in h.handle("Friend", "@rate")


def test_party_verbs():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    assert h.handle("Friend", "@invite") == "inviting Friend"
    assert bot._state.dequeue() == "invite Friend"
    assert h.handle("Friend", "@wait") == "waiting"
    assert bot._state.dequeue() == bot._config.party.wait_cmd
    assert h.handle("Friend", "@rego") == "resuming"
    assert bot._state.dequeue() == bot._config.party.resume_cmd
    assert h.handle("Friend", "@forget") == "party forgotten"
    assert bot._state.party == []


def test_events_verb():
    from mmud.config.schema import ScheduleEvent
    config = MudConfig()
    config.schedule.events = [ScheduleEvent(type="relog", every_seconds=3600)]
    bot = _bot(WILDCARD)
    bot._config.schedule = config.schedule
    from mmud.automation.scheduler import Scheduler
    bot._scheduler = Scheduler(config.schedule, send=lambda c: None,
                               goto=lambda c: None, start_loop=lambda n: None,
                               relog=lambda: None, logoff=lambda: None,
                               now=lambda: 0.0)
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@events")
    assert "relog" in reply


def test_events_verb_empty():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    assert "no events" in h.handle("Friend", "@events").lower()
