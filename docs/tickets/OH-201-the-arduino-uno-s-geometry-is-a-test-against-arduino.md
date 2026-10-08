---
id: OH-201
title: The Arduino Uno's geometry is a test against Arduino's board file, not a dated
  sentence, and its source names that file
status: in-progress
priority: P2
created: '2026-10-08'
touches:
- webui/boards/Arduino Uno.json
- tests/rules/test_uno_geometry.py
---

Part of OH-174. The Arduino Uno holds three of the four TWINS layers -- a model composed from Arduino's own board file, 22 of 22 pins, and a run -- and misses geometry, because `webui/boards/Arduino Uno.json` records no `source` (`tools/inventory.py` prints `none`).

Its pads are not unchecked. They are in artwork space on purpose, because they are painted over `share/boards/Arduino Uno/board.svg`, and the board file's `derivation` says they were CHECKED on 2026-08-27 against `UNO-TH_Rev3e.brd` read by `tools/import_board.py` from the elements IOH, IOL, POWER and AD: all 32 pads pair by row and order, a residual of median 0.005 mm and worst 0.008 mm after one fitted scale and offset, and every label agrees with the net its pad sits on. Its `assumption` also records a 0.41% anisotropy between the artwork's two axes.

That check is a sentence. Nothing re-runs it, so it is exactly the kind of claim this repository keeps catching out of date. Adding `source.file` alone would flip the scorecard on the strength of that sentence, which is the thing not to do.

Make the check a test that reads the vendor's `.brd` through `tools/import_board.py` and asserts what the derivation says: the pairing by row and order, the fit and its residual bound, the anisotropy, and every label against its pad's net. The test skips naming the path and `python tools/get_board_sources.py arduino-uno` when the file is absent, and is seen to fail once (move one pad, swap two labels). Then record `source` on the board file naming that `.brd` inside the registry's `arduino-uno` tree, with its vendor and licence as `tools/board_sources.py` states them, and cut from `derivation` and `assumption` whatever the test now holds, pointing at the test instead. The coordinates stay in artwork space: they must land on the drawing they are painted over.

Done when the Uno's geometry layer reads `file`, a test fails if the artwork pads and the vendor's board file stop agreeing, and the board file no longer carries a dated sentence in place of that test.
