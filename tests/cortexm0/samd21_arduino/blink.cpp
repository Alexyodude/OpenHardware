// OpenHardware — the stock Arduino Blink, for a XIAO SAMD21.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// The sibling of `tests/avr/arduino/blink.cpp`, and the same three lines, and
// the point is again everything they do NOT say. No vector table, no `main`,
// no clock tree and no pin table: all of that arrives from
// `framework-arduino-samd` and Seeed's own variant at link time, which is what
// makes the result a *vendor* image rather than one this repository wrote.
//
// `tests/cortexm0/test_samd21_arduino.py` compiles it. **The binary is not
// committed**, for the licence reason the AVR sibling gives: linking Arduino's
// core makes the image a derivative of LGPL-2.1 code, and
// `rules/licence-hygiene.md` keeps this repository MIT with no vendored trees.
// The test skips where any of the four pieces is absent, and says which.
//
// ## Why `delay(1)` and not `delay(500)`
//
// Because virtual time here is retired instructions. `SysTick_Config` gives
// this part a 48,000-instruction millisecond, so `delay(500)` is twenty-four
// million steps through a ctypes boundary and `delay(1)` is forty-eight
// thousand. The AVR sibling can afford `delay(500)` because its own arithmetic
// works out to sixteen instructions per microsecond; this one cannot, and the
// period the test asserts is derived either way rather than fitted.
//
// `LED_BUILTIN` rather than a number, because the whole point is that Seeed's
// variant table is what maps it: pin 13, and entry 13 of `g_APinDescription`
// is `{ PORTA, 17 }`. `webui/boards/samd21.py` cites the same two lines for
// `LED_PIN`, and if they ever disagree this test is what says so.

#include <Arduino.h>

void setup() { pinMode(LED_BUILTIN, OUTPUT); }

void loop() {
    digitalWrite(LED_BUILTIN, HIGH);
    delay(1);
    digitalWrite(LED_BUILTIN, LOW);
    delay(1);
}
