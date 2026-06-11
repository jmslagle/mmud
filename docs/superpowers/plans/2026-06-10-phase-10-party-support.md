# Phase 10: Party Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the long-dormant `[party]` config: track party members and their HP from the party list, heal/bless them, wait for stragglers (wait/resume protocol), share cash, auto-accept friend invites, and expose the party @-verbs.

**Architecture:** A stateful `PartyParser` (anchored on EXACT strings recovered from megamud.exe's `party_list_parse @ 0x004618e0`) maintains `GameState.party`/`party_leader`. A `PartyDecider` at the reserved `PRIO_PARTY = 100` slot handles heal → wait/resume → bless → share → status-refresh in that order, one command per `decide()`. An invite monitor auto-joins invitations from `friend=True` players. Everything is inert without `[party]` config, so the existing suite stays green.

**Tech Stack:** Python 3.11+, stdlib only. Transcript-tested via `make_transcript_bot`.

**Prerequisites:** Phases 2–5 complete; `pytest -q` green (376).

**Recovered anchors (EXACT — from the binary; do not re-derive):**
- `"You are not in a party"` → clear party state.
- `"The following people are in your"` → party-list header; following lines are member rows until one doesn't match.
- `"You are following <Name>."` → leader name (strip trailing `.`).

> **Live-tune caveat:** the member-ROW format (columns/brackets) is reconstructed
> — the original's parser reads name, surname, `[class]`, and bracketed HP%/MP%
> integers, but the exact column layout is fuzzy in the decompile. Record the
> real rows in docs/testing-plan.md and tune `_ROW_RE`. The `share`/`join`
> command syntax is likewise reconstructed.

**Existing config to wire (all unused today, `src/mmud/config/schema.py`):**
`PartyConfig`: heal_spell, heal_hp_pct (0.50), wait_hp_pct (0.30),
wait_max_seconds (30), wait_cmd ("wait"), resume_cmd ("go"),
attack_with_leader, share_cash, bless: list[PartyBless(cmd, wait_seconds)].
`PlayerRule.dont_heal` / `dont_bless`.

---

## File Map

```
src/mmud/
  parser/party_parser.py     NEW — PartyMember + PartyParser
  automation/party.py        NEW — PartyDecider + InviteMonitor
  state/game_state.py        MODIFY — party, party_leader
  config/schema.py           MODIFY — PartyConfig additions (status_cmd, status_interval_s)
  config/loader.py           MODIFY
  automation/remote.py       MODIFY — @invite @wait @rego @share @forget
  bot.py                     MODIFY — wire parser/decider/monitor
tests/
  test_party_parser.py       NEW
  test_party.py              NEW
  test_remote.py             MODIFY
  test_config.py             MODIFY
  test_bot.py                MODIFY — party e2e
characters/example.toml      MODIFY
README.md                    MODIFY
```

---

### Task 1: PartyParser + GameState fields

**Files:**
- Create: `src/mmud/parser/party_parser.py`
- Modify: `src/mmud/state/game_state.py`
- Test: `tests/test_party_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_party_parser.py
from mmud.parser.party_parser import PartyParser, PartyMember
from mmud.state.game_state import GameState


def _feed(lines):
    gs = GameState()
    p = PartyParser()
    for line in lines:
        p.feed(line, gs)
    return gs


def test_party_list_parsed():
    gs = _feed([
        "The following people are in your party:",
        "Krang          [Warrior]   [ 75] [100]",
        "Beeze Moan     [Cleric]    [100] [ 40] P",
        "Obvious exits: north",          # non-row ends the list
    ])
    assert [m.name for m in gs.party] == ["Krang", "Beeze"]
    assert gs.party[0].hp_pct == 75
    assert gs.party[0].mp_pct == 100
    assert gs.party[0].klass == "Warrior"
    assert gs.party[1].hp_pct == 100
    assert gs.party[1].is_leader is True    # trailing P flag


def test_not_in_a_party_clears():
    gs = _feed([
        "The following people are in your party:",
        "Krang          [Warrior]   [ 75] [100]",
        "You are not in a party.",
    ])
    assert gs.party == []
    assert gs.party_leader == ""


def test_following_sets_leader():
    gs = _feed(["You are following Krang."])
    assert gs.party_leader == "Krang"


def test_rows_outside_list_ignored():
    gs = _feed(["Krang          [Warrior]   [ 75] [100]"])
    assert gs.party == []                   # no header seen: not a party row


def test_list_replaces_previous():
    gs = _feed([
        "The following people are in your party:",
        "Krang          [Warrior]   [ 75] [100]",
        "[HP=100/100]:",
        "The following people are in your party:",
        "Beeze          [Cleric]    [ 50] [ 50]",
        "[HP=100/100]:",
    ])
    assert [m.name for m in gs.party] == ["Beeze"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_party_parser.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/mmud/parser/party_parser.py`**

```python
from __future__ import annotations
import re
from dataclasses import dataclass
from mmud.state.game_state import GameState

# EXACT anchors from megamud.exe party_list_parse @ 0x004618e0.
_NOT_IN_PARTY_RE = re.compile(r"You are not in a party", re.IGNORECASE)
_LIST_HEADER_RE = re.compile(r"The following people are in your", re.IGNORECASE)
_FOLLOWING_RE = re.compile(r"^You are following\s+(\w+)", re.IGNORECASE)

# Member row — RECONSTRUCTED layout (live-tune in docs/testing-plan.md):
# "Name [Surname] [Class] [HP%] [MP%] [P]"
_ROW_RE = re.compile(
    r"^\s*([A-Z][\w']*)"            # first name
    r"(?:\s+[A-Z][\w']*)?"          # optional surname
    r"\s+\[([^\]]+)\]"              # [Class]
    r"\s+\[\s*(\d+)\]"              # [HP%]
    r"(?:\s+\[\s*(\d+)\])?"         # [MP%] (optional)
    r"(?:\s+(P))?\s*$"              # leader/rank flag
)


@dataclass
class PartyMember:
    name: str
    hp_pct: int = 100
    mp_pct: int = 100
    klass: str = ""
    is_leader: bool = False


class PartyParser:
    """Stateful party-list parser: header line opens the list, the first
    non-matching line closes it."""

    def __init__(self) -> None:
        self._in_list = False
        self._pending: list[PartyMember] = []

    def feed(self, line: str, state: GameState) -> bool:
        """Returns True when the line was party-related."""
        if _NOT_IN_PARTY_RE.search(line):
            self._in_list = False
            self._pending = []
            state.party = []
            state.party_leader = ""
            return True
        if _LIST_HEADER_RE.search(line):
            self._in_list = True
            self._pending = []
            return True
        if m := _FOLLOWING_RE.match(line.strip()):
            state.party_leader = m.group(1)
            return True
        if self._in_list:
            if m := _ROW_RE.match(line):
                self._pending.append(PartyMember(
                    name=m.group(1),
                    klass=m.group(2).strip(),
                    hp_pct=int(m.group(3)),
                    mp_pct=int(m.group(4)) if m.group(4) else 100,
                    is_leader=bool(m.group(5)),
                ))
                return True
            # list ended: commit what we collected
            self._in_list = False
            state.party = self._pending
            self._pending = []
        return False
```

- [ ] **Step 4: GameState fields** — in `GameState.__init__` (after `last_exits`):

```python
        self.party: list = []          # list[PartyMember]
        self.party_leader: str = ""
```

- [ ] **Step 5: Run** — `pytest tests/test_party_parser.py -v` → 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/mmud/parser/party_parser.py src/mmud/state/game_state.py tests/test_party_parser.py
git commit -m "feat: PartyParser — party list/leader tracking from exact RE anchors"
```

---

### Task 2: PartyConfig additions

**Files:**
- Modify: `src/mmud/config/schema.py`, `src/mmud/config/loader.py`, `characters/example.toml`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_party_additions(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[party]
status_cmd = "par"
status_interval_s = 30
""")
    cfg = load_config(p)
    assert cfg.party.status_cmd == "par"
    assert cfg.party.status_interval_s == 30


def test_party_additions_defaults():
    cfg = load_config(None)
    assert cfg.party.status_cmd == ""        # "" = no periodic refresh
    assert cfg.party.status_interval_s == 60
```

- [ ] **Step 2: Run to confirm failure** — AttributeError

- [ ] **Step 3: Implement** — append to `PartyConfig` in schema.py:

```python
    status_cmd: str = ""           # command that prints the party list ("" = off)
    status_interval_s: int = 60    # refresh cadence
```

Loader `party` block gains the two `p.get(...)` lines. `example.toml` `[party]`
block gains both keys with the schema comments.

- [ ] **Step 4: Run + commit**

```bash
git add src/mmud/config/ characters/example.toml tests/test_config.py
git commit -m "feat: party status_cmd/status_interval_s config"
```

---

### Task 3: PartyDecider — heal, wait/resume, bless, share, status

**Files:**
- Create: `src/mmud/automation/party.py`
- Test: `tests/test_party.py`

Order inside `decide()` (one command per call): wait/resume protocol → heal →
bless slots → share-cash → status refresh.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_party.py
from mmud.automation.party import PartyDecider, InviteMonitor
from mmud.automation.decision import PRIO_PARTY
from mmud.config.schema import PartyBless, PartyConfig, PlayerRule
from mmud.parser.party_parser import PartyMember
from mmud.state.game_state import GameState
from mmud.state.inventory import Inventory
from mmud.state.tasks import TaskType


def _decider(cfg=None, rules=(), t=100.0):
    holder = {"t": t}
    d = PartyDecider(cfg or PartyConfig(), list(rules), now=lambda: holder["t"])
    return d, holder


def _state(*members):
    gs = GameState()
    gs.party = list(members)
    gs.inventory_dirty = False
    return gs


def test_heals_lowest_member():
    # hp 45/35: below heal_hp_pct (50) but above wait_hp_pct (30) so the
    # wait protocol stays quiet and the heal fires.
    d, _ = _decider(PartyConfig(heal_spell="cast heal", heal_hp_pct=0.50))
    gs = _state(PartyMember(name="Krang", hp_pct=45),
                PartyMember(name="Beeze", hp_pct=35))
    assert d.decide(gs) == "cast heal Beeze"
    assert gs.task.type is TaskType.CASTING
    assert gs.task.priority == PRIO_PARTY


def test_dont_heal_rule_respected():
    d, _ = _decider(PartyConfig(heal_spell="cast heal", heal_hp_pct=0.50),
                    rules=[PlayerRule(name="Beeze", dont_heal=True)])
    gs = _state(PartyMember(name="Beeze", hp_pct=20))
    assert d.decide(gs) is None


def test_wait_then_resume():
    # status_cmd engages party automation (the wait protocol is gated on
    # heal_spell-or-status_cmd so pure-default configs stay inert).
    cfg = PartyConfig(wait_hp_pct=0.30, wait_cmd="wait", resume_cmd="go",
                      wait_max_seconds=30, status_cmd="par",
                      status_interval_s=9999)
    d, _ = _decider(cfg)
    gs = _state(PartyMember(name="Krang", hp_pct=10))
    assert d.decide(gs) == "wait"
    assert gs.task.type is TaskType.WAITING
    assert d.decide(gs) is None              # already waiting
    gs.party = [PartyMember(name="Krang", hp_pct=90)]
    assert d.decide(gs) == "go"              # recovered: resume
    assert not gs.task.is_active


def test_bless_slot_cooldown():
    cfg = PartyConfig(bless=[PartyBless(cmd="cast pbless", wait_seconds=60)])
    d, holder = _decider(cfg, t=100.0)
    gs = _state(PartyMember(name="Krang"))
    assert d.decide(gs) == "cast pbless"
    assert d.decide(gs) is None              # cooling down
    holder["t"] = 161.0
    assert d.decide(gs) == "cast pbless"


def test_share_cash_one_denom_per_decide():
    cfg = PartyConfig(share_cash=True)
    d, _ = _decider(cfg)
    gs = _state(PartyMember(name="Krang"))
    gs.inventory = Inventory(coins={"copper": 90, "gold": 2})
    assert d.decide(gs) in ("share 2 gold", "share 90 copper")
    first = gs.inventory_dirty
    assert first is False                    # dirty only after the last share
    second = d.decide(gs)
    assert second is not None and second.startswith("share")
    assert d.decide(gs) is None
    assert gs.inventory_dirty is True        # blocks re-share until refresh


def test_status_refresh_interval():
    cfg = PartyConfig(status_cmd="par", status_interval_s=60)
    d, holder = _decider(cfg, t=100.0)
    gs = _state()                            # works even before a party exists
    assert d.decide(gs) == "par"
    assert d.decide(gs) is None
    holder["t"] = 161.0
    assert d.decide(gs) == "par"


def test_quiet_without_config():
    d, _ = _decider(PartyConfig())
    gs = _state(PartyMember(name="Krang", hp_pct=10))
    assert d.decide(gs) is None


def test_invite_monitor_friends_only():
    m = InviteMonitor([PlayerRule(name="Krang", friend=True)])
    assert m.check("Krang has invited you to join his party.") == "join Krang"
    assert m.check("Sneaky has invited you to join her party.") is None
    assert m.check("Just a normal line") is None
```

- [ ] **Step 2: Run to confirm failure** — ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/automation/party.py`**

```python
from __future__ import annotations
import re
import time
from typing import Callable
from mmud.automation.decision import PRIO_PARTY
from mmud.config.schema import PartyConfig, PlayerRule
from mmud.state.game_state import GameState
from mmud.state.inventory import WEALTH_RATES
from mmud.state.tasks import TaskType

HEAL_TIMEOUT_S = 5.0

# Reconstructed; live-tune in docs/testing-plan.md.
_INVITE_RE = re.compile(r"(\w+) has invited you to join", re.IGNORECASE)


class InviteMonitor:
    """Auto-accept party invites from friend=True players."""

    def __init__(self, rules: list[PlayerRule]) -> None:
        self._friends = {r.name.lower() for r in rules if r.friend}

    def check(self, line: str) -> str | None:
        m = _INVITE_RE.search(line)
        if m and m.group(1).lower() in self._friends:
            return f"join {m.group(1)}"
        return None


class PartyDecider:
    """PRIO_PARTY slot: wait/resume -> heal -> bless -> share -> status."""

    def __init__(self, config: PartyConfig, rules: list[PlayerRule],
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self._dont_heal = {r.name.lower() for r in rules if r.dont_heal}
        self._now = now
        self._bless_last = [float("-inf")] * len(config.bless)
        self._status_last = float("-inf")
        self._waiting = False
        self._share_queue: list[str] = []

    def decide(self, state: GameState) -> str | None:
        now = self._now()
        # The wait protocol is gated on party automation being IN USE
        # (heal_spell or status_cmd) — wait_cmd/wait_hp_pct have non-empty
        # defaults, and a pure-default config must stay inert.
        engaged = bool(self._cfg.heal_spell or self._cfg.status_cmd)
        # 1) wait/resume protocol
        if engaged and self._cfg.wait_cmd and self._cfg.wait_hp_pct > 0 \
                and state.party:
            low = [m for m in state.party
                   if m.hp_pct < self._cfg.wait_hp_pct * 100]
            if low and not self._waiting:
                self._waiting = True
                state.begin_task(TaskType.WAITING, priority=PRIO_PARTY,
                                 timeout_s=self._cfg.wait_max_seconds, now=now)
                return self._cfg.wait_cmd
            if self._waiting:
                if low:
                    return None                  # keep waiting
                self._waiting = False
                if state.task.type is TaskType.WAITING:
                    state.complete_task()
                return self._cfg.resume_cmd
        # 2) heal the lowest eligible member
        if self._cfg.heal_spell and state.party:
            hurt = [m for m in state.party
                    if m.hp_pct < self._cfg.heal_hp_pct * 100
                    and m.name.lower() not in self._dont_heal]
            if hurt:
                target = min(hurt, key=lambda m: m.hp_pct)
                state.begin_task(TaskType.CASTING, priority=PRIO_PARTY,
                                 timeout_s=HEAL_TIMEOUT_S, now=now)
                return f"{self._cfg.heal_spell} {target.name}"
        # 3) party bless slots
        if state.party:
            for i, bless in enumerate(self._cfg.bless):
                if bless.cmd and now - self._bless_last[i] >= bless.wait_seconds:
                    self._bless_last[i] = now
                    return bless.cmd
        # 4) share cash
        if self._cfg.share_cash and state.party and not state.inventory_dirty:
            if not self._share_queue and state.inventory.coins:
                self._share_queue = [
                    f"share {n} {denom}"
                    for denom, n in sorted(
                        state.inventory.coins.items(),
                        key=lambda kv: -WEALTH_RATES.get(kv[0], 0))
                    if n > 0]
            if self._share_queue:
                cmd = self._share_queue.pop(0)
                if not self._share_queue:
                    state.inventory_dirty = True   # re-sync; blocks re-share
                return cmd
        # 5) periodic party status refresh
        if (self._cfg.status_cmd
                and now - self._status_last >= self._cfg.status_interval_s):
            self._status_last = now
            return self._cfg.status_cmd
        return None
```

- [ ] **Step 4: Run** — `pytest tests/test_party.py -v` → 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/automation/party.py tests/test_party.py
git commit -m "feat: PartyDecider — heal/wait/bless/share/status + friend invite monitor"
```

---

### Task 4: Bot wiring + e2e

**Files:**
- Modify: `src/mmud/bot.py`
- Test: `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_party_heal_e2e():
    config = MudConfig()
    config.party.heal_spell = "cast heal"
    config.party.heal_hp_pct = 0.50
    bot = make_transcript_bot(
        ["The following people are in your party:\n",
         "Beeze          [Cleric]    [ 40] [100]\n",   # 40: heal yes, wait no
         "[HP=100/100]:\n"],          # ends the list; decider fires
        config=config)
    await bot.run()
    assert "cast heal Beeze" in bot._conn.sent


@pytest.mark.asyncio
async def test_friend_invite_autojoin():
    config = MudConfig()
    config.players = [PlayerRule(name="Krang", friend=True)]
    bot = make_transcript_bot(
        ["Krang has invited you to join his party.\n", "ok\n"], config=config)
    await bot.run()
    assert "join Krang" in bot._conn.sent
```

- [ ] **Step 2: Run to confirm failure** — nothing wired → no heal/join sent

- [ ] **Step 3: Wire into `bot.py`**

`__init__` (after the commerce registration; import `PRIO_PARTY` in the
decision import list):

```python
        from mmud.parser.party_parser import PartyParser
        from mmud.automation.party import PartyDecider, InviteMonitor
        self._party_parser = PartyParser()
        self._invites = InviteMonitor(self._config.players)
        self._engine.register("party",
                              PartyDecider(self._config.party, self._config.players),
                              PRIO_PARTY)
```

In `_process_line` (after `self._commerce.on_line(clean)`):

```python
        self._party_parser.feed(clean, self._state)
        if join_cmd := self._invites.check(clean):
            self._state.enqueue(join_cmd)
```

- [ ] **Step 4: Run** — `pytest tests/test_bot.py -v -k "party_heal or invite"` then `pytest -q` → green

- [ ] **Step 5: Commit**

```bash
git add src/mmud/bot.py tests/test_bot.py
git commit -m "feat: wire party tracking, heals, and friend auto-join into bot"
```

---

### Task 5: Party @-verbs + docs

**Files:**
- Modify: `src/mmud/automation/remote.py`, `README.md`
- Test: `tests/test_remote.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to confirm failure** — unknown verbs

- [ ] **Step 3: Register in `_register_builtins`**

```python
        self.register("invite", lambda s, a: (
            bot._state.enqueue(f"invite {s}") or f"inviting {s}"))
        self.register("wait", lambda s, a: (
            bot._state.enqueue(bot._config.party.wait_cmd) or "waiting"))
        self.register("rego", lambda s, a: (
            bot._state.enqueue(bot._config.party.resume_cmd) or "resuming"))
        self.register("share", lambda s, a: (
            bot._state.enqueue(f"share {a}".strip()) or "sharing"))
        self.register("forget", self._forget_party)
```

and the method:

```python
    def _forget_party(self, sender: str, arg: str) -> str:
        self._bot._state.party = []
        self._bot._state.party_leader = ""
        return "party forgotten"
```

- [ ] **Step 4: README** — add the five verbs to the @-commands table and a
short "Party support (`[party]`)" section: tracking anchors, heal/wait/bless/
share behavior, `status_cmd` refresh, friend auto-join, and the member-row
live-tune caveat.

- [ ] **Step 5: Run** — `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/remote.py README.md tests/test_remote.py
git commit -m "feat: party @-verbs; party docs"
```

---

## Verification

- `pytest -q` — full suite green after every task.
- Transcript e2e: party list → heal fires; friend invite → auto-join.
- Live test (user, per docs/testing-plan.md): run the real party command and
  capture actual member rows — tune `_ROW_RE` (THE load-bearing reconstruction
  here); verify `join`/`share`/`wait`/`go` syntax; confirm the wait/resume
  cycle against a real lagging member; check `dont_heal` players are skipped.
- Deliberately deferred: `attack_with_leader` beyond the WAITING-task pinning
  (needs live observation of leader-engagement lines), NPC party members
  (`party_member_find_npc_by_name` exists in the original — add when seen
  live), bless targeting specific members (`dont_bless` currently unused by
  the slot-cooldown design — note for live tuning).
