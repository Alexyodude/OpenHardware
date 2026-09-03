---
id: OH-157
title: The RP2350 runs through its Hazard3 half, and needs no new core or oracle
status: blocked
priority: P1
created: '2026-09-03'
touches:
- webui/boards/rp2350.py
- tests/riscv32/rp2350/**
---

Two of the fourteen dead boards can probably be made to run without a new
core, without a new oracle, and without touching the Cortex-M33 work at all.
Nobody has tried, because the RP2350 sits inside OH-36's Armv8-M block and
that ticket is blocked.

THE RP2350 IS TWO ARCHITECTURES ON ONE DIE. Dual Cortex-M33 and dual Hazard3
RISC-V, whichever is unused held in reset (docs/architectures.md 5.4, marked
[V]). OH-36 says so itself -- "The RP2350's RISC-V half may reach through the
RV32 core instead. Whether that is a cheaper route to a running RP2350 than
Armv8-M is worth answering before starting" -- and then, correctly, does not
answer it, because OH-36 is about Armv8-M. So the question was asked in a
place where nobody would act on it.

EVERYTHING THE RISC-V ROUTE NEEDS ALREADY EXISTS EXCEPT ONE FILE.

* The core: core/riscv32 is built and firmware-verified on four chips
  (ESP32-C3, C5, C6 and, through RP2040 for cortexm0, separately).
* The oracle: rvcpp, Hazard3's OWN 1,080-line C++17 golden model, which this
  repository already ships, builds and runs -- docs/architectures.md 2.1b.
  It is the oracle the whole riscv32 corpus rests on. There is no oracle gap
  here of the kind that blocks Armv8-M, Xtensa and Armv7E-M.
* The ISA: core/riscv32/abi.py already carries a Hazard3 constant, with the
  datasheet's own string cited --
  rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp -- and Zcb and Zcmp
  landed at OH-146.
* The second core: docs/architectures.md 5.5 establishes that core 1 can
  simply not exist. At reset it parks itself and drains its mailbox; nothing
  at boot waits FOR it. The SIO FIFO registers need to exist as stubs that do
  not fault.

WHAT IS MISSING is webui/boards/rp2350.py. catalogue.py reports the RP2350 as
described=NO, and that single fact is why both its boards report unrunnable
while their core is built and their oracle is running. Compare
webui/boards/esp32c6.py, which is the nearest sibling in shape.

STEPS, in the order that keeps each one falsifiable:

1. Answer the cheap question first: does a minimal image built -march=rv32imac
   avoid Zbb and Zbkb entirely? abi.py's own note says those two are NOT
   modelled and that the Hazard3 constant "describes a part that does not
   exist". If a blink needs them, this ticket grows a decoder step; if it
   does not, it does not. Do not assume -- build one and disassemble it.
2. Write webui/boards/rp2350.py: flash and SRAM origins and sizes, and the
   GPIO registers, each cited to the RP2350 datasheet the way esp32c6.py
   cites ESP-IDF's soc.h. Nothing invented; a register whose address is not
   in the datasheet is left unmapped, which is the rule that made the C3's
   GPIO_IN absence honest.
3. Stub the SIO FIFO registers so a single-core image that touches them does
   not fault, and say in the file that core 1 does not exist rather than
   modelling it.
4. Verify the OH-148 way: a named test that watches a real compiled image
   drive the board's own pin, not merely that a loader accepted bytes. The
   RP2350 is composed and its 3D model already draws, so the pin names are
   already correct.

DONE WHEN both XIAO-RP2350 boards report runnable and firmware_verified from
catalogue.py, on the RISC-V half, with the file stating plainly that the
Cortex-M33 half is not modelled and that OH-36 is where that lives.

THIS DOES NOT TOUCH OH-36 and must not. That ticket is held by another
session and claims core/cortexm33/** and tests/cortexm33/**; this one claims
none of them. If this succeeds it makes OH-36 smaller -- seven boards rather
than nine -- and it does not make OH-36 unnecessary, because a real RP2350
boots its Arm half by default and the M33 remains the honest target.

**Note 2026-09-04:** BLOCKED ON A DATASHEET, 2026-09-04, and that is the answer to this ticket's own step 2 rather than a failure to start it. Every address in a webui/boards/*.py file cites a header or a datasheet line, and for the RP2350 nothing on this machine or in this tree carries one. Searched, by two independent passes:

    $USERPROFILE/.platformio/               tool-rp2040tools; pico-sdk 1.x vendored inside
                                            framework-arduino-mbed with rp2040/ only (no
                                            rp2350/); SVDs: rp2040.svd only
    third_party/bsp/arduino-pico/pico-sdk/  an EMPTY directory -- an uninitialised submodule
                                            pointing at raspberrypi/pico-sdk, zero files
    third_party/                            RP2350.kicad_pcb, RP2350.zip, two .kicad_mod files,
                                            Seeed's four wiki pages (XIAO-RP2350*.md), and
                                            hazard3/ -- a board, its footprint, its pinout and
                                            the CPU; not the chip's register map
    docs/research/peripheral-layer/         esp32c3/, rp2040_v2/, stm32c0/ -- no rp2350

So XIP_BASE, the SRAM window, SIO_BASE and its GPIO_OUT/OE set-and-clear offsets, IO_BANK0's GPIOn_CTRL, PADS_BANK0 and the SIO FIFO registers -- every number rp2350.py would need -- would have to be written from memory, which is the one thing this repository refuses. Two RP2350 facts ARE citable offline and neither is an address: the ISA string (docs/architectures.md:725, tests/rv32/conftest.py) and the LED pin (third_party/bsp/arduino-pico/variants/seeed_xiao_rp2350/pins_arduino.h:33, PIN_LED 25, D0 = 26).

THREE THINGS THIS TICKET GOT WRONG, found while checking it, so the next attempt does not inherit them:

1. "described=NO is that single fact" is false. runnable = core_built AND described, and catalogue.CHIPS maps RP2350 to core "cortexm33", which is not built. Measured: both XIAO-RP2350 boards report core cortexm33, core_built False. Writing rp2350.py alone leaves them unrunnable; the CHIPS row would have to say riscv32, and that breaks two committed tests (tests/webui/test_board_catalogue.py:176, which needs the cortexm33 backlog to spell its ISA two ways, and :510, which pins the Cortex-M33 boards at nine). CHIPS is a one-core-per-chip table and the RP2350 is two cores; deciding how that table says so is a design step this ticket did not budget.

2. Step 1 cannot be falsified with this toolchain, so its "yes" proves nothing. A blink built -march=rv32imac -Os (the -march=rv32imac_zicsr the ticket wrote is rejected by this GCC 8.4.0: "unsupported ISA substring '_zicsr'") disassembles to addi, bgeu, bltu, j, lui, lw, sw -- no Zbb, no Zbkb -- but -march=rv32imac_zbb and _zbkb are ALSO rejected, and a function written to beg for them (__builtin_clz/ctz/popcount/bswap32, a min) compiled to libcalls. GCC 8.4.0 cannot emit a Zbb or Zbkb instruction under any flag. "No Zbb appeared" is a property of the compiler, and the decoder question stays open for any newer one.

3. The test path is wrong. There is no tests/riscv32/esp32c6/; the shape is a flat tests/riscv32/test_esp32c6_board.py beside a fixture directory tests/riscv32/c6blink/. The mirror is tests/riscv32/test_rp2350_board.py plus tests/riscv32/rp2350blink/, and this ticket's touches should say so before anyone writes to them.

WHAT UNBLOCKS IT, concretely, and it is one fetch: pico-sdk's src/rp2350/hardware_regs/include/hardware/regs/ (addressmap.h, sio.h, io_bank0.h, pads_bank0.h, xip.h), blobless and sparse, the way tools/import_pindefs.py --fetch brings arduino-esp32's variants/ -- initialising the submodule that is already declared under third_party/bsp/arduino-pico would do it -- or the RP2350 datasheet with its section numbers, the way rp2040.py's research files cite the RP2040's. Either is a citation; neither is here. Fetch it, decide what CHIPS says about a two-core part, and then rp2350.py can be written the way esp32c6.py was, with the Cortex-M33 half stated as not modelled and OH-36's.

Nothing under core/cortexm33/** or tests/cortexm33/** was touched, and nothing was fetched.
