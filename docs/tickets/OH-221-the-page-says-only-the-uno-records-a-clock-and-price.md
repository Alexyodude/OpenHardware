---
id: OH-221
title: The page says only the Uno records a clock, and prices delay(500) without the
  ESP32 boards OH-161 gave one
status: open
priority: P3
created: '2026-10-09'
touches:
- webui/static/clock.js
- webui/static/emulator.js
---

Found by OH-161's delay() review (2026-10-09). Two comments in the page say only the ATmega328P records a nominal clock, which stopped being true when OH-161 step 2 gave `webui/boards/esp32c3.py`, `esp32c5.py` and `esp32c6.py` a cited `CPU_HZ`: `webui/static/clock.js` ~54 ("only the ATmega328P records a nominal clock (`F_CPU_HZ`, ...)") and `webui/static/emulator.js` ~876-878. Their worked `delay(500)` costs name the Uno and the SAMD21 only; since OH-161 moved delay() onto the SYSTIMER, an ESP32's delay(500) is 80,000,000 instructions at 160 MHz (120,000,000 on the C5's 240 MHz).

STEPS:
1. Correct both comments to say which boards record a clock and where, read from the board modules rather than listed by hand if the comment can point at the source instead.
2. Add the ESP32's delay(500) to the worked costs with a rate measured on the core the page actually runs (see the build-type ticket filed alongside this: the cores build Debug on Windows today, so a rate taken now would be the Debug core's and should say so or wait).
3. Decide, and say in the page, whether "N steps/s" beside the button is enough for a board whose default Blink takes tens of seconds per half period, or whether the page should also say how far behind real time that is now that these boards have a cited clock. clock.js's header refused "1/29 of a real SAMD21" because the SAMD21's 48 MHz was not recorded; for the ESP32 boards it now is.
