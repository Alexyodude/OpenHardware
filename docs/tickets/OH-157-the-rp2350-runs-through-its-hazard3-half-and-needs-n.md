---
id: OH-157
title: The RP2350 runs through its Hazard3 half, and needs no new core or oracle
status: in-review
priority: P1
created: '2026-09-03'
touches:
- webui/boards/rp2350.py
- webui/boards/catalogue.py
- tests/webui/test_board_catalogue.py
- tests/rules/test_board_claims.py
- tests/webui/test_pin_view.py
- docs/architectures.md
- tests/webui/test_xiao_rp2350_board.py
- tests/webui/xiao_rp2350/**
- tests/rules/test_import_pindefs.py
- webui/boards/XIAO-RP2350-*.json
- webui/api.py
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

**Note 2026-10-08:** 2026-10-08: unblocked by fetching what it was blocked on. Started in lane4. A RISC-V compiler is on this machine: the ESP32 Arduino core's esp-rv32 toolchain (riscv32-esp-elf-gcc) under Arduino15/packages/esp32/tools/esp-rv32. third_party/bsp/arduino-pico/pico-sdk is declared and empty.

**Note 2026-10-08:** BLOCKED ON CLAIMS, 2026-10-08, with the work done and run. Every step of this ticket is implemented and passes in lane4; none of it is committed, because committing it either collides with OH-161's claim or turns tests red in files this ticket does not claim. What is committed here is this note and docs/architectures.md 5.4's measured facts.

THE SOURCE IS FETCHED AND PINNED. pico-sdk 2.3.0 at 98a542c1a62fb549ffb5d66a3e5892b06276b670 -- the commit arduino-pico 33201a6 pins as its pico-sdk submodule -- blobless and sparse (src/rp2350/hardware_regs only) into that submodule's own empty path, third_party/bsp/arduino-pico/pico-sdk (git init; fetch --depth 1 --filter=blob:none origin <sha>; sparse-checkout set src/rp2350/hardware_regs; checkout FETCH_HEAD). BSD-3-Clause. And the RP2350 Datasheet, release 8, build 80d627281ed5, build date 01/10/2026, from https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf, sha256 a638d6780da919162660691bfa02c6dcf7c2a0b6e9f18e2d7519c80b664a2e39 (CC BY-ND; downloaded to a scratch directory, not into the tree, as the RP2040's was). No fetch registry was edited: the submodule path was already declared.

STEP 1, NOW FALSIFIABLE. The compiler is riscv32-esp-elf GCC 14.2.0 (crosstool-NG esp-14.2.0_20260121, the ESP32 Arduino core's esp-rv32 2601), not the PlatformIO GCC 8.4.0 the 2026-09-04 note had. The blink is the same bytes under -march=rv32imac and under rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp, and the same compiler emits clz, minu and rev8 for a three-function probe under the full string and none under rv32imac. So no Zbb and no Zbkb is a property of the program. Its code is lui, jal, addi, andi, bltu, c.addi, c.li, c.lw, c.sw, c.lwsp, c.swsp, c.j: RV32I and C only, no M, no A, all decoded by core/riscv32/disasm.py.

WHAT IS IN THE WORKING TREE, AND RUNS. webui/boards/rp2350.py (new): the XIAO's 2 MB flash at XIP_BASE 0x10000000, SRAM 0x20000000..0x20082000, RESETS.RESET and its XOR/SET/CLR aliases (stored, not obeyed), IO_BANK0 GPIO0..29_CTRL, PADS_BANK0 GPIO0..29 at reset 0x116 with ISO set, SIO CPUID and GPIO_OUT/OE with their write-only SET/CLR/XOR, and the FIFO stubbed (FIFO_ST 0x2, FIFO_WR and FIFO_RD swallow writes and read 0); RESET_DONE, GPIO_IN and the ROM unmapped. Each address cites a pico-sdk header line, each behaviour a datasheet section and PDF page; HEADER is generated by import_pindefs --write-headers. pin_states reads FUNCSEL, then ISO and OD, then OE/OUT. It says the Cortex-M33 half is not modelled and is OH-36's, core 1 does not exist, and the image is entered at its lowest address because that is where the boot ROM enters a minimum RISC-V IMAGE_DEF (datasheet 5.9.5.2, Table 504). catalogue.py: CHIPS RP2350 core cortexm33 -> riscv32 (the ISA string still names both halves), FIRMWARE_VERIFIED RP2350 -> tests/riscv32/rp2350/test_rp2350_board.py. tests/riscv32/rp2350/: blink.c (its GPIO given as -DBLINK_GPIO from rp2350.HEADER["D3"], never typed), blink.ld, blink.bin (sha256 ea90feb7c7691fbf40b89ce7bc165b36bf5222a2228ff69e3d74f30dec6e6cd3, with the 20-byte minimum RISC-V IMAGE_DEF after the code), and test_rp2350_board.py, 15 tests: the XIAO-RP2350-DIP and -SMD loaded by name through api.load_firmware, stepped, and the pad whose chip_index is HEADER["D3"] (GPIO5) watched through api.pin_view going input, low, high, then alternating at a steady period while every other GPIO pad reads input; why D3 (the one label of D0..D10 the two XIAOs' tables send to different GPIOs, and the RP2040's GPIO29 is no pad here); a byte-for-byte rebuild; the Zbb control; lockstep against rvcpp for 3000 steps on the same source rebuilt with its four bases and stack moved into the testbench RAM (differing from blink.bin only in lui immediates); every cited pico-sdk value and line. Each of the 15, and each changed catalogue and pin-view test, was seen red under a deliberate break. check_board_claims accepts the entry. Inventory with it in place: "TWINS -- 19 of 37 boards hold all four; ... runs 25", both XIAO-RP2350 rows "RP2350" where they read "RP2350:no". A copy of all of it is in .omc/handoffs/OH-157/ (tracked.patch, files/, architectures.md).

WHAT BLOCKS IT, file by file, and the edit that clears each:
1. docs/tickets/OH-161-*.md touches tests/riscv32/**, which covers this ticket's tests/riscv32/rp2350/**. collisions() compares files on disk, so the moment blink.bin exists check_ticket_claims and tests/rules/test_tickets.py::test_this_repositorys_tickets_parse_and_do_not_collide fail and the pre-commit hook refuses every commit in the worktree. Clear by narrowing OH-161's claim to the files it needs, or by giving this ticket a path outside it.
2. pyproject.toml (unclaimed): tests/rules/test_testpaths.py requires every directory holding a test_*.py in testpaths, so tests/riscv32/rp2350 must be added. The alternative is the flat shape the 2026-09-04 note recommended -- tests/riscv32/test_rp2350_board.py beside a fixture directory -- which needs no pyproject edit but puts the test file in OH-161's claim.
3. tests/webui/test_board_run.py:777 (OH-161's): test_each_refusal_arrives_as_itself uses XIAO-RP2350-DIP as its core-not-built witness, which stops being true; any board on cortexm33, cortexm4 or xtensa (XIAO-MG24-DIP) is still one.
4. tests/rules/test_import_pindefs.py (unclaimed): test_the_committed_modules_match_the_generator pins the chips with HEADER markers at four (add RP2350); test_the_board_file_and_the_module_agree_on_every_labelled_pad pins checked boards at 11 (13 with the two RP2350s); and test_the_committed_board_files_match_the_generator needs item 5.
5. webui/boards/XIAO-RP2350-DIP.json and -SMD.json (unclaimed): regenerate with `python tools/import_pindefs.py --write-boards`; filled_board shows only their `assumption` sentence changes, from "No board module describes RP2350 here" to "webui/boards/rp2350.py reads a level through the same table".
6. Not failing, stale: webui/api.py:1087 (unclaimed) says "all six modules with PIN_NAMES"; it would be seven.

Full suite with everything in place, lane4: "10 failed, 2438 passed, 67 skipped in 542.37s". Five of the ten fail at HEAD without this work, measured: the OCP pair in test_import_3d_model, test_compose_board_3d::test_nothing_is_declared_absent_that_no_board_actually_has, and test_import_pindefs's test_the_real_tree_never_resolves_a_pad_from_nothing and test_the_committed_board_files_match_the_generator, the last two because lane4's third_party has no olimex-esp32-c3-devkit-lipo checkout. The other five are items 1-4. Nothing under core/**, tests/cortexm33/** or the rest of tests/riscv32/** was edited.

**Note 2026-10-08:** 2026-10-08, the orchestrator's decision on the claims blocker: the evidence moves out of tests/riscv32/ (OH-161's glob, which collides on disk) to tests/webui/test_xiao_rp2350_board.py and tests/webui/xiao_rp2350/, beside the KB2040's, so neither OH-161's claim nor pyproject.toml's testpaths changes. tests/webui/test_board_run.py's core-not-built example moved to the MG24 under OH-161 on master (393d452). This ticket now also claims tests/rules/test_import_pindefs.py, the two XIAO-RP2350 board files and webui/api.py, all unclaimed, for the chip list, the count, the regenerated assumption sentence and the stale module count in a comment.

**Note 2026-10-08:** 2026-10-08, done in lane4 and in review. THE EVIDENCE MOVED out of tests/riscv32/ as decided: tests/webui/test_xiao_rp2350_board.py, and tests/webui/xiao_rp2350/ holding blink.c, blink.ld and blink.bin (blink.bin byte-identical, sha256 ea90feb7c7691fbf40b89ce7bc165b36bf5222a2228ff69e3d74f30dec6e6cd3). tests/riscv32/rp2350/ is gone from disk, so neither OH-161's claim nor pyproject.toml's testpaths changed; where the two 2026-10-08 notes above say tests/riscv32/rp2350/, these are those files. The test imports tests/riscv32/lockstep unchanged, finds the pico-sdk checkout one directory less deep, and its 15 tests pass with none skipped. blink.c, rp2350.py, catalogue.py's FIRMWARE_VERIFIED entry and comment, and test_board_catalogue.py name the new path. check_board_claims: "RP2350 -> tests/webui/test_xiao_rp2350_board.py"; with xiao_rp2350/blink.bin moved aside it exits 1 naming the entry, so check 5 reads the new location.

RE-RUN RED AFTER THE MOVE, each file restored byte for byte by digest: the headline, with the image rebuilt from the same source for the RP2040's D3 (GPIO29, no pad here), sees ['input'] and nothing else; the rebuild, with blink.c's delay bound 100 -> 101 and blink.bin left alone, differs at byte 40; the lockstep, with this core given RP2350_MODELLED less C, stops at pc 0x80000050 on a compressed encoding rvcpp executed.

tests/rules/test_import_pindefs.py: the chips carrying HEADER markers gain RP2350, and the docstring no longer counts them; the boards whose file and module agree on every labelled pad are 13, three C3 files and two each of C5, C6, RP2040, RP2350 and SAMD21. `python tools/import_pindefs.py --write-boards` rewrote only XIAO-RP2350-DIP.json and XIAO-RP2350-SMD.json, and in each only the `assumption` sentence; a second run wrote nothing. webui/api.py's pin_view comment names the test that asserts every PIN_NAMES module has pin_states, rather than a count of them. Lane4's third_party now holds olimex-esp32-c3-devkit-lipo, pcbcupid-glyph-c3, pcbcupid-glyph-c6 and sparkfun-thing-plus-esp32-c5, fetched with tools/get_board_sources.py.

Commits: 5631e56 (rp2350.py, the pin-view test), 81655d6 (the generator test, the two board files), b54fa9d (the catalogue, its tests and the evidence), 853735c (the api comment). Inventory: "TWINS — 19 of 37 boards hold all four; by layer: geometry 37, model 31 (5 not built here), pins 33, runs 25", and both XIAO-RP2350 rows read RP2350 in the runs column. Full suite, lane4: "2 failed, 2475 passed, 38 skipped in 577.71s (0:09:37)", the two being test_import_3d_model's OCP pair (No module named 'OCP'), which fail at HEAD without this work. Nothing under core/**, tests/cortexm33/** or tests/riscv32/** was edited.
