---
id: OH-222
title: IDIV of DX:AX = 0x80000000 by 0xFFFF divides INT32_MIN by -1 on the host and
  kills the process instead of trapping
status: in-review
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

**Note 2026-10-10:** FIXED at af8594b, steps 1-3 done.

FIX. core/i8086/muldiv.cc's IDIV returns the divide-error trap for dividend == INT32_MIN && divisor == -1 before it divides, in the shape of the divisor == 0 case, with a comment saying why (C++ UB; the host's idiv faults, SIGFPE on Linux, STATUS_INTEGER_OVERFLOW on Windows; the part raises type 0 because +2^31 does not fit in 16 bits). The early return also covers INT32_MIN % -1, which is UB for the same reason. The byte form cannot reach it: its dividend is a sign-extended 16-bit value and -32768 / -1 fits.

OTHER UB IN muldiv.*: none found. MUL and DIV are unsigned (the widest product, 0xFFFF * 0xFFFF, fits uint32); IMUL's widest signed product is (-32768)^2 = 2^30, which fits int32; DIV and IDIV return on a zero divisor before dividing. AAM is in bcd.cc, outside this ticket's claim; read only: it divides two unsigned bytes behind its own immediate == 0 trap, so nothing there either.

TEST. tests/i8086/test_idiv_overflow.py, one test. It runs IDIV BX (F7 FB) with DX:AX = 8000:0000 and BX = FFFF in a child `python -X faulthandler -c`, and asserts the child exits 0 having taken vector 0 (CS:IP = B000:1234) with AX = 0000 and DX = 8000 untouched, SP = 01FA, and 0000:0102 pushed. SEEN TO FAIL FIRST, at 00f1329 with the DLL rebuilt: the child exited 1, with stderr "Windows fatal exception: integer overflow" and "OSError: exception: integer overflow" raised from Cpu.step() (core/i8086/abi.py:353). The exit was not 0xC0000095: ctypes wraps every foreign call in a structured-exception handler on Windows and raises STATUS_INTEGER_OVERFLOW as OSError. So on Windows the symptom is an exception out of step() with the C++ frames abandoned mid-instruction, not a dead process; the ticket's "kills the process" holds on Linux (SIGFPE), which was not run here (this machine's WSL has no toolchain). Whether webui/emulator_server.py survives that OSError on Windows was not checked.

CORPUS. The conformance suite reads third_party/sst8088/v2/F7.7.json.gz (git-ignored), which tools/get_8088_tests.sh fetches from raw.githubusercontent.com/SingleStepTests/8088/main/v2/F7.7.json.gz. A local copy exists, md5 1544c21846b75a66356072ec4a508085, the same in the main checkout. Its 10,000 cases contain no DX:AX = 0x80000000: no case has DX = 8000 at all, and the most negative dividend is 8012:7826 (idx 4717). None has a divisor of FFFF either; divisors were computed from each case's modrm, prefixes and initial RAM, and that extraction reproduces all 2,411 non-trapping results (2,243 exactly, 168 with OH-11's sign-negated quotient). So the suite never met this case. It would not have executed it anyway: F7.7 is in PARTIAL, which test_the_fetched_corpus_passes_completely skips, and the floor test drops every case whose SP moved, i.e. every trapping one, before running it.

VERIFIED. python tools/build_core.py rebuilt build/lib/i8086.dll. python -m pytest -q -p no:cacheprovider tests/i8086 -> 234 passed in 165.93s. Each checkall row but the suite exits 0: check_layering, check_board_contract, check_part_schemas, check_licenses (300 files), check_deltas, check_banned_symbols (69 C/C++ files), check_board_claims, check_ticket_claims, ticket_guard --self-test (6/6), check_facts, docs/research/board-sources/render.py --check. The full suite was not run here.

core/i8086/muldiv.* goes back to OH-11 when this closes.

**Note 2026-10-10:** REVIEW: an independent review, APPROVE. It reproduced the pre-fix failure (the guard deleted, rebuilt: the child exits 1 with 'Windows fatal exception: integer overflow'), restored and rebuilt (tests/i8086 234 passed), and re-derived the corpus claims from each case's prefixes, modrm, registers and RAM: no F7.7 case has DX = 8000 or a divisor of FFFF. THE TITLE OVERSTATES THE WINDOWS SYMPTOM, corrected here rather than renamed: on Windows the process survives. The review ran an in-process emulator_server against the unguarded DLL with BA0080 B80000 BBFFFF F7FB F4: the server lived, /api/run got no reply (RemoteDisconnected, a traceback on stderr, since Session.step catches only abi.Unimplemented and Handler._api no OSError), and the IDIV was silently skipped -- IP already advanced past it, no trap, status still running, the next step ran the HLT. So on Windows the defect was a dropped request and a silently corrupted machine; 'kills the process' stays true only where the host's fault is a signal (x86-64 Linux, SIGFPE), which neither the author nor the review could run. And the server's Origin check refuses cross-origin pages, so 'any page that can reach the server' was too broad. With the fix the same probe takes vector 0. LOWS FIXED in the test: it says it sees the regression only where the host's divide faults (AArch64's sdiv does not); a child that exits 0 without printing JSON fails with its stdout and stderr, not a bare JSONDecodeError; and why the pushed FLAGS word is not asserted (OH-11's microcode intermediates). LEFT, filed elsewhere: a host fault surfaced by ctypes half-executes an instruction and drops the request, for any future fault (its own ticket); IDIV accepting a quotient of -128 where the 8088 traps, the conformance floor test dropping every case the part trapped on, and the negated quotient being exactly the REP-prefixed cases (OH-11, whose files these are).
