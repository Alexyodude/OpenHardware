---
id: OH-174
title: 'Every open-source board a digital twin: what the four layers are, and the
  order they are reached in'
status: in-progress
priority: P1
owner: oh-174-worktree
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

**Note 2026-11-05:** Every slice is now a ticket; this ticket edits nothing itself, as its body says, so it closes as the definition and the order, and OH-248 and OH-249 hold what is left. SLICE TO TICKET (each board's adding commit read from git log --diff-filter=A on its webui/boards/ file): (1) scorecard: OH-175, done; tools/inventory.py's TWINS section scores every board on the four layers. (2) a non-XIAO board is a row, not an exception, piloted on the SparkFun Thing Plus ESP32-C6: OH-176, done; tools/board_manifest.py, and IRREGULAR in webui/boards/catalogue.py is now refused for a name that has a row. (3) the pilot's 3D model from its EAGLE board file: OH-180, done. (4) the other two fetched sources, HUZZAH32 and ESP32-POE: no ticket until now; filed as OH-248. Both are on disk with their variants (arduino-esp32 feather_esp32 and esp32-poe), both are the classic ESP32, which has no core, so they reach three layers; the HUZZAH32's CC BY-SA 3.0 licence is the first thing it decides. (5) new sources for boards whose chip runs: OH-177 (QT Py ESP32-C3, Feather ESP32-C6), OH-181 (KB2040), OH-188 (Pro Micro ESP32-C3, Qwiic Pocket ESP32-C6), OH-192 (Glyph Mini RP2040), OH-194 (Glyph C3 and C6, Olimex ESP32-C3-DevKit-Lipo, Thing Plus ESP32-C5), OH-198 (Olimex ESP32-C6-EVB), all done, with OH-182 and OH-198 making KiCad board files read. (6) discovery at vendor scale: no ticket until now; filed as OH-249. STALE IN THE BODY, left as written because it is the record of 2026-09-29: seven chips run now, not six (RP2350, OH-157; catalogue.FIRMWARE_VERIFIED), and IRREGULAR no longer makes every non-XIAO board an exception. THE NUMBER: python tools/inventory.py in this worktree prints 0 of 38 boards holding all four, pins 38 and runs 26, because geometry and model need the vendor trees and meshes fetched (third_party/ is git-ignored and this worktree has fetched none); the count of 'all' is that section run in a fetched checkout, and it is not written here, per CLAUDE.md.

**Note 2026-11-05:** Verification 2026-11-05 (oh-174 worktree, no third_party fetched): docs only, so no failing-first test applies. check_board_claims OK, check_facts OK, tests/rules/test_tickets.py + test_ticket_hooks.py + test_board_claims.py 104 passed. checkall: 'FAILED: no two tickets claim one file, the test suites pass'. The claims row diffs against the stale local master and names every ticket file changed upstream since; against origin/master it names only OH-248 and OH-249, which are filed under their own ids, so each commit is checked and pushed under its own OH_TICKET. The suite row's deterministic failures are five in tests/rules/test_compose_board_3d.py that fail rather than skip with third_party unfetched, filed as OH-250; the others in that run did not recur with a private --basetemp.
