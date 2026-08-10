# Upstream deltas

Every file that existed at tag `fork-point` and has since been modified must
appear here as a `## ` heading naming its repo-relative path in backticks,
followed by the reason.

Enforced by `tools/check_deltas.py`, per `.claude/rules/upstream-sync.md`.

**Current count: one.**

## `src/lib/board.h`

Reason: added `ARCH_X86` to the architecture enum at line 40, for the x86-16
core in slice 2 (`i8086.int.arch-enum` in `docs/features/i8086.md`).

`MGetArchitecture()` is a pure virtual returning one of these values, so a new
architecture cannot be added without extending the enum. There is no registry
and no extension point — this is the one edit slice 2 cannot avoid, and the
strategy document records it as such.

Inserted before `ARCH_UNKNOWN`, which renumbers that member. Checked before
making the change: `ARCH_*` values appear only as symbolic return values from
`MGetArchitecture()` implementations across `src/sim_backend/` and
`src/boards/board_Breadboard.cc`, and are never serialised. A `.pzw` workspace
is a zip storing board and processor **by name** — `parts_Arduino_Uno.pcf`,
`mdump_Arduino_Uno_atmega328p.hex` — so no saved workspace carries an
architecture integer that renumbering could invalidate.

The enum was also reflowed one-member-per-line. That is cosmetic and enlarges
the diff against upstream by nine lines; it was done so future additions are
one-line diffs rather than edits to a 100-column single line.

**This delta should not be permanent.** One enum member is an obvious upstream
contribution. Offering it to `lcgamboa/picsimlab` would retire this entry and
return the fork to zero deltas.
