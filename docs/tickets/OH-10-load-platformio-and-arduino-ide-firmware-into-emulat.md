---
id: OH-10
title: Load PlatformIO and Arduino IDE firmware into emulated boards
status: open
priority: P1
owner: session/toolchain
created: '2026-08-23'
touches:
- webui/firmware.*
- tools/import_firmware.py
- tests/webui/test_firmware.py
- docs/features/firmware.md
---

A user writes firmware in PlatformIO or the Arduino IDE, builds it, and loads the artefact into an emulated board.

Scope is the loading path on this side: find the build output (.pio/build/<env>/firmware.elf|bin|hex, or the Arduino IDE's export), read ELF/HEX, and hand the image to a board that can run it.

Upstream already has Project Wizard integration for Arduino IDE, MPLAB X and VSCode+PlatformIO, so the editor side is solved for PICSimLab's own boards. What does not exist is the path from a PlatformIO artefact to one of the 25 imported XIAO boards.

Partially blocked, and honestly so: only XIAO ESP32-C3 has a backend today (bsim_qemu, inherited from the shipped ESP32-C3-DevKitC-02). RP2040, SAMD21, nRF52840 and MG24 have none, so firmware for them can be parsed and inspected but not executed. See OH-9 and known-issues 4a.6.
