---
id: OH-57
title: ESP32-C5 and C6 board descriptions, the four boards after the C3
status: open
priority: P2
created: '2026-08-25'
touches:
- webui/boards/esp32c5.py
- webui/boards/esp32c6.py
- tests/riscv32/test_esp32c5_c6.py
---

Four of the seven C-series boards: XIAO-ESP32-C5-DIP/SMD and XIAO-ESP32-C6-DIP/SMD. Filed separately from OH-48's C3 because they are the widening pass, not the vertical slice, and because the C5 is not simply a C3 with different addresses.

catalogue.CHIPS records the difference and it is load-bearing:
    ESP32-C3  RV32IMC
    ESP32-C6  RV32IMAC
    ESP32-C5  RV32IMAC + Zcb/Zcmp/Zcmt

So the C6 adds A, and the C5 adds A plus three Zc* groups this core does not implement. core/riscv32/cpu.h:56 records kExtA as classified-and-refused, and cpu.h:72 records Zcb and Zcmp as absent from MODELLED rather than pretending the part lacks them.

That means a C5 board description written today would describe a part whose ISA this core cannot fully execute. THE HONEST MOVE IS TO SAY SO PER CHIP rather than to describe all three and let the difference surface as a fault twenty thousand instructions in. A board is runnable when a core is built and a description exists; whether that core implements the part's whole ISA is a separate claim, and rules/board-claims.md governs it -- only a named test that watched an image execute licenses "runs firmware".

So: describe the C6 and the C5, and let each one's FIRMWARE_VERIFIED entry be earned or withheld on its own evidence. Expect the C6 to be reachable and the C5 to need Zcb/Zcmp/Zcmt first, and record that rather than discovering it.

Also unresolved and worth the next reader's attention: the ESP32-C61 is a real Espressif part and webui/boards/catalogue.py's chip_for has a delimiter check specifically because XIAO-ESP32-C61-DIP once resolved to ESP32-C6. There is no C61 board in the catalogue today. If one arrives it is a different chip, not a C6 variant.

Depends on OH-54, OH-47 and OH-48. Done when the C6 and C5 boards report runnable in the catalogue, each states which of its ISA this core executes, and any firmware claim names a test that watched a real image.
