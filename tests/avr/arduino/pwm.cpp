// OpenHardware — a pad the timer owns, beside a pad PORTD owns.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// The counter-example for OH-71, and it exists so that the limitation is
// pinned by a run rather than by an argument. Both pins here are PORTD and
// both are configured as outputs; the difference is who is driving them.
//
// `analogWrite(3, 128)` hands PD3 to timer 2's compare output — measured
// 2026-08-26: `DDRD` 0b00001000, `PORTD` 0b00000000, `TCCR2A` 0b00100001 with
// `COM2B1` set. `webui/boards/atmega328p.py`'s `pin_states` reads `DDRD` then
// `PORTD` and answers `low` about a pin carrying a square wave. `7` is beside
// it to show that the honest answer is still available on the same port: the
// defect is per-pad, not a broken table.
//
// **The binary is not committed**, for the licence reason `blink.cpp` records.
// This one also needs `wiring_analog.c`, which `webui/compile.py`'s Uno recipe
// does not compile — so it cannot be built through the browser at all, which
// is why OH-71 is P3.

#include <Arduino.h>

void setup() {
    pinMode(7, OUTPUT);
    digitalWrite(7, HIGH);

    analogWrite(3, 128);
}

void loop() {}
