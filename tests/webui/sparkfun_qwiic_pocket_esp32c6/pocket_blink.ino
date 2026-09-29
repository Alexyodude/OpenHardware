/* OpenHardware - a blink on the SparkFun Qwiic Pocket ESP32-C6's MOSI.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * `MOSI` by name: which GPIO it is comes from the pin table the build puts
 * on the include path, and
 * `tests/webui/test_sparkfun_qwiic_pocket_esp32c6_board.py` reads which.
 * `pocket_blink.bin` beside this is `webui.compile.build` of this file for
 * that board, and the same test rebuilds it.
 */

void setup() { pinMode(MOSI, OUTPUT); }

void loop() {
  digitalWrite(MOSI, HIGH);
  delay(1);
  digitalWrite(MOSI, LOW);
  delay(1);
}
