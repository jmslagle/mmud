# Combat — targeting, cast-vs-melee, rest

## What to attack: kill-type tier, NOT alignment

The bot was attacking town guards/shopkeepers because it attacked every "Also here:"
creature with no hostility filter. MegaMud does NOT compare alignment numbers at
runtime — it gates on a **kill-type tier** byte.

- Each `MONSTERS.MD` record has a tier byte at **disk 0x25** (in-memory `+0x28`; our
  `Monster.combat_rating`).
- `combat_flee_or_hide_decide @0x408f36` gates verbatim: `if (entity.tier != 4) return 0;`
- `room_entity_classify_all @0x459880` promotes: `if (AttackNeutral && type==monster && tier==3) tier=4;`

Tier values (histogram `{2:153, 3:60, 4:437, 5:4}`):

| Tier | Meaning | Attack? |
|------|---------|---------|
| 2 | good/protected NPC (shopkeeper, healer, sheriff, woodelf guard) | never |
| 3 | neutral (giant rat, filthbug, guardsman) | only if **AttackNeutral** on |
| 4 | hostile/enemy (kobold thief, orc, ogre) | always |
| 5 | special | never (auto) |

The only toggle is **AttackNeutral** (string `0x4bc9f0` → `gs+0x37ac`). There are NO
AttackGood/AttackEvil flags. The `alignment` field (disk 0x3d) is separate and unused
for targeting — don't gate on it.

**Our port:** `combat.is_attackable(kill_type, attack_neutral)` (4 or 0 → attack;
3 → toggle; 2/5 → never). `MonsterSighting.kill_type` carries `rec.combat_rating`.
`CombatConfig.attack_neutral` defaults False. Unknown/learned (kill_type 0, not in
`MONSTERS.MD`) = attackable, so the bot still works pre-DB; protection is DB-driven.

**All attack paths share one picker** — `combat.select_attack_target` +
`attackable_sightings` — used by melee `CombatEngine`, nuke `SpellEngine` (needs the
`attack_neutral=` ctor arg), `BackstabEngine`, and kill attribution. Only *initiation*
is filtered; once `in_combat` we fight back against anything. (The first fix only
touched `CombatEngine`, so spell/backstab kept attacking guards until unified.)

### Adjective name matching (the real guard culprit)
"happy guardsman" ≠ DB "guardsman" → kill_type 0 → attacked. `MonsterDB.find` now does
a word-boundary suffix match, mirroring `monster_db_lookup_by_name @0x4544d0` /
`pattern_match_remove @0x485e60` (DB base name matches at offset 0 or after a space; no
adjective table, no article stripping). We use suffix + longest-match (safer than
MegaMud's left-only test). MegaMud tie-break: records with flag bit `0x08` win, else
array order.

### Learned-record shadowing (survived the first two fixes)
The store (`gamedb.json`) held a learned monster `{id:-1, name:'happy guardsman',
combat_rating:0}` from when lookups were exact-only. `find` matched it (kill_type 0 →
attackable) before the adjective fallback could reach the real 'guardsman' (kt 2). Fix:
a real (record_id ≥ 0) record always wins; learned placeholders never shadow a real
base. `store.prune_learned_resolvable` (run in `import_md`) drops learned monsters that
resolve to a real one. **A long-running bot that only relogs keeps the old code +
poisoned store — restart the process to pick up fixes.**

## Cast vs melee, per round

`combat_flee_or_hide_decide @0x408f36`, `combat_spell_cast @0x407b7d`,
`combat_weapon_equip_decide @0x408fd0`:

- **ManaAttack% is a FLOOR** (`state+0x3794`): cast only if `curMana(0x5390) >=
  ManaAttack% * maxMana(0x5398) / 100`; **below it → MELEE** (logs "Mana/Kai too low").
  It is NOT a wait — per-round, so it resumes casting if mana recovers.
- **Cast caps, reset per encounter:** `MaxCastCnt` (`0x4d74`; per-spell override at
  spell+0x44) caps the number of attack casts; `AttMaxDmg` (`0x4d78`) caps accumulated
  damage (`0x9584`). castCount `0x4d70`. Hitting either → melee the rest of the fight.
  Counters reset on room entry / new combat.
- **Per-spell min mana** (`SPELLS.MD +0x60`) and a 4-second cast cooldown also gate a
  cast inside `combat_spell_cast`; failing either → melee.
- Weapon swap (`combat_weapon_equip_decide`, flag `0x531c`) equips the cast/melee
  weapon as needed. Melee issues `"{AttackCmd} {target}"` (AttackCmd `state+0x519d`).

**Our port:** `CombatEngine` has NO mana gate (it melees whenever it runs).
`SpellEngine(mana_attack_pct=, ...)` casts only at/above the floor and under
`max_cast_count`; below the floor it yields (combat melees); at the cap it swaps to the
melee weapon once and stays melee for the encounter. Tune `mana_attack_pct` (floor) and
`max_cast_count`.

## Rest / meditate to recover

`combat_rest_decide @0x40b380` + `mana_meditate_decide @0x40caa0` (when NOT in combat):

- HP < **HpRest%** (`state+0x375c`) → `rest`; HP < **HpFull%** (`0x3768`) → rest to full.
- Mana < **ManaRest%** (`0x3778`) → `rest`; Mana < **ManaFull%** (`0x3784`) → rest to full.
- If a meditate skill exists (`0x4e48`) and HP is OK, prefer **`meditate`** (`0x4e4c`
  gates rest-vs-meditate); `mana_meditate_decide` fires when Mana < **ManaMeditate%**
  (`0x3774`). Both `rest` and `meditate` are hardcoded literals.
- It **HOLDS** position and rests until HP & mana reach the Full% targets — not one-shot.

Offsets: curHP `0x5384`, maxHP `0x538c`, curMana `0x5390`, maxMana `0x5398`.

**Our port (`combat/combat.py`):** rest was HP-only and one-shot (rested a tick, then
the loop walked off → "not resting"). Now hold-to-recover: out of combat, if
HP < `rest_threshold` OR mana < `rest_mana_pct` (config; 0 = off), send `rest` and begin
a **RESTING task at PRIO_REST (50)** — which blocks travel (110) but lets flee(20)/
combat(40)/spells(30) preempt. Holds until HP & mana ≥ `_REST_FULL` (0.95); 180 s
timeout safety net. `activity_reason` reports "resting".

**Recovery is tracked in a `_recovering` flag, not the task** — and we **resume
resting after a buff cast** (like MegaMud, which rests *through* its bless casts).
A cast is higher priority than rest, so the engine **aborts** the RESTING task when
SpellEngine casts; if we keyed "still resting?" off the task we'd stop the moment mana
climbed back over the (lower) start threshold. Instead `_recovering` persists until HP
& mana hit `_REST_FULL`, re-begins the task if a cast aborted it, and re-issues `rest`
after the stand-up — so an idle bot that casts a bless mid-rest sits back down and
finishes recovering. `rest` itself is debounced once per `[HP=..]` prompt cycle. Web Settings exposes
`rest_threshold` / `rest_mana_pct` / `flee_threshold` / `mana_attack_pct`.

We use `rest` for mana too (universal). `meditate` (faster mana regen) is a follow-up
toggle — but a Warlock can't use it until the **Level 23 quest** unlocks the skill.

**`rest` is debounced to once per prompt cycle.** `_next_command` runs on every
received line, and `_resting` is only set when the "(Resting)" prompt arrives — so in
the window before that confirmation we re-issued `rest` on every line (echoes, etc.)
and **flooded the server** (30+ in 0.5 s → "Why don't you slow down?"). Fix: a
`_rest_pending` flag set when we send `rest`, cleared on the next `[HP=..]` prompt; we
won't re-send while resting OR pending. Issues exactly one `rest` per prompt cycle.
