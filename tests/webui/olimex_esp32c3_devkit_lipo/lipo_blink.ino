/* OpenHardware - a blink on the Olimex ESP32-C3-DevKit-Lipo's LED_BUILTIN.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * `LED_BUILTIN` by name: which GPIO it is comes from the pin table the build
 * puts on the include path, and
 * `tests/webui/test_olimex_esp32c3_devkit_lipo_board.py` reads which.
 * `lipo_blink.bin` beside this is `webui.compile.build` of this file for that
 * board, and the same test rebuilds it.
 */

void setup() { pinMode(LED_BUILTIN, OUTPUT); }

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(1);
  digitalWrite(LED_BUILTIN, LOW);
  delay(1);
}
