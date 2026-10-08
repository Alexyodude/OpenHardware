---
id: OH-209
title: The XIAO RP2350 SMD's BOOT pad says what Seeed's own file shows it reaches
status: in-review
priority: P2
created: '2026-10-08'
touches:
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- webui/boards/XIAO-RP2350-*.json
- webui/boards/rp2350.py
---

Part of OH-174. Since OH-157, XIAO-RP2350-SMD holds geometry, model and runs, and misses pins on one pad: BOOT. Its why_null is the generic one the TWINS pins layer counts as unanswered, because OH-170 found no BOOT net in Seeed's `third_party/seeed-pcb/RP2350.kicad_pcb`, and Seeed's wiki calls BOOT a button, which says nothing about a pin.

The RP2350 samples BOOTSEL on QSPI_SS rather than on a GPIO (RP2350 Datasheet, its boot sequence chapter), so the honest answer for this pad may be a specific reason rather than a chip pin. Find what Seeed's own sources say the BOOT pad reaches: the board file's copper from that pad (trace it with the repository's tracer before concluding there is no net), Seeed's schematic for the XIAO RP2350 if one is published, and the footprint. If the pad reaches QSPI_SS or the flash chip-select, write that as the pad's reason, citing both the board's source and the datasheet section; if it reaches a GPIO, write the chip pin. Do not answer it from the datasheet alone.

Done when XIAO-RP2350-SMD's BOOT pad names a chip pin or a reason specific to that pad, each resting on Seeed's own file, and the board holds all four layers.

**Note 2026-10-08:** In review. BOOT on XIAO-RP2350-SMD now carries a reason specific to it, read from Seeed's own files, and the board holds all four layers.

WHAT SEEED'S FILE SHOWS. The SMD footprint's BOOT is pad 27 of `XIAO-RP2350-SMD.kicad_mod`, at (3.57, -1.27). In `third_party/seeed-pcb/RP2350.kicad_pcb` the module's castellated edge, `MOUDLE14P-XIAO-HALF-HOLE` (U2, at 108.3977, 72.876), stands unturned on the front with its pads 1-14 at the footprint's own x, so the footprint's frame is U2's. In that frame every one of the footprint's underside pads lands on one back-side `Test Point` within 0.01 mm (measured: the next nearest point is 1.99 mm or more away), and every underside pad whose label names a signal (D11-D18, SWDIO, SWDCLK) lands on that signal's net. BOOT lands on TP2 (111.963, 71.603). TP2's net is `/04 RP2350/QSPI_SS`, and on it are exactly: U4 `RP2350-A` pad 60, pinfunction `QSPI_SS` (the footprint names its GPIOs `GPIO0`-`GPIO29` apart from it); U5 `16Mbit` pad 1, pinfunction `/CS` (Description "SMD IC Memory;16Mbit-SPI-..."); R4 `1K`, whose other net `Net-(K1-A0)` holds only K1 (`SKTAAAE010`, Part Type "Button"), whose other two pads are GND; and TP2. So the BOOT button K1 pulls QSPI_SS to ground through 1 kohm, and the BOOT pad is on QSPI_SS directly. The second button, K2, is on `/04 RP2350/RUN`.

SEEED'S SCHEMATIC. `RP2350.zip`, from which the board file was taken byte for byte, also holds `04 RP2350.kicad_sch`. Its column of six names (3V3, BOOT, GND, RUN, SWDCLK, SWDIO) sits beside test points TP1-TP6; pairing each name with the test point to its left and nearest in height puts BOOT on TP2 and the other five on test points whose board-file nets carry those names. So the vendor labels TP2 `BOOT` itself, independently of the position join.

WHY OH-170 MISSED IT. It searched the net names and none is called BOOT. The pad's net is named for what it is, QSPI_SS. "BOOT has no net in RP2350.kicad_pcb" was true of the names and not of the pad.

THE ANSWER WRITTEN. A reason, not a chip pin: QSPI_SS is outside the GPIO0-GPIO29 numbering `chip_pin` uses. `_RP2350_BOOT` in `tools/import_pindefs.py`, wired into `XIAO-RP2350-SMD`'s `reasons=` beside `_RP2350_DEBUG`. Verbatim: "the RP2350's flash chip-select, QSPI_SS, which is outside its GPIO0 through GPIO29 numbering: in Seeed's own RP2350.kicad_pcb this pad lands on the underside test point TP2, whose net '/04 RP2350/QSPI_SS' carries the RP2350's pad 60 'QSPI_SS' and the '/CS' of U5, a 16Mbit SPI memory, and runs through R4 (1K) to the button K1, whose other side is GND; Seeed's schematic in the same RP2350.zip, '04 RP2350.kicad_sch', prints 'BOOT' beside TP2. The RP2350 Datasheet, release 8, section 5.2.8 'BOOTSEL (USB/UART) boot', has the bootrom sample QSPI CSn shortly after reset and enter BOOTSEL if it is driven low, so this pad is that strap and there is no GPIO number for it to have". The datasheet copy read is release 8, sha256 a638d6780da919162660691bfa02c6dcf7c2a0b6e9f18e2d7519c80b664a2e39, outside the tree (CC BY-ND, cited not copied); its 5.2.2 "Check BOOTSEL" step reads "QSPI CSn is low (BOOTSEL button)".

REGENERATED. `--write-boards`: only `webui/boards/XIAO-RP2350-SMD.json` written, its BOOT `why_null`; every other board file unchanged. `--write-headers`: every module unchanged, rp2350.py included.

TEST. `test_the_rp2350_smd_boot_pad_is_the_flash_chip_select_in_seeeds_own_board_file` reads the footprint, the board file and the zip, makes both joins, walks the net, and finds each part in the clause of the reason that names it; the datasheet clause is the one it cannot read. `test_every_pad_either_names_its_pin_or_says_why_it_has_none` moves one pad from generic to specific: 66 -> 67 and 5 -> 4. DELIBERATE BREAKS, both red: (1) `XIAO-RP2350-SMD` wired back to `reasons=_RP2350_DEBUG` alone: "XIAO-RP2350-SMD wires reasons for ['SWDCLK', 'SWDIO'] and none for BOOT ..."; (2) the test run against a scratch copy of the board file, and a zip rebuilt around it, with TP2's pad moved from net 2 `/04 RP2350/QSPI_SS` to net 16 `/04 RP2350/RUN`: red at `('TP2', '/04 RP2350/RUN')`. Both reverted; nothing in the tree was left changed.

COMMIT: ca94d31.

TWINS after: "18 of 37 boards hold all four; by layer: geometry 37, model 29 (7 not built here), pins 34, runs 25" (was 17 and pins 33). XIAO-RP2350-SMD reads `footprint  composed  19+3/22  RP2350` and holds all four; XIAO-RP2350-DIP unchanged at 19/19. VERIFIED in lane3 at ca94d31: the four named files 252 passed, 2 skipped; check_ticket_claims, check_facts and check_board_claims OK; full suite "2 failed, 2478 passed, 39 skipped, 1 warning in 459.40s (0:07:39)", the two failures the OCP pair in tests/rules/test_import_3d_model.py ("No module named 'OCP'"), pytest exit 1 for that reason alone.

FOUND AND NOT TAKEN. The SMD's EN pad (25) lands the same way on TP4, net `/04 RP2350/RUN`, which carries the RP2350's RUN pad and the reset button K2. `SUPPLY_LABELS` lists EN, so the TWINS pins layer does not count it, and it keeps the generic sentence; writing it is outside this ticket. The module's own underside silkscreen also prints `BOOT` and `RST` beside those test points; not relied on.
