// OpenHardware — the stock Arduino Blink, as a sketch and nothing more.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Three lines, and the point of them is everything they DO NOT say. There is
// no vector table here, no `main`, no timer setup and no pin table: all of
// that arrives from `framework-arduino-avr` at link time, which is what makes
// the resulting image a *vendor* image rather than one this repository wrote.
//
// `tests/avr/test_arduino_sketch.py` compiles it. **The binary is not
// committed**, and that is a licence decision rather than an oversight —
// linking Arduino's core makes the image a derivative of LGPL-2.1 code, and
// `rules/licence-hygiene.md` keeps this repository MIT with no vendored trees.
// The test skips where the framework is absent and says so.

#include <Arduino.h>

void setup() { pinMode(13, OUTPUT); }

void loop() {
    digitalWrite(13, HIGH);
    delay(500);
    digitalWrite(13, LOW);
    delay(500);
}
