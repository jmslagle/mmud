# Hardening & Gap-Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps between the merged 11-phase parity roadmap and a production-ready bot *before* live-server user testing. Three concerns: (1) eliminate dead config (every `schema.py` field is either wired with a transcript test or deleted), (2) add the stat counters the future web panel will render (matching MegaMud's Ghidra-sourced model), and (3) make the 620-line `bot.py` god-object and the repetitive `loader.py` maintainable — all behavior-preserving and test-guarded.

**Architecture:** `MudBot` (`src/mmud/bot.py`) owns a `DecisionEngine` (`src/mmud/automation/decision.py`) — a priority-ordered chain of `Decider` objects (one `decide(state) -> str | None` each). The bot reads lines, runs a fixed `_process_line` hook pipeline that mutates `GameState` (`src/mmud/state/game_state.py`), then asks the engine for the next command. `SessionManager` (`src/mmud/session.py`) tracks session-scope stats with an injected clock. Config is plain dataclasses (`src/mmud/config/schema.py`) parsed by `load_config` (`src/mmud/config/loader.py`). Events are dataclasses posted on a `GameEventBus` (`src/mmud/events.py`); the web panel (Doc 3) subscribes to these.

**Tech Stack:** Python 3.x, pytest, asyncio

**Working agreements for every step:**
- TDD loop per step: write the failing test → run it (see it fail for the right reason) → write the *minimal* implementation → run it (see it pass) → commit.
- Run a single test file with: `python -m pytest tests/<file>.py -q`
- Run the whole suite with: `python -m pytest -q` (baseline: **415 passing**).
- Transcript tests use the `make_transcript_bot(lines, **kwargs)` / `FakeConnection` harness in `tests/conftest.py`: build the bot, `await bot.run()`, then assert on `bot._conn.sent` (a `list[str]` of every command sent). Transcript tests are `@pytest.mark.asyncio async def`.
- Every new feature MUST be inert under a pure-default `MudConfig()` so the existing 415 tests stay green. Gate each on an explicit opt-in flag/non-empty string.
- Commit message footer (every commit):
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## Task 1: Dead-config triage

**Verified unread set** (confirmed via `grep -rn <field> src/ | grep -v 'schema.py\|loader.py'` on 2026-06-11 — re-run before starting to confirm nothing changed):

| Field | Disposition |
|---|---|
| `spells.multi_attack` | **WIRE** — chained secondary attack spell |
| `stealth.must_sneak` | **WIRE** — gate the attack until a sneak succeeds |
| `party.attack_with_leader` | **WIRE** — leader-engagement line monitor (interim: wait-pin) |
| `navigation.start_room` | **DELETE** — never read; `auto_start` + `loop_path` cover startup |
| `items.runic_name` | **DELETE** — `collect_runic` already keys off the literal `"runic"` denom |
| `items.max_coins` | **DELETE** — coin up-conversion is out of scope; recommend deleting |
| `party.dont_bless` (`PlayerRule.dont_bless`) | **DELETE** — party bless is slot-based, not per-player |

> NOTE: `loop_path` and `session.logout_cmd` ARE read (loop_runner/bot, bot relog) — do **not** touch them. There is **no** `combat.multi_attack` field; `multi_attack` lives only in `SpellsConfig`.

**Files:**
- `src/mmud/automation/spells.py`
- `src/mmud/combat/combat.py`
- `src/mmud/automation/party.py`
- `src/mmud/config/schema.py`
- `src/mmud/config/loader.py`
- `characters/example.toml`
- `tests/test_spells.py`, `tests/test_combat.py`, `tests/test_party.py`, `tests/test_config.py`

### 1a. Wire `spells.multi_attack` (chained secondary attack)

- [ ] Add a failing test to `tests/test_spells.py`:
```python
def test_multi_attack_chains_after_primary_attack():
    from mmud.automation.spells import SpellEngine
    from mmud.config.schema import SpellsConfig
    from mmud.state.game_state import GameState, MonsterSighting
    cfg = SpellsConfig(attack="cast fireball", multi_attack="cast magic missile")
    eng = SpellEngine(cfg)
    gs = GameState()
    gs.set_combat(True)
    gs.set_mana(100, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    assert eng.decide(gs) == "cast fireball"       # primary first
    assert eng.decide(gs) == "cast magic missile"  # multi second
    assert eng.decide(gs) == "cast fireball"        # cycles back


def test_multi_attack_inert_when_unset():
    from mmud.automation.spells import SpellEngine
    from mmud.config.schema import SpellsConfig
    from mmud.state.game_state import GameState, MonsterSighting
    eng = SpellEngine(SpellsConfig(attack="cast fireball"))
    gs = GameState()
    gs.set_combat(True)
    gs.set_mana(100, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    assert eng.decide(gs) == "cast fireball"
    assert eng.decide(gs) == "cast fireball"  # no multi -> stays primary
```
- [ ] Run: `python -m pytest tests/test_spells.py -q` (expect FAIL).
- [ ] In `src/mmud/automation/spells.py`, add `self._cast_primary_next = True` to `__init__` (after `self._swapped_to_melee = False`). Replace the attack-spell block (the `if state.in_combat and self._cfg.attack and state.monsters_present:` block) with:
```python
        # Attack spell (in combat, takes priority over bless) — with cast limit.
        # When multi_attack is set, alternate primary -> multi -> primary ...
        if state.in_combat and self._cfg.attack and state.monsters_present:
            limit = self._cfg.max_cast_count
            if limit <= 0 or self._attack_casts < limit:
                self._attack_casts += 1
                if self._cfg.multi_attack and not self._cast_primary_next:
                    self._cast_primary_next = True
                    return self._cfg.multi_attack
                self._cast_primary_next = False
                return self._cfg.attack
            if not self._swapped_to_melee and self._cfg.melee_weapon_cmd:
                self._swapped_to_melee = True
                return self._cfg.melee_weapon_cmd
            return None
```
- [ ] In the same file, in the not-in-combat reset block, add `self._cast_primary_next = True` alongside the `self._attack_casts = 0` resets (both the `if self._swapped_to_melee:` branch and the trailing `self._attack_casts = 0`), so each encounter starts on the primary.
- [ ] Run: `python -m pytest tests/test_spells.py -q` (expect PASS).
- [ ] Add `multi_attack` documentation to `characters/example.toml` under `[spells]` (the `multi_attack  = ""` key already exists — append the comment `# secondary attack spell, alternated with attack`).
- [ ] Run full suite: `python -m pytest -q` (expect 417 passing — 415 + 2 new).
- [ ] Commit: `feat(spells): wire multi_attack chained secondary cast`

### 1b. Wire `stealth.must_sneak` (gate attack until sneak succeeds)

`CombatEngine` already sneaks once per encounter when `auto_sneak` is on (`sneak_cmd` passed in by the bot). `must_sneak` adds the stronger rule: do **not** issue the melee attack until a sneak *succeeded*. Combat already knows when sneak failed via the existing `_SNEAK_FAIL_RE`/`_SNEAK_OK_RE` in `backstab.py`, but `CombatEngine` is line-blind — so add a small line hook to `CombatEngine`.

- [ ] Add a failing test to `tests/test_combat.py`:
```python
def test_must_sneak_holds_attack_until_sneak_succeeds():
    from mmud.combat.combat import CombatEngine
    from mmud.config.schema import CombatConfig
    from mmud.state.game_state import GameState, MonsterSighting
    ce = CombatEngine(CombatConfig(attack_cmd="kill"),
                      sneak_cmd="sneak", must_sneak=True)
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(50, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    assert ce.decide(gs) == "sneak"   # sneak first
    assert ce.decide(gs) is None       # must_sneak: wait for the result line
    ce.on_line("You move silently into the shadows.")
    assert ce.decide(gs) == "kill orc"  # sneak confirmed -> attack


def test_must_sneak_retries_after_failure():
    from mmud.combat.combat import CombatEngine
    from mmud.config.schema import CombatConfig
    from mmud.state.game_state import GameState, MonsterSighting
    ce = CombatEngine(CombatConfig(attack_cmd="kill"),
                      sneak_cmd="sneak", must_sneak=True)
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    assert ce.decide(gs) == "sneak"
    ce.on_line("You fail to sneak and make a noise.")
    assert ce.decide(gs) == "sneak"   # retry, not attack
```
- [ ] Run: `python -m pytest tests/test_combat.py -q` (expect FAIL).
- [ ] In `src/mmud/combat/combat.py`, add the sneak-result regexes at module top (after the imports):
```python
import re

# Tune against the live server; record real wording in docs/testing-plan.md.
_SNEAK_OK_RE = re.compile(r"move silently|begin to sneak", re.IGNORECASE)
_SNEAK_FAIL_RE = re.compile(r"fail to sneak|make a noise", re.IGNORECASE)
```
- [ ] Change the constructor signature to `def __init__(self, config: CombatConfig | None = None, sneak_cmd: str = "", must_sneak: bool = False) -> None:` and add to the body (after `self._sneaked_this_encounter = False`):
```python
        self.must_sneak = must_sneak
        self._sneak_confirmed = False
```
- [ ] Add an `on_line` method to `CombatEngine` (after `__init__`):
```python
    def on_line(self, line: str) -> None:
        if not self.must_sneak:
            return
        if _SNEAK_OK_RE.search(line):
            self._sneak_confirmed = True
        elif _SNEAK_FAIL_RE.search(line):
            self._sneaked_this_encounter = False  # re-issue the sneak
```
- [ ] In `decide`, replace the sneak block:
```python
            # Sneak before first attack if configured
            if self.sneak_cmd and not self._sneaked_this_encounter:
                self._sneaked_this_encounter = True
                return self.sneak_cmd
```
with:
```python
            # Sneak before first attack if configured
            if self.sneak_cmd and not self._sneaked_this_encounter:
                self._sneaked_this_encounter = True
                return self.sneak_cmd
            # must_sneak: hold the attack until a sneak has been confirmed
            if self.must_sneak and not self._sneak_confirmed:
                return None
```
- [ ] In `decide`, in the not-in-combat reset (`self._sneaked_this_encounter = False`), also add `self._sneak_confirmed = False`.
- [ ] In `src/mmud/bot.py` `__init__`, change the `CombatEngine(...)` construction to pass `must_sneak`:
```python
        self._combat = CombatEngine(
            config=self._config.combat,
            sneak_cmd=self._config.stealth.sneak_cmd if self._config.stealth.auto_sneak else "",
            must_sneak=self._config.stealth.must_sneak,
        )
```
- [ ] In `src/mmud/bot.py` `_process_line`, add `self._combat.on_line(clean)` immediately after the existing `self._backstab.on_line(clean)` line.
- [ ] Run: `python -m pytest tests/test_combat.py tests/test_bot.py -q` (expect PASS).
- [ ] `characters/example.toml`: the `must_sneak = false` key already exists under `[stealth]`; append `# require a successful sneak before attacking`.
- [ ] Run full suite: `python -m pytest -q` (expect 419 passing).
- [ ] Commit: `feat(combat): wire must_sneak — hold attack until sneak confirmed`

### 1c. Wire `party.attack_with_leader` (leader-engagement monitor)

The intent: when in a party, don't open on a monster until the leader has engaged it. Implement a line monitor on `PartyDecider` that flips a flag when a leader-attack line is seen, and (interim) document that the existing party wait-pin remains the safety net. Inert when `attack_with_leader` is False **or** no `party_leader` is known.

- [ ] Add a failing test to `tests/test_party.py`:
```python
def test_attack_with_leader_blocks_until_leader_engages():
    from mmud.automation.party import PartyDecider
    from mmud.config.schema import PartyConfig
    from mmud.state.game_state import GameState, MonsterSighting
    cfg = PartyConfig(heal_spell="cast heal", attack_with_leader=True)
    dec = PartyDecider(cfg, [], now=lambda: 0.0)
    gs = GameState()
    gs.party_leader = "Krang"
    gs.monsters_present = [MonsterSighting(name="orc")]
    assert dec.leader_engaged is False
    dec.on_line("Krang swings at the orc.")
    assert dec.leader_engaged is True


def test_attack_with_leader_resets_when_no_monsters():
    from mmud.automation.party import PartyDecider
    from mmud.config.schema import PartyConfig
    from mmud.state.game_state import GameState
    dec = PartyDecider(PartyConfig(attack_with_leader=True), [], now=lambda: 0.0)
    dec._leader_engaged = True
    gs = GameState()
    gs.party_leader = "Krang"
    gs.monsters_present = []
    dec.decide(gs)
    assert dec.leader_engaged is False
```
- [ ] Run: `python -m pytest tests/test_party.py -q` (expect FAIL).
- [ ] In `src/mmud/automation/party.py`, after the existing `_INVITE_RE`, add:
```python
# Leader-engagement detector. RECONSTRUCTED; live-tune in docs/testing-plan.md.
# Filled in per-line with the current party leader name.
_LEADER_HIT_RE = re.compile(
    r"\b(?:swings?|attacks?|hits?|strikes?|slashes?|casts?)\b", re.IGNORECASE)
```
- [ ] In `PartyDecider.__init__`, add (after `self._share_queue: list[str] = []`):
```python
        self._attack_with_leader = config.attack_with_leader
        self._leader_engaged = False
        self._leader_name = ""
```
- [ ] Add to `PartyDecider`:
```python
    @property
    def leader_engaged(self) -> bool:
        return self._leader_engaged

    def on_line(self, line: str) -> None:
        if not self._attack_with_leader or not self._leader_name:
            return
        low = line.lower()
        if low.startswith(self._leader_name.lower()) and _LEADER_HIT_RE.search(line):
            self._leader_engaged = True
```
- [ ] At the very top of `PartyDecider.decide`, after `now = self._now()`, add:
```python
        # Track the leader for the attack_with_leader monitor; reset when the
        # room has no monsters (new encounter starts un-engaged).
        self._leader_name = state.party_leader
        if not state.monsters_present:
            self._leader_engaged = False
```
- [ ] In `src/mmud/bot.py`, the `PartyDecider` is currently constructed inline in `self._engine.register("party", PartyDecider(...), PRIO_PARTY)`. Change it to bind a reference so the bot can feed it lines:
```python
        self._party_decider = PartyDecider(self._config.party, self._config.players)
        self._engine.register("party", self._party_decider, PRIO_PARTY)
```
- [ ] In `src/mmud/bot.py` `_process_line`, add `self._party_decider.on_line(clean)` immediately after `self._party_parser.feed(clean, self._state)`.
- [ ] Run: `python -m pytest tests/test_party.py tests/test_bot.py -q` (expect PASS).
- [ ] `characters/example.toml`: `attack_with_leader = true` key exists under `[party]`; append comment `# wait for the party leader to engage before attacking`. Add an interim-behavior note as a comment: `# (interim: the wait/resume protocol remains the safety net)`.
- [ ] Run full suite: `python -m pytest -q` (expect 421 passing).
- [ ] Commit: `feat(party): wire attack_with_leader leader-engagement monitor`

### 1d. Delete dead fields: `navigation.start_room`, `items.runic_name`, `items.max_coins`, `PlayerRule.dont_bless`

- [ ] Add a guard test to `tests/test_config.py` proving the deleted keys are silently ignored (forward-compat for old config files):
```python
def test_deleted_keys_are_ignored(tmp_path):
    from mmud.config.loader import load_config
    p = tmp_path / "old.toml"
    p.write_text(
        "[navigation]\nstart_room = \"HOME\"\n"
        "[items]\nrunic_name = \"runic\"\nmax_coins = 500\n"
        "[[players]]\nname = \"Krang\"\ndont_bless = true\n",
        encoding="utf-8")
    cfg = load_config(p)            # must not raise
    assert not hasattr(cfg.navigation, "start_room")
    assert not hasattr(cfg.items, "runic_name")
    assert not hasattr(cfg.items, "max_coins")
    assert not hasattr(cfg.players[0], "dont_bless")
```
- [ ] Run: `python -m pytest tests/test_config.py -q` (expect FAIL on the `hasattr` assertions).
- [ ] In `src/mmud/config/schema.py`:
  - Remove `start_room: str = ""` from `NavigationConfig`.
  - Remove `runic_name: str = "runic"` and `max_coins: int = 0` (and its trailing comment) from `ItemsConfig`.
  - Remove `dont_bless: bool = False` from `PlayerRule`.
- [ ] In `src/mmud/config/loader.py`:
  - Remove `start_room=n.get("start_room", ""),` from the `NavigationConfig(...)` block.
  - Remove `runic_name=it.get("runic_name", "runic"),` and `max_coins=it.get("max_coins", 0),` from the `ItemsConfig(...)` block.
  - Remove `dont_bless=pl.get("dont_bless", False),` from the `PlayerRule(...)` comprehension.
- [ ] In `characters/example.toml`, delete any `start_room`, `runic_name`, `max_coins`, and `dont_bless` lines.
- [ ] Grep to confirm no references remain: `grep -rn "start_room\|runic_name\|max_coins\|dont_bless" src/ characters/` (expect no hits).
- [ ] Run: `python -m pytest tests/test_config.py -q` (expect PASS).
- [ ] Run full suite: `python -m pytest -q` (expect 422 passing).
- [ ] Commit: `chore(config): delete dead fields start_room/runic_name/max_coins/dont_bless`

---

## Task 2: Missing stat tracking (web-panel facing)

Add the MegaMud-model counters the web panel (Doc 3) will render. Counters live on `GameState` (per-session combat/stealth) and `SessionManager` (comms + rates); each new derived stat emits a `SessionStatUpdated(key, value)` event. **Ghidra-sourced formulas (the spec):**
- `hit% = hits*100/(miss+special+hit)` (already implemented as `GameState.hit_pct`)
- `sneak% = sneak_success*100/total`
- `dodge% = dodges*100/(dodges+monster_hits)`
- `backstab% = bs_success*100/bs_attempts`
- `gold/hr = weapon_gold*100/session_secs`

**Files:**
- `src/mmud/state/game_state.py`
- `src/mmud/session.py`
- `src/mmud/bot.py`
- `tests/test_game_state.py`, `tests/test_session.py`, `tests/test_bot.py`

### 2a. Stealth & dodge counters + derived percentages on GameState

- [ ] Add a failing test to `tests/test_game_state.py`:
```python
def test_sneak_and_dodge_percentages():
    from mmud.state.game_state import GameState
    gs = GameState()
    assert gs.sneak_pct == 0.0
    assert gs.dodge_pct == 0.0
    gs.record_sneak(success=True)
    gs.record_sneak(success=True)
    gs.record_sneak(success=False)
    assert gs.sneak_pct == 200.0 / 3   # 2 of 3
    gs.record_dodge()
    gs.record_dodge()
    gs.record_monster_hit()            # 2 dodges, 1 hit-taken -> 2/3
    assert gs.dodge_pct == 200.0 / 3


def test_backstab_pct_property():
    from mmud.state.game_state import GameState
    gs = GameState()
    assert gs.backstab_pct == 0.0
    gs.record_backstab(success=True)
    gs.record_backstab(success=False)
    assert gs.backstab_pct == 50.0
```
- [ ] Run: `python -m pytest tests/test_game_state.py -q` (expect FAIL).
- [ ] In `src/mmud/state/game_state.py` `__init__`, after `self.backstab_successes: int = 0`, add:
```python
        self.sneak_attempts: int = 0
        self.sneak_successes: int = 0
        self.dodges: int = 0
        self.ran_away: int = 0          # times the bot fled a dangerous room
        self.health_low: int = 0        # times HP dropped below flee threshold
```
- [ ] Add methods (after `record_backstab`):
```python
    def record_sneak(self, success: bool) -> None:
        self.sneak_attempts += 1
        if success:
            self.sneak_successes += 1

    def record_dodge(self) -> None:
        self.dodges += 1

    def record_ran_away(self) -> None:
        self.ran_away += 1

    def record_health_low(self) -> None:
        self.health_low += 1
```
- [ ] Add properties (after the existing `avg_damage` property):
```python
    @property
    def sneak_pct(self) -> float:
        return (self.sneak_successes / self.sneak_attempts * 100) \
            if self.sneak_attempts > 0 else 0.0

    @property
    def dodge_pct(self) -> float:
        total = self.dodges + self.monster_hits
        return (self.dodges / total * 100) if total > 0 else 0.0

    @property
    def backstab_pct(self) -> float:
        return (self.backstab_successes / self.backstab_attempts * 100) \
            if self.backstab_attempts > 0 else 0.0
```
- [ ] Extend `reset_combat_stats` to zero the new counters:
```python
        self.sneak_attempts = 0
        self.sneak_successes = 0
        self.dodges = 0
        self.ran_away = 0
        self.health_low = 0
```
- [ ] Run: `python -m pytest tests/test_game_state.py -q` (expect PASS).
- [ ] Run full suite: `python -m pytest -q` (expect 424 passing).
- [ ] Commit: `feat(state): add sneak/dodge/ran-away/health-low counters + percentages`

### 2b. Comms counters on SessionManager

- [ ] Add a failing test to `tests/test_session.py`:
```python
def test_comms_counters_increment():
    from mmud.config.schema import SessionConfig
    from mmud.session import SessionManager
    m = SessionManager(SessionConfig(), now=lambda: 0.0)
    assert m.dialed == 0
    m.on_dial()
    m.on_dial()
    m.on_connect()
    m.on_dial_failed()
    m.on_carrier_lost()
    assert (m.dialed, m.connected, m.dial_failed, m.carrier_lost) == (2, 1, 1, 1)
```
- [ ] Run: `python -m pytest tests/test_session.py -q` (expect FAIL).
- [ ] In `src/mmud/session.py` `__init__`, after `self._fired = False`, add:
```python
        # Comms counters (MegaMud comms model; survive relog/reset).
        self.dialed = 0
        self.dial_failed = 0
        self.connected = 0
        self.carrier_lost = 0
```
- [ ] Add methods (after `on_exp`):
```python
    def on_dial(self) -> None:
        self.dialed += 1

    def on_dial_failed(self) -> None:
        self.dial_failed += 1

    def on_connect(self) -> None:
        self.connected += 1

    def on_carrier_lost(self) -> None:
        self.carrier_lost += 1
```
- [ ] In `reset(self, now)`, do **not** zero the comms counters (they are lifetime-of-process). Leave `reset` as-is.
- [ ] Run: `python -m pytest tests/test_session.py -q` (expect PASS).
- [ ] Commit: `feat(session): add comms counters (dialed/failed/connected/lost)`

### 2c. Time-to-level ETA on SessionManager

Build on the existing `exp_rate_per_hour()`. ETA needs the current exp, the level threshold, and the rate.

- [ ] Add a failing test to `tests/test_session.py`:
```python
def test_time_to_level_eta_hours():
    from mmud.config.schema import SessionConfig
    from mmud.session import SessionManager
    m = SessionManager(SessionConfig(), now=lambda: 0.0)
    m.on_exp(0, now=0.0)
    m.on_exp(1000, now=3600.0)           # 1000 exp/hr
    # need 2500 more exp -> 2.5 hours
    assert m.time_to_level_hours(exp_to_next=2500) == 2.5


def test_time_to_level_eta_zero_rate():
    from mmud.config.schema import SessionConfig
    from mmud.session import SessionManager
    m = SessionManager(SessionConfig(), now=lambda: 0.0)
    assert m.time_to_level_hours(exp_to_next=2500) == 0.0   # no rate yet
```
- [ ] Run: `python -m pytest tests/test_session.py -q` (expect FAIL).
- [ ] In `src/mmud/session.py`, add (after `hours_elapsed`):
```python
    def time_to_level_hours(self, exp_to_next: int) -> float:
        """Hours until the next level at the current exp rate (0.0 = unknown)."""
        rate = self.exp_rate_per_hour()
        if rate <= 0 or exp_to_next <= 0:
            return 0.0
        return exp_to_next / rate
```
- [ ] Run: `python -m pytest tests/test_session.py -q` (expect PASS).
- [ ] Commit: `feat(session): add time_to_level_hours ETA`

### 2d. Bot wiring: increment ran-away / health-low / comms; emit stat events

- [ ] Add a failing transcript/unit test to `tests/test_bot.py`:
```python
@pytest.mark.asyncio
async def test_ran_away_counter_increments_on_flee():
    from mmud.config.schema import MudConfig
    config = MudConfig()
    config.combat.max_monsters = 1   # 2+ monsters is dangerous
    bot = make_transcript_bot(
        ["A goblin and a goblin and a goblin are here.\n"], config=config)
    await bot.run()
    assert "flee" in bot._conn.sent
    assert bot._state.ran_away >= 1


@pytest.mark.asyncio
async def test_health_low_counter_increments():
    from mmud.config.schema import MudConfig
    config = MudConfig()
    config.combat.flee_threshold = 0.15
    bot = make_transcript_bot(["[HP=10/100]\n"], config=config)
    await bot.run()
    assert bot._state.health_low >= 1
```
- [ ] Run: `python -m pytest tests/test_bot.py -q` (expect FAIL).
- [ ] In `src/mmud/bot.py` `_parse_vitals`, inside the HP branch, after `self._state.set_hp(hp, max_hp)` add a health-low edge detector. Add an instance flag `self._was_low = False` in `__init__` (near `self._auto_started = False`), then in `_parse_vitals`:
```python
            low = max_hp > 0 and hp / max_hp <= self._config.combat.flee_threshold
            if low and not self._was_low:
                self._state.record_health_low()
                self._emit(SessionStatUpdated(
                    key="health_low", value=str(self._state.health_low)))
            self._was_low = low
```
  (place this right after the `set_hp` call, before the existing AFK hangup-on-low-hp check).
- [ ] Wire ran-away counting where the flee/run actually fires. `RunDecider.decide` begins the `RUNNING` task and returns the first escape move. Rather than thread a counter into the decider, count it in the bot when a `RUNNING` task starts. In `_next_command`, capture whether a run just started:
```python
    def _next_command(self) -> str | None:
        was_running = self._state.task.type is TaskType.RUNNING
        cmd = self._engine.next_command(self._state)
        if (not was_running and self._state.task.type is TaskType.RUNNING):
            self._state.record_ran_away()
            self._emit(SessionStatUpdated(
                key="ran_away", value=str(self._state.ran_away)))
        return cmd
```
- [ ] In `src/mmud/bot.py` `run()`, wire the comms counters into the reconnect/redial loop. Replace the loop body's redial section:
```python
            if (not self._config.safety.reconnect
                    or redials >= self._config.safety.max_redials):
                break
            redials += 1
            await asyncio.sleep(self._redial_delay_s)
```
with:
```python
            if (not self._config.safety.reconnect
                    or redials >= self._config.safety.max_redials):
                break
            redials += 1
            self._session.on_dial()
            self._emit(SessionStatUpdated(
                key="dialed", value=str(self._session.dialed)))
            await asyncio.sleep(self._redial_delay_s)
```
  And in `_run_session`, after a successful `await self._conn.connect()`, add:
```python
        self._session.on_connect()
        self._emit(SessionStatUpdated(
            key="connected", value=str(self._session.connected)))
```
- [ ] In `run()`, in the `except (ConnectionError, OSError):` clause (about to gain logging in Task 4d), call `self._session.on_carrier_lost()` and emit `SessionStatUpdated(key="carrier_lost", value=str(self._session.carrier_lost))`.
- [ ] Run: `python -m pytest tests/test_bot.py -q` (expect PASS).
- [ ] Run full suite: `python -m pytest -q` (expect 426 passing).
- [ ] Commit: `feat(bot): increment comms/ran-away/health-low stats + emit events`

---

## Task 3: Live-tune regex harness

Create `docs/testing-plan.md` — a single reference listing every load-bearing reconstructed regex with `file:line`, the **current** pattern (quoted from source), a blank "real capture" slot, and the tuning procedure. This is the on-site checklist for the user's first live session.

**Files:**
- `docs/testing-plan.md` (new)

### 3a. Author docs/testing-plan.md

- [ ] Re-read each source file's current regex (they may have drifted) before quoting. Create `docs/testing-plan.md` with this exact content (verify each quoted pattern still matches the source line cited):

```markdown
# Live-Tuning Plan — Reconstructed Regexes

Every pattern below was reconstructed from MegaMud's behavior, not captured from
the live server. On the first live session, for EACH pattern:

1. Trigger the in-game event and copy the exact server line into the "Real
   capture" slot.
2. Add a failing test asserting the parser/monitor handles that real line
   (use the transcript harness or a direct unit test).
3. Run it, then adjust the regex minimally until it passes.
4. Commit `test+fix: tune <pattern> against live capture`.

Run a single area's tests with `python -m pytest tests/<file>.py -q`.

---

## Conditions — onset / recovery
File: `src/mmud/state/conditions.py` (ONSET_PATTERNS / RECOVERY_PATTERNS, ~line 17-32)
Current (onset, sample):
- POISONED: `you (?:are|have been|feel) .*poison`
- BLIND: `you (?:are|have been|go) blind|you cannot see`
- HELD: `you (?:are|have been) (?:held|paralyzed)|you cannot move`
Current (recovery, sample):
- POISONED: `poison has worn off|poison leaves? your`
- BLIND: `you can see again|your (?:sight|vision) returns`
Real capture (onset): __________________________________________________
Real capture (recovery): _______________________________________________

## Inventory — carrying / wearing / wealth / encumbrance
File: `src/mmud/parser/inventory_parser.py` (lines 5-14)
Current:
- `^You are carrying\s+(.*)$`
- `^You are wearing\s+(.*)$`
- `^Wealth:\s+(\d+)\s+(copper|silver|gold|platinum|runic)`
- `^Encumbrance:\s+(\d+)/(\d+)\s*-\s*(\w+)\s*\[(\d+)%\]`
Real capture: __________________________________________________________

## Loot — "You notice ... here."
File: `src/mmud/automation/items.py` (line 14)
Current: `^You notice (.+?) here\.?$`
Real capture: __________________________________________________________

## Exits — "Obvious exits:"
File: `src/mmud/parser/exits_parser.py` (line 4)
Current: `^Obvious exits:\s*(.+?)\.?$`
Note: this line doubles as the ARRIVAL signal for unnamed rooms (88% of graph).
Real capture: __________________________________________________________

## Doors — closed / locked
File: `src/mmud/automation/doors.py` (lines 6-7)
Current:
- closed: `(?:the )?door is closed|it'?s closed`
- locked: `(?:the )?door is locked|it'?s locked`
Real capture (closed): _________________________________________________
Real capture (locked): _________________________________________________

## Party — member row / leader / invite
File: `src/mmud/parser/party_parser.py` (lines 7-20), `src/mmud/automation/party.py` (line 14)
Current:
- header: `The following people are in your`
- following: `^You are following\s+(\w+)`
- row: `^\s*([A-Z][\w']*)(?:\s+[A-Z][\w']*)?\s+\[([^\]]+)\]\s+\[\s*(\d+)\](?:\s+\[\s*(\d+)\])?(?:\s+(P))?\s*$`
- invite: `(\w+) has invited you to join`
- leader-hit (attack_with_leader): `\b(?:swings?|attacks?|hits?|strikes?|slashes?|casts?)\b`
Real capture (row): ____________________________________________________
Real capture (invite): _________________________________________________
Real capture (leader-hit): _____________________________________________

## Commerce — train ready / done
File: `src/mmud/automation/commerce.py` (lines 15-19)
Current:
- ready: `enough experience to advance|you may now advance|ready to train`
- done: `you advance to level|you are now level|welcome to level`
Bank/shop/share command SYNTAX (verify these are the server's commands):
- `deposit <n> <denom>` / `withdraw <n> copper` (commerce.py 138/143)
- `sell <item>` / `buy <item>` (commerce.py 146/150)
- `share <n> <denom>` (party.py 86)
Real capture (train ready): ____________________________________________
Real capture (train done): _____________________________________________
Confirmed command syntax: ______________________________________________

## Backstab — hide / sneak / backstab stages
File: `src/mmud/combat/backstab.py` (lines 10-15)
Current:
- hide ok: `slip into the shadows|you are hidden`
- hide fail: `fail to hide|can'?t hide`
- sneak ok: `move silently|begin to sneak`
- sneak fail: `fail to sneak|make a noise`
- bs ok: `plant your weapon|backstab.*for \d+`
- bs fail: `backstab attempt fails|fails? to find an opening`
Real capture (hide): ___________________________________________________
Real capture (sneak): __________________________________________________
Real capture (backstab): _______________________________________________

## Combat — player hit / miss / monster hit / backstab (bot.py)
File: `src/mmud/bot.py` (lines 50-53)
Current:
- player hit: `You (?:hit|strike|slash|pierce|bash|backstab)\w* \w.+? for (\d+) damage`
- player miss: `You miss\b`
- monster hit: `(?:hits?|strikes?|slashes?|bashes?|pierces?) you for (\d+) damage`
- backstab: `You backstab`
Real capture: __________________________________________________________
```
- [ ] Verify it renders (no broken fences): `python -c "import pathlib; print(len(pathlib.Path('docs/testing-plan.md').read_text()))"`.
- [ ] Commit: `docs: add live-tuning regex harness (testing-plan.md)`

---

## Task 4: Maintainability refactors (behavior-preserving, test-guarded)

All existing tests MUST stay green after each step (`python -m pytest -q`). No behavior change.

**Files:**
- `src/mmud/automation/decision.py`
- `src/mmud/config/loader.py`
- `src/mmud/bot.py`
- `tests/test_decision.py`, `tests/test_config.py`

### 4a. Name the backstab priority slot (decision.py)

- [ ] Add a test to `tests/test_decision.py`:
```python
def test_prio_backstab_sits_just_above_combat():
    from mmud.automation.decision import PRIO_BACKSTAB, PRIO_COMBAT
    assert PRIO_BACKSTAB == PRIO_COMBAT - 1
```
- [ ] Run: `python -m pytest tests/test_decision.py -q` (expect FAIL — name not defined).
- [ ] In `src/mmud/automation/decision.py`, add after `PRIO_COMBAT = 40 ...`:
```python
PRIO_BACKSTAB = PRIO_COMBAT - 1  # hide/sneak/stab, just before melee
```
- [ ] In `src/mmud/bot.py`, change `self._engine.register("backstab", self._backstab, PRIO_COMBAT - 1)` to use `PRIO_BACKSTAB`, and add `PRIO_BACKSTAB` to the decision import block at the top of `bot.py`.
- [ ] Run: `python -m pytest tests/test_decision.py tests/test_bot.py -q` (expect PASS).
- [ ] Commit: `refactor(decision): name PRIO_BACKSTAB slot`

### 4b. Table-driven decider registry + `_build_engines()` (bot.py)

The 13 `self._engine.register(...)` calls and their scattered deferred imports become one ordered table built in a single method. This is behavior-preserving: same names, same priorities, same instances.

- [ ] Add a test to `tests/test_bot.py` that pins the registry order (guards the refactor):
```python
@pytest.mark.asyncio
async def test_engine_registry_order_and_names():
    from mmud.config.schema import MudConfig
    bot = make_transcript_bot([], config=MudConfig())
    slots = bot._engine._slots  # list[(priority, name, decider)]
    names = [name for _prio, name, _d in slots]
    # priorities must be sorted ascending and include every registered slot
    prios = [p for p, _n, _d in slots]
    assert prios == sorted(prios)
    for expected in ("queue", "cures", "run", "backstab", "spells", "combat",
                     "refresh", "equip", "items", "commerce", "party",
                     "travel", "search"):
        assert expected in names
```
- [ ] Run: `python -m pytest tests/test_bot.py -q` (expect PASS — this just documents current behavior; keep it green through the refactor).
- [ ] In `src/mmud/bot.py`, pull the deferred local imports that build deciders up into a single `_build_engines()` method. Create the method and have `__init__` call it. The construction of each decider object stays identical; only the wiring is consolidated. Define `_build_engines` to assemble a list of `(name, decider, priority)` tuples and register them in a loop:
```python
    def _build_engines(self) -> None:
        from mmud.automation.cures import CureDecider
        from mmud.automation.run_rules import RunDecider
        from mmud.combat.backstab import BackstabEngine
        from mmud.state.inventory import RefreshDecider
        from mmud.automation.equip import EquipDecider
        from mmud.automation.travel import TravelDecider
        from mmud.automation.search import SearchDecider
        from mmud.automation.commerce import CommerceEngine
        from mmud.automation.party import PartyDecider

        self._backstab = BackstabEngine(self._config.combat, self._config.stealth)
        self._equip_decider = EquipDecider(
            self._item_db, enabled=self._config.items.auto_get,
            on_mark=(lambda n: self._store.add_mark("no_auto_equip", n)) if self._store else None)
        self._travel = TravelDecider(self._config.items, self._config.stealth,
                                     self._bus or GameEventBus())
        self._commerce = CommerceEngine(
            self._config.commerce, self._config.items,
            navigate=self.navigate_to_room,
            resume_loop=lambda: self.start_loop(),
            loop_running=lambda: bool(self._loop_runner and self._loop_runner.running),
            travel_active=lambda: self._travel.active)
        self._party_decider = PartyDecider(self._config.party, self._config.players)

        registry: list[tuple[str, object, int]] = [
            ("queue",    QueueDecider(),                                          PRIO_QUEUE),
            ("cures",    CureDecider(self._config.health),                        PRIO_CURE),
            ("run",      RunDecider(self._config.combat, self._config.navigation), PRIO_FLEE),
            ("backstab", self._backstab,                                          PRIO_BACKSTAB),
            ("spells",   self._spell_engine,                                      PRIO_SPELLS),
            ("combat",   self._combat,                                            PRIO_COMBAT),
            ("refresh",  RefreshDecider(),                                        PRIO_REFRESH),
            ("equip",    self._equip_decider,                                     PRIO_EQUIP),
            ("items",    self._get_decider,                                       PRIO_ITEMS),
            ("commerce", self._commerce,                                          PRIO_COMMERCE),
            ("party",    self._party_decider,                                     PRIO_PARTY),
            ("travel",   self._travel,                                            PRIO_TRAVEL),
            ("search",   SearchDecider(self._config.navigation),                  PRIO_SEARCH),
        ]
        for name, decider, prio in registry:
            self._engine.register(name, decider, prio)
```
  > IMPORTANT: `self._get_decider`, `self._spell_engine`, `self._combat`, `self._inv_parser`, the `MonsterDB`/`ItemDB`, and `self._store` mark-replay must still be constructed *before* `_build_engines()` runs (they are dependencies). Keep their construction in `__init__` in the existing order, then replace the 13 inline `register` calls (and the now-duplicated decider constructions for backstab/equip/travel/commerce/party) with a single `self._engine = DecisionEngine(); self._build_engines()`. Leave the `self._store` mark-replay block (`for n in self._store.marks(...)`) where it is, after `_build_engines()` so the deciders exist.
- [ ] Carefully delete the now-duplicated inline constructions (the old `self._engine.register("queue"...)`, `register("spells"...)`, `register("combat"...)`, `register("cures"...)`, `register("run"...)`, `register("backstab"...)`, `register("refresh"...)`, `register("items"...)`, `register("equip"...)`, `register("travel"...)`, `register("search"...)`, `register("commerce"...)`, `register("party"...)` lines and the duplicated `BackstabEngine`/`EquipDecider`/`TravelDecider`/`CommerceEngine`/`PartyDecider`/`PartyParser` decider construction). Keep `self._party_parser`, `self._invites`, `self._doors`, `self._inv_parser` construction (they are not deciders).
- [ ] Run: `python -m pytest tests/test_bot.py -q` then the **full** suite `python -m pytest -q` (expect 426 passing, no change). If any test fails, the registry order or a missing dependency is wrong — fix before committing.
- [ ] Commit: `refactor(bot): table-driven decider registry via _build_engines()`

### 4c. Document `_process_line` hook ordering + class docstring (bot.py)

- [ ] No new test (comment-only). Add a `MudBot` class docstring (right under `class MudBot:`):
```python
    """Top-level bot: reads MUD lines, runs the _process_line hook pipeline to
    update GameState, then asks the DecisionEngine for the next command to send.

    Wiring: __init__ builds parsers + monitors + the decider registry
    (_build_engines). run() drives the reconnect loop; _run_session() owns one
    connection's read/decide/send loop plus the 1Hz _ticker (spell cooldowns,
    AFK, task/session timeouts, scheduler).
    """
```
- [ ] Add an ordered comment block at the top of `_process_line` documenting each hook and its dependency:
```python
        # _process_line hook order (DEPENDENCIES — do not reorder blindly):
        #  1. session.on_line    — raw capture BEFORE ANSI strip
        #  2. emit LineReceived  — web/UI sees raw line
        #  3. ANSI strip -> clean; all hooks below consume `clean`
        #  4. _parse_vitals      — HP/MP gauges; feeds AFK + health_low
        #  5. inventory parser   — multi-line accumulate; completes WAITING task
        #  6. _parse_conditions  — onset aborts task; BLIND stops loop
        #  7. safety/backstab/combat/commerce/party line monitors
        #  8. loot + get-results — must precede room parse (room clears ground)
        #  9. _parse_room        — clears monsters/players/ground, resets backstab
        # 10. _parse_exits       — arrival signal for unnamed rooms (after room)
        # 11. combat-exit + combat-stats, doors, nav-failure
        # 12. conversation/login/who-exp
        # 13. matcher.match      — effect apply/remove + combat onset (LAST)
```
- [ ] Run full suite `python -m pytest -q` (expect 426 passing).
- [ ] Commit: `docs(bot): document MudBot + _process_line hook ordering`

### 4d. Logging on the silent reconnect except (bot.py)

- [ ] Add a test to `tests/test_bot.py`:
```python
@pytest.mark.asyncio
async def test_connection_loss_is_logged(caplog):
    import logging
    from mmud.config.schema import MudConfig
    bot = make_transcript_bot([], config=MudConfig())

    async def boom():
        raise ConnectionError("boom")
    bot._run_session = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="mmud.bot"):
        await bot.run()
    assert any("boom" in r.getMessage() or "connection" in r.getMessage().lower()
               for r in caplog.records)
```
- [ ] Run: `python -m pytest tests/test_bot.py -q` (expect FAIL).
- [ ] In `src/mmud/bot.py`, add at module top: `import logging` and `_log = logging.getLogger(__name__)`. Replace:
```python
            except (ConnectionError, OSError):
                pass
```
with:
```python
            except (ConnectionError, OSError) as exc:
                _log.warning("connection lost: %s", exc)
                self._session.on_carrier_lost()
                self._emit(SessionStatUpdated(
                    key="carrier_lost", value=str(self._session.carrier_lost)))
```
  (If Task 2d already added the `on_carrier_lost()` call here, keep just the `_log.warning` line and the existing comms wiring — do not double-count.)
- [ ] Run: `python -m pytest tests/test_bot.py -q` (expect PASS).
- [ ] Commit: `fix(bot): log connection loss instead of swallowing it`

### 4e. Table-driven loader via dataclass introspection (loader.py)

Replace the repetitive `Cfg(field=d.get("field", default), ...)` blocks with one generic helper that reads the dataclass's own fields + defaults. **This helper is the shared foundation Doc 2's config writer reuses** — keep it general and well-typed.

- [ ] Add a test to `tests/test_config.py`:
```python
def test_unpack_dataclass_uses_defaults_and_overrides():
    from dataclasses import dataclass, field
    from mmud.config.loader import unpack_dataclass

    @dataclass
    class Sample:
        a: str = "x"
        b: int = 1
        c: list = field(default_factory=list)

    assert unpack_dataclass(Sample, {}) == Sample()
    got = unpack_dataclass(Sample, {"b": 5, "c": ["k"]})
    assert got == Sample(a="x", b=5, c=["k"])
    # unknown keys are ignored (forward-compat)
    assert unpack_dataclass(Sample, {"zzz": 9}) == Sample()


def test_loader_still_parses_full_config(tmp_path):
    from mmud.config.loader import load_config
    p = tmp_path / "c.toml"
    p.write_text(
        "[server]\nhost=\"h\"\nport=1234\n"
        "[combat]\nattack_cmd=\"slay\"\nflee_threshold=0.2\n",
        encoding="utf-8")
    cfg = load_config(p)
    assert cfg.server.host == "h"
    assert cfg.server.port == 1234
    assert cfg.combat.attack_cmd == "slay"
    assert cfg.combat.flee_threshold == 0.2
```
- [ ] Run: `python -m pytest tests/test_config.py -q` (expect FAIL — `unpack_dataclass` undefined).
- [ ] In `src/mmud/config/loader.py`, add the helper (after the imports):
```python
import dataclasses
from typing import TypeVar

_T = TypeVar("_T")


def unpack_dataclass(cls: type[_T], data: dict, *,
                     skip: set[str] | None = None) -> _T:
    """Build a flat dataclass from a TOML dict, using the dataclass's own field
    names + defaults. Unknown keys are ignored (forward-compat). Nested
    dataclass / list-of-dataclass fields are listed in `skip` and handled by the
    caller. Shared with Doc 2's config writer — keep this generic.
    """
    kwargs = {}
    skip = skip or set()
    for f in dataclasses.fields(cls):
        if f.name in skip or f.name not in data:
            continue
        kwargs[f.name] = data[f.name]
    return cls(**kwargs)
```
- [ ] Refactor the *flat* sections of `load_config` to use it (sections with no nested-dataclass fields). For example replace the `ServerConfig(...)` block with `cfg.server = unpack_dataclass(ServerConfig, s)`, and similarly for `LoginConfig`, `CombatConfig`, `StealthConfig`, `NavigationConfig`, `ItemsConfig`, `AfkConfig`, `HealthConfig`, `SafetyConfig`, `RemoteConfig`, `PvpConfig`, `LearningConfig`, `CommerceConfig`, `SessionConfig`, `UiConfig`. For sections with nested list-of-dataclass fields (`SpellsConfig.bless`, `PartyConfig.bless`, `ScheduleConfig.events`, top-level `players`), use `skip={"bless"}` (etc.) and assign the nested list explicitly afterward, e.g.:
```python
    if sp := data.get("spells"):
        cfg.spells = unpack_dataclass(SpellsConfig, sp, skip={"bless"})
        cfg.spells.bless = [
            BlessSpell(cmd=b.get("cmd", ""), mana_pct=b.get("mana_pct", 0.80))
            for b in sp.get("bless", [])
        ]
    if p := data.get("party"):
        cfg.party = unpack_dataclass(PartyConfig, p, skip={"bless"})
        cfg.party.bless = [
            PartyBless(cmd=b.get("cmd", ""), wait_seconds=b.get("wait_seconds", 60))
            for b in p.get("bless", [])
        ]
    if sc := data.get("schedule"):
        cfg.schedule = ScheduleConfig(events=[
            unpack_dataclass(ScheduleEvent, ev) for ev in sc.get("events", [])
        ])
    cfg.players = [unpack_dataclass(PlayerRule, pl) for pl in data.get("players", [])]
```
  > Keep the `if <key> := data.get(...)` guards so a missing section leaves the default instance untouched. Remove the now-unused per-field `.get(...)` blocks. The unused imports (`ServerConfig`, etc.) stay — they are the `cls` arguments.
- [ ] Run: `python -m pytest tests/test_config.py -q` (expect PASS).
- [ ] Run full suite `python -m pytest -q` (expect 426 passing).
- [ ] Commit: `refactor(loader): table-driven via unpack_dataclass introspection`

---

## Task 5: Test gaps

**Files:**
- `tests/test_navigator.py` (new)
- `tests/test_connection.py` (new)
- `tests/test_decision.py`

### 5a. Unit tests for Navigator

Read `src/mmud/navigation/navigator.py` first. It maps `(from_code, to_code) -> GamePath`; `list_loop_paths()` returns sorted `from_code`s where `from==to`.

- [ ] Create `tests/test_navigator.py`:
```python
from mmud.navigation.navigator import Navigator
from mmud.data.paths import GamePath, PathStep
from mmud.state.game_state import GameState


def _path(fc, tc, steps):
    return GamePath(from_code=fc, from_region="", from_name="",
                    to_code=tc, to_region="", to_name="", npc="",
                    steps=[PathStep(hex_id="", command=c) for c in steps])


def test_get_path_returns_registered_path():
    p = _path("AAAA", "BBBB", ["n", "e"])
    nav = Navigator([p])
    assert nav.get_path("AAAA", "BBBB") is p
    assert nav.navigate_to("AAAA", "BBBB") is p


def test_get_path_unknown_returns_none():
    nav = Navigator([])
    assert nav.get_path("AAAA", "ZZZZ") is None


def test_execute_path_enqueues_commands():
    nav = Navigator([_path("AAAA", "BBBB", ["n", "e", "u"])])
    gs = GameState()
    nav.execute_path(nav.get_path("AAAA", "BBBB"), gs)
    assert [gs.dequeue() for _ in range(3)] == ["n", "e", "u"]


def test_list_loop_paths_is_sorted_and_deduped():
    nav = Navigator([
        _path("ZZZZ", "ZZZZ", ["n"]),
        _path("AAAA", "AAAA", ["s"]),
        _path("AAAA", "BBBB", ["e"]),   # not a loop
    ])
    assert nav.list_loop_paths() == ["AAAA", "ZZZZ"]
```
- [ ] Run: `python -m pytest tests/test_navigator.py -q` (expect PASS).
- [ ] Commit: `test(navigator): unit-test path lookup + loop listing`

### 5b. Unit tests for MudConnection (IAC handling + line framing)

Read `src/mmud/net/connection.py` first. `_strip_iac(bytes) -> str` strips/responds to telnet IAC sequences; `readlines()` frames on `\n` with an 80ms prompt-flush timeout.

- [ ] Create `tests/test_connection.py`:
```python
import asyncio
import pytest
from mmud.net.connection import (
    MudConnection, IAC, WILL, DO, DONT, OPT_TERM_TYPE, OPT_ECHO,
)


def test_strip_iac_passes_plain_text():
    c = MudConnection("h", 0)
    assert c._strip_iac(b"hello world\n") == "hello world\n"


def test_strip_iac_removes_negotiation_sequence():
    c = MudConnection("h", 0)
    # DO TERM_TYPE in the middle of text is consumed (writer is None -> no reply)
    data = b"abc" + bytes([IAC, DO, OPT_TERM_TYPE]) + b"def"
    assert c._strip_iac(data) == "abcdef"


def test_strip_iac_escaped_iac_becomes_single_byte():
    c = MudConnection("h", 0)
    assert c._strip_iac(bytes([IAC, IAC])) == "\xff"


@pytest.mark.asyncio
async def test_readlines_frames_on_newline():
    c = MudConnection("h", 0)

    class FakeReader:
        def __init__(self, chunks):
            self._chunks = list(chunks)

        async def read(self, _n):
            await asyncio.sleep(0)
            return self._chunks.pop(0) if self._chunks else b""

    c._reader = FakeReader([b"line one\nline two\n", b""])
    lines = [line async for line in c.readlines()]
    assert lines == ["line one\n", "line two\n"]
```
- [ ] Run: `python -m pytest tests/test_connection.py -q` (expect PASS).
- [ ] Commit: `test(connection): unit-test IAC stripping + line framing`

### 5c. Decision-engine preemption-boundary + task-pinning edge cases

Read `src/mmud/automation/decision.py` and `src/mmud/state/tasks.py`. Key rule: a slot at priority `>= task.priority` is skipped; only a *strictly lower* priority decider preempts (and aborts the task). A decider that begins its own task and returns a command in the same call must NOT be aborted.

- [ ] Append to `tests/test_decision.py`:
```python
def test_equal_priority_decider_does_not_preempt_its_own_task():
    # A decider at the same priority as an active task is skipped, not run.
    engine = DecisionEngine()
    same = StubDecider("x")
    engine.register("same", same, priority=PRIO_COMBAT)
    gs = GameState()
    gs.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)
    assert engine.next_command(gs) is None
    assert same.calls == 0
    assert gs.task.is_active


def test_self_starting_task_command_is_not_aborted():
    # A decider that begins a task AND returns a command in the same call
    # (e.g. RunDecider) must keep its task — only strictly-higher slots abort.
    from mmud.state.game_state import GameState as GS

    class SelfStarter:
        def decide(self, state):
            state.begin_task(TaskType.RUNNING, priority=PRIO_COMBAT)
            return "flee"

    engine = DecisionEngine()
    engine.register("runner", SelfStarter(), priority=PRIO_COMBAT)
    gs = GS()
    assert engine.next_command(gs) == "flee"
    assert gs.task.is_active             # NOT aborted by its own slot
    assert gs.task.type is TaskType.RUNNING


def test_lower_number_slot_preempts_active_higher_number_task():
    engine = DecisionEngine()
    engine.register("cure", StubDecider("cast cure"), priority=PRIO_CURE)
    gs = GameState()
    gs.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)  # higher number
    assert engine.next_command(gs) == "cast cure"
    assert not gs.task.is_active          # preempted + aborted


def test_pinned_task_blocks_lower_priority_but_higher_still_runs():
    engine = DecisionEngine()
    high = StubDecider("high")   # numerically lower -> tried first, can preempt
    low = StubDecider("low")     # numerically higher -> pinned out
    engine.register("high", high, priority=PRIO_CURE)
    engine.register("low", low, priority=PRIO_TRAVEL)
    gs = GameState()
    gs.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)
    assert engine.next_command(gs) == "high"
    assert low.calls == 0
```
- [ ] Run: `python -m pytest tests/test_decision.py -q` (expect PASS).
- [ ] Run full suite `python -m pytest -q` (expect 426 + new test deltas; all green).
- [ ] Commit: `test(decision): preemption-boundary + task-pinning edge cases`

---

## Self-Review

Before declaring the plan done, confirm each of these (use superpowers:verification-before-completion — run the commands, read the output, don't assert from memory):

- [ ] **Existing 415 tests stay green.** Every new feature is inert under a pure-default `MudConfig()`: `multi_attack`/`must_sneak`/`attack_with_leader` all gate on opt-in flags or non-empty strings; new stat counters start at 0 and only emit events from real transcript lines. Run `python -m pytest -q` after every task and confirm the count only grows (415 → ~426+), never drops.
- [ ] **No placeholders.** Every step above contains complete, runnable code — no `TODO`, no "similar to above". Deleted fields are removed from schema, loader, and example.toml together, with a forward-compat guard test.
- [ ] **Type-consistent signatures across tasks.** `CombatEngine.__init__(..., must_sneak: bool = False)` and `CombatEngine.on_line(line: str) -> None` match the `on_line` convention used by backstab/commerce/party. `PartyDecider.on_line(line: str) -> None` and `.leader_engaged: bool` are consistent. `SessionManager` counters are plain `int`; `time_to_level_hours(exp_to_next: int) -> float`. All `record_*` methods return `None`.
- [ ] **The loader-introspection helper (`unpack_dataclass`) is the shared foundation Doc 2 reuses.** It is generic (works on any flat dataclass via `dataclasses.fields`), ignores unknown keys (forward-compat), and exposes a `skip` param for nested-dataclass sections. Doc 2's in-app config *writer* inverts it (dataclass → TOML dict) over the same field metadata — do not duplicate field lists; both read the dataclass as the single source of truth.
- [ ] **Regex harness is actionable.** `docs/testing-plan.md` quotes the *current* source pattern with `file:line` for every load-bearing regex, has a blank capture slot, and a 4-step tune procedure — ready to fill in during the first live session.
