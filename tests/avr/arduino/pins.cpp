// OpenHardware — one pin of each of the Uno's three ports, driven.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// The third sketch here, and the same arrangement `blink.cpp` records: three
// lines of ours, everything that makes them work arriving from
// `framework-arduino-avr` at link time, and **the binary not committed**, for
// the licence reason that file states.
//
// ## Why one pin from each port and not one pin
//
// OH-70 made `webui/boards/atmega328p.py` answer for all three ports, and the
// mistake it could most easily have made is a `HEADER` row pointing at the
// wrong port's registers — `A0` reading `DDRD` instead of `DDRC` still looks
// like a working table until something drives both. So this drives `7` (PD7),
// `A0` (PC0) and `13` (PB5), each to a *different* level, and leaves `4` (PD4)
// alone. One pin per port, no two of them agreeing.
//
// `13` is `LOW` rather than `HIGH` on purpose: it is the one pin that already
// worked before OH-70, so a change that broke the old path while adding the
// new one has to show up as `13` reading something other than `low`.
//
// `A4` is the fifth and it is here for a different reason. The Uno's R3 header
// brings PC4 out a second time as `SDA`, so `A4` and `SDA` are two labels on
// one piece of silicon — and a `HEADER` where they had drifted apart would
// still pass every test that drives one of them. Driving `A4` and reading both
// is what makes them one pad rather than two that happen to agree.

#include <Arduino.h>

void setup() {
    pinMode(7, OUTPUT);
    pinMode(A0, OUTPUT);
    pinMode(13, OUTPUT);
    pinMode(A4, OUTPUT);
    pinMode(4, INPUT);

    digitalWrite(7, HIGH);
    digitalWrite(A0, HIGH);
    digitalWrite(13, LOW);
    digitalWrite(A4, HIGH);
}

void loop() {}
