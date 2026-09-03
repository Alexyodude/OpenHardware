---
id: OH-156
title: Six boards run firmware and no sketch can be built for them
status: open
priority: P2
created: '2026-09-03'
touches:
- webui/compile.py
- webui/arduino
- tests/webui/test_compile.py
---

Six boards execute firmware and cannot be built for. The Build button is
absent on a board the emulator can genuinely run, which is the opposite of
the false affordance OH-148 was careful to avoid, and nothing said so.

Measured 2026-09-03 from webui/boards/catalogue.catalogue() and
webui.compile.RECIPES:

    26 boards
    12 runnable (core built AND a board description exists)
    12 firmware VERIFIED (a named test watched an image execute)
     6 a sketch can be BUILT for

    runnable but NOT buildable:
        XIAO-ESP32-C5-DIP, XIAO-ESP32-C5-SMD    ESP32-C5   riscv32
        XIAO-ESP32-C6-DIP, XIAO-ESP32-C6-SMD    ESP32-C6   riscv32
        XIAO-RP2040-DIP,   XIAO-RP2040-SMD      RP2040     cortexm0

The other fourteen boards are blocked on a missing core and are already
tracked as such -- OH-36 (cortexm33, nine boards), OH-38 (xtensa, three) and
OH-64 (cortexm4, two) -- so this is the whole of the untracked gap.

THE TWO HALVES ARE NOT THE SAME SIZE, and filing them together is only
justified because they share one file.

The ESP32-C5 and ESP32-C6 are the small half. Both are riscv32, both already
have a built core and a board description, both are firmware-verified, and
the C5's core gained Zcb/Zcmp/Zcmt this session. The path OH-148 built for
the C3 -- webui/arduino/cores/openhardware plus a per-board variant of
oh_board.h and link.ld -- should extend to them by supplying each board's
own flash and DRAM origins and its GPIO register addresses, all of which
webui/boards/esp32c5.py and esp32c6.py already map. What must NOT be assumed
is that the C3's numbers carry over: OH_STACK_TOP, the GPIO W1TS/W1TC
addresses and OH_DELAY_LOOPS_PER_MS are per-chip, and the delay constant is
a stated judgement that has to be re-measured per board rather than copied.

The RP2040 is the larger half and should probably be split out once the
first two land. webui/arduino/cores/openhardware/main.c today reads

    #if defined(__riscv)
        ... li sp / tail oh_run ...
    #else
    #error "no _start for this architecture yet; add its branch when its recipe arrives"

so the core anticipated exactly this and refuses loudly rather than
guessing. A Cortex-M0+ branch needs a vector table with the initial stack
pointer and reset vector at the image's start -- not a naked function at the
lowest address, which is the RISC-V convention machine.py enters on -- so it
is a real design step and not a copied stanza.

Each board added must come with the OH-148 shape of evidence: a test that
builds a sketch AND watches the image drive the board's own named pin, not
merely that a compiler exited zero. tests/webui/test_compile.py's C3 block
is the pattern, and OH-151's test is the one that catches the silent half.

WHY THIS IS ONE TICKET AND NOT TWENTY-SIX. The per-board question is already
answered by a generator: catalogue.missing_cores() groups the unrunnable
boards by the core that would unlock them and states what each would cost in
oracles, and CLAUDE.md is explicit that an inventory is the document that
rots fastest and that the generator should be run rather than a list
maintained. Twenty-six hand-written per-board tickets would be exactly that
list. What is worth filing is the gap the generator does NOT cover, which is
this one: missing_cores() reasons about whether a board can RUN, and says
nothing about whether anything can be COMPILED for it.
