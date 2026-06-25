# Data formats — the `.MD` files

The `.MD` data files are MDB2 keyed-record B-tree databases (container format in
[`../cdb-mdb2-format.md`](../cdb-mdb2-format.md)). A record on disk is the **payload**
of a B-tree entry; the in-memory struct order differs from the on-disk order.

- **On-disk** layouts (below) are the validated truth from the `*_md_save` functions
  + real files, and are what `src/mmud/data/binary.py` parses. Use these for parsing.
- **In-memory** layouts (further down) are for Ghidra navigation only.

Magics: `MONSTERS=MDB2U`, `ITEMS=MDB2S`, `SPELLS=MDB2T`, `CLASSES/RACES=MDB2\x02`,
`PATHS=MDB24`. `ROOMS.MD`, `MESSAGES.MD`, `MACROS.MD` are **text**, not MDB2.

> Method caveat: the `*_md_save` stack-locals have padding gaps, so scalar on-disk
> offsets were pinned empirically against real records. String fields + flags are
> reliable (explicit `str_copy_safe`/writes); some numeric semantics are best-effort.

## On-disk record layouts (use these to parse)

### MONSTERS.MD — 210 B/record, `MDB2U` (`monsters_md_save @0x453e50`)
| Off | Type | Field |
|-----|------|-------|
| 0x00 | u16 | record id |
| 0x02 | char[31] | name |
| 0x21 | u32 | flags (`0x40000000` = active) |
| 0x25 | u8 | **combat_rating** (kill-type tier — see [combat.md](combat.md)) |
| 0x35 | i16 | level |
| 0x39 | i16 | exp |
| 0x3d | i16 | alignment (NOT used for targeting) |
| 0x3f | i16 | hp |

Real count 788. Sanity: giant rat = lvl 1, exp 12, hp 20.

### ITEMS.MD — 200 B/record, `MDB2S` (`items_md_save @0x441210`)
| Off | Type | Field |
|-----|------|-------|
| 0x00 | u16 | record id |
| 0x02 | char[30] | name |
| 0x20 | char[41] | source (the **shop that sells it**, e.g. "Furniture Shop" — NOT a description) |
| 0x49 | char[14] | suffix |
| 0x57 | i16 | ac_or_dmg |
| 0x59 | i16 | weight |
| 0x5b | u8 | item_type |
| 0x5d | i16 | value |
| 0x5f | u32 | extra |
| 0x63 | u32 | flags (reads 0 on disk — no usable active flag) |
| 0xa3 | u8 | equip_slot |

1336 live records; the B-tree holds only live records, so **load all** (no active filter).

### SPELLS.MD — 158 B/record, `MDB2T` (`spells_md_save @0x47cfc0`)
| Off | Type | Field |
|-----|------|-------|
| 0x00 | u16 | record id |
| 0x02 | char[30] | full_name |
| 0x20 | char[7] | short_name (mnemonic, e.g. `mmis`) |
| 0x27 | u32 | flags (`0x40000000` active, `0x1000` known) |
| 0x2b | char[41] | desc (empty in file) |
| 0x54 | u8 | level_req |
| 0x56 | u16 | duration |
| 0x63 | u8 | kai_cost |

936 unique. Sanity: `mmis` = lvl 1, kai 4.

### CLASSES.MD (81 B, `classes_md_save @0x4153e0`) & RACES.MD (87 B, `races_md_save @0x46ff20`)
`id i16@0x00`, `name[30]@0x02`, plus stat-mod bytes. 15 classes, 13 races.
(class 10 = Gypsy, race 7 = Dark-Elf.) Loaders: `load_classes`/`load_races` + `ClassRaceDB`.

### PLAYERS.MD — 248 B/record (`players_md_save_one_record @0x46c719`; **keyed by name**, no record id)
| Off | Type | Field |
|-----|------|-------|
| 0x00 | char[11] | name |
| 0x0b | char[19] | title |
| 0x1e | char[31] | guild |
| 0x3d | char[21] | location |
| 0x52 | u32 | flags (`0x4000` friend, `0x8000` enemy, `0x80000000` deleted) |
| 0x56 | i16 | level |
| 0x58 | i16 | exp_rank |
| 0x5a | i16 | alignment |
| 0x5c | i16 | class_id |
| 0x5e | i16 | race_id |
| 0x76 | i16 | reputation |
| 0x78 | u32 | combat_rating |
| 0x7c | i32 | last_seen |
| 0x80 | i32 | first_seen |

`PLAYERS.MD` is the **who/spy DB of other players** (not the bot's own settings —
those live in per-character `BBS.INI`). Absent from the extraction → Ghidra-confirmed
only. Parsed by `parse_player_record`.

### PATHS.MD — variable-length directory (`paths_md_save @0x465860`)
Indexes the `.MP` step files. `from_desc[61]@0x00`, `npc[41]@0x3d`,
`mp_file(key)[14]@0x66`, `to_region_name[31]@0x74`, `to_code[14]@0x93`,
`flags u32@0xaf` (`0x10000000` active). 69 entries (`load_paths_index`). The `.MP`
step files are parsed by `mmud.data.paths`.

## In-memory layouts (Ghidra navigation only — NOT for parsing files)

### RACE (0x60 B, `races_md_load`)
`i16 race_id@0x00 · u8 source_tier@0x02 (0=global,1=alt,2=custom,3=network) ·
char[31] name@0x08 · i16 hp_bonus@0x34 · u8[6] min_stat_mods@0x36 (STR,INT,WIS,DEX,CON,CHR) ·
u8[6] max_stat_mods@0x3c`. Array @gs+0x21c8, count +0x21c0, cap +0x21c4.

### CLASS (0x5c B, `classes_md_load`)
`i16 class_id@0x00 · u8 source_tier@0x02 · char[31] name@0x08 ·
i16 magic_type_flags@0x28 · u8 magic_school_mask@0x2e`. Array @gs+0x21f8, count +0x21f0, cap +0x21f4.

### MACRO (0x80 B, `macro_record_alloc`)
`u8 source_tier@0x00 · i32 key_code@0x04 · i32 shift@0x08 · i32 ctrl@0x0c · i32 alt@0x10 ·
char[101] command@0x18`. Array @gs+0x1d9c, count +0x1d94, cap +0x1d98, dirty +0x56d0.

## GameState DB array offsets (Ghidra navigation)
| DB | count | capacity | ptr | dirty |
|----|-------|----------|-----|-------|
| Players | +0x1e28 | +0x1e2c | +0x1e30 | +0x56b0 |
| Monsters | +0x1e44 | +0x1e48 | +0x1e4c | +0x56b4 |
| Items | +0x1e74 | +0x1e78 | +0x1e7c | +0x56b8 |
| Spells | +0x1ea4 | +0x1ea8 | +0x1eac | +0x56bc |
| Rooms | +0x2c40 | +0x2c44 | +0x2c48 | +0x56c4 |

## Combat-accuracy stats block (gs+0x9500)
`hit% = player_hit / (player_miss + player_hit + special) * 100`. Field offsets:

```
player_miss      0x9500   player_hit       0x9504
player_dmg_min   0x9508   player_dmg_max   0x950c   player_dmg_sum   0x9510
special_count    0x9514   special_min..sum 0x9518/0x951c/0x9520
crit_count       0x9524   crit_min..sum    0x9528/0x952c/0x9530
monster_miss     0x9534   monster_hit      0x9538   monster_dmg_*    0x953c..0x9544
spell1_*         0x9548..0x9558   spell2_*  0x955c..0x956c
total_hits       0x957c   last_damage      0x9580   cumulative_dmg   0x9584
all_time_min/max 0x9588/0x958c   dmg_sum   0x9590
backstab_attempts 0x9594  backstab_successes 0x9598
```

## Condition table (gs+0x1f1c ptr array, count +0x1f14, ~0x120 B/entry)
```
+0x00  u8        condition char           +0x01  char[31] display name
+0x20  char      onset match glob         +0x71  char     auto-response template
+0xc2  char      trigger template
+0x114 u16 flags 0x0001 poisoned 0x0002 diseased 0x0004 ill 0x0008 held
                 0x0010 stunned 0x0020 dazed 0x0040 blind 0x0080 slept
                 0x0400 use pattern_match_remove   0x8000 disabled
+0x115 u8        0x02 confused, 0x10 interrupt task, 0x20 interrupt if in combat
+0x118 i32       category (2 counter, 3/4 gs flags, 5 speed, 6 hangup)
+0x11c i32       onset timestamp (gs+0x9410)
```
Per-condition gs flags: poisoned +0x565c, diseased +0x5660, ill +0x5664, blind +0x566c,
held +0x5670, slept +0x5674, confused +0x5678, stunned +0x567c, dazed +0x5680.

## File header (binary `.MD`)
6-byte header: bytes 0–4 magic (`MDB2U`…), byte 5 version/type. Records follow.
Skip any record with `flags & 0x80000000` (deleted). (The MDB2 B-tree walk in
`binary.py` handles this; raw offset-stepping is only a fallback.)
