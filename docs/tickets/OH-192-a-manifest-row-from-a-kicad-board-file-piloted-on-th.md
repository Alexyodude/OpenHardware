---
id: OH-192
title: A manifest row from a KiCad board file, piloted on the PCBCUPID Glyph Mini
  RP2040
status: in-progress
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-192-*
- tools/board_manifest.py
- tools/import_pindefs.py
- tools/kicad.py
- tests/rules/test_kicad.py
- tests/rules/test_board_manifest.py
- tests/rules/test_import_pindefs.py
- tests/webui/test_pin_view.py
- webui/boards/PCBCUPID*
- README.md
- PROVENANCE.md
---

Part of OH-174. Every manifest row so far is an EAGLE board. Several open boards whose chips already run here publish only KiCad: the PCBCUPID Glyph Mini RP2040 (`glyph-mini-rp2040.kicad_pcb`, MIT, LICENSE file read by the OH-177 survey), the PCBCUPID Glyph C3 and C6, the Olimex ESP32-C3-DevKit-Lipo and ESP32-C6-EVB, and the SparkFun Thing Plus ESP32-C5. OH-182 made tools/import_board.py read a whole-board `.kicad_pcb` (header footprints by reference, one pad per pad number, pads labelled by net). What stops a KiCad row, per OH-181's and OH-180's notes:

1. `Row` requires an EAGLE schematic, whose connects merge one pin's pads. A `.kicad_pcb` already carries pad numbers and nets, and OH-182 merges one pin's pads without a schematic, so the schematic is optional for a KiCad row.
2. Pins: the Glyph Mini's pads are labelled `/GPIO-n`, which no variant label matches. OH-178 traces an EAGLE board's copper to the chip's pad and reads the datasheet table; do the same for a `.kicad_pcb` (pads, nets and footprints are all in the file), with the RP2040 QFN-56 table OH-181 added. A net name is a cross-check only, as for EAGLE.
3. The composer refuses a KiCad manifest row by name (OH-180). Leave that refusal in place: the model layer for KiCad rows is its own ticket.

Pilot: the Glyph Mini RP2040, whose licence is established. The other KiCad boards' licences are stated in READMEs only (the survey marks them S); adding them is a separate decision, not this ticket's.

Done when the Glyph Mini is a manifest row whose pads trace to its `.kicad_pcb` and whose pins come from the variant and the traced copper, the composer still refuses it by name, and an EAGLE row and the XIAO files are unchanged.

**Note 2026-09-30:** 2026-09-30: in review. Commits a0841e3 (kicad), bd1c3e2 (the shared trace), dca9095 (the row), on lane3 at master 9574bb8.
ROW: `PCBCUPID Glyph Mini RP2040` in tools/board_manifest.py, from glyph-mini-rp2040.kicad_pcb, --select J3 J4 J5, RP2040, arduino-pico variant pcbcupid_glyph_mini_2040, labels (). `Row.schematic` is `str | None`: check() refuses a .kicad_pcb row that names a schematic, and any other row that names none, before anything is read. geometry() passes connects only for an EAGLE row. 23 pads from 46 (a hole and a castellated half-hole per pin), grouped J3/J4/J5, each matched by number and millimetres to its footprint's whole hole placed by kicad.pad_on_board. Licence: the repository's LICENSE reads 'MIT License'.
PINS: the trace, refactored so that both formats share one rule: read_eagle_traced and the new read_kicad_traced each present the board's parts as `_Part` (reference, package, value, one (number, net) per pin) to `_trace`. A KiCad footprint is placed as its footprint name without the library and its value (kicad.Placement gains `value`, read from (property "Value") or (fp_text value); kicad.read_board takes `text=`). KiCad joins pads to pins by number, so one number is one pin and one contact; an unnumbered pad is no pin; one number on two nets is refused. import_pindefs.TRACED_READERS picks the reader by suffix, and a row whose CAD none reads is refused naming it. The net-name cross-check reads PCBCUPID's `GPIO-<n>` as well as `GPIO<n>`/`IO<n>`. The chip is footprint QFN-56-1EP_7x7mm_P0.4mm_EP5.6x5.6mm, value RP2040 (IC1): the row's table is RP2040_QFN56 with that package and value and no footprint_pads, since the footprint numbers its central pad 57 as the page does (tested: 57 at the centroid of 1-56, the 16 unnumbered pads B.Paste on no net). RP2040_QFN56 gains pins 14-18 = GPIO11-15, read off Table 615 on PDF p. 613 of the pinned PDF (sha256 be56fbb7..., checked) by pdftotext, plain and -layout; the vendor's own symbol names the same pin on each IC1 pad (`pinfunction`), which the second-statement test now reads for a KiCad row. The used-rows test groups tables by PDF, and holds rows reading one PDF to one transcription.
RESULT: 20 of 23 pads named, all by the trace alone (chip_pin_from = [pcbcupid-glyph-mini-2040]): /GPIO-0..15 and /GPIO-26..29, each directly on IC1. By the variant: 0. Its preprocessed reading numbers D0-D29 through common.h and no label a pad carries (tested), so the variant is read for the chip check and names no pad. DISPUTED: 0; there is no variant claim to disagree with. GND: no GPIO, IC1 pad 19 = TESTEN; pad 57 = GND. +3V3: no GPIO, IC1 6 pads = IOVDD; 43 ADC_AVDD; 44 VREG_VIN; 48 USB_VDD. /5V: NOT_TRACED (R7 100K to /L_EN, which holds U2 AP2127K-3.3 pad 3 and no pad of the chip). SUPPLY_LABELS gains +3V3 and /5V. Wrong net name refused: /GPIO-3 renamed /GPIO-30 gives "'/GPIO-30' is named for GPIO30 and its copper reaches IC1 pad 5 = GPIO3".
TWINS: 12 of 31; geometry 30, model 29, pins 25, runs 15. Glyph Mini: file, footprint:no source, 20/20, RP2040:no. No run is claimed. The composer still refuses it by name (compose_board_3d.py --board ... --check exits 2, "composition from a .kicad_pcb manifest row is not supported yet"), and import_3d_model's COMPOSED takes .brd rows only. README lists it.
EAGLE UNCHANGED: each EAGLE row's traces (repr of every Traced) and board_report JSON were dumped before and after the refactor: identical by diff -r. `python tools/board_manifest.py` then `python tools/import_pindefs.py --write-boards --write-headers` rewrites every file: the LF-normalised md5 of all 30 existing board files and 9 board modules are the same as before, and git status shows only the new file.
RED ON PURPOSE, 29 mutants, each restored, all red. kicad (4): value never read; property only; fp_text only; text ignored. Reader (11): one pad one pin; unnumbered pad a pin; two nets on a number taken; reference taken from the first; first chip taken; chip by footprint alone; value read from the reference; GPIO-n not read in a name; file left out of a parse error; unread suffix not refused; the KiCad parts given no values. Row (14): KiCad row with a schematic accepted; EAGLE row without one accepted; KiCad geometry given connects; pin 16 as GPIO12; pin 17 as GPIO16; pin 18 left out; the KB2040's P$1 kept; the KB2040's value; J3 not selected; the schematic always wanted; /5V and +3V3 each not a supply; the Glyph's table with 57 twice (red on the once-each test); a second transcription of the PDF (red on the grouping test; the once-each test, run alone as a control, stays green).
SUITE at dca9095: 2 failed, 2369 passed, 37 skipped: the OCP pair (test_import_3d_model), the baseline. All CLAUDE.md checkers, ticket_guard --self-test and check_facts OK.
LEFT: PROVENANCE.md 2d names the two Adafruit ESP32 files and neither the KB2040 nor this board; not edited here. lane2's OH-188 rows will conflict in ROWS, the counts and the row lists; rebase when it lands.
