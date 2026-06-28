# `game_menu_prompt_parse` @ `0x0045f650`

Auto-answers MajorMUD/BBS pager pauses (the news/who-list "(C)ontinue?" pager) and the
`[MAJORMUD]` relog/cleanup case. Called FIRST in `server_message_dispatch` on the
un-terminated current line (param_3==0 = a prompt), before the logon script — so it fires on
EVERY pager prompt, however many appear (the count varies with the who-list/news length, which
is why a fixed sequential script can't cover them).

Matcher = `pattern_match_remove @0x485e60` (case-sensitive literal substring). `"\r"` @0x4b52d8.

```c
if (param_3 == 0 &&
    (pattern_match_remove(line, "or (C)ontinue?")            != -1 ||   // @0x4c0784
     pattern_match_remove(line, "Press any key to continue") != -1 ||   // @0x4c0768
     pattern_match_remove(line, "Hit any key to continue")   != -1)) {  // @0x4c0750
    if (connected/active) {
        net_buffer_receive(gs, "\r");        // bare Enter (= Continue) — NOT "N"/"Q"
        return 1;
    }
}
// (a parallel "[MAJORMUD]" branch handles relog: expand/send RelogCmd (gs+0x2A6F) or hang up,
//  per the relog/cleanup flags)
```

**Behaviour.** The pager is answered with a bare carriage return (the default action =
Continue), never "N" or "Q". Three hardcoded substrings cover it: `"or (C)ontinue?"`,
`"Press any key to continue"`, `"Hit any key to continue"`. Stateless and always-on, so any
number of pagers in any order are drained automatically.

**Ported to.** `src/mmud/automation/login.py` `_PAGER_RE` → reply `""` (Enter), checked on
every line regardless of the login script. See [`bbs_login_sequence_handle`](bbs_login_sequence_handle.md).
