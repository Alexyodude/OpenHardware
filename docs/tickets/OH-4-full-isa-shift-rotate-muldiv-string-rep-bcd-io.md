---
id: OH-4
title: 'Full ISA: shift/rotate, muldiv, string, rep, bcd, io'
status: open
priority: P1
owner: session/isa
created: '2026-08-23'
touches:
- core/i8086/shift.*
- core/i8086/muldiv.*
- core/i8086/bcd.*
- core/i8086/decode.*
- core/i8086/exec_core.*
- core/i8086/cpu.*
- core/i8086/abi.*
- core/i8086/CMakeLists.txt
- tests/i8086/test_isa_full.py
- tests/i8086/conformance.py
- tests/i8086/test_abi.py
---

Slice 2d. Includes flag.undefined, whose documented-undefined results are only knowable from hardware -- which is what the oracle is.

## `touches` was rewritten on 2026-08-23, and why

It named `core/i8086/exec_full.*`, a file that does not exist and now will not.
That was a guess made before OH-3 landed, and splitting the executor along a
*ticket* boundary rather than a responsibility boundary is the wrong seam: the
new opcodes dispatch from the same `Step()` as every existing one, so a second
executor file would exist only to hold what this ticket happened to add.

The seam that is real is the one `alu.*` already uses -- a pure function of
values and flags, with no `Cpu` and no memory, testable exhaustively. So
`shift.*`, `muldiv.*` and `bcd.*` follow that shape, and the dispatch stays in
`exec_core.cc` beside the ALU group's.

## What the corpus is actually called

The handoff said to fetch `D0 D1 D2 D3 F6 F7`. Those files do not exist.
SST8088 splits group opcodes by their modrm `reg` extension, so the shift group
is 32 files, `D0.0` through `D3.7`, and the `F6`/`F7` group is 16 more:

    bash tools/get_8088_tests.sh --opcodes D0.0 D0.1 ... D3.7

The `/6` member is **SETMO** (`SETMOC` for the CL forms), an undocumented
instruction the Intel manual does not list. The corpus names it, which is the
whole argument for having a hardware oracle.
