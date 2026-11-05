---
id: OH-275
title: Seeed's nRF52840 variant says LED_STATE_ON (1) while its own initVariant and
  Zephyr treat the LEDs as active low
status: open
priority: P3
created: '2026-11-05'
---

Found 2026-11-05 under OH-64. Seeed-Studio/Adafruit_nRF52_Arduino @ 667f05f, variants/Seeed_XIAO_nRF52840/variant.h says LED_STATE_ON (1); the same variant's initVariant turns the three LEDs off by driving them HIGH, and Zephyr's boards/seeed/xiao_ble/xiao_ble_common.dtsi @ 0a2e408 marks led0-led2 GPIO_ACTIVE_LOW. webui/boards/nrf52840.py reports levels and not lit/dark for exactly this reason, so nothing here is wrong; but the page cannot say 'lit' for the XIAO's LED until one source wins.

Done when: the polarity is settled from something better than either file -- Seeed's schematic for the board, which tools/get_board_sources.py can fetch -- and either the pin view says lit/dark for these three with the schematic cited, or this is closed with the schematic's answer recorded and an upstream issue filed against whichever file is wrong.
