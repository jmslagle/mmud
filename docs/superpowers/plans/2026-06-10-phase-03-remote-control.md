# Phase 3: Remote Control via Tells (@-commands) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let trusted players drive the bot from another character by sending tells like `@status`, `@loop ORCS`, `@stop`, `@kill orc`, `@hangup` — the original MegaMud's telepath-command system, gated per-player by the existing (unused) `PlayerRule.remote_cmds` config.

**Architecture:** A `RemoteCommandHandler` holds a verb registry (`dict[str, handler]`) so later phases can register their own verbs (@wealth in Phase 5, party verbs in Phase 10, @relog in Phase 9). `MudBot._parse_conversation()` routes tell-channel messages starting with `@` to the handler; permission is checked against `config.players`; replies go back via a configurable tell format. The original supports 47 verbs — this phase implements the 12 that map to existing bot capabilities.

**Tech Stack:** Python 3.11+, stdlib only. Depends on Phase 1 (transcript harness) and Phase 2 (`SafetyMonitor` for @hangup/@panic!).

**Prerequisites:** Phases 1 and 2 complete (`bot._safety` exists, `pytest -q` green).

---

## File Map

```
src/mmud/
  automation/remote.py      NEW — RemoteCommandHandler with verb registry
  config/schema.py          MODIFY — RemoteConfig
  config/loader.py          MODIFY — parse [remote]
  bot.py                    MODIFY — route @-tells to handler
tests/
  test_remote.py            NEW
  test_bot.py               MODIFY — end-to-end transcript test
  test_config.py            MODIFY — [remote] parsing
characters/example.toml     MODIFY — document [remote] + players remote_cmds
README.md                   MODIFY — @-command reference
```

---

### Task 1: RemoteConfig

**Files:**
- Modify: `src/mmud/config/schema.py`, `src/mmud/config/loader.py`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_remote_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[remote]
enabled = true
tell_format = "/{name} {text}"

[[players]]
name = "Friend"
friend = true
remote_cmds = ["*"]
"""
    )
    cfg = load_config(p)
    assert cfg.remote.enabled is True
    assert cfg.remote.tell_format == "/{name} {text}"
    assert cfg.players[0].remote_cmds == ["*"]


def test_remote_disabled_by_default():
    cfg = load_config(None)
    assert cfg.remote.enabled is False
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_config.py -v -k remote`
Expected: FAIL (`AttributeError: 'MudConfig' object has no attribute 'remote'`)

- [ ] **Step 3: Add to `src/mmud/config/schema.py`** (after `SafetyConfig`):

```python
@dataclass
class RemoteConfig:
    enabled: bool = False    # opt-in: remote commands off unless explicitly enabled
    # Reply template; MajorMud telepath syntax. Adjust to the live server's syntax
    # ("/<name> <text>" or "telepath <name> <text>") during in-person testing.
    tell_format: str = "/{name} {text}"
```

Add to `MudConfig` (after `safety`):

```python
    remote: RemoteConfig = field(default_factory=RemoteConfig)
```

- [ ] **Step 4: Add to `src/mmud/config/loader.py`**

Add `RemoteConfig` to the schema imports, then after the `safety` block:

```python
    if r := data.get("remote"):
        cfg.remote = RemoteConfig(
            enabled=r.get("enabled", False),
            tell_format=r.get("tell_format", "/{name} {text}"),
        )
```

- [ ] **Step 5: Run tests, then commit**

Run: `pytest tests/test_config.py -v`
Expected: all pass

```bash
git add src/mmud/config/schema.py src/mmud/config/loader.py tests/test_config.py
git commit -m "feat: [remote] config section — opt-in remote control"
```

---

### Task 2: RemoteCommandHandler with permission gating

**Files:**
- Create: `src/mmud/automation/remote.py`
- Test: `tests/test_remote.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_remote.py
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_remote.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/mmud/automation/remote.py`**

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from mmud.bot import MudBot

# verb handler signature: (sender, arg) -> reply text
VerbHandler = Callable[[str, str], str]


class RemoteCommandHandler:
    """Telepath-command dispatcher, after megamud.exe's say_tell_message_dispatch.

    Verbs are a registry so later phases can add their own
    (@wealth → Phase 5, @relog → Phase 9, @invite/@wait → Phase 10).
    Permission: sender must match a PlayerRule whose remote_cmds contains
    the verb or "*". Unknown senders are denied silently (no reply leak).
    """

    def __init__(self, bot: "MudBot") -> None:
        self._bot = bot
        self._verbs: dict[str, VerbHandler] = {}
        self._register_builtins()

    def register(self, verb: str, handler: VerbHandler) -> None:
        self._verbs[verb.lower()] = handler

    def handle(self, sender: str, text: str) -> str | None:
        """Process a tell. Returns reply text, or None for no reply."""
        text = text.strip()
        if not text.startswith("@"):
            return None
        parts = text[1:].split(None, 1)
        verb = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""
        if verb not in self._verbs:
            return None
        rule = self._find_rule(sender)
        if rule is None:
            return None   # unknown player: silent
        if "*" not in rule.remote_cmds and verb not in rule.remote_cmds:
            return "permission denied"
        return self._verbs[verb](sender, arg)

    def _find_rule(self, sender: str):
        for rule in self._bot._config.players:
            if rule.name.lower() == sender.lower():
                return rule
        return None

    # ---- built-in verbs ----------------------------------------------------

    def _register_builtins(self) -> None:
        bot = self._bot
        self.register("status", lambda s, a: bot.status_text())
        self.register("health", lambda s, a: (
            f"HP {bot._state.hp}/{bot._state.max_hp} "
            f"MP {bot._state.mana}/{bot._state.max_mana}"
        ))
        self.register("loop", lambda s, a: bot.start_loop(a))
        self.register("stop", lambda s, a: bot.stop_all())
        self.register("goto", lambda s, a: bot.navigate_to_room(a) if a else "usage: @goto CODE")
        self.register("kill", self._kill)
        self.register("hangup", self._hangup)
        self.register("panic!", self._panic)
        # Toggle existing config flags, after the original's @auto-* verbs
        self.register("auto-sneak", self._toggle("stealth", "auto_sneak"))
        self.register("auto-hide", self._toggle("stealth", "auto_hide"))
        self.register("auto-get", self._toggle("items", "auto_get"))
        self.register("auto-cash", self._toggle("items", "auto_cash"))

    def _kill(self, sender: str, arg: str) -> str:
        if not arg:
            return "usage: @kill TARGET"
        self._bot._state.enqueue(f"{self._bot._config.combat.attack_cmd} {arg}")
        return f"attacking {arg}"

    def _hangup(self, sender: str, arg: str) -> str:
        self._bot._safety.request_hangup(f"remote @hangup from {sender}")
        return "hanging up"

    def _panic(self, sender: str, arg: str) -> str:
        panic_cmd = self._bot._config.safety.panic_cmd
        if panic_cmd:
            self._bot._state.enqueue(panic_cmd)
        self._bot._safety.request_hangup(f"remote @panic from {sender}")
        return "panic!"

    def _toggle(self, section: str, attr: str) -> VerbHandler:
        def toggle(sender: str, arg: str) -> str:
            cfg = getattr(self._bot._config, section)
            if arg:
                value = arg.lower() in ("on", "true", "1", "yes")
            else:
                value = not getattr(cfg, attr)
            setattr(cfg, attr, value)
            return f"{attr} {'on' if value else 'off'}"
        return toggle
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_remote.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/automation/remote.py tests/test_remote.py
git commit -m "feat: RemoteCommandHandler — permission-gated @-verbs with extensible registry"
```

---

### Task 3: Wire into MudBot conversation flow

**Files:**
- Modify: `src/mmud/bot.py`
- Test: `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot.py`:

```python
from mmud.config.schema import PlayerRule, RemoteConfig


def _remote_config() -> MudConfig:
    config = MudConfig()
    config.remote = RemoteConfig(enabled=True)
    config.players = [PlayerRule(name="Friend", friend=True, remote_cmds=["*"])]
    return config


@pytest.mark.asyncio
async def test_remote_tell_executes_and_replies():
    # The bot sends ONE command per received line, so the @kill tell queues two
    # commands (the attack, then the reply) — a second server line drains the second.
    bot = make_transcript_bot(
        ["[Friend tells you] @kill orc\n", "ok\n"], config=_remote_config()
    )
    await bot.run()
    assert "kill orc" in bot._conn.sent
    assert "/Friend attacking orc" in bot._conn.sent


@pytest.mark.asyncio
async def test_remote_disabled_ignores_tells():
    config = _remote_config()
    config.remote.enabled = False
    bot = make_transcript_bot(["[Friend tells you] @kill orc\n"], config=config)
    await bot.run()
    assert "kill orc" not in bot._conn.sent


@pytest.mark.asyncio
async def test_stranger_tell_ignored():
    bot = make_transcript_bot(
        ["[Stranger tells you] @hangup\n"], config=_remote_config()
    )
    await bot.run()
    assert not bot._safety.hangup_requested
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_bot.py -v -k remote`
Expected: FAIL (no handler wired)

- [ ] **Step 3: Modify `src/mmud/bot.py`**

Import:

```python
from mmud.automation.remote import RemoteCommandHandler
```

In `__init__`, after `self._safety = SafetyMonitor(...)`:

```python
        self._remote = RemoteCommandHandler(self)
```

Replace `_parse_conversation` with:

```python
    def _parse_conversation(self, line: str) -> None:
        msg = self._convo_parser.parse(line)
        if msg is None:
            return
        self._emit(ConversationReceived(
            channel=msg.channel,
            sender=msg.sender,
            text=msg.text,
        ))
        if self._config.remote.enabled and msg.channel == "tell":
            reply = self._remote.handle(msg.sender, msg.text)
            if reply:
                self._state.enqueue(
                    self._config.remote.tell_format.format(name=msg.sender, text=reply)
                )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_bot.py -v -k remote` then `pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/mmud/bot.py tests/test_bot.py
git commit -m "feat: route @-tells through RemoteCommandHandler with tell replies"
```

---

### Task 4: Docs

**Files:**
- Modify: `characters/example.toml`, `README.md`

- [ ] **Step 1: Append to `characters/example.toml`**

```toml
[remote]
# Allow trusted players to control the bot via tells (e.g. "@status", "@stop").
enabled = false
# Reply template — adjust to your server's telepath syntax.
tell_format = "/{name} {text}"

# Per-player permissions. remote_cmds is a list of allowed verbs, or ["*"] for all.
# [[players]]
# name = "MyAltChar"
# friend = true
# remote_cmds = ["*"]
```

- [ ] **Step 2: Add an "@-Commands (remote control)" section to `README.md`**

Document: enable via `[remote] enabled = true` + a `[[players]]` rule with `remote_cmds`; table of verbs — @status, @health, @loop NAME, @stop, @goto CODE, @kill TARGET, @hangup, @panic!, @auto-sneak/-hide/-get/-cash [on|off]; note that unknown players are ignored silently and more verbs arrive in later phases.

- [ ] **Step 3: Commit**

```bash
git add characters/example.toml README.md
git commit -m "docs: remote @-command configuration and verb reference"
```

---

## Verification

- `pytest -q` — full suite green.
- Live test (user): from a second character listed in `[[players]]` with `remote_cmds = ["*"]`, send `@status`, `@health`, `@kill <monster>`, `@stop` — confirm execution and tell replies; send `@hangup` and confirm disconnect; from an unlisted character, send `@hangup` and confirm it is ignored.
- Confirm the server's actual telepath reply syntax and adjust `[remote] tell_format` (and the default in `RemoteConfig`) if `/{name} {text}` is wrong.
