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
---

Three boards -- XIAO-ESP32-C3-DIP, -DIP-SMD and -SMD -- become runnable the moment this file exists, exactly as two SAMD21 boards did under OH-39. The C6 and C5 follow the same shape afterwards and are separate tickets, because the board-file convention is one file per chip.

DEPENDS on MMIO for the RISC-V core. There is nothing to map peripherals with until that lands, and an empty esp32c3.py must NOT be added -- it would flip three boards to CORE+BOARD on the strength of a filename, which is the mistake rules/board-claims.md check 3 is named after.

A RISC-V toolchain IS available here: toolchain-riscv32-esp is already in the PlatformIO packages directory, so a bare-metal image can be compiled the way tests/cortexm0/blink/blink.c is. Bare metal is not optional on this part: verified 2026-08-24 against ESP-IDF, apps link ROM-resident functions through esp32c3.rom.ld and esp_rom_delay_us is called from rtc_clk.c on every clock switch, so a vendor-runtime image cannot run without a mask ROM this project does not ship -- the same wall the RP2040's Arduino image hit.

Two facts already measured that will save a session: the XIAO ESP32-C3 has NO user LED and no LED_BUILTIN, so the fixture must observe a GPIO register rather than a pin somebody can name; and its D0-D10 map to GPIO 2,3,4,5,6,7,21,20,8,9,10, three-way verified against the Seeed wiki, pins_arduino.h and the vendor KiCad pad labels.

Licences: ESP-IDF soc/*_reg.h are 'Apache-2.0 OR MIT' -- elect MIT, and spot-check each header. Do NOT draft from espressif/svd: Apache-only, self-declared incomplete, stale since 2024-02.

Done when a real compiled image is watched driving an ESP32-C3 GPIO register, ESP32-C3 is in FIRMWARE_VERIFIED with the pinned test updated deliberately, and every adopted register cites its source.
