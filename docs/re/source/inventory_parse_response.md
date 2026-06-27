# `inventory_parse_response` @ `0x43d650`

Parses the server's `i`/`inv` response into the carried/worn item array. Called per
received line; recurses into itself for the keys sub-list (`is_key_sublist=1`).

**Game-state offsets**

| offset | meaning |
|---|---|
| `gs+0x3178` | item count |
| `gs+0x317c` | item array; slot = `{ [0]=quantity, [1]=flags, [2]=ptr to record }`, name at `record+3` |
| `gs+0x53fc` | pending-partial buffer (word-wrap rejoin) |
| `gs+0x3180` | wealth (copper-equiv) |
| `gs+0x31a8/+0x31ac/+0x31b0` | encumbrance cur / max / level (1=Light..3=Heavy) |

**Line prefixes** (strings `@0x4bd8xx`): `"You are carrying "` (+0x11), `"You have "`
(+9, wrapped form; rejected if `"lives"`), `"You have the following keys: "` (keys mode,
recurse), `"You have no keys."`/`"Nothing."`/`"No money."` (terminators), `"Wealth: "`,
`"Encumberance: "` (**sic** — binary misspells it; finalises the pass).

```c
void inventory_parse_response(GameState *gs, char *line, int is_key_sublist) {
    char *body = match_prefix(line);   /* "You are carrying " etc., else continuation */

    for (char *pos = body; ; ) {
        /* Tokenise on ',' and '.' ONLY — never " and ". So multi-word names containing
         * "and" ("rope and grapple") stay intact. */
        char *sep = string_find_substr_from(pos, ",");      /* DAT_004b82a0 = "," */
        if (!sep) sep = string_find_substr_from(pos, ".");  /* DAT_004b6b84 = "." */

        if (!sep && !is_key_sublist) {
            /* Trailing partial with no separator before EOL: stash and return; next line
             * prepends "<pending> " to its first token (string_insert_at, " ") then
             * clears gs+0x53fc -> word-wrapped names rejoin. */
            strcpy(gs->pending /*0x53fc*/, pos);
            return;
        }

        char token[0x32];
        strncpy(token, pos, 0x31);
        string_trim_whitespace(token);

        /* "(Slot)" suffix -> worn. pattern_match_remove(token, " (") locates it; slot
         * name matched against the equip-slot table (+ "Offhand"->0xc, "Weapon"->-2);
         * token truncated at " (" and re-trimmed -> bare name. Leading digit = qty. */
        int slot = parse_and_strip_slot(token);
        int qty  = leading_digit(token) ? string_parse_int(token) : 1;

        /* Resolve by NAME (never a numeric id): walk gs+0x317c calling
         * item_name_match(record+3, token); else currency_type_resolve for money; else
         * item_record_alloc adds a NEW known item. equip_location!=-1 marks worn. */
        store_item(gs, token, qty, slot);

        pos = sep + 1;
        if (!*pos) break;
    }
}
```

## Behaviour
One comma/period-delimited list, wrapped across lines (rejoined via the pending buffer —
**not** leading whitespace), worn gear inlined with `(Slot)` suffixes, keys parsed as more
carried items. Items stored and compared by **name string**, never a numeric ITEMS.MD id.

**Ported to:** `src/mmud/parser/inventory_parser.py`. See [`../parsing.md`](../parsing.md)
and [`item_name_match.md`](item_name_match.md).
