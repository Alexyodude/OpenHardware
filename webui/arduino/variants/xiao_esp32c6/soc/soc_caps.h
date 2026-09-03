/* OpenHardware - the one line Seeed's XIAO ESP32-C6 pin table includes.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * `third_party/bsp/arduino-esp32/variants/XIAO_ESP32C6/pins_arduino.h`
 * opens with `#include "soc/soc_caps.h"`, ESP-IDF's per-chip capability
 * header, and then uses NOTHING from it: every line after that include is
 * a `static const uint8_t` or a `#define` of a literal (counted 2026-09-04
 * at revision 2787dab -- zero `SOC_` tokens in the file). The C3's and the
 * C5's tables do not include it at all.
 *
 * This build has no ESP-IDF, on purpose (see `Arduino.h`), so the include
 * would fail on a file whose every fact the build wants. This empty header
 * sits on the variant's include path so the vendor's file is used
 * VERBATIM from its checkout rather than copied here with a line removed.
 * If a future revision of that table starts using a capability macro, the
 * compile error will name it, and this file is where the answer goes.
 */
