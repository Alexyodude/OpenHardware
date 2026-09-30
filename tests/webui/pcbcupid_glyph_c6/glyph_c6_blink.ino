/* OpenHardware - a blink on the PCBCUPID Glyph C6's LED_BUILTIN.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * `LED_BUILTIN` by name: which GPIO it is comes from the pin table the build
 * puts on the include path, and `tests/webui/test_pcbcupid_glyph_c6_board.py`
 * reads which. `glyph_c6_blink.bin` beside this is `webui.compile.build` of
 * this file for that board, and the same test rebuilds it.
 */

void setup() { pinMode(LED_BUILTIN, OUTPUT); }

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(1);
  digitalWrite(LED_BUILTIN, LOW);
  delay(1);
}
