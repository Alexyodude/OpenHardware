---
id: OH-158
title: Three tickets are blocked on tools nobody tried to install, and one is already
  stale
status: open
priority: P1
created: '2026-09-03'
touches:
- docs/architectures.md
- webui/boards/catalogue.py
---

Three tickets are blocked on tools this machine does not have, and in each
case the test performed was "can it be BUILT from source here", never "can a
prebuilt binary be obtained". Those are different questions and only one of
them was asked.

Verified on this box 2026-09-03, by resolving the compile service's own
toolchain paths rather than by looking on PATH:

    on PATH:   gcc ABSENT, clang ABSENT, meson ABSENT,
               qemu-system-arm ABSENT, arm-none-eabi-gcc ABSENT
               cl.exe present (MSVC 14.44), node present, cmake and ninja present

    resolved through PlatformIO packages:
        avr-gcc                 FOUND   toolchain-atmelavr
        riscv32-esp-elf-gcc     FOUND   toolchain-riscv32-esp
        arm-none-eabi-gcc       FOUND   toolchain-gccarmnoneeabi
                                        -> "xPack GNU Arm Embedded GCC x86_64" 12.3.1, runs

ONE BLOCKER IS ALREADY STALE AND SHOULD BE RETIRED ON SIGHT. OH-36's note of
2026-08-25 records TWO blockers, the second being "(b) No image:
arm-none-eabi-gcc is absent". It is not absent. It arrived with the SAMD21
build recipe, which is why XIAO-SAMD21-DIP and -SMD are two of the six
boards a sketch can currently be built for. It is not on PATH, which is
almost certainly why a `which`-style check said otherwise -- every cross
toolchain here lives under ~/.platformio/packages and none of them is on
PATH.

**OH-36 is held by another session and must not be edited by this one.**
Whoever holds it should re-test blocker (b) and strike it. This ticket
exists partly so that finding is written somewhere they will see it.

WHAT REMAINS GENUINELY UNTESTED, and it is the same untested step three
times over:

1. OH-36(a): "qemu-system-arm absent, and it cannot be built here -- QEMU
   needs meson plus GCC or Clang and all four are absent". True as written,
   and it settles building. QEMU publishes Windows binaries; nobody has
   recorded trying to install one. If one runs, OH-36's oracle blocker
   becomes the single-source limitation it already planned to record, rather
   than an absence.

2. OH-64: "QEMU is not installed here -- verified twice: no qemu-system-arm,
   no PlatformIO package, nothing in Program Files". Again a search, not an
   installation attempt. Same step, same binary, and it would serve
   Armv7E-M as well as Armv8-M.

3. OH-9: blocked on a working PICSimLab build, and the ticket's own note of
   2026-08-24 already spotted this -- "worth checking whether upstream
   publishes prebuilt releases at all, since install_root() accepts a binary
   install and that would sidestep the compiler problem entirely". Nobody
   has. install_root() needs only share/, so a binary release would satisfy
   it.

STEPS:

1. For each of QEMU-for-Windows and PICSimLab, establish whether an official
   prebuilt exists, what it is signed or checksummed with, and what its
   licence permits. Record the answer either way; a NO is as useful here as
   a YES and stops the fourth session re-asking.
2. If a QEMU binary runs, execute one known image under it and under this
   repository's cortexm0 core and diff, so the oracle is demonstrated rather
   than assumed present.
3. Update docs/architectures.md's oracle survey and catalogue.py's ORACLES
   strings with what was found. ORACLES is what missing_cores() reports to a
   reader, so a stale entry there is what makes a board look deader than it
   is.
4. Do NOT relax the single-source objection if QEMU appears. It is a real
   one: QEMU alone can detect a disagreement and cannot adjudicate it, and
   OH-36 and OH-64 both already say so. A running QEMU turns "no oracle at
   all" into "one source, limitation recorded", which is the bar OH-36
   already set for itself.

WHAT THIS IS NOT. It is not a request to vendor a binary into the repository,
and it is not permission to weaken rules/conformance-fixtures.md. It is the
one experiment that three separate tickets each assumed the answer to.
