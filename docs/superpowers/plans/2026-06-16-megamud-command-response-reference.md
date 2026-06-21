# MegaMud Command & Response Reference Docs + Config Parity Gap-Fix

> Handoff plan (2026-06-16). Source: `~/.claude/plans/so-do-research-there-swirling-neumann.md`.
> Phases 1–3 below are the executable steps; Phase 1 findings get written into the
> two reference docs (Phase 2), and Phase 3 records the concrete config edit list
> at the end of this file.

## Context

Over the parity buildout we added many config knobs (e.g. `combat.attack_cmd`,
`items.cash_cmd = "get {amount} {denom}"`, several `*_cmd` fields). The concern:
**most of these aren't actually configurable in MegaMud** — we invented
adjustability the real client doesn't have, and in a few places we did the
opposite (hardcoded a verb MegaMud lets the user set). Rather than keep round-
tripping to Ghidra ad hoc, we **distill MegaMud's actual command and response
behavior into reference docs**, then use those docs as the source of truth for a
gap-fix pass.

**Decisions:**
- Deliverable = **reference docs covering ALL command AND response structures**
  MegaMud implements, **plus a gap-fix plan** that references those docs.
- The response/parsing doc must be a real **"how the app WORKS"** reference —
  the full incoming-text parsing pipeline, **with monster detection and room
  detection logic as the centerpiece**.
- Guiding rule = **match MegaMud exactly**. If MegaMud hardcodes a verb, we
  hardcode it and remove the knob. If MegaMud exposes it as a setting, we expose
  it. Parity is the source of truth — stop inventing configurability.

### Key findings already established (binary-grounded, megamud.exe)

MegaMud stores per-character automation settings in **`%s\BBS\%s\BBS.INI`**
(string @ `0x004b6c1c`), loaded via `GetPrivateProfileString`. The config
loaders are `FUN_00431d90` (@ `0x00431d90`) and `FUN_00438e50` (@ `0x00438e50`).
This is **distinct from `PLAYERS.MD`** (the who/spy DB of other players — names,
guild, alignment). Command settings are NOT in PLAYERS.MD.

Command dispatch choke points (each logs `"Issuing … command \"%s\""`):
- `FUN_00404cd0` (@ `0x0040521d`) — `"Issuing command \"%s\" from timed event"` (`0x004b5678`)
- `FUN_0040caa0` / `FUN_0040b380` — `"Issuing pre-rest command \"%s\""` (`0x004b64c0`)
- `FUN_00405b60` (@ `0x00406641`) — `"Issuing path command: %s"` (`0x004b5880`)

Configurable vs hardcoded (confirmed by presence/absence of an INI key + xrefs):

| Command | MegaMud | Evidence | Our bot today | Action |
|---|---|---|---|---|
| attack | **config** `AttackCmd` @0x004bcb1c | 2 xrefs in loaders | `combat.attack_cmd="kill"` | keep ✓ |
| rest | **config** `CmdRest` @0x004bc1d4 | pre-rest dispatch | **hardcoded `"rest"`** | **add config (gap)** |
| sneak | **config** `CmdSneak` @0x004bc1c8 | 2 xrefs | `stealth.sneak_cmd` | keep ✓ |
| hide | **config** `CmdHide` @0x004bc1c0 | 2 xrefs | `stealth.hide_cmd` | keep ✓ |
| search | **config** `CmdSearch` @0x004bc1b4 | 2 xrefs | **hardcoded `"search"`** | **add config (gap)** |
| inventory | **config** `CmdInv` @0x004bc1f4 | loaded | `items.inventory_cmd` | keep ✓ |
| flee | **hardcoded** | `flee`/`Flee` 0 xrefs to config | hardcoded | match ✓ |
| backstab | **hardcoded** | `backstab` 0 cfg xrefs | hardcoded | match ✓ |
| bash/open (doors) | **hardcoded** | no `Cmd*` key | hardcoded | match ✓ |
| get | **hardcoded** | `get` 0 cfg xrefs | `items.cash_cmd` template | **remove over-config (gap)** |
| equip | **hardcoded** | `equip` 0 cfg xrefs | hardcoded | match ✓ |

Other INI keys already spotted: `CmdExp`, `CmdStat`, `CmdWho`, `CmdReply`, and a
family of `Def*` keys (`DefSneak1/2`, `DefHide1/2`, `DefSearch1/2`, `DefGet1/2`,
`DefTrack1/2`). The **complete** key list is not yet enumerated — that is the
first execution step.

Response side (string-derived leads; all response-side claims are *to-verify from
the binary*, not established). Internals to document, with string anchors:

- **RX pipeline:** `"Receive buffer:"` (`0xbf0b0`), `"Receive len: %d"` (`0xbf0c8`),
  `"Current line: \"%s\""` (`0xbf0e4`, `0xc0538`), `"DBG: Recursive receive!"`
  (`0xbea54`), `"-RX Queue overflow"`.
- **Room detection (centerpiece):** room id `"In room: %08lX"` (`0xbf158`);
  exits `"Obvious exits: "` (`0xb82d4`), `"[No allowed exits]"` (`0xb57ac`);
  matching/learning `"[Adding room \"%s\" from path \"%s\"]"` (`0xb94a4`),
  `"[Path \"%s\" begins at an unknown room]"` (`0xb94c8`), `"Unknown room"`
  (`0xb816c`), `"[Uncertain room (Path %s, step %d): Trying step anyway]"`
  (`0xb5914`), `"The room you are currently in already matches"` (`0xc1f10`);
  refresh `"Re-displaying room"` (`0xb52dc`), `"Re-showing room exits"` (`0xb5a90`),
  `"10-second room refresh"`, `"[Room light updated]"` (`0xb58d4`).
- **Monster detection (centerpiece):** `"[%s added to known monsters]"` (`0xb7668`),
  `"[%s marked as enemy!]"` (`0xb7e54`), `"[%s marked as non-enemy]"` (`0xb764c`),
  `"[%s marked as flee!]"` (`0xb7e18`), `"[PVP detected! (%s)]"` (`0xb7ed4`);
  run rules `"[Running: Too many monsters! (%s)]"` (`0xb5eb8`),
  `"[Running: Too much monster experience! (%s)]"` (`0xb5e10`).
- **Named parsers:** `ParseInventory` (`0xbd80c`) → `GainItem` (`0xbdbd0`,
  `"[%s added to known items]"` `0xbd824`); `ParseWho` (`0xc635c`); `SortMessages`
  (`0xbd0c0`); MESSAGES.MD matcher (`"Messages.md"` `0xb8864`); prompt parser
  (`"[HP="` `0xbe178`, `"%d[HP=%h"` `0xc2b0c`).

---

## Phase 1 — Authoritative Ghidra research (binary only; ignore our Python port)

**Rule:** every claim cites a megamud.exe function/address. Do NOT consult
`src/mmud/**` to decide what MegaMud does — that is what we're auditing.

1. **Enumerate the full BBS.INI key set.** Decompile `FUN_00431d90` and
   `FUN_00438e50`; walk every `GetPrivateProfileString`/`...Int` call; record each
   key string, address, default, and the field it populates. Capture section names
   and the INI path template (`0x004b6c1c`).
2. **Map each configurable command to its dispatch.** Trace `AttackCmd`, `CmdRest`,
   `CmdSneak`, `CmdHide`, `CmdSearch`, `CmdInv` (and any new keys) from loaded
   buffer to the dispatch choke points; note pre-rest/post-rest/path/timed-event.
3. **Confirm the hardcoded set.** For `flee`, `backstab`, `bash`, `open`, `get`,
   `equip`, `train`, `deposit/withdraw`, `buy/sell`, `join/invite`, `share` —
   confirm no INI key, cite the literal's address and emitting function.
4. **Response/parsing side — "how the app works".** Decompile the function reached
   via `get_xrefs_to` on each anchor and describe the algorithm + data structures:
   - **RX pipeline / line classifier** — line assembly + central dispatch.
   - **ROOM DETECTION (centerpiece)** — keyed by id/name/exit-set/path position?
     exit parsing (+ hidden/searched), ROOMS.MD + `.MP` correlation,
     uncertain-room/resync logic, multi-line assembly + refresh triggers.
   - **MONSTER DETECTION (centerpiece)** — name extraction, MONSTERS.MD matching
     (article stripping, prefix/partial, plurals), enemy/non-enemy/flee
     classification, target priority, lifecycle tracking, run-rule inputs.
   - **Other parsers** — `ParseInventory`/`GainItem`, `ParseWho`, MESSAGES.MD
     matcher (record layout + wildcard/anchor), prompt parser (exact fields).
   - **Category catalog** — status/combat/conditions/exp-level-train/ground-items/
     login prompts, each with recognizing function(s)/strings.

Run as a small set of focused Ghidra sub-agents, each told to cite addresses and
avoid the Python port.

## Phase 2 — Write the reference docs (the deliverables)

At `docs/` root (mirror `cdb-mdb2-format.md` style — tables, addresses as evidence):

1. **`docs/megamud-commands-reference.md`** — per command: verb, configurable
   (exact `BBS.INI` key + default + address) or hardcoded (literal + emitting
   function), trigger, format/args. Include the full BBS.INI key table and the
   dispatch-choke-point explanation. End each row with **"our bot today"** +
   **"parity action"** so it doubles as the gap checklist.
2. **`docs/megamud-responses-reference.md`** — a "how MegaMud works" internals
   reference: RX pipeline + line-classification dispatch; **Room detection** (lead);
   **Monster detection** (lead); MESSAGES.MD format + matcher; prompt-line field
   extraction; category catalog. Include a pipeline diagram; cite the
   function/address behind each behavior.

## Phase 3 — Gap-fix edit list (apply "match MegaMud exactly")

Reconcile `src/mmud/config/schema.py` + consumers against the commands-reference.
Record the concrete edit list (file:line + justifying reference-doc row) in the
**"Phase 3 results"** section at the bottom of this doc. Representative changes:

- **Add missing real knobs:** `rest` → `combat.rest_cmd` (default `"rest"`,
  consumed `src/mmud/combat/combat.py:60`); `search` → `navigation.search_cmd`
  (default `"search"`, consumed `src/mmud/automation/search.py:35`); any other
  `Cmd*`/`Def*` key we lack.
- **Remove invented over-config:** `items.cash_cmd` template (MegaMud hardcodes
  `get`); audit `party.wait_cmd`/`resume_cmd`/`status_cmd`, `session.logout_cmd`,
  `afk.reply`, `health.*_cmd`, `stealth.auto_hide` (dead) against the Phase-1 key
  list; drop knobs with no MegaMud key, keep those that map to a real key.
- **Confirm correct matches:** flee/backstab/bash/open/equip hardcoded — no change,
  documented as intentional parity.

## Verification

- Each configurable-command claim cites a real `GetPrivateProfileString` key +
  address; each hardcoded claim cites the literal + emitting function. Spot-check 5
  keys by re-decompiling.
- Grep `schema.py` for `*_cmd`/`cmd` fields; every one maps to a commands-reference
  row (real key or documented divergence). Anything else is removed.
- `rest`/`search` still emit `"rest"`/`"search"` by default after becoming
  configurable; `pytest` passes.

---

## Phase 1 results

Done. Findings written into the two reference docs:
- `docs/megamud-commands-reference.md` — command catalog (configurable vs hardcoded).
- `docs/megamud-responses-reference.md` — RX pipeline + room/monster detection internals.

**Key corrections vs. the pre-research assumptions** (these reverse earlier guesses):
- The `Cmd*` INI keys (`CmdRest`/`CmdSneak`/`CmdHide`/`CmdSearch`/`CmdInv`/…) are
  **UI toolbar buttons only** — automation never reads them. So their existence
  does NOT make the automation verbs configurable.
- **rest** and **search** automation send **literal** `"rest"` / `"search %s"` —
  HARDCODED. We were already correct to hardcode them. ❌ Do NOT add
  `combat.rest_cmd` / `navigation.search_cmd` (the original plan's idea was wrong).
- **sneak** and **hide** automation send **literal** `"sneak"` / `"hide"` —
  HARDCODED. Our `stealth.sneak_cmd` / `stealth.hide_cmd` are invented over-config.
- **backstab** sends literal `"bs %s"` (verb `bs`, not `backstab`).
- Genuinely configurable: `AttackCmd` (attack prefix), spell commands
  (`AttackSpl`/`PreAttack`/`MultAttack`/`BlessCmd*`/`PartyBless*`/`PartyHeal*`),
  and `PreRestCmd` (a pre-rest command we don't have).

## Phase 3 results

Concrete config edit list, applying "match MegaMud exactly". Each change cites its
justifying row in `docs/megamud-commands-reference.md` (§3 = hardcoded, §2 = real knob).

### A. Remove invented over-config (MegaMud hardcodes these in automation)

1. **`stealth.sneak_cmd`** (schema.py:81) → remove field. Hardcode literal `"sneak"`
   at consumers: `src/mmud/combat/combat.py` (auto-sneak before attack) and
   `src/mmud/combat/backstab.py` (sneak step). Also `automation/travel.py` +
   `bot.py` auto-sneak-before-move paths. [ref §3 sneak — literal `0x004b5b28`]
2. **`stealth.hide_cmd`** (schema.py:84) → remove field. Hardcode literal `"hide"`
   at `src/mmud/combat/backstab.py` (hide step). [ref §3 hide — literal `0x004b5bcc`]
3. **`stealth.auto_hide`** (schema.py:83) → remove: dead/unused config (no consumer).
4. **`items.cash_cmd`** (schema.py:108) → remove the configurable *template*; MegaMud
   hardcodes the get-currency verb. Keep the amount/denom formatting in code
   (`src/mmud/automation/items.py`), but as a fixed `f"get {amount} {denom}"`, not a
   user-editable string. [ref §3 get(coins)]

### B. Fix verb to match MegaMud exactly

5. **Backstab verb**: `src/mmud/combat/backstab.py` sends `f"backstab {target}"`;
   MegaMud sends `f"bs {target}"`. Change to `bs` for parity. [ref §3 backstab —
   `0x004b5d2c`] (Both are accepted by MajorMUD; `bs` is what MegaMud emits.)

### C. Confirm correct — NO change (we already match MegaMud)

- `rest` (combat.py) hardcoded `"rest"`; `search` (search.py) hardcoded `"search"`;
  `flee`; door `open`/`bash`; `equip`; `train`; banking `deposit`/`withdraw`;
  shop `buy`/`sell`; party `join`/`invite`/`share`. [ref §3]
- `combat.attack_cmd`, `spells.*`, `party.bless[]` — real MegaMud knobs, keep. [ref §2]

### D. Add real knob we lack (optional, for full parity)

6. **Pre-rest command**: add `combat.pre_rest_cmd: str = ""` (sent before resting,
   template-expanded). Maps to MegaMud `PreRestCmd`. [ref §2]
   - Note: MegaMud has **two** `PartyHeal` slots (`PartyHeal1/2`); we expose one
     (`party.heal_spell`). Consider a 2-slot list if we want exact parity.

### E. Verify before touching (NOT decompiled on the automation path yet)

Do a follow-up Ghidra pass before changing these — unknown whether MegaMud exposes
an INI key or hardcodes on the automation path:
- `items.inventory_cmd` (schema.py:104) — likely over-config (CmdInv is UI-only),
  but the automation inventory-refresh command wasn't traced.
- `party.wait_cmd` / `party.resume_cmd` / `party.status_cmd` (schema.py:132,133,137).
- `session.logout_cmd` (schema.py:207).
- `afk.reply` (schema.py:145).
- `health.blind_cmd`/`poison_cmd`/`disease_cmd`/`freedom_cmd` (schema.py:153-156) —
  cures may be part of MegaMud's configurable spell/action system; confirm.

### Implementation notes

- After removing fields from `src/mmud/config/schema.py`, update consumers, any
  TOML example configs, `config/introspect.py`/`writer.py` round-trip, README
  config table, and tests. Run `pytest`.
- Verification (from plan): grep `schema.py` for `*_cmd`/`cmd` fields — each must
  map to a commands-reference row (real key or documented divergence); `rest`/
  `search` still emit `"rest"`/`"search"` by default; tests pass.

### Implementation status (2026-06-17) — applied on branch `fix/command-config-parity`

**Done (sections A, B, C):**
- A.1/A.2 Removed `stealth.sneak_cmd` / `stealth.hide_cmd`; hardcoded literals
  `"sneak"`/`"hide"` at consumers (`bot.py:151`, `combat/backstab.py:39-40`,
  `automation/travel.py:71`).
- A.3 Removed `stealth.auto_hide` (no automation reads it) + its `@auto-hide`
  remote toggle (`automation/remote.py`) + README row. Note: maps to MegaMud's
  real `AutoHide` key (ref §2) but is dead in our code — re-add mapped to
  `AutoHide` if/when an auto-hide behavior is implemented.
- A.4 Removed `items.cash_cmd` template; loot now emits fixed `f"get {amount} {denom}"`
  (`automation/items.py:88`).
- B.5 Backstab verb `backstab {t}` → `bs {t}` (`combat/backstab.py:78`).
- C No-change items confirmed (rest/search/flee/door/equip/banking/shop/party).
- Cleaned example TOMLs (`characters/{example,raist}.toml`) + README stealth block.
- Tests updated; full suite green (611 passed). Loader ignores unknown keys, so
  pre-existing TOMLs with the removed keys still load (forward-compat).
- `BackstabEngine`'s `stealth` param is retained (now unused) to keep the
  combat+stealth grouping and the `bot.py` wiring stable.

**Deferred (intentionally not done):**
- D (optional): `combat.pre_rest_cmd` / 2-slot `PartyHeal` — NOT added. Adding an
  unwired knob would reintroduce the dead-config we're removing; wire a consumer
  first (own task).
- E (verify-first): `inventory_cmd`, `party.wait_cmd`/`resume_cmd`/`status_cmd`,
  `session.logout_cmd`, `afk.reply`, `health.*_cmd` cures — left untouched pending
  the follow-up Ghidra pass the plan requires before changing them.
