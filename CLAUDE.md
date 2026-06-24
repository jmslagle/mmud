# mmud — working principles

This project is a faithful Python re-implementation of MegaMud (a MajorMUD client/bot).

## Go to the source (the binary) for ground truth

When behavior must match MegaMud — parsing, hashing, combat/targeting rules, data
formats, timing — **reverse-engineer `megamud.exe` in Ghidra to get the exact
algorithm; do NOT guess from observed behavior or plausible heuristics.** Ghidra is
connected via the `mcp__ghidra__*` MCP tools (program already open). The decompiled
`*_md_save`/`*_parse` functions are authoritative. Verify the RE'd algorithm against
real data (ROOMS.MD/MONSTERS.MD bytes, live session logs) before shipping.

This has repeatedly turned "confident but wrong" guesses into correct
implementations (e.g. monster kill-type targeting, the binary .MD layouts, and the
room-id hash = `((title_hash & 0xFFF) << 20) | exit_bits`). When unsure how MegaMud
does something, spawn a focused Ghidra subagent (keep the big decompiles out of the
main context) and have it return the exact algorithm + function addresses + verbatim
decisive lines.

Memory under `~/.claude/projects/.../memory/` records confirmed RE findings — check
it before re-deriving, and update it when you confirm something new.

## Workflow
- Branch → commit → merge (never commit straight to main). End commit messages with
  the Co-Authored-By trailer.
- TDD: write the failing test first, then the fix.
- Run the full suite before merging.
