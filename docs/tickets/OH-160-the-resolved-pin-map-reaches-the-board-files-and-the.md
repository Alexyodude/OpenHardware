---
id: OH-160
title: The resolved pin map reaches the board files and the board modules, so a XIAO
  pad answers a wire
status: open
priority: P1
created: '2026-09-04'
touches:
- tools/import_pindefs.py
- webui/boards/*.json
- webui/boards/esp32c3.py
- webui/boards/esp32c5.py
- webui/boards/esp32c6.py
- webui/boards/rp2040.py
- tests/rules/test_import_pindefs.py
- tests/riscv32/test_esp32c*_board.py
---

On 25 of 26 boards a pad still refuses a wire, and the answer has been sitting in a report nobody consumes since OH-26.

Measured 2026-09-04:

    webui/boards/*.json          582 pads, 28 carry a `pin` -- all 28 on the Arduino Uno.
                                 Every XIAO file has `pin: null` on every pad, and says
                                 in its own `assumption` field that such a pad "draws and
                                 refuses a wire".
    tools/import_pindefs.py      resolves 321 of 550 XIAO pads from six fetched vendor
    --all --summary              packages (0 disputed; 229 null with a stated reason:
                                 GND, VBUS, 3V3_OUT, EN, SWD, PAD -- not GPIOs).
    webui/api.py (the pad listing) reads `PIN_NAMES` off the board MODULE, not the
                                 JSON, and only atmega328p.py and samd21.py publish one.

So the join OH-26 built is never made. OH-26 left the JSON writes to OH-22, which is done and never made them either, and recorded the one real blocker: on 8 boards (SAMD21, MG24, nRF54L15, nRF54LM20A) 123 resolved pads name a chip pin with no flat integer -- PA02, PC0, P2.08 -- so "the simulator's integer pin" is undefined there and `chip_pin` is the answer. That question was left undecided and this ticket decides it: **the board module's own table is the join**, not the JSON. samd21.py already shows the shape -- a `HEADER` table (label -> the pin the model reads levels through) with `PIN_NAMES` derived from it -- so a label has one meaning in the register read and in the tooltip. What is missing is the same table on the boards that have a description and no HEADER: esp32c3.py, esp32c5.py, esp32c6.py, rp2040.py (a flat GPIO number each), and the label -> GPIO facts already exist in third_party/bsp at a recorded revision (2787dab for arduino-esp32; the C3's D10 = GPIO10, the C6's D10 = GPIO18, the C5's D10 = GPIO10, per OH-156).

For comparison, sim86.com publishes a per-board pin table (its XIAO ESP32-C3 page: D0 -> GPIO2 ... D10 -> GPIO10, "those bus functions are defaults, not fixed wiring") and Xplora3D snaps a wire to a pin by name; neither has more information than this repository already fetched.

STEPS, each checkable:

1. Generate, do not transcribe. Extend tools/import_pindefs.py to EMIT a HEADER table per described board (label -> GPIO number, or -> chip pin string where the vendor has no flat number), with the source file and revision in the generated header, the way the pindefs report already names them. A hand-typed table is the drift CLAUDE.md forbids.
2. Each described board module imports or embeds that table and derives PIN_NAMES from it, as samd21.py does; api.py needs no change.
3. Fill `pin` in the board JSONs from the same generator, so a XIAO pad carries the number its module reads -- and a test asserts JSON pin == module HEADER for every labelled pad, so the two cannot drift. Pads the report leaves null stay null WITH the reason string, not silently.
4. Done when: `import_pindefs.py --all --summary` and the JSON counts agree (generated, both), a wire from a XIAO ESP32-C3 D10 pad reaches GPIO10 in the model (a watched test, the OH-148 shape: the pad's level follows the register), and the 8 no-flat-number boards say in their module which string their pins are and that a wire to them is refused by statement until their core exists.

NOT this ticket: the 229 pads with no GPIO (they are correctly null), and the XIAO-XIAO STM32C5-SMD, which has no board-support package anywhere (0 of 35 pads, OH-26).
