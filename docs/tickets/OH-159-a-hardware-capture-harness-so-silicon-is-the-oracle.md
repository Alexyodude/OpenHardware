---
id: OH-159
title: A hardware capture harness, so silicon is the oracle Xtensa and Armv7E-M lack
status: open
priority: P2
created: '2026-09-03'
touches:
- tools/capture_trace.py
- tests/fixtures/hardware/**
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
