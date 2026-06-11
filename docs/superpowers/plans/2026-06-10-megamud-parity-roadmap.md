# MegaMud Parity Roadmap

> **For agentic workers:** This is the master roadmap. Phases 1–3 have fully detailed task-by-task plans (links below) — execute those with superpowers:subagent-driven-development or superpowers:executing-plans. For each later phase, FIRST run superpowers:writing-plans to expand it into a detailed plan (its specifics depend on the Phase 1 Decider API and on what live testing reveals), THEN execute.

**Goal:** Close the feature gap between the Python port (`src/mmud/`) and the original megamud.exe, whose full behavior was cataloged via Ghidra RE (~92% of 1440 functions documented).

**Tech stack:** Python 3.11+, asyncio, Textual TUI, TOML config, stdlib `re` — no new dependencies anticipated until the web UI.

---

## Gap Summary — what the original has that the port lacks

**Architecture gap (load-bearing):**
1. **"DoSomething" priority AI loop** — the original tries ~40 decision functions in strict priority order per tick (queued → cure → flee → combat → rest → refresh → bless → equip → items → party → travel → search) with a **task state machine** (Getting / Dropping / Stashing / Equipping / Searching / Running / Blessing / Casting / Resting / Waiting / Relogging / Hanging / Training) and task timeouts. The port has a flat 3-step `_next_command()` (queue → spells → combat) in `src/mmud/bot.py`.

**Behavior gaps:**
2. **Conditions & cures** — poisoned/diseased/held/stunned/blind/confused detection; cure commands (blind/poison/disease/freedom); conditions interrupt tasks; blind blocks movement.
3. **Combat depth** — backstab workflow (track→hide→sneak→backstab, run-if-bs-fails), run rules (max monsters, max monster exp, run-rooms count, run backwards), attack-spell cast-count limit + weapon swap, monster priority/pinning, PvP handling (action/spell/flee-room/delayed hangup).
4. **Inventory/loot/cash** — inventory model from `inv` parsing, auto-get after combat, auto-equip, drop/stash, coin upconversion, max-coins/max-wealth/min-wealth, cursed items, encumbrance gating (`items.*` config exists, unused).
5. **Shopping/banking/training** — buy/sell deciders, mid-path shop/bank detours, deposit/withdraw, auto-train.
6. **Multi-hop pathfinding** — room-graph BFS with error codes (no-path / level-gated / blocked / need-boat), destination queue, **path resync from history**, uncertain-room retry, roaming, door bash/pick/trap, hidden-exit search. Port is single-hop .MP lookup only.
7. **Party support** — member HP tracking, party heal/buff, leader wait/resume protocol, share cash, invites. `PartyConfig` exists in full, entirely unused.
8. **Remote control via tells** — 47 @-verbs (@kill/@goto/@loop/@stop/@hangup/@status/@health/@auto-*/@panic! …) gated per-player. `PlayerRule.remote_cmds` exists, unused.
9. **Hangup/disconnect safety** — hangup on AFK/naked/death/hangup-player-or-monster, max-hours-per-day, exp-rate-too-low logoff, relog-instead, auto-reconnect with redial max.
10. **Timed-event scheduler** — EVENTS.MD (Logon/Logoff/Relog/GoTo/Command/LoopPathChange), simple script stepper with conditionals, command template expansion; MACROS.MD key binds.
11. **Live DB learning** — auto-add unknown monsters/items/players on sight; persist non-enemy/un-gettable/no-auto-equip marks. (Binary loaders for MONSTERS/ITEMS/SPELLS/PLAYERS.MD exist in `src/mmud/data/binary.py` but are unused in bot logic.)
12. **Session management** — capture-to-file, exp-rate calc, session timers, relog flow.

**Deliberately skipped:** Zmodem/Xmodem, modem/RAS/serial, registration/copy-protection, Win32 UI specifics (the TUI + GameEventBus replace them; a web UI can subscribe to the same bus later).

---

## Phase Index

| # | Phase | Size | Status | Plan |
|---|-------|------|--------|------|
| 1 | Decision Engine Core | M | ✅ complete | [2026-06-10-phase-01-decision-engine.md](2026-06-10-phase-01-decision-engine.md) |
| 2 | Conditions, Cures, Panic Safety | M | ✅ complete | [2026-06-10-phase-02-conditions-cures-safety.md](2026-06-10-phase-02-conditions-cures-safety.md) |
| 3 | Remote Control via Tells | S–M | ✅ complete | [2026-06-10-phase-03-remote-control.md](2026-06-10-phase-03-remote-control.md) |
| 3.5 | **MDB2 Parser Rewrite** (prereq for 4–5) | S | ✅ complete | [2026-06-10-mdb2-parser-rewrite.md](2026-06-10-mdb2-parser-rewrite.md) |
| 4 | Combat Depth | L | ✅ complete | [2026-06-10-phase-04-combat-depth.md](2026-06-10-phase-04-combat-depth.md) |
| 5 | Inventory, Loot, Cash | L | planned | [2026-06-10-phase-05-inventory-loot-cash.md](2026-06-10-phase-05-inventory-loot-cash.md) |
| 6 | Multi-hop Pathfinding, Resync, Doors, Search | L | not started | write plan at phase start |
| 7 | Live DB Learning | S–M | not started | write plan at phase start |
| 8 | Shopping, Banking, Training | M | not started | write plan at phase start |
| 9 | Session Management & Full Disconnect Logic | M | not started | write plan at phase start |
| 10 | Party Support | M | not started | write plan at phase start |
| 11 | Scheduler, Scripts, Macros | M | not started | write plan at phase start |

**Order rationale:** Phase 1 is the refactor everything else hangs off. Phases 2–3 are small and maximize live-testing safety/value now. Phases 4–6 are the big parity pillars in dependency order (combat → inventory → pathfinding). Phases 7–11 are leaf features that each depend on one or two earlier pillars. Phase 7 is order-flexible — pull it earlier if unknown-monster sightings become annoying during Phase 4 testing.

**One deliberate deviation:** the LoopRunner step-cursor rewrite (one move at a time, resync from history) is deferred entirely to Phase 6 rather than starting in Phase 1. The current bulk-enqueue looping is live-tested and works; rewriting it before the room graph and resync logic exist would destabilize the user's active testing for no immediate gain.

---

## Phase Summaries (4–11) — inputs for their future detailed plans

### Phase 4 — Combat Depth (L) — first consumer of binary MONSTERS.MD
- New `src/mmud/data/monster_db.py` — name-indexed wrapper over existing `load_monsters()` (case/article-insensitive lookup, exp values).
- `GameState.monsters_present` upgraded from `list[str]` to `list[MonsterSighting]` (name + DB record + flags).
- `src/mmud/combat/combat.py`: run rules (count > max_monsters or summed exp > max_monster_exp → `RUNNING` task using existing `navigation.flee_rooms`; optional run_backwards), target priority list + pinned target, attack spell with max_cast_count then melee, weapon swap around casting. Wire existing `combat.attack_order` / `combat.polite_attacks`.
- New `src/mmud/combat/backstab.py` — track→hide→sneak→backstab as a multi-step task; wire existing `combat.backstab`, `stealth.auto_hide`/`hide_cmd`/`sneak_cmd`; fail path per run_if_bs_fails.
- New `src/mmud/combat/pvp.py` — player-in-room detection → pvp action/spell/flee-room/delayed hangup.
- Config adds: `[combat]` max_monsters / max_monster_exp / run_backwards / run_if_bs_fails / use_shield_for_bs / monster_priority (list); `[spells]` max_cast_count / cast_weapon / melee_weapon; new `[pvp]` action / spell / flee_room / hangup_delay_s.

### Phase 5 — Inventory, Loot, Cash (L)
- New `src/mmud/parser/inventory_parser.py` — multi-line `inv` output → items + coins + encumbrance level.
- New `src/mmud/state/inventory.py` — `Inventory` on GameState with a `dirty` flag; a refresh decider (PRIO_REFRESH slot) issues `inv` when dirty (set after get/drop/buy/sell/combat-end).
- New `src/mmud/automation/items.py` — GetDecider (get-after-combat, per-denomination coin collection per existing `items.collect_*`, un-gettable marking), Drop/StashDecider, coin upconversion, cursed-item handling.
- New `src/mmud/automation/equip.py` + `src/mmud/data/item_db.py` wrapper over existing `load_items()` (equip slot data).
- Encumbrance gates travel — wire existing `dont_go_heavy`/`dont_go_medium`. Config adds: max_coins / max_wealth / min_wealth.

### Phase 6 — Multi-hop Pathfinding, Resync, Doors, Search (L — largest)
The port has **no room exit data** — the graph must be stitched from the 1198-path .MP corpus (`PathStep.hex_id` + `Room.hex_id` give room→room edges with commands) plus live-learned exits from an "Obvious exits:" parser.
- New `src/mmud/navigation/graph.py` — `RoomGraph` with edge attributes (door/lock/trap/level-gate/boat), BFS returning the original's error codes (no-path / level-gated / blocked / need-boat).
- New `src/mmud/parser/exits_parser.py` — "Obvious exits:" → learned edges; uncertain-room re-`look`.
- `Navigator`: multi-hop `navigate_to()` + destination queue.
- Rewrite `src/mmud/automation/loop_runner.py` as a step-cursor TravelDecider (PRIO_TRAVEL slot): one move per arrival; match arrived room vs expected step; scan path history to resync ("[Resynced from step X to Y]"); replaces the clear-and-restart `on_nav_failure`.
- New `src/mmud/automation/doors.py` — wire existing `can_pick_locks`/`can_disarm_traps`, bash fallback.
- Search decider (PRIO_SEARCH, bottom of chain) — auto_search/search_max as `SEARCHING` task; roaming (random exit). Config adds: `[navigation]` auto_search / search_max / roam / bash_doors.

### Phase 7 — Live DB Learning (S–M)
- New `src/mmud/data/learned.py` — JSON sidecar overlay per database (**do NOT write the binary B-trees**); merged at load by the monster_db/item_db/player wrappers (overlay checked first); atomic write-on-change.
- Hooks: unknown monster/item/player seen → record; non-enemy / un-gettable / no-auto-equip marks; Phase 6 learned exits use the same store. Config: `[learning] enabled = true`.

### Phase 8 — Shopping, Banking, Training (M) — needs Phases 5+6
- New `src/mmud/automation/commerce.py` — buy/sell/bank/train deciders, `TRAINING` task; travel decider inserts shop/bank detour destinations; deposit/withdraw vs wealth thresholds from Phase 5.
- Config: `[commerce]` bank_room / shop_room / sell_items / buy_items / auto_train / train_room.

### Phase 9 — Session Management & Full Disconnect Logic (M)
- New `src/mmud/session.py` — pure event-bus consumer: capture-to-file, exp-rate calculation, session/combat/idle timers.
- Relog flow (`RELOGGING` task reusing `LoginHandler`), max_hours_per_day, exp-rate-too-low logoff, relog-vs-hangup choice; completes Phase 2's basic reconnect; @relog/@rate verbs registered with the Phase 3 handler.
- Config: `[session]` capture_file / max_hours_per_day / min_exp_rate / low_rate_action (hangup|relog).

### Phase 10 — Party Support (M) — pure wiring of existing `[party]` config
- New `src/mmud/parser/party_parser.py` (member HP lines, invites) + `src/mmud/automation/party.py` (PartyDecider at PRIO_PARTY: heal members below heal_hp_pct respecting `PlayerRule.dont_heal`/`dont_bless`, party bless slots, `WAITING` task with wait_cmd/resume_cmd protocol, share-cash via Phase 5 inventory, invites).
- Register party @-verbs (@invite @wait @rego @share @forget) with the Phase 3 handler.

### Phase 11 — Scheduler, Scripts, Macros (M)
- New loaders `src/mmud/data/events_md.py` / `src/mmud/data/macros_md.py`; new `src/mmud/automation/scheduler.py` driven by the existing 1Hz `_ticker` — event types Logon / Logoff / Relog / GoTo / Command / LoopPathChange.
- Command template variable expansion (shared with @-command replies); TUI macro keybinds in `src/mmud/tui/app.py`.

---

## Cross-cutting rules (apply to every phase)

- **Reuse existing config fields first** — ~25 unused fields already exist (`items.*`, `party.*`, `players[].remote_cmds`, `combat.backstab`/`attack_order`/`polite_attacks`, `stealth.auto_hide`, `navigation.can_pick_locks`/`can_disarm_traps`, `afk.hangup_on_low_hp`). Wire them before adding new sections.
- **Event bus discipline** — every new subsystem emits events on `GameEventBus` (`TaskChanged`, `ConditionChanged`, `InventoryChanged`, `PartyChanged`, …); no decider ever touches TUI widgets. This keeps the future web UI viable.
- **TDD with transcripts** — every phase is testable offline via the `FakeConnection`/`make_transcript_bot` fixture built in Phase 1 Task 4: recorded server lines in → expected command sequence out. No live server needed for any test.
- **Frequent commits** — one commit per task, conventional-commit messages.
- **Critical files:** `src/mmud/bot.py`, `src/mmud/state/game_state.py`, `src/mmud/automation/loop_runner.py`, `src/mmud/config/schema.py`, `src/mmud/combat/combat.py`.

## Verification

- Full suite green after every task: `pytest -q` (139 passing as of commit 37b69ea must stay green; Phase 1 changes no behavior).
- Live smoke test after Phases 2, 3, 4, and 6 against the real MajorMUD server (user-driven, per `docs/testing-plan.md` — record actual condition/cure/door message formats there and tune the regexes).
- Parity acceptance reference: the Ghidra feature catalog (gap summary above) — each numbered gap maps to a phase.
