from __future__ import annotations
from mmud.bot import MudBot
from mmud.config.schema import MudConfig, WebConfig
from mmud.events import GameEventBus


def _bot(cfg):
    return MudBot("test", 0, event_bus=GameEventBus(), config=cfg)


def test_no_web_section_means_no_server():
    bot = _bot(MudConfig())                 # web.enabled defaults False
    assert bot.maybe_build_web_server() is None
    assert bot._web_server is None


def test_web_enabled_builds_server():
    cfg = MudConfig()
    cfg.web = WebConfig(enabled=True, host="127.0.0.1", port=8099)
    bot = _bot(cfg)
    server = bot.maybe_build_web_server()
    assert server is not None
    assert bot._web_server is server
    from mmud.events import HpChanged
    assert HpChanged in bot._bus._subscribers
