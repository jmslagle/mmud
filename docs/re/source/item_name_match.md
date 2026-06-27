# `item_name_match` @ `0x442080`

The shared item-name comparator used by both the inventory parser
([`inventory_parse_response`](inventory_parse_response.md)) and the path required-item
gate (`pathfind_next_step @0x42b7b0`). Operates purely on **name strings**, never numeric
ITEMS.MD ids.

```c
int item_name_match(const char *a, const char *b) {
    char x[...], y[...];
    strcpy(x, a); strcpy(y, b);
    string_remove_all_char(x, '\'');     /* strip apostrophes from both */
    string_remove_all_char(y, '\'');

    if (strcmp(x, y) == 0) return 1;     /* exact (case-SENSITIVE — works because the */
                                         /* server + PATHS data are lowercase) */
    /* trailing-'s' plural tolerance: accept where one == the other + "s"
     * (so "black star keys" matches a "black star key" gate). */
    if (equals_plus_s(x, y) || equals_plus_s(y, x)) return 1;
    return 0;                            /* NOT a substring match */
}
```

`inventory_item_find_by_name @0x43d210` loops the carried/equipped array calling this,
**plus** boat interchangeability: `wooden skiff` / `log raft` / `silverbark canoe` satisfy
each other.

## Behaviour
Apostrophe-stripped exact compare with trailing-`'s'` plural tolerance; case-sensitive in
the binary but lowercase in practice; not substring. Boats are interchangeable for a
boat-gated path leg.

**Ported to:** `src/mmud/navigation/code_route.py` (`_names_match`, `_item_held`,
`_BOAT_EQUIV`). See [`../parsing.md`](../parsing.md).
