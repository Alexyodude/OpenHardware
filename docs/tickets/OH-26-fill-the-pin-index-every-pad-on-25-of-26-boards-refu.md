---
id: OH-26
title: 'Fill the pin index: every pad on 25 of 26 boards refuses a wire'
status: open
priority: P0
created: '2026-08-25'
touches:
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
---

Of 582 pads across 26 boards, 28 carry a simulator pin index and all 28 are on Arduino Uno. Every XIAO file states the consequence in its own 'assumption' field: 'A pad with pin null draws and refuses a wire.' This is the largest single gap between the board data that exists and a board you can run code on -- geometry without a pin index is a picture with coordinates.

The mapping from a silkscreen label to an MCU pin is published, just not in the CAD. It lives in board-support packages: an Arduino core's variant.cpp and pins_arduino.h, a Zephyr board .dts, CircuitPython's board module. Extract label -> chip GPIO from those, per board, with the source file named in the output the way 'derivation' already names the footprint.

Three things that will bite. The label is not the GPIO -- XIAO 'D6' is GPIO21 on ESP32-C3 and a different number on RP2040, so the mapping is per board and never per family. A board may appear in several board-support packages that disagree; a disagreement gets recorded, not averaged. And a pad that no board-support package covers stays null, because the current null is honest and a guessed number would wire the circuit wrongly while reporting success.

Done when a XIAO pad accepts a wire, every non-null pin traces to a named vendor file, and the count of resolved pads is generated rather than written down.

Note: writes into webui/boards/*.json, which OH-22 claims wholesale.
