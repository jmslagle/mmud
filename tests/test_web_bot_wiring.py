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
