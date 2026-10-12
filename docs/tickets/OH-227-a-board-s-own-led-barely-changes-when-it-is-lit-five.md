---
id: OH-227
title: 'A board''s own LED barely changes when it is lit: five levels of green on
  a near-white box, while the pin beside it turns plainly green'
status: in-progress
priority: P2
created: '2026-10-12'
touches:
- webui/static/board3d.js
- tests/webui/test_board_led.py
---

Seen in the page 2026-10-12, Playwright against `python webui/emulator_server.py` on loopback, Release cores, master 9e6e2f8: the Arduino Uno running the page's default sketch (pin 13 blink), its own "L" LED (`led_parts: {"L": "13"}`) lit and unlit, in both themes, stopped by the page's own Run/Stop the moment `/api/board/pins` said pin 13 was high and again when low.

What changes when pin 13 goes high, measured as mean sRGB over the same pixels of device-scale screenshots of the board canvas:

    the LED's body     (211, 210, 203)  ->  (209, 215, 204)    light theme and dark alike
    the LED's cap      (153, 138, 136)  ->  (153, 138, 136)
    pin 13's post      (221, 220, 217)  ->  (113, 207, 145)    (dark theme)

So the board's own LED does not visibly light: five levels of green on a near-white box, nothing on the cap, while the header post beside it turns plainly green. A person watching a blink sees the pin, not the lamp.

The cause, by reading: `webui/static/board3d.js`'s `placeLeds` draws a box over the LED's solid with `color: palette.states.unknown` and `emissive: palette.states.high`, and `lightLeds` sets `emissiveIntensity = PIN_GLOW` when the level is high. The box is the LED's bounding box drawn over the vendor's body, in a near-white, and `PIN_GLOW` was set for a brass post (OH-128/129), not for a lamp. The comment beside it is right that an LED should not glow a colour written down in this file; it does not follow that it should glow almost not at all.

STEPS:
1. Make a lit board LED unmistakable in both themes without writing a colour into board3d.js: e.g. an emissive intensity of its own for lamps, measured the way PIN_GLOW was, and/or the LED's own lens colour from the model (the vendor's or KiCad's LED body carries one) as `parts.js` does for a bench LED.
2. Hold it with a test that runs the page's own code (the node harness OH-215 used) and asserts the lit-minus-unlit difference over the LED's pixels or its material exceeds a stated threshold in both palettes.
3. Look at it in the page in both themes, and say what was seen.

Related: OH-217 is the bench LED part's `LIT_GAIN` (parts.js), a different lens and a different code path.
