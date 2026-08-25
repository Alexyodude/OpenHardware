---
id: OH-48
title: An ESP32-C3 board description, and a blink that proves it
status: open
priority: P1
created: '2026-08-25'
touches:
- webui/boards/esp32c3.py
- tests/riscv32/test_board_esp32c3.py
- tests/riscv32/esp32c3/*
- tests/riscv32/test_esp32c3_board.py
- webui/boards/catalogue.py
- tests/webui/test_board_catalogue.py
- tests/riscv32/c3blink/*
---

Three boards -- XIAO-ESP32-C3-DIP, -DIP-SMD and -SMD -- become runnable the moment this file exists, exactly as two SAMD21 boards did under OH-39. The C6 and C5 follow the same shape afterwards and are separate tickets, because the board-file convention is one file per chip.

DEPENDS on MMIO for the RISC-V core. There is nothing to map peripherals with until that lands, and an empty esp32c3.py must NOT be added -- it would flip three boards to CORE+BOARD on the strength of a filename, which is the mistake rules/board-claims.md check 3 is named after.

A RISC-V toolchain IS available here: toolchain-riscv32-esp is already in the PlatformIO packages directory, so a bare-metal image can be compiled the way tests/cortexm0/blink/blink.c is. Bare metal is not optional on this part: verified 2026-08-24 against ESP-IDF, apps link ROM-resident functions through esp32c3.rom.ld and esp_rom_delay_us is called from rtc_clk.c on every clock switch, so a vendor-runtime image cannot run without a mask ROM this project does not ship -- the same wall the RP2040's Arduino image hit.

Two facts already measured that will save a session: the XIAO ESP32-C3 has NO user LED and no LED_BUILTIN, so the fixture must observe a GPIO register rather than a pin somebody can name; and its D0-D10 map to GPIO 2,3,4,5,6,7,21,20,8,9,10, three-way verified against the Seeed wiki, pins_arduino.h and the vendor KiCad pad labels.

Licences: ESP-IDF soc/*_reg.h are 'Apache-2.0 OR MIT' -- elect MIT, and spot-check each header. Do NOT draft from espressif/svd: Apache-only, self-declared incomplete, stale since 2024-02.

Done when a real compiled image is watched driving an ESP32-C3 GPIO register, ESP32-C3 is in FIRMWARE_VERIFIED with the pinned test updated deliberately, and every adopted register cites its source.

**Note 2026-08-25:** Delivered, and it unlocks THREE boards rather than one: XIAO-ESP32-C3-DIP, -DIP-SMD and -SMD. The catalogue now reports 8 runnable and 8 firmware-verified, up from 5.

Every address cited from Espressif's own SoC headers, which turned out to be installed with framework-arduinoespressif32 -- soc.h:45 for DR_REG_GPIO_BASE, soc.h:217-228 for the memory map, gpio_reg.h:58/66/74/90/98/106/122 for the registers. No remembered numbers.

THE NO-LED CLAIM IS NOW MEASURED, not inherited. The previous handoff recorded that the XIAO ESP32-C3 has no user LED; Seeed's own variant file XIAO_ESP32C3/pins_arduino.h is 34 lines and contains "LED" zero times, where the Uno's defines LED_BUILTIN 13. So the fixture watches GPIO8's register rather than a pin.

TWO REAL GAPS THE END-TO-END RUN FOUND, both of which a unit test would not have:

 1. The board never said which part it was, so the core had NO extensions and refused the second instruction. Fixed by giving the board an ISA string and the core a `set_isa` that translates letters to bits -- `RV32IMC` is a datasheet fact and belongs in the board; the letters-to-bits map is an ABI fact and belongs in the core. `set_isa` REFUSES an extension it cannot represent rather than dropping it, because a part described RV32IMAC on a core that ignored the A would execute atomics an ESP32-C3 must trap.

 2. The image had no stack pointer. An Armv6-M part loads SP from its vector table; an RV32 part does not, and every RISC-V image sets its own in crt0. The `-nostartfiles` blink had none, so the first push faulted -- correctly. The fix belongs in the IMAGE, not in the board inventing one: blink.c gains a `_start`, which is the one thing the missing crt0 would have done.

 And a third that the first fix exposed: without a linker script the linker placed `main` first and `_start` after it, so the stack setup was silently skipped. An image that links cleanly and runs the wrong instruction first is exactly the silent class, so blink.ld now KEEPs .text.start first and test_the_image_begins_with_its_startup_and_not_with_main asserts the first instruction is a LUI into sp.

TWO LIMITATIONS STATED RATHER THAN HIDDEN, each with a test:
 - GPIO_IN is unmapped and READS FAULT. It reflects the pin's electrical level, which this model cannot express; faulting beats the wrong zero. The same call samd21.py makes, and the opposite of what atmega328p.py could do -- an AVR data space has no holes.
 - SRAM's instruction-bus alias at 0x4037C000 is NOT mapped. It and 0x3FC80000 are two views of one 384 KB array and add_region cannot express an alias; mapping both would make two arrays that must agree and will not.

AND THE BIG ONE: an ESP-IDF application will not run on this board. The C3 resets into 384 KB of Espressif mask ROM that sets up the cache, the clock and its function table, and that ROM is not redistributable. Bare-metal images run, which is the standard the other three boards meet.

FOUR TRIPWIRES FIRED, all correctly:
 - test_only_the_board_a_real_image_ran_on_claims_to_have_run_one, pinned deliberately.
 - test_each_refusal_arrives_as_itself used the C3 as its example of an UNDESCRIBED chip. Moved to the C6 -- with a note that OH-57 kills that too, after which no board is core-built-and-undescribed and the fix is the synthetic-directory treatment test_a_built_core_without_a_board_description_is_not_runnable already uses.
 - test_rvc.py's blink tests, because the fixture gained a startup stub. Its duplicate rebuild-and-compare is now DELETED: two copies of one compiler invocation is how one goes stale, and that is exactly what happened.
 - described_chips() counted contract.py as a board and returned a phantom chip "CONTRACT". Harmless while no chip is called that, and a latent lie. Both lists of non-board modules are now pinned together.

Browser-verified with one listener checked first: 26 boards / 8 enabled, ESP32-C3 loads and runs 200,000 instructions, 33 registers with the RISC-V ABI names, sp 0x3FCDFFE0, zero flags -- which is correct, RV32 has no condition codes -- hexdump showing the image, and the listing pane saying core.riscv32.disasm does not exist. 0 console messages.

The Disassembly pane is the one thing still missing, and that is OH-56.

1,239 passed, 17 skipped; all eight checkers exit 0.
