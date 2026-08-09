---
rule: determinism
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_banned_symbols.py
    armed: true
  - tier: TEST-ENFORCED
    checker: tests/rules/test_replay_determinism.py
    armed: false
    blocked_by: >-
      Requires a verified Makefile.NOGUI build producing VCD output without a
      display. Spec section 8.4 is still open.
---

# Determinism

Same firmware, same inputs, same output. A simulator that violates this
produces plausible results that cannot be reproduced, and the resulting bug
hunt is measured in weeks.

## 1. 2026-08-09 — SCRIPT-ENFORCED: no nondeterministic calls in new simulation code

`tools/check_banned_symbols.py` rejects `rand(`, `time(`, and `clock(` in files
added since `fork-point`. `srand(` is deliberately not matched — the regex uses
a negative lookbehind for word characters, and `test_srand_is_not_mistaken_for_rand`
pins that, since seeding is how determinism is *achieved*.

Scoped to new files only. Forcing upstream's existing usage to comply would
require an upstream delta, which section 3 of `.claude/rules/upstream-sync.md`
exists to discourage.

## 2. 2026-08-09 — TEST-ENFORCED, NOT YET ARMED: identical replay

Two headless runs of the same firmware must produce byte-identical VCD output.
`armed: false` until spec section 8.4 confirms `Makefile.NOGUI` emits VCD
without a display.

The unarmed state is declared in this file's frontmatter and checked by
`test_every_unarmed_mechanism_explains_why`. A rule claiming enforcement it
does not have is worse than no rule, because it implies coverage that is not
there.

## 3. 2026-08-09 — CONVENTION: simulation time is an integer

Accumulating simulated time in a float makes step size affect results and
sequence affect totals, so two runs that differ only in scheduling order
diverge. Not enforced: distinguishing a time accumulator from any other float
needs more than a grep.
