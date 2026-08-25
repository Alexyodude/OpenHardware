// OpenHardware — the stock Arduino serial "hello", as a sketch and nothing more.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Companion to `blink.cpp`, and the same arrangement: three lines of ours, and
// everything that makes them work -- `HardwareSerial`, `Print`, the ring
// buffer, the vector table -- arriving from `framework-arduino-avr` at link
// time. **The binary is not committed**, for the licence reason `blink.cpp`
// records.
//
// `println` rather than `print`, deliberately: it appends CR LF, so the test
// asserting `b"hello\r\n"` is also asserting that two bytes the sketch never
// mentions arrive in the right order.

#include <Arduino.h>

void setup() {
    Serial.begin(9600);
    Serial.println("hello");
}

void loop() {}
