---
id: OH-185
title: The SparkFun Thing Plus ESP32-C6 and QT Py ESP32-C3 build against their own
  variants and run as themselves
status: open
priority: P1
created: '2026-09-29'
touches:
- docs/tickets/OH-185-*
---

Part of OH-174. The SparkFun Thing Plus ESP32-C6 and the Adafruit QT Py ESP32-C3 hold geometry and pins, and OH-180 composes their models, but neither builds against its own variant, so neither can hold the runs layer. OH-179 and OH-183 measured why, by asking the compiler:

    SparkFun Thing Plus ESP32-C6   variants/sparkfun_esp32c6_thing_plus/pins_arduino.h uses SOC_GPIO_PIN_COUNT, which nothing on the build's include path defines
    Adafruit QT Py ESP32-C3        variants/adafruit_qtpy_esp32c3/pins_arduino.h includes soc/soc_caps.h, absent from the C3 build's include path, and also uses SOC_GPIO_PIN_COUNT

Both definitions belong to Espressif's SoC headers. docs/esp-idf-reference.md says how this repository reads them (the ESP-IDF v5.5 reference checkout) and holds the C3 numbers to the tree already used. Read each value from `components/soc/<chip>/include/soc/soc_caps.h` at that revision, cite file and line, and add only what the two variants need. `webui/arduino/variants/xiao_esp32c6/soc/soc_caps.h` is the existing stub, whose comment speaks only of Seeed's table (OH-179 noted this); the C3 build has no such file.

Then give each board its own run evidence the way OH-179 did for the Feather: a test compiles a sketch for that board against its own variant, runs it, and watches a GPIO the variant names change level through the board's own pad. Both variants define LED_BUILTIN as SOC_GPIO_PIN_COUNT plus an RGB pin, which matches no pad (OH-183), so pick a pin the variant names that a pad carries.

The XIAO builds must not change: same recipe, commands and image bytes for every board that builds today.

Done when both boards build, each has a BOARD_FIRMWARE_VERIFIED entry whose test check_board_claims accepts, the XIAO images are byte-identical, and TWINS shows both boards' runs cells holding.

webui/arduino/** is OH-161's and is lent to this ticket for its duration.
