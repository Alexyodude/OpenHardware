/* OpenHardware - the ESP-IDF capability header the ESP32-C3 pin tables include.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * A vendor's `pins_arduino.h` for an ESP32-C3 board may open with
 * `#include "soc/soc_caps.h"`, ESP-IDF's per-chip capability header. This
 * build has no ESP-IDF, on purpose (see `Arduino.h`), so this header sits
 * on the ESP32-C3 build's include path and the vendor's table is used
 * VERBATIM from its checkout rather than copied here with a line removed.
 *
 * It defines what the tables this build compiles use from it, and nothing
 * else. Each value is ESP-IDF v5.5's (docs/esp-idf-reference.md), cited by
 * the file and line it was read from; `tests/webui/test_soc_caps.py` reads
 * that line and holds the value to it, and holds the names defined here to
 * the names those tables use. A table that uses one more fails to compile
 * naming it, and this file is where the answer goes.
 */

/* components/soc/esp32c3/include/soc/soc_caps.h:160 */
#define SOC_GPIO_PIN_COUNT 22
