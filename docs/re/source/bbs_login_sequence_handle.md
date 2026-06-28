# `bbs_login_sequence_handle` @ `0x00444e50`

The logon engine: scans the user's LogonPrompt/LogonReply script, then applies MegaMud's
HARDCODED handling of the standard MajorMUD prompts (ANSI, `[MAJORMUD]:` entry, `[HP=]`
in-game flip). Called from `server_message_dispatch` while connection state ∈ {1..0xA,0x12,0x13}.

State offsets: `LogonPrompt[0] = +0x23C9` (stride 0x29, default "--Unused--"),
`LogonReply[0] = +0x26FD` (stride 0x29), `MenuPrompt = +0x2A31` (default "[MAJORMUD]:"),
`RelogCmd = +0x2A6F`, `AnsiCmd = +0x2A84` (default "=a"), connection state = +0x546C.
Matcher = `pattern_match_remove @0x485e60` (case-SENSITIVE literal substring, returns offset
or -1). Prompt matching runs on the UN-terminated current line (param_3==0 = a prompt).

```c
// 1) scripted LogonPrompt scan
for (i = 0; i < 20; i++) {
    p = gs + 0x23C9 + i*0x29;
    if (nonempty(p) && pattern_match_remove(line, p) != -1) {
        ui_connection_status_update(gs, 10);                  // "Logging on..."
        command_template_expand(gs, gs + 0x26FD + i*0x29, reply);   // LogonReply[i] (^M etc.)
        net_buffer_receive(gs, reply);                        // TX
        return 1;
    }
}
// 2) hardcoded prompts (independent of the script)
if (pattern_match_remove(line, "*ANSI RECOMMENDED*") != -1) { send "x\r"; once; return 1; }
if (pattern_match_remove(line, "[MAJORMUD]:") != -1 ||
    pattern_match_remove(line, gs+0x2A31 /*MenuPrompt*/) != -1) {
    ui_connection_status_update(gs, 0x12);                    // "Entering game ..."
    net_buffer_receive(gs, "enter\r");                        // s_enter @0x4be16c
    return 1;
}
if (pattern_match_remove(line, "but the game is currently full") != -1) { retry/redial; }
if (pattern_match_remove(line, "[HP=") == 0 &&                // MUST be at offset 0
    pattern_match_remove(line, "]:") != -1) {                 // a "[HP=...]:" prompt
    if (state != 8 /*not still verifying pw*/) {
        session_connect_toggle(gs, 1);
        ui_connection_status_update(gs, 0xB);                 // ONLINE -> leave logon mode
        net_buffer_receive(gs, "\r");
        return -1;                                            // fall through to in-game parsing
    }
}
```

**Behaviour.** User-ID/password are SCRIPTED (LogonPrompt/LogonReply). Everything standard is
HARDCODED and always-on: `*ANSI RECOMMENDED*`→"x", `[MAJORMUD]:`→"enter", game-full→redial,
and a line starting `[HP=` containing `]:` flips to in-game (state 0xB) and starts the AI.
The pager `(C)ontinue?` is handled separately in [`game_menu_prompt_parse`](game_menu_prompt_parse.md).

**Ported to.** `src/mmud/automation/login.py` `LoginHandler.process_line`: `_HP_PROMPT_RE`→
`in_game`, `_MAJORMUD_MENU_RE`→`"enter"`, `_GAME_FULL_RE`→`game_full`, then the scripted
steps. All hardcoded handlers run regardless of the user script.
