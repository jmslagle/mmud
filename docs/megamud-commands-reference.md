# MegaMud Commands Reference

A binary-grounded catalog of every command MegaMud sends to the MajorMUD server,
and **which ones are user-configurable vs. hardcoded**. Built by decompiling
`megamud.exe` (fully analyzed in Ghidra). The goal: be the source of truth so we
don't re-derive command behavior from Ghidra each time, and so our bot's config
**matches MegaMud exactly** (no invented knobs, no missing real ones).

> Companion: [`megamud-responses-reference.md`](megamud-responses-reference.md) —
> how MegaMud parses incoming text (room/monster detection, prompt, MESSAGES.MD).

---

## 1. How MegaMud issues commands

- **Settings store:** per-character `BBS.INI` at path template `%s\BBS\%s\BBS.INI`
  (`0x004b6c1c`), read via `GetPrivateProfileString` / `GetPrivateProfileInt` in
  the config loaders `config_ini_load` (`0x00431d90`) and saved by
  `config_ini_save` (`0x00438e50`). Sections include `[MegaMud] [Default]
  [Alerts] [Combat] [Comms] [Display] [Auto-roam] [Party] [PvP]`.
  **This is distinct from `PLAYERS.MD`** (the who/spy DB of *other* players).
- **Transmit path:** commands are sent through `net_buffer_receive` /
  `net_command_queue` (the latter appends `\r`). User-typed strings go through
  `command_template_expand` first (token substitution).
- **Dispatch choke points** (each logs to the debug status line):
  - `scheduler_event_execute` (`0x00404cd0`) — `"Issuing command \"%s\" from timed event"` (`0x004b5678`)
  - `combat_rest_decide` (`0x0040b380`) / `mana_meditate_decide` (`0x0040caa0`) — `"Issuing pre-rest command \"%s\""` (`0x004b64c0`)
  - `path_follow_step_decide` (`0x00405b60`) — `"Issuing path command: %s"` (`0x004b5880`)

### The crucial distinction: automation vs. toolbar

MegaMud has **two** categories of outbound command, and they behave differently:

1. **Automation commands** — what the bot sends while acting on its own (combat,
   rest, movement, loot). These are mostly **hardcoded literals**; only a small,
   specific set is read from INI.
2. **Toolbar / hotkey commands** — the `Cmd*` INI keys (`CmdRest`, `CmdSneak`,
   `CmdHide`, `CmdSearch`, `CmdInv`, `CmdWho`, `CmdStat`, `CmdExp`). These are
   **UI buttons only**: they are referenced *exclusively* by `config_ini_load`/
   `config_ini_save` and the UI button handler — **never by the automation
   logic**. (Verified: the auto-search path sends a literal, while the UI Search
   button #`0x6c8` sends `net_command_queue("search\r")`.)

⚠️ **Earlier analysis conflated these.** `CmdRest`/`CmdSneak`/`CmdHide`/`CmdSearch`
existing in the INI does **not** mean the bot's automation rest/sneak/hide/search
verbs are configurable — those are hardcoded. See §3.

---

## 2. Configurable command strings (the real automation knobs)

These INI values are read and transmitted by the **automation** logic. The
attack prefix uses format `"%s %s\r"` (`0x004b5c04`) = `{prefix} {target}`, where
the prefix buffer is at game-state offset `0x519d` (loaded from `AttackCmd`).

| MegaMud action | INI key (addr) | Format | Our bot field | Parity |
|---|---|---|---|---|
| Melee attack prefix | `AttackCmd` (`0x004bcb1c`) | `{prefix} {target}` | `combat.attack_cmd` (`"kill"`) | ✅ keep |
| Attack spell | `AttackSpl` (`0x004bcaa8`) | cast string | `spells.attack` | ✅ keep |
| Pre-attack spell | `PreAttack` (`0x004bcab4`) | cast string | `spells.pre_attack` | ✅ keep |
| Multi/AoE attack spell | `MultAttack` (`0x004bcac0`) | cast string | `spells.multi_attack` | ✅ keep |
| Bless spells (10 slots) | `BlessCmd1..10` (`0x004bcb94..0x004bcb28`) | cast string | `spells.bless[]` | ✅ keep |
| Party bless (4 slots) | `PartyBless1..4` (`0x004bc7c4..0x004bc7a0`) | cast string | `party.bless[]` | ✅ keep |
| Party heal (2 slots) | `PartyHeal1..2` (`0x004bc7dc..0x004bc7d0`) | cast string | `party.heal_spell` (1 slot) | ⚠️ MegaMud has 2 |
| **Pre-rest command** | `PreRestCmd` (`~0x004bcc24`) | template, sent **before** resting | — (we lack it) | ➕ gap: add |

Also configurable but not command-*strings* (thresholds/toggles, mapped already):
`HpRest__`/`HpHeal__`/`HpFull__`, `ManaRest__`/`ManaHeal__`/`ManaFull__`,
`MaxCastCnt`/`PreCastCnt`/`MultCastCnt`, `Want{Gold,Silver,Copper,Plat,Runic}`,
`Max/Min Wealth`, `CanBackStab`/`DontBsIfMulti`/`RunIfBsFails`, `BashMax`/`PickMax`/
`SearchMax`/`DisarmMax`, `AutoCombat`/`AutoNuke`/`AutoHeal`/`AutoSearch`/`AutoSneak`/
`AutoHide`/`AutoGet`/`AutoCash` (action enable toggles), AFK settings, timing
(`FleeTimeout`/`HideDelay`/`TrackDelay`/`PvpSafePeriod`). The `Def*` family
(`DefCombat1/2`, `DefNuke1/2`, …) are **alternate command strings used in
"defense mode"** — loaded identically to their normal counterparts.

---

## 3. Hardcoded automation commands (NOT configurable)

These verbs are emitted as literal strings with **no INI lookup**. Per
"match MegaMud exactly", our bot should hardcode them too.

| Command | Literal (addr) | Emitting function (addr) | Our bot today | Parity action |
|---|---|---|---|---|
| rest | `"rest\r"` (`0x004b6440`) | `combat_rest_decide` (`0x0040b380`) | hardcoded `"rest"` | ✅ correct — keep hardcoded |
| meditate | `"meditate\r"` (`0x004b67e0`) | `mana_meditate_decide` (`0x0040caa0`) | n/a | — |
| search | `"search %s\r"` (`0x004b5ae4`, dir) | `path_exit_attempt` (`0x00406a1a`) | hardcoded `"search"` | ✅ correct — keep hardcoded |
| **sneak** | `"sneak\r"` (`0x004b5b28`) | `combat_backstab_prepare` (`0x0040767c`) | **`stealth.sneak_cmd` (configurable)** | ❌ remove knob, hardcode |
| **hide** | `"hide\r"` (`0x004b5bcc`) | `combat_hide_attempt` (`0x004077c6`) | **`stealth.hide_cmd` (configurable)** | ❌ remove knob, hardcode |
| **backstab** | `"bs %s\r"` (`0x004b5d2c`) | `combat_flee_or_hide_decide` (`0x00408f36`) | `"backstab {target}"` | ⚠️ verb is `bs`, not `backstab` |
| bash (door) | `"bash %s\r"` (`0x004b5a58`) | door handler | hardcoded `"bash"` | ✅ match |
| open (door) | `"open %s\r"` (`0x004b5a3c`) | door handler | hardcoded `"open"` | ✅ match |
| get (item) | `"get %s\r"` | auto-get / timed | hardcoded `"get"` | ✅ match |
| get (coins) | hardcoded get-currency format | loot path | **`items.cash_cmd` template** | ❌ remove template, fix format |
| equip | `"equip %s\r"` (`0x004b5b80`) | equip path (toggle `EquipAll`) | hardcoded `"equip"` | ✅ match |
| train | `"train\r"` (`0x004b5860`) | `combat_train` | hardcoded `"train"` | ✅ match |
| withdraw | `"withdraw %u\r"` (`0x004b5468`) | `cash_withdraw` | hardcoded | ✅ match |
| deposit | `"deposit %u\r"` (`0x004b544c`) | bank path (toggle `DepositAll`) | hardcoded | ✅ match |
| buy | `"buy %s\r"` (`0x004b548c`) | `shop_buy_item` | hardcoded | ✅ match |
| sell | `"sell %s\r"` (`0x004b54a4`) | `shop_sell_item` | hardcoded | ✅ match |
| join | `"join %s\r"` (`0x004c0dcc`) | `party_join` | hardcoded | ✅ match |
| invite | `"invite %s\r"` (`0x004b5420`) | `party_invite` | hardcoded | ✅ match |
| share | `"share %d <coin> with party\r"` (`0x004b5548`) | party share (toggle `ShareCash`) | hardcoded | ✅ match |
| flee | `"flee"` (no config xref) | combat/escape | hardcoded | ✅ match |

---

## 4. UI toolbar command keys (configurable, but UI-only — not automation)

These `Cmd*` keys are sent when the user clicks a toolbar button / hotkey. They
are **not** consumed by the bot's automation, so they are *not* a justification
for an automation config knob.

| INI key (addr) | Toolbar button | Default |
|---|---|---|
| `CmdRest` (`0x004bc1d4`) | Rest | `rest` |
| `CmdSneak` (`0x004bc1c8`) | Sneak | `sneak` |
| `CmdHide` (`0x004bc1c0`) | Hide | `hide` |
| `CmdSearch` (`0x004bc1b4`) | Search | `search` |
| `CmdInv` (`0x004bc1f4`) | Inventory | `inv` |
| `CmdWho` (`0x004bc1dc`) | Who | `who` |
| `CmdStat` (`0x004bc1e4`) | Stats | `stat` |
| `CmdExp` (`0x004bc1ec`) | Experience | `exp` |

> Our bot is headless-automation-first. If we ever expose toolbar/quick-tool
> buttons (web panel already has some), *those* may mirror `Cmd*`. The automation
> code must not.

---

## 5. Our config vs. MegaMud — gap summary

See `2026-06-16-megamud-command-response-reference.md` "Phase 3 results" for the
concrete edit list. Headlines:

- **Over-config to remove** (MegaMud hardcodes in automation): `stealth.sneak_cmd`,
  `stealth.hide_cmd`, `items.cash_cmd` (template → fixed format), `stealth.auto_hide`
  (dead/unused).
- **Correct as-is** (we already hardcode what MegaMud hardcodes): `rest`, `search`,
  `flee`, `bash`, `open`, `get`, `equip`, `train`, banking/shop/party verbs.
- **Verb mismatch:** our backstab sends `backstab {target}`; MegaMud sends `bs {target}`.
- **Real knob we lack:** `PreRestCmd` (pre-rest command).
- **To verify in a follow-up pass** (whether MegaMud exposes a key or hardcodes —
  not yet decompiled): `items.inventory_cmd`, `party.wait_cmd`/`resume_cmd`/
  `status_cmd`, `session.logout_cmd`, `afk.reply`, `health.*_cmd` cures.

## 6. Confidence

§2/§3 attack/rest/search/sneak/hide/backstab rows are **high confidence** —
decompiled with quoted transmit lines. The hardcoded banking/shop/party verbs and
the full BBS.INI key inventory come from loader decompilation (high confidence on
existence; some struct offsets inferred). The §5 "to verify" items have not been
decompiled on the automation path and must not be changed until confirmed.
