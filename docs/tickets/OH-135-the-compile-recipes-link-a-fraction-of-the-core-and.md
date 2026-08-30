---
id: OH-135
title: The compile recipes link a fraction of the core and no libraries at all
status: open
priority: P2
created: '2026-08-30'
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
