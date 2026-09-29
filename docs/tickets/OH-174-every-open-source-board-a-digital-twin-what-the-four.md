---
id: OH-174
title: 'Every open-source board a digital twin: what the four layers are, and the
  order they are reached in'
status: open
priority: P1
created: '2026-09-29'
touches:
- docs/tickets/OH-174-*
---

The goal is every open-source board as a digital twin. This ticket defines what that means so it can be measured, and orders the work. It edits nothing itself; each slice is its own ticket.

**A board is a twin when four layers hold, each read from the repository rather than claimed:**

1. geometry: its pads come from the vendor's own CAD file, and `source` names that file.
2. model: the 3D view draws the vendor's mesh, or one composed from the vendor's own PCB, not an extruded footprint.
3. pins: every pad that is not a supply names the chip pin it reaches, read from a vendor's board-support package, or says why it cannot.
4. runs: its chip is in `FIRMWARE_VERIFIED`, so a named test has watched a compiled image execute on that chip (rules/board-claims.md).

**"All" is bounded by sources, not boards.** docs/research/board-sources/README.md already argues this: a list of every board rots, a list of who publishes what does not. A board can join when its CAD is published under a licence that lets it be fetched. The pin side is not the constraint: third_party/bsp/ holds 404 arduino-esp32 variants and 151 arduino-pico variants.

**What is on disk today and unused.** The registry (tools/board_sources.py) fetches three sources that were never imported as boards: adafruit-huzzah32, sparkfun-thing-plus-esp32-c6 and olimex-esp32-poe. webui/boards/ holds the Arduino Uno and 25 XIAO files only. `chip_for` in webui/boards/catalogue.py raises for any name not starting `XIAO-` unless it is in `IRREGULAR`, so every non-XIAO board is a hand-written exception today.

**Order.** Boards whose chip already runs come first, because they can reach all four layers. Six chips run: ATmega328P, RP2040, SAMD21, ESP32-C3, ESP32-C5, ESP32-C6. Then boards on chips with no core, which reach three layers and wait for the core.

Slices, each its own ticket:

- a scorecard: the four layers per board, generated, so "all" has a number.
- a board that is not a XIAO footprint is a row in a table, not an exception; the SparkFun Thing Plus ESP32-C6 is the pilot, because every input it needs is already on disk and its chip runs.
- the pilot's 3D model, composed from its EAGLE board file as the Uno's is.
- the other two fetched sources, HUZZAH32 and ESP32-POE.
- new sources for boards whose chip runs.
- discovery at vendor scale: a vendor's published PCB repositories joined to the BSP variants that name the same board.
