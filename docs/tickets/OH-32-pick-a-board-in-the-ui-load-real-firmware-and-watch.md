---
id: OH-32
title: Pick a board in the UI, load real firmware, and watch it run
status: open
priority: P0
created: '2026-08-25'
touches:
- webui/api.py
- tests/webui/test_board_run.py
---

The headline: a person opens the emulator, chooses a development board, points at firmware they built, and the board runs it. Every piece exists separately and none of them meet.

What exists. OH-19 landed target selection driven by which cores are built, and refuses anything not ready rather than accepting-and-disabling. OH-10 landed the format layer (UF2/ELF/HEX/bin -> Image) and artefact discovery over PlatformIO and arduino-cli builds. tests/cortexm0/test_blink.py runs a real compiled image on the RP2040. OH-22 is building the catalogue view.

What is missing is the seam: a load_firmware operation in webui/api.py that takes a board rather than a core, resolves that board to its runtime description, checks the image belongs on that chip, and starts it. Today the emulator is chosen by *core*; a person thinks in boards.

Refuse loudly at the joins, since each is a different failure. A board with no runtime description cannot run anything -- 25 of 26 are in that state. A core that is not built cannot run its boards. And an image built for the wrong chip must be rejected on its own headers, not run until it faults.

Done when a PlatformIO artefact, unmodified, is selected against a board in the UI and executes -- RP2040 first, since it is the only board that can prove it.

Depends on OH-10 (the load path), OH-19 (selection), OH-22 (the catalogue), and the runtime board contract ticket. It claims none of their files; the seam is webui/api.py, which is the layer both transports share.
