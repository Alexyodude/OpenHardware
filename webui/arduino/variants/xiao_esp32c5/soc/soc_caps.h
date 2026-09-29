/* OpenHardware - the ESP-IDF capability names the ESP32-C5 build uses.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * ESP-IDF's per-chip capability header is `soc/soc_caps.h`, which a
 * vendor's `pins_arduino.h` may include. This build has no ESP-IDF, on
 * purpose (see `Arduino.h`), so this header sits on the ESP32-C5 build's
 * include path in its place, and this variant's `oh_board.h` takes the
 * chip's GPIO count from it.
 *
 * It defines what that build uses from it -- in the pin tables it compiles
 * and in `oh_board.h` -- and nothing else. Each value is ESP-IDF v5.5's
 * (docs/esp-idf-reference.md), cited by the file and line it was read
 * from; `tests/webui/test_soc_caps.py` holds the value to the reference by
 * name, the citation to the line that defines it, and the names defined
 * here to the names that build uses.
 */

#pragma once

/* components/soc/esp32c5/include/soc/soc_caps.h:207 */
#define SOC_GPIO_PIN_COUNT 29
