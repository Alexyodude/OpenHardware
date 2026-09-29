/* OpenHardware - a blink on the Adafruit QT Py ESP32-C3's SDA.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * `SDA` by name: which GPIO it is comes from the pin table the build puts
 * on the include path, and `tests/webui/test_qtpy_esp32c3_board.py` reads
 * which. `qtpy_blink.bin` beside this is `webui.compile.build` of this
 * file for that board, and the same test rebuilds it.
 */

void setup() { pinMode(SDA, OUTPUT); }

void loop() {
  digitalWrite(SDA, HIGH);
  delay(1);
  digitalWrite(SDA, LOW);
  delay(1);
}
