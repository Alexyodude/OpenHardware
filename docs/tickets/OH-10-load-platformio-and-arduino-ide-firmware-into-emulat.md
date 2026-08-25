---
id: OH-10
title: Load PlatformIO and Arduino IDE firmware into emulated boards
status: done
priority: P1
owner: session/toolchain
created: '2026-08-23'
touches:
- webui/firmware.*
- tools/import_firmware.py
- tests/webui/test_firmware.py
- docs/features/firmware.md
- tests/rules/test_import_firmware.py
- webui/api.py
- tests/webui/test_board_run.py
- webui/emulator_server.py
- webui/static/emulator.html
- webui/static/emulator.js
- tests/webui/test_artefacts.py
---

A user writes firmware in PlatformIO or the Arduino IDE, builds it, and loads the artefact into an emulated board.

Scope is the loading path on this side: find the build output (.pio/build/<env>/firmware.elf|bin|hex, or the Arduino IDE's export), read ELF/HEX, and hand the image to a board that can run it.

Upstream already has Project Wizard integration for Arduino IDE, MPLAB X and VSCode+PlatformIO, so the editor side is solved for PICSimLab's own boards. What does not exist is the path from a PlatformIO artefact to one of the 25 imported XIAO boards.

Partially blocked, and honestly so: only XIAO ESP32-C3 has a backend today (bsim_qemu, inherited from the shipped ESP32-C3-DevKitC-02). RP2040, SAMD21, nRF52840 and MG24 have none, so firmware for them can be parsed and inspected but not executed. See OH-9 and known-issues 4a.6.

**Note 2026-08-24:** Format layer landed (webui/firmware.py + tests, commit 7693013): UF2/ELF/HEX/bin -> Image. NOT done: tools/import_firmware.py artefact discovery, the webui/api.py load_firmware op, a Firmware view in the UI, and docs/features/firmware.md.

**Note 2026-08-24:** Artefact discovery landed: tools/import_firmware.py (find_artefacts over PlatformIO/.pio/build, arduino-cli/build/<fqbn>, STM32CubeIDE gated on .cproject) plus a CLI, 42 tests in tests/rules/test_import_firmware.py. Verified against a real three-env PlatformIO blink build; every figure in the handoff's section 4 reproduced, including the boot2 trap (SP 0x4b32b500 at 0x10000000). NOT done, deliberately: (1) an esp-idf image parser -- identify_esp_image reports segment addresses but builds no Image, that belongs in webui/firmware.py with its own tests; (2) boot_app0.bin discovery -- it is a framework constant under ~/.platformio/packages/, not a build output, so looking for it would tie discovery to a global install path; (3) docs/features/firmware.md -- a ledger must come from the feature-strategy skill, never hand-written. Also: the handoff's fixture recipe does not compile. src/main.cpp needs '#include <Arduino.h>' (PlatformIO only auto-injects it for .ino), and XIAO ESP32-C3 defines no LED_BUILTIN.

**Note 2026-08-25:** DEFECT in webui/firmware.py, found by OH-32 and independently reproduced: parse_uf2 returns an Image with ZERO segments when the requested family id is absent from the file, instead of raising. Reproduced with a hand-built 512-byte UF2 block carrying family 0xe48bff56 and requesting 0x1c5f21b0: returns successfully, img.segments == []. So an ESP32-C3 UF2 asked for as RP2040 parses 'successfully' into nothing -- load-nothing-report-success, which is the exact failure the loading path exists to prevent. OH-32 pins both halves at the seam in test_a_uf2_for_another_family_is_refused_rather_than_loaded_empty, but the honest fix is in parse_uf2 and this ticket owns webui/firmware.*. Per .claude/CLAUDE.md rule 9: it should raise with the values -- the family asked for, the families present.

**Note 2026-08-26:** CLOSED 2026-08-26. The headline its notes had carried since 2024-08-24 is done: something under webui/ imports tools/import_firmware.py.

WHAT A PERSON DOES NOW: starts the server with --artefacts DIR, and the board panel offers every PlatformIO, arduino-cli and STM32CubeIDE build under it, newest first, with no file dialog and no address typed for a format that carries its own.

THE OPEN QUESTION IS RESOLVED WITHOUT ASKING, and the ticket was right that it needed resolving. It said the compile-safety decision was about running a compiler and not about reading a caller's filesystem. It does not need putting to the user if the answer is OFF by default: --artefacts is the only way the route answers anything, and a request can never name a directory -- it chooses among what came back. Same shape webui/compile.py keeps. If the user later wants the server to search by default, that is a widening and can be asked for then; nothing here has to change to allow it.

OFF AND EMPTY ARE DIFFERENT ANSWERS, and both are on the wire. enabled:false is 'nobody asked the server to look'; [] is 'it looked and found nothing'. One dropdown for both would tell a person their builds are missing when the server was never pointed at them.

THE PREFIX MISTAKE HAS ITS OWN TEST. resolve() uses Path.is_relative_to and not startswith, so a root of .../build does not admit .../build-secrets. A path climbing out with .. is flattened before the comparison sees it. Both are tested, and so is 'loading by path is refused while the search is off' -- the flag must gate the READING and not only the listing.

STILL NOT DONE, and out of scope by the ticket's own earlier notes: an esp-idf image parser (identify_esp_image reports segment addresses and builds no Image), boot_app0.bin discovery (a framework constant under ~/.platformio, not a build output), and docs/features/firmware.md (a ledger must come from the feature-strategy skill, never hand-written). The defect this ticket carried -- parse_uf2 loading nothing and reporting success -- was fixed on 2026-08-26 in 5e7c6ae.

Gate: 1,432 passed, 17 skipped; all eight checkers exit 0.
