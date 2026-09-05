---
id: OH-169
title: A board's own LED never lights in the 3D view, however hard the program blinks
  it
status: done
priority: P1
created: '2026-09-05'
touches:
- webui/boards/atmega328p.py
- webui/api.py
- webui/static/board3d.js
- tests/webui/test_pin_view.py
- tests/webui/test_board3d.py
---

A board's own LED never lights, however hard the program blinks it.

Reported 2026-09-05: the LED does not update in real time in the 3D view. It does not update at all. The levels are live and correct -- a compiled blink on a XIAO SAMD21 gives `HllllllHHHHHHllllllHHHHHHHllllllHHHHHHll` over forty samples, and an Uno toggles pin 13 the same way -- and `setLevels` recolours every PAD and re-solves the bench circuit on every poll. What it does not do is light the LED printed on the board itself, because `board3d.js` has no LED handling of any kind: a board's own components are one merged mesh, and the only things it recolours are the pad posts.

**A user LED is a pin and not a pad** (`test_the_xiaos_led_is_a_pin_and_not_a_pad`), so it has a state and no coordinate, and the one place it appears is the table.

WHAT CAN BE DONE HONESTLY, measured 2026-09-05 across all 26 boards. A board needs three things: a module that reads levels, a user LED, and that LED drawn in its 3D model.

  Arduino Uno          levels yes   LED `L` drawn   -> can be lit
  XIAO SAMD21 x2       levels yes   no LED in the model at all
  XIAO ESP32-C3 x3     levels yes   only `CHG0`, a charge LED
  XIAO ESP32-C5 x2     levels yes   `D3` and `D4`, neither identified
  XIAO ESP32-C6 x2     levels yes   `CHG1` and `D4`, neither identified
  XIAO RP2040 x2       levels yes   no LED in the model at all
  the other fourteen   no module, so no level to light one with

So this ticket is the Arduino Uno and says so. The C3 is not an omission: `webui/boards/esp32c3.py` records, measured, that this board has no user LED and that its own fixture watches a GPIO register instead.

**The Uno's LED is identified from Arduino's own board file and not from knowledge.** `third_party/arduino-uno/UNO-TH_Rev3e.brd`, five hops:

  ZU4 pad 19   the ATmega328P's PB5, which is digital 13
    -> net `SCK`      also reaching ICSP.3, IOH.6 and a test point named `TP_13`
    -> U5 pad 5       the LMV358's input; Arduino buffers this pin so the LED
                      does not load it
  U5 pads 6,7
    -> net `L13`      and a test point named `TP_LCMD`
    -> RN2 pad 8      a resistor network
  RN2 pad 1
    -> net `N$1`      -> `L` pad A, the LED's anode; `L` pad C is on GND

Two of those net names, `L13` and `TP_13`, state the pin number in the vendor's own file. The component `L` is drawn -- the composed model lists `L (LED_0805_2012Metric)` -- and its box is stated: min [-13.833, 1.6, -16.494], max [-12.583, 2.7, -14.494], 1.25 x 1.1 x 2.0 mm.

The board also carries `ON`, `RX` and `TX`, which is exactly why this had to be traced: three of the four LEDs on an Uno are not the user's, and lighting the wrong one would be a picture that lies while reporting success.

STEPS:

1. The board module states it, the way `PIN_NAMES` and `SUPPLY` are already stated: `LED_PARTS`, mapping the mesh component's name to the header label that drives it, with the trace above beside it. `webui/api.py` publishes it by `getattr` like `SUPPLY`, so nothing in the API learns what an LED is.

2. `board3d.js` draws a glow at that component's own box, from `view.solids`, which already carries every component's name and bounds in the model's frame. Lit from the same pad state the table reads, in `setLevels`, so the picture cannot disagree with the table. Test: the panel reads `led_parts` and the glow's intensity follows the pin.

3. It must go dark for every state that is not `high` -- `low`, `input` and `unknown` -- and `unknown` matters most: a board picked and not loaded must not sit there glowing, which is OH-164's mistake in a different medium.

4. A board with no `LED_PARTS`, or one whose named component is not in the model, draws nothing and says nothing. Twenty-five of twenty-six boards are in that case on the day this is written, so it is the ordinary path and not the error path.

NOT in scope, recorded so the next session does not re-derive it: the SAMD21 and RP2040 have a user LED in the module and no LED component in their 3D models, so they need the composer to identify one before anything can light it. The C5 and C6 have LED components nobody has traced to a pin. Each is a board-file trace like the one above, and none of them is this ticket.

**Note 2026-09-05:** Done 2026-09-05 for the Arduino Uno, which the ticket says is the only board that can be. Found on the way and NOT fixed, because it is not this change: view.solids are stated in the model's own frame -- board3d.js says so at its own field -- and boardSolid only puts them through matrixWorld when solid.local is set, which tools/compose_board_3d.py never emits. So every component box a wire collides with is used untransformed. view.slab sets local: true and is correct; the components beside it are not. The LED glow does not depend on it, being parented to the model group and using the local coordinates directly.
