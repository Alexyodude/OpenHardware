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

**Note 2026-10-13:** 2026-10-13 (lane4): step 4 done (README section 5 and sources.json carry the dated re-check; the 2026-08-29 record is kept as true-then; sources.json gained correction_3, an STM32C5 pcb/schematic/rechecked block with sha256s, all re-fetched: sitemap lists the six xiao_stm32c5_* pages, the zip answers 200 with Content-Length 1559346, local copy sha256 matches). Steps 1 and 2 STOPPED at the licence, for the owner: the zip holds no LICENSE file and the PCB names none, but all six .kicad_sch files carry a LOGO_CC_BY-SA_4.0 symbol (so do the C3, C5, C6, MG24 and nRF54LM20A zips in third_party/seeed-pcb; RP2350 and nRF54L15 have none). The repo records two inconsistent bases for these zips: compose_board_3d.py PCB_CACHE says they 'state no licence at all', and import_pindefs.py Package seeed-pcb says 'OSHW, per Seeed's XIAO series repository' (an MIT repo that holds only the STM32C5 footprint). Neither demonstrably applies to this zip. No board_sources row, no import_pindefs change, no board regeneration made. Inventory TWINS pins stays 37 (before = after; checked). Checks run alone: layering, board_contract, part_schemas, licenses, deltas, banned_symbols, board_claims, ticket_claims, ticket_guard self-test, check_facts, board-sources render --check all OK; test_board_sources + test_inventory 110 passed. No new test (no code changed). LEFT: owner decides the licence, then steps 1-2, then step 3 (waits on OH-226).

**Note 2026-10-13:** 2026-10-13 (lane4) steps 1-2 done, step 3 LEFT. Licence: judgement made on the owner's behalf by the stand-in (coordinator) with an Opus consult -- step 1's 'say so and stop for the owner' is met by a registry row that says none is stated; only the licence question stops for the owner (OH-234), not the steps. Row seeed-xiao-stm32c5 in tools/board_sources.py: https-archive, 1,559,346 bytes, sha256 676070c1...b1b, licence 'none stated' (NONE_STATED), file/quote/notice empty, cite records the LOGO_CC_BY-SA_4.0 symbol on all six .kicad_sch as seen, not a grant (OH-234). Pins: its own Package seeed-xiao-stm32c5 (not the shared seeed-pcb, so the 10 OSHW board files are untouched); board file pindefs licence now 'none stated'. read_seeed_traced gained lead=True (label first in Seeed's STM32 net names, D0{slash}A0{slash}PA0) and _CHIP_PIN_NAME now takes P[A-H] (D8 is on PE2); pin always read from the MCU pad on the net, never the name. Regenerated: only the STM32C5 board file changed. D0-D10, SWDIO, SWCLK = 13 pads named (was 2); D11-D15 given a reason, not asked for (their join to the nets is by position, unread). The symbol-sweep sentence in the board file's assumption is gone (the board no longer reads the symbol library); seeed_symbol is kept, used only by tests. Tests seen to fail: held_to_the_vendors_nets and no_licence_and_says (against the HEAD board file: old reading has 2 pads and MIT); only_with_lead (against HEAD importer: TypeError, no lead); spellings (regex broken back to P[A-D]: PE2 not taken); board_sources row test (against HEAD board_sources: ImportError NONE_STATED; row licence set to OSHW: assert fails). Updated: counts 136->147, 571->582, 63->52, uncovered-board sentence tests. Inventory TWINS pins 37 -> 37 (NOT 38): the pins layer needs every non-supply pad named or specifically reasoned, and 8 are not: CANL, CANH, STM32C5_BOOT, USB_D-, STM32C5_RST, and VOUT_3V3 on pads 12 and 30 (inventory's supply list lacks VOUT_3V3; tools/inventory.py is not claimed here). Checks run alone all OK; test files: import_pindefs 150 passed 1 skipped, board_sources 33/1, inventory 77, board_manifest 67, catalogue 50, board_claims 61, pin_view 45 passed 1 failed (test_a_running_manifest_board_lists_its_own_pads_and_no_xiao_label: riscv32.dll lacks riscv32_map_sampler, identical on the stashed HEAD tree, environmental). LEFT: step 3 (compose, OH-226); the 8 pads' reasons or VOUT_3V3 as a supply for TWINS pins 38; return tools/import_pindefs.py and its tests to OH-172.
