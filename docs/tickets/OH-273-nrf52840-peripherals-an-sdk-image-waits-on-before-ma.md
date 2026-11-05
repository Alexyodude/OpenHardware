---
id: OH-273
title: 'nRF52840 peripherals an SDK image waits on before main: CLOCK, POWER, NVMC,
  FICR/UICR'
status: open
priority: P2
created: '2026-11-05'
---

Found 2026-11-05 under OH-64. webui/boards/nrf52840.py models GPIO OUT, DIR, their SET/CLR windows and PIN_CNF.DIR, and nothing else; the blink image (tests/webui/nrf52840/blink.c) is bare metal for exactly that reason. A Zephyr, nRF5 SDK or Seeed Arduino image starts HFCLK and polls EVENTS_HFCLKSTARTED, reads FICR and UICR, may write NVMC and POWER, and starts RTC1 or a TIMER for its tick, so it spins or stops before main.

Done when: an image built by a vendor's own toolchain for the XIAO nRF52840 -- Seeed's Arduino core's Blink is the obvious one, and needs OH-271 (the FPU) too -- reaches its first LED toggle on the board by name, watched by a named test, with each peripheral register it touches modelled from the nRF52840 PS v1.7 and cited. Needs OH-64.
