---
id: OH-231
title: 'Seeed now publishes the XIAO STM32C5''s KiCad PCB and schematic: read its
  pins from them and compose it, retiring ''nobody has published this one'''
status: open
priority: P2
created: '2026-10-13'
touches:
- docs/research/board-models/README.md
- docs/research/board-models/sources.json
- webui/boards/XIAO-XIAO STM32C5-SMD.json
- tools/board_sources.py
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- tests/rules/test_board_sources.py
- tools/inventory.py
- tests/rules/test_inventory.py
---

Found by OH-163 step 4's dated re-check of the vendor (2026-10-13). docs/research/board-models/README.md section 5 and sources.json record that on 2026-08-29 (OH-109) Seeed's wiki sitemap had no STM32C5 page, files.seeedstudio.com answered 403, and OSHW-XIAO-Series held only XIAO-STM32C5-SMD.kicad_mod -- "a footprint for a board that appears never to have shipped". tools/import_pindefs.py says the same in its STM32C5 row ("Nobody has published this one. Zephyr has no xiao_stm32c5 board"). None of that is true any more:

- wiki: https://wiki.seeedstudio.com/xiao_stm32c5_getting_started/ (200) and five sibling pages in the sitemap (_pin_multiplexing, _application, _canfd_usage, _with_micropython, _with_stm32cubeide); product page https://www.seeedstudio.com/XIAO-STM32C5-p-7011.html.
- KiCad project: https://files.seeedstudio.com/wiki/XIAO_STM32C5/res/XIAO_STM32C5_v1.0_SCH%26PCB.zip, 1,559,346 bytes, sha256 676070c1e35935869c39a52a624dec7cb937850e6d6e12401b061786aab35b1b -- five .kicad_sch sheets and "XIAO STM32C5.kicad_pcb" (files dated 2026-07-27..31). No STEP.
- schematic PDF: https://files.seeedstudio.com/wiki/XIAO_STM32C5/res/Seeed-Studio-XIAO-STM32C5-v1.0.pdf, 1,397,144 bytes, sha256 6e32a6515372feb5b5c6e16864d37423c9d938b442907b26ea556fc93f35ce21 (no text layer).
- pinout sheet XIAO-STM32C5-pinout_sheet.xlsx (sha256 9fd284fa...) -- an ST pin table with a XIAO column whose rows are misaligned (it puts BAT_EN on PE2; the PCB puts D8/SPI_SCK there and BAT_EN on PA15): not a source.
- Zephyr board: Seeed-Studio/platform-seeedboards zephyr/stm32/boards/seeed/xiao_stm32c5/ at 57250b6f9157a5600eb2b232cc90618b3ed1b3be (2026-10-08), "extracted from schematic 04 XIAO Header&STM32C5.kicad_sch"; MCU STM32C5A3CG, UFQFPN48.

Read from the PCB in scratch (U10 the castellated footprint, U4 the MCU, joined by net name; the Zephyr connector agrees): D0-D3 PA0-PA3, D4 PB7, D5 PB6, D6 PA9, D7 PA10, D8 PE2, D9 PB0, D10 PB15; pads 12-14 VOUT_3V3, GND, VBUS; D11-D15 (FDCAN, CAN_STB) on test pads and the transceiver, not U10 pads; SWDIO PA13, SWCLK PA14 (U4 pads 34, 37). That is a reading to be repeated by a committed tool, not a source to copy.

STEPS:
1. Fetch: a board_sources row for the zip (https-archive, pinned by size and sha256; say how it is fetched, as the Pico's and the Uno's are), with its licence as the zip or the wiki states it -- and if neither states one, say so and stop for the owner rather than assume one.
2. Pins: read the PCB's nets in tools/import_pindefs.py as the other Seeed KiCad XIAOs are read, retire the "Nobody has published this one" row and its reasons, regenerate the board file, and hold it with a test that fails on the old row. Expected TWINS pins 37 -> 38.
3. Model: compose the board from the PCB in tools/compose_board_3d.py (after OH-226 merges), so it draws its copper, silkscreen and parts instead of an extruded footprint. Expected TWINS model 37 -> 38.
4. Correct docs/research/board-models/README.md section 5 and sources.json with this dated re-check, keeping the 2026-08-29 record as what was true then.
Runs stay out of reach: the STM32C5A3CG is a Cortex-M33 (OH-36, blocked on an oracle).

Claims: tools/import_pindefs.py and its tests are OH-172's (open, nobody building), the composer and import_3d_model OH-163's (lent to OH-226): borrow each when its step starts.

**Note 2026-10-13:** 2026-10-13: borrows tools/import_pindefs.py and tests/rules/test_import_pindefs.py from OH-172, and claims tests/rules/test_board_sources.py (unclaimed). Return the first two to OH-172 when this closes.

**Note 2026-10-13:** 2026-10-13: borrows tools/inventory.py from OH-172 and claims tests/rules/test_inventory.py (unclaimed). Return inventory.py to OH-172 when this closes.
