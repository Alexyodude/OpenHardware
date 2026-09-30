/* OpenHardware - a blink on the SparkFun Thing Plus ESP32-C5's MOSI.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * `MOSI` by name: which GPIO it is comes from the pin table the build puts
 * on the include path, and `tests/webui/test_sparkfun_esp32c5_board.py`
 * reads which. `sparkfun_c5_blink.bin` beside this is `webui.compile.build`
 * of this file for that board, and the same test rebuilds it.
 */

void setup() { pinMode(MOSI, OUTPUT); }

void loop() {
  digitalWrite(MOSI, HIGH);
  delay(1);
  digitalWrite(MOSI, LOW);
  delay(1);
}
