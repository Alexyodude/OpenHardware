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
- tests/rules/test_import_firmware.py
---

A user writes firmware in PlatformIO or the Arduino IDE, builds it, and loads the artefact into an emulated board.

Scope is the loading path on this side: find the build output (.pio/build/<env>/firmware.elf|bin|hex, or the Arduino IDE's export), read ELF/HEX, and hand the image to a board that can run it.

Upstream already has Project Wizard integration for Arduino IDE, MPLAB X and VSCode+PlatformIO, so the editor side is solved for PICSimLab's own boards. What does not exist is the path from a PlatformIO artefact to one of the 25 imported XIAO boards.

Partially blocked, and honestly so: only XIAO ESP32-C3 has a backend today (bsim_qemu, inherited from the shipped ESP32-C3-DevKitC-02). RP2040, SAMD21, nRF52840 and MG24 have none, so firmware for them can be parsed and inspected but not executed. See OH-9 and known-issues 4a.6.

**Note 2026-08-24:** Format layer landed (webui/firmware.py + tests, commit 7693013): UF2/ELF/HEX/bin -> Image. NOT done: tools/import_firmware.py artefact discovery, the webui/api.py load_firmware op, a Firmware view in the UI, and docs/features/firmware.md.

**Note 2026-08-24:** Artefact discovery landed: tools/import_firmware.py (find_artefacts over PlatformIO/.pio/build, arduino-cli/build/<fqbn>, STM32CubeIDE gated on .cproject) plus a CLI, 42 tests in tests/rules/test_import_firmware.py. Verified against a real three-env PlatformIO blink build; every figure in the handoff's section 4 reproduced, including the boot2 trap (SP 0x4b32b500 at 0x10000000). NOT done, deliberately: (1) an esp-idf image parser -- identify_esp_image reports segment addresses but builds no Image, that belongs in webui/firmware.py with its own tests; (2) boot_app0.bin discovery -- it is a framework constant under ~/.platformio/packages/, not a build output, so looking for it would tie discovery to a global install path; (3) docs/features/firmware.md -- a ledger must come from the feature-strategy skill, never hand-written. Also: the handoff's fixture recipe does not compile. src/main.cpp needs '#include <Arduino.h>' (PlatformIO only auto-injects it for .ino), and XIAO ESP32-C3 defines no LED_BUILTIN.
