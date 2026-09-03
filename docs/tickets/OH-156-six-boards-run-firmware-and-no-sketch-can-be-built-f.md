---
id: OH-156
title: Six boards run firmware and no sketch can be built for them
status: done
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

**Note 2026-09-04:** The small half is DONE 2026-09-04: a sketch builds for the ESP32-C5 and the ESP32-C6 on the openhardware core, runs on the described board, and drives the vendor's own D10. Counted from catalogue.catalogue() against RECIPES: 26 boards, 12 runnable, 10 buildable (was 6). The two left are the RP2040s, and this ticket's own text says they are the larger half and should be split out; nothing here touched main.c's #error branch.

What landed, and what was measured rather than copied:

* webui/arduino/variants/xiao_esp32c5/ and xiao_esp32c6/, each an oh_board.h and a link.ld restating that board's OWN webui/boards/*.py -- the C5's ENABLE trio at +0x34/+0x38/+0x3C where the C6's is +0x20/+0x24/+0x28 on the same base; stack tops 0x4085FFF0 and 0x4087FFF0 from each part's SOC_DRAM_HIGH; regions 32M/384K and 16M/512K. The parity test now runs per variant against its own description and asserts the region LENGTHs too.
* OH_DELAY_LOOPS_PER_MS stays 4,000 on both and the MEASUREMENT is each part's own: 24,043 steps rise-to-rise on the C5 and on the C6. The C3 re-measured today is 24,043 as well (its header said 24,031, dated 2026-08-31, now annotated), so the twelve steps lie between the dates and not between the parts. A first draft of the C5 comment blamed -march=rv32imac for the difference; building the C5 with rv32imc gave 24,043 too, so that sentence was wrong and is gone.
* Pin names: PlatformIO's framework-arduinoespressif32 (3.20017.241212) ships XIAO_ESP32C3 and XIAO_ESP32S3 variants and no other XIAO, measured by listing it. The C5's and C6's pins_arduino.h are in third_party/bsp/arduino-esp32 already, the checkout tools/import_pindefs.py --fetch makes (at 2787dab; both files byte-identical to upstream master modulo CRLF; last changed a850760 2025-12-01 and 38d6ed5 2024-08-02). So Recipe gained bsp_includes, resolved under BOARD_SUPPORT with a refusal naming the fetch -- fetched, not vendored, for the reason that tool gives. The C6's table includes soc/soc_caps.h and uses nothing from it (zero SOC_ tokens), so the C6 variant carries an empty header of that name with the argument in its comment, and the vendor file is used verbatim.
* -march=rv32imac for both: this toolchain is GCC 8.4.0 (esp-2021r2), which rejects _zicsr_zifencei ("unsupported ISA substring", measured) and knows no Zc; ESP-IDF's own C5 build omits Zc on purpose (ZCMP_WORKAROUND, per esp32c5.py). The core executes the datasheet's set, the compiler emits the toolchain's subset.
* webui/compile.py: the three ESP32 rows now come from one _openhardware() factory, because written out they differed in four fields and repeated forty lines -- the copy the C3 row's own comments warned against. Its hints name the row's OWN oh_board.h, and a test holds that.
* tests/webui/test_compile.py: per board, build with the in-repo core; run on the described board and toggle D10 watched on the bit the vendor's table gives (C5 GPIO10, C6 GPIO18, written as numbers so a wrong table shows as the wrong bit); delay steady and scaling; the hint names the right header. 54 passed.

Mutations, run and restored byte-for-byte: C5 header given the C6's ENABLE offsets -> 2 fail; D10 numbers swapped -> 2 fail; C6 stack top copied from the C5 -> 1 fail; the soc_caps.h shim deleted -> the C6 build fails; a header's delay constant divided by 100 -> passes, and the delay test's docstring now says so, because the value is the labelled judgement and only the scaling is asserted.

One correction to the process: the first mutation run "restored" the C5 header from the C6's backup, because both are named oh_board.h and the backups were keyed by basename. Caught by the hash check, the header was rewritten from its text and re-verified against the description before the run was repeated.

**Note 2026-09-04:** Gate 2026-09-04: tools/checkall.py all 12 checks pass, 2,020 passed / 17 skipped (707 s). A first run alongside my own builds and mutation runs failed two server-timing tests (test_an_upload_from_another_origin_is_refused -- the handoff's known flaky one -- and test_a_state_poll_answers_while_a_build_runs); both pass in isolation and the re-run with the box to itself was clean. Load-dependent, as the 08-31 handoff's 9.1 reads it; not fixed here.
