# mmud roadmap

Forward-looking work, grounded in the MegaMud binary (RE'd) and our current code.
Ordered roughly by value/effort. Check items off as they ship (branch → commit → merge, TDD).

> Ground truth is `megamud.exe` in Ghidra. RE notes live in `docs/re/` (+ `docs/re/source/`).
> When you implement an item, link the PR/commit and the `docs/re/source/<fn>.md` you wrote.

---

## A. Combat & survival

- [ ] **A1 — Configurable, split HP/Mana rest *resume* target** _(S, highest value)_
  - MegaMud `combat_rest_decide @0x40b380`: separate **Min (trigger)** / **Max (resume)** per HP
    *and* per Mana (`HpRest% 0x375c`/`HpFull% 0x3768`, `ManaRest% 0x3778`/`ManaFull% 0x3784`).
  - We hardcode a single `_REST_FULL = 0.95` for both (`combat/combat.py:10`, used in `decide` ~235-253).
  - Do: add `hp_full_pct` / `mana_full_pct` to `CombatConfig`, use per-stat targets, expose in web Settings.
  - ⚠️ Memory notes disagree on `0x3768` (HpFull vs HpRun) — **confirm offset→setting against the
    settings panel before wiring defaults.**
- [ ] **A2 — In-combat self-heal (opt-in)** _(S-M, class-dependent)_
  - MegaMud casts a heal mid-fight before fleeing. Ours only heals **out** of combat (`spells.py:123-126`);
    `HealthConfig.heal_spell` is party-only.
  - Do: add an `in_combat_heal` branch in `SpellEngine.decide` above the attack block (cast when
    `hp_pct < heal_hp_pct` and mana available), gated by a config flag.
- [ ] **A5 — Meditate + emergency item-use in combat** _(defer)_
  - `mana_meditate_decide @0x40caa0` (faster mana regen, gated `state+0x4e48`); potion/wand quaff.
    Class/quest-gated (Warlock can't meditate pre-L23). Note now, build later.

## B. Navigation

- [ ] **B1 — Finish the one-room-id path-follow** _(M, fixes lost-in-maze)_
  - MegaMud `path_follow_step_decide @0x405b60` / `path_find_current_step @0x42bf40`: position is **one**
    id (`state+0xba6`); a mismatch only bumps a miss counter (`state+0x152d`); **±1 peek** realign;
    full-path resync only after **3 misses** ("Resynced from path step %d to %d"); id-not-found →
    **Lost! (`state+0x1588`) STOP** (never blind-wander). Wildcards `0x99999999`/`0xffffffff` skip.
  - We have: advance-one-per-arrival + confident-name re-anchor (partial). **Not ported:** the ±1 peek,
    3-miss counter, true id-based Lost stop. We only landed the collision-reject (Fix A) this session.
  - Do: narrow `seen_hexes` to the single title-coloured line everywhere; add the per-route mismatch
    counter + ±1 peek before the optimistic advance (`travel.py on_arrival ~212-291`); replace the
    `_MAX_WANDER` giveup with an id-not-found Lost stop. (Algorithm fully RE'd in `navigation.md`.)
- [ ] **B2 — Use the `.MP` step flags (trap / rest / sneak / stop)** _(M, survival in trap zones)_
  - `.MP` step is `HexID:flags:command`; the 16-bit flags drive `path_follow_step_decide` /
    `path_exit_attempt @0x406920`: `0x02` stop-before, `0x04` rest-before, `0x08` sneak-only,
    `0x10` rest-after, `0x40` notify, `0x200` **TRAP** (search + `disarm trap <dir>` before stepping,
    gated `CanDisarmTraps gs+0x379c`).
  - We **throw the flags away** (`data/paths.py:123` splits and keeps only hex+command); `RouteStep`
    (`navigation/graph.py:17`) has no flags. Traps are only handled *after* tripping (`doors.py`).
  - Do: add `flags:int` to `PathStep`/`RouteStep`, thread through `code_route`, pre-emit
    `search`/`disarm trap` (config-gated) before a `0x200` step, honor rest-before/after waypoints.

## C. Web panel & TUI — feature completeness  _(being scoped; see below)_

Goal: bring the web/TUI control surface to parity with MegaMud's Windows UI (every setting editable,
the map/status/log surfaces present). To be filled from a binary **resource/dialog audit** (settings
dialogs, menus, the map view, status fields) — agent running.

- [ ] C0 — Audit MegaMud's UI resources (dialog templates, settings tabs, menus, map) → enumerate the
      full config surface and views we should expose.
- [ ] C1 — _(tbd from C0)_ Complete the Settings surface (every CombatConfig/Nav/Items/etc. field editable in web).
- [ ] C2 — _(tbd from C0)_ Map view (rooms/exits, current position, the loop path overlay).
- [ ] C3 — _(tbd from C0)_ …

---

## Done this session (for context)
- Login auto-handling (pager/`[MAJORMUD]`/`[HP=]`), auto-connect, no-spells-during-login.
- Encumbrance gates PICKUP not movement; DropCoins; read inventory on entry; request exp on entry/periodic.
- Nav **Fix A**: reject confident room-match whose hash isn't the room's own title id (cave-loop cycle).
- Resume loop after reconnect; emergency recall stops the loop; session-exp-made vs total exp stats.
- Web `POST /api/loop` to start/stop a loop by name.
