/* OpenHardware - the ESP-IDF capability names the ESP32-C6 build uses.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * A vendor's `pins_arduino.h` for an ESP32-C6 board may open with
 * `#include "soc/soc_caps.h"`, ESP-IDF's per-chip capability header. This
 * build has no ESP-IDF, on purpose (see `Arduino.h`), so this header sits
 * on the ESP32-C6 build's include path and the vendor's table is used
 * VERBATIM from its checkout rather than copied here with a line removed;
 * this variant's `oh_board.h` takes the chip's GPIO count from it too.
 *
 * It defines what that build uses from it -- in the pin tables it compiles
 * and in `oh_board.h` -- and nothing else. Each value is ESP-IDF v5.5's
 * (docs/esp-idf-reference.md), cited by the file and line it was read
 * from; `tests/webui/test_soc_caps.py` holds the value to the reference by
 * name, the citation to the line that defines it, and the names defined
 * here to the names that build uses. A table that uses one more fails to
 * compile naming it, and this file is where the answer goes.
 */

#pragma once

/* components/soc/esp32c6/include/soc/soc_caps.h:188 */
#define SOC_GPIO_PIN_COUNT 31
