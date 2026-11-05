---
id: OH-159
title: A hardware capture harness, so silicon is the oracle Xtensa and Armv7E-M lack
status: blocked
priority: P2
owner: oh-159-worktree
created: '2026-09-03'
touches:
- tools/capture_trace.py
- tests/fixtures/hardware/**
- docs/tickets/OH-159-*
- tests/rv32/test_capture_trace.py
---

Two blocked tickets want the same thing and neither can produce it alone: an
oracle that does not descend from the implementation being checked. For
Xtensa there is no software answer at all, and for Armv7E-M the only software
answer is single-sourced. Silicon is the answer to both, and no ticket owns
building the thing that captures it.

WHY THE SOFTWARE ROUTES DO NOT CLOSE:

* OH-38, Xtensa LX7, three ESP32-S3 boards. catalogue.py's ORACLES: "NONE.
  QEMU-xtensa and binutils-xtensa both derive from the same Tensilica archive
  via import_core.sh, so their agreement is a tautology." Two references that
  look independent, one source. OH-38 puts it exactly right: a core checked
  against both "would pass every test and prove nothing, which is worse than
  a core with no tests, because the tests would be believed."

* OH-64, Armv7E-M, two nRF52840 boards. Decode is DONE and committed --
  verified against objdump over 172,032 wide encodings, 1,260 IT-block
  renderings and a real image at 143 of 143 lines (ca38cb7). Only EXECUTION
  lacks an oracle. QEMU is a single source there, so a disagreement is
  detectable and not adjudicable.

OH-64 already names the ranking: "a second independent Armv7E-M
implementation ... or real hardware, since an nRF52840 board with a debug
probe is a hardware-captured source and outranks both". OH-38 names the same
thing: "a hardware-captured trace from a real S3, which makes the silicon the
oracle". Both name it; neither owns it; so it never gets built.

WHAT THIS TICKET IS. The capture harness, once, in a form both can use --
not a core, and not a decision about either core.

STEPS:

1. Decide the capture mechanism per part before buying anything, because
   they differ. The nRF52840 has a CoreSight debug port and SWD; halting
   single-step over SWD gives an architectural register trace directly. The
   ESP32-S3 has no equivalent that is as simple, so establish whether its
   JTAG plus OpenOCD can single-step and dump the register file, and whether
   the on-chip trace unit is reachable, BEFORE treating an S3 board as
   sufficient.
2. Define the fixture format first, and reuse the one the rv32 and i8086
   corpora already use if it fits, so the existing conformance machinery
   reads it. rules/conformance-fixtures.md governs; this ticket does not get
   to invent a second format quietly.
3. Prove the harness on a part that is ALREADY verified before trusting it
   on one that is not. Capture a trace from a real ESP32-C3 or an ATmega328P
   and check it against this repository's own core, which is known good.
   A harness whose first use is on unverified silicon cannot be told from a
   broken harness. This step is the whole reason the ticket is worth
   filing separately.
4. Only then capture for the S3 and the nRF52840, and hand the fixtures to
   OH-38 and OH-64.

HARDWARE REQUIRED, and that is why this is filed rather than started: an
XIAO ESP32-S3 and an XIAO nRF52840, a debug probe, and a known-good board for
step 3. None of that exists in this environment; all of it is ordinary and
cheap.

THIS DOES NOT CLAIM core/xtensa/** or tests/xtensa/**, which are OH-38's, nor
OH-64's paths. It produces fixtures and a capture tool; the cores stay where
they are.

A NOTE ON ORDERING. Step 3 is what makes the rest honest, and it is also the
cheapest, needing only a board this project already supports. If the harness
cannot reproduce a known-good trace, nothing after it is worth doing, and
that is knowable long before any S3 is involved.

**Note 2026-11-05:** Step 1, mechanism per part, recorded in tools/capture_trace.py's docstring: ESP32-C3 by its built-in USB-Serial-JTAG (openocd-esp32 board/esp32c3-builtin.cfg, riscv32-esp-elf-gdb stepi); ESP32-S3 by its built-in USB-JTAG (board/esp32s3-builtin.cfg, xtensa-esp32s3-elf-gdb), where it is still to be shown on a board that stepi retires one instruction and that GDB's dump is the physical AR file plus WINDOWBASE/WINDOWSTART, not only a0-a15; nRF52840 by SWD over CMSIS-DAP (target/nrf52.cfg, arm-none-eabi-gdb). Only the C3 converter is written; the S3 and nRF converters wait for a real probe's log, since writing them now would be writing them against a guess at it.

**Note 2026-11-05:** Step 2, the fixture format: the rv32 corpus case (mnemonic, encoding, width, initial, one oracle cell holding status and writes), with the oracle cell named silicon. It differs in three ways, each forced. initial is the whole register file, never a delta. The case carries its own pc, and the silicon cell records the pc after the step. There is no requires field, because the file-level part names the one chip that executed it. Provenance records the board, captured_on (an argument, never a clock call), the mechanism and the log's sha256. 'check' replays each case through core/riscv32 with webui.boards.esp32c3.ISA and compares all 31 registers and the pc. A load or store faults on the replay's memory and is counted as skipped. A SYSTEM opcode (CSR read) is skipped by name. A file in which nothing was compared exits 1.

**Note 2026-11-05:** Step 3 is NOT done: no capture has been taken. This machine has no OpenOCD, no riscv32-esp-elf-gdb and no ~/.espressif, only esptool. About 12 Espressif USB-JTAG devices are attached (VID 303A PID 1001; COM3/5/7/8/10/11/12/13/14/15/21; chip type of each unknown). They were deliberately not halted, flashed or probed, because they may belong to other work. tests/rv32/test_capture_trace.py proves the harness on synthetic GDB-format logs only: agreement, a wrong result register, a register silicon changed and the core did not, a register the core wrote and silicon did not (the delta hazard), a wrong next pc, an instruction the core cannot execute, a CSR skip, a load skip, and refusal of empty, truncated, one-halt, missing-register, duplicate-register and bytes-not-at-pc logs. Five mutations of the tool were each caught. test_every_committed_capture_replays skips, saying so, until tests/fixtures/hardware/ holds a real capture.

**Note 2026-11-05:** Blocked on hardware: the harness (tools/capture_trace.py, tests/rv32/test_capture_trace.py) is landed; step 3 needs openocd-esp32 and riscv32-esp-elf-gdb installed and consent to halt one of the attached ESP32-C3 boards, which may belong to other work. Run 'python tools/capture_trace.py script --steps 200 > capture.gdb', capture, then 'convert' into tests/fixtures/hardware/ and 'check'.
