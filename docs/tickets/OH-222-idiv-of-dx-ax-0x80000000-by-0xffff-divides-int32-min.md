---
id: OH-222
title: IDIV of DX:AX = 0x80000000 by 0xFFFF divides INT32_MIN by -1 on the host and
  kills the process instead of trapping
status: open
priority: P1
created: '2026-10-10'
touches:
- core/i8086/muldiv.*
- tests/i8086/test_idiv_overflow.py
---

Found by OH-220's review (2026-10-10), read and not executed: executing it would kill the process that ran it.

`core/i8086/muldiv.cc`'s IDIV computes `dividend / divisor` in `std::int32_t` before it checks the quotient's range. For the word form with DX:AX = 0x8000:0x0000 and a divisor of 0xFFFF, that is `INT32_MIN / -1`: undefined behaviour in C++, and on x64 the host's own `idiv` raises #DE (STATUS_INTEGER_OVERFLOW on Windows, SIGFPE on Linux). Nothing catches it, so it takes down whatever loaded the core -- pytest, or `webui/emulator_server.py`, where loading a program is arbitrary 8086 code by design (CLAUDE.md, "Running the emulator"). Any page that can reach the server can end it with four instructions.

The part itself raises a divide error there (type 0), because the quotient, +2^31, does not fit in 16 bits; the range check a few lines later already returns that trap for every other out-of-range quotient. The byte form cannot reach it: its dividend is a sign-extended 16-bit value, and -32768 / -1 fits in 32 bits. `core/riscv32/exec.cc` guards the same case for DIV (~123-131).

Debug and Release both crash; OH-220 did not cause it and does not change it.

`core/i8086/muldiv.*` is OH-11's (microcode-exact IMUL, DIV and IDIV), so this needs those files lent or OH-11 to take it.

STEPS:
1. Return the divide-error trap for INT32_MIN / -1 before dividing, in the same shape as the divisor == 0 case.
2. A test that executes IDIV r/m16 with DX:AX = 0x80000000 and a divisor of 0xFFFF and expects the divide-error trap with AX and DX unchanged, as the existing out-of-range cases do -- seen to fail first, which means seen to crash, so run the failing case in a subprocess and assert on its exit rather than letting it take the suite down.
3. Check the oracle's corpus (the F7.7 cases the conformance suite fetches) for whether it contains this dividend; if it does, say why the suite never crashed.

**Note 2026-10-10:** 2026-10-10: borrows core/i8086/muldiv.* from OH-11 and claims a new tests/i8086/test_idiv_overflow.py.
