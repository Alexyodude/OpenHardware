---
id: OH-135
title: The compile recipes link a fraction of the core and no libraries at all
status: done
priority: P2
created: '2026-08-30'
touches:
- tests/webui/test_compile.py
- webui/compile.py
- tests/avr/test_arduino_sketch.py
---

_No description yet._

CLAIMS NOTHING yet; re-claims webui/compile.py when it starts.

From the 2026-08-30 API/IDE survey; all measured against the installed
toolchain by really building.

  * The Uno recipe names 11 core sources; the framework also ships
    wiring_analog.c, WMath.cpp, WInterrupts.c, Tone.cpp, wiring_shift.c,
    wiring_pulse.c/.S. Measured: map(), random(), analogWrite, analogRead,
    tone(), attachInterrupt, shiftOut, pulseIn ALL fail to link; blink
    builds. 8 of 13 beginner idioms dead.
  * The SAMD21 recipe is missing Tone.cpp, wiring_shift.c, pulse.c and
    pulse_asm.S the same way.
  * NO libraries/ include root at all: Wire.h, SPI.h, EEPROM.h, Servo.h are
    "No such file or directory" on both boards, while the page promises "Type
    an Arduino sketch and build it here".

Closing this makes OH-71's unknown-PWM answer REACHABLE from the IDE, which
that ticket predicted: "a ticket that adds wiring_analog.c to that recipe
makes this reachable and should say so".

DONE WHEN the probed idioms build on both boards, the library roots resolve,
and a test builds an analogWrite sketch through the API and watches pin 3
report unknown -- OH-71's test, finally driven from the front door.

---

**CLOSED 2026-08-30.** All three defects fixed in `webui/compile.py`, each
verified by really building, before and after.

  * **The Uno's seven missing core sources** joined the recipe --
    wiring_analog.c, WMath.cpp, WInterrupts.c, Tone.cpp, wiring_shift.c and
    BOTH halves of wiring_pulse (.c and the cycle-counted .S). Measured: the
    eight dead idioms (map, random, analogWrite, analogRead, tone,
    attachInterrupt, shiftOut, pulseIn) all went "undefined reference" ->
    linked image, and blink still builds.
  * **The SAMD21's four** the same way -- Tone.cpp, wiring_shift.c, and
    pulse's pair, which that core spells pulse.c/pulse_asm.S.
  * **Libraries are a new `Library` row on `Recipe`**: header name, include
    root, sources. A library is compiled ONLY for a sketch that names its
    header (the Arduino IDE's own rule) -- unconditional compilation would
    put Wire's TWI interrupt handler in blink's image, because the vector
    table pulls a handler in whether or not anything calls it. The test
    reads that vector table: blink's TWI slot (0x60, vector 24 per
    iom328p.h) equals its SPM_READY slot -- both `__bad_interrupt` -- and
    the Wire build's does not.
  * The two layouts differ and both rows say so: AVR keeps sources under
    `src/` and Wire needs `utility/twi.c` beside `Wire.cpp`; Seeed's SAMD
    core keeps each library at its own root and its Wire is single-file
    (the bus state machine is the core's own SERCOM.cpp).

**What stays refused, honestly**: `Servo.h` on both boards -- it lives in a
separate arduino-libraries repository and NEITHER framework bundles it, so
there is no row to write; and `EEPROM.h` on the SAMD21, whose silicon has no
EEPROM and whose core ships no such library. Both refusals are the
compiler's own "No such file", asserted as results.

**The promised front-door test exists**:
`test_an_analogwrite_sketch_built_at_the_front_door_reports_unknown` in
tests/webui/test_compile.py builds `analogWrite(3, 128)` through
`compiler.build`, loads it through `api.load_firmware`, and watches pin 3
answer `unknown` while pin 7 on the same port answers `high` -- OH-71's
answer, reachable from the IDE. The `pwm_sketch` fixture's docstring in
tests/avr/test_arduino_sketch.py no longer claims the recipe cannot link
analogWrite; it now says why it still builds by hand (board test vs service
test, the file's own split).

Suites: tests/webui/test_compile.py 24 -> 29 passed;
tests/avr/test_arduino_sketch.py 16 passed. Six mutations, all killed: each
missing-source class re-introduced (Uno wiring_analog.c, SAMD Tone.cpp,
Wire's twi.c), selection made unconditional, selection made never-match, and
the Wire include root de-src'd.
