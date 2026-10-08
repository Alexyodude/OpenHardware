---
id: OH-198
title: A KiCad 5 board file reads, so the Olimex ESP32-C6-EVB and Olimex's older boards
  can be rows
status: in-review
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-198-*
- tools/kicad.py
- tests/rules/test_kicad.py
- tests/rules/kicad5/**
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tools/import_3d_model.py
- tools/board_sources.py
- tests/rules/test_board_sources.py
- tools/board_manifest.py
- tests/rules/test_board_manifest.py
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- webui/boards/Olimex ESP32-C6-EVB.json
- webui/boards/catalogue.py
- tests/webui/test_board_catalogue.py
- tests/rules/test_board_claims.py
- tests/webui/test_pin_view.py
- tests/webui/test_olimex_esp32c6_evb_board.py
- tests/webui/olimex_esp32c6_evb/**
- PROVENANCE.md
- README.md
- rules/board-claims.md
- webui/api.py
---

Part of OH-174, found by OH-194. The Olimex ESP32-C6-EVB stopped before a registry row because its only board file, `HARDWARE/Hardware-revision-A/ESP32-C6-EVB_Rev_A.kicad_pcb`, is KiCad 5: `kicad.read_board` refuses a board that places its parts as `(module ...)` (OH-182 made that refusal name the format). The survey found Olimex is the strongest KiCad source with real variants, and earlier Olimex revisions are KiCad 5 too (OH-182's review).

Read KiCad 5 boards. The differences that matter to this repository are known and finite: `(module ...)` instead of `(footprint ...)`, `(fp_text reference ...)` and `(fp_text value ...)` instead of properties, the pad and net syntax of that version, and layer names. Read them into the same structures `tools/kicad.py` already returns, so import_board, the trace and the composer need no second path. Parse, do not convert with a tool: a converter's output is not the vendor's file.

The OH-194 worker also found a KiCad 7 copy of the same board in the repository's `HARDWARE/Dimensions/` folder (title block rev A, the same 121 footprints and net references plus dimension annotations). Do not use it in place of the board file: it is a drawing derived from the board, and whether it is kept in step is not stated. It can serve as a cross-check that the KiCad 5 reading is right.

Done when the ESP32-C6-EVB's board file reads, its headers import and trace like the other KiCad rows, and a KiCad 5 construct this reader does not handle is refused by name rather than skipped.

**Note 2026-10-08:** 2026-10-08: paused before any code. Its first worker (lane4) was stopped by the operator's park before editing anything. The claims stay so the reader is not edited elsewhere meanwhile: OH-195 (done) calls kicad.py's API and asked that Placement.back/body/mark and pad_on_board's transform keep their meaning. Also waiting here from OH-195: kicad._on_board mirrors an underside footprint's silkscreen while its pads are not mirrored (OH-184's note).

**Note 2026-10-08:** In review: phase 1, the reader, at 7f2f879 (lane4).

WHAT IT DOES. `tools/kicad.py` reads a KiCad 5 board (version 20171130) into the same structures as a KiCad 6+ one, by respelling its tree, not by a second reader: `board_tree(path, text=None)` returns a board's tree as KiCad 6 spells it, and `read_board` reads through it. Respelled: `(module ...)` as `(footprint ...)`; each `gr_arc` and `fp_arc` from KiCad 5's centre, start and sweep (`(start C) (end S) (angle A)`, in its own parser's words "the start keyword actually gives the arc center") to start, mid and end, the end by 5.1's `GetArcEnd`/`RotatePoint`, the mid as KiCad 7's `GetArcMid`, a negative sweep's ends swapped as KiCad 7's `SetArcAngleAndEnd( angle, true )` does, each point rounded to KiCad's nanometre. `_models_of` reads `(at (xyz ...))` as INCHES, x 25.4, in any version, as `PCB_PARSER::parse3DModel` does at 5.1 and at 7.0. The brief's "KiCad 5 writes at in inches, 6+ offset in mm" needed one correction from KiCad's source: KiCad 5's writer writes `(offset ...)` in mm whenever the offset is non-zero and `(at ...)` only for an all-zero one ("fewer file changes"); every `at` in every KiCad 5 file read here is zero. Read alike and left as the vendor wrote them: `fp_text reference`/`value` (`_reference_of`/`_value_of` answer alike for a raw module and a footprint), `(width w)`, pad `(at x y angle)` (position in the part's frame, angle absolute: `parseD_PAD`, `parseMODULE_unchecked` at 5.1), pad nets (bare names keep one backslash; quoted ones double it, and both read as one), canonical layer names.

REFUSED BY NAME (construct, file, version): a `(module ...)` in any version but 20171130 (OH-182's refusal, narrowed); a copper layer a KiCad 5 `(layers ...)` table renames (KiCad 5 writes copper under its user's name, `BOARD::GetLayerName`); an arc not stated as start/end/angle. WHAT A KICAD 5 FILE CANNOT STATE: `dnp`, `exclude_from_bom`, `board_only` (its `attr` takes only `smd` and `virtual`); a hidden model (5.1's `parse3DModel` takes at, offset, scale, rotate only); a castellated pad (pad properties are version 20200104). `attr` is not read by kicad.py and reaches callers as written: KiCad 7 reads `virtual` as exclude_from_pos_files + exclude_from_bom, and the ESP32-PoE's KiCad 5 revisions mark LAN_CON1, the RJ45, `virtual` -- a composer decision for phase 2, not the reader's.

CROSS-CHECK. OLIMEX/ESP32-C6-EVB at 7b66d23cabba3c573a1e63d83363675b5fb74f06: `HARDWARE/Hardware-revision-A/ESP32-C6-EVB_Rev_A.kicad_pcb` (KiCad 5, md5 0d916d5b48e9e70a2d87eaab4a8201e3) against `HARDWARE/Dimensions/ESP32-C6-EVB_DIMM_Rev_A.kicad_pcb` (KiCad 7 20221018, md5 6795eed287f617f4b7cdad0adc0c12bb), fetched to lane4's `.omc/tmp/kicad5/` and not committed. Alike in both readings: every placement (library, position, turn modulo 360 -- KiCad 7 writes 270 as -90 --, side, value, body, pin-1 mark), every pad's kind, shape, size, turn, layers, net and `pad_on_board` position, every model's offset, turn and scale, the outline including its KiCad 5 arcs, silkscreen, tracks, vias, and the counts of what is not drawn. Two differences, neither the reader's: (1) the paste-only apertures on U3 and UEXT1 are numbered `Past`/`past` in the KiCad 5 file and unnumbered in the copy, because KiCad 7's reader clears the number of a pad that may not have one (`PAD::CanHaveNumber`: no copper, or NPTH; pcb_parser.cpp "At some point it was possible to assign a number to aperture pads"); kicad.py reports what the file says. (2) every model path is `${KIPRJMOD}/3d/...` in the board and `${KISYS3DMOD}/...` in the copy; KiCad's reader takes a path verbatim, so the copy was edited and the board is the vendor's statement. `test_the_c6_evbs_*` (five tests) hold all of this; with `OH_KICAD5_BOARDS=.omc/tmp/kicad5`: 5 passed; without, each skips naming the file, the SHA and how to fetch it.

OTHER KICAD 5 FILES, all read: ESP32-PoE revisions B1 to L1 in `third_party/olimex-esp32-poe/` (including E's BackupFiles copy), and ESP32-C3-DevKit-Lipo revisions A and B (OLIMEX/ESP32-C3-DevKit-Lipo at 5d93e79d46cf3b05782d9fe0f95a8a2e1ca6abbe, fetched to `.omc/tmp/kicad5/`). Measured by a scratch script, not a test: front and back pads alike sit on a track end or via of their own net at the rate the KiCad 7 revisions M, M1 and M2 of the same board do; the misses on both are zone-fed GND pads.

FOR PHASE 2. (a) `compose_board_3d.kicad_statements` (that file is OH-163's) walks `parse_sexp`'s tree for `footprint` and returns no statements at all for a KiCad 5 board, silently: it needs `kicad.board_tree(layout)` in place of `kicad.parse_sexp(layout.read_text(...))`. `import_board` and the tracer read through `read_board` and need nothing (`read_geometry` reads the C6-EVB's EXT1: ten pads, each named by its net). (b) the C6-EVB's U3 (ESP32-C6-WROOM-1) carries paste apertures numbered `Past` on no net, and the tracer takes every numbered pad as a pin. (c) whether `virtual` means not fitted.

SEEN, NOT FIXED (KiCad 6+ behaviour, outside this ticket): KiCad 6 and 7 write a hidden model as a bare `hide` (pcb_plugin.cpp at 7.0) and `_models_of` reads only KiCad 8's `(hide yes)`; no KiCad 6 or 7 board on disk hides a model. A KiCad 5.99 nightly's legacy arc in a `(footprint ...)` file (versions to 20210925) is still dropped without a word. OH-184's `_on_board` mirror question stands; KiCad 5 stores a flipped part's graphics already flipped as KiCad 6 does, so the KiCad 5 reading inherits its answer.

VERIFIED. `compose_board_3d.py --check` (miniconda, OCP) byte-identical against HEAD's kicad.py, md5 0d6635718db317b0b2a1bc4cb30158f0 both (a first, cold-cache baseline differed only in `fetch` lines for models it downloaded). The five-file run: 500 passed, 24 skipped; with the real files, 505 passed, 19 skipped. tests/rules/test_compose_board_3d.py under miniconda: 185 passed. Every new test was seen red once under a deliberate break of kicad.py (or, for the version check, of the files it is given). checkall: every row PASS but "the test suites pass", which is the OCP pair. Full suite: 2 failed (test_import_3d_model.py's OCP pair, "No module named 'OCP'" under python 3.14), 2493 passed, 43 skipped.

Next: phase 2, the C6-EVB's registry row, manifest row, board file, header import and trace.

**Note 2026-10-08:** 2026-10-08: phase 1 merged to master by fast-forward at 30e113b; master's full suite 2 failed (the OCP pair), 2493 passed, 43 skipped. Its review (MERGE) left for phase 2: compose_board_3d.kicad_statements finds no statements in a KiCad 5 file (it must read through kicad.board_tree); _models_of reads KiCad 8's (hide yes) but not KiCad 6/7's bare hide or (hide); a KiCad 5.99 nightly file (20201115 to 20210925) still writes arcs the old way and they are dropped silently; (attr virtual) is not respelled as KiCad 7 reads it (exclude from position files and BOM); a zero-angle fp_arc is kept where KiCad 5.1 drops it; and two transforms (inches, unmirrored back pads) rest only on hand-written tests. Phase 2 claims the composer (lent from OH-163), the registry, the manifest, the pin importer, the board file, the run-evidence files and the docs a new board row touches.

**Note 2026-10-08:** In review: phase 2, lane4 on master 20cdfe8, five slices, each verified before the next. The Olimex ESP32-C6-EVB holds all four TWINS layers: "file composed 5+1/6 ESP32-C6 Olimex ESP32-C6-EVB".



SLICE 1, registry (3a7b446). olimex-esp32-c6-evb: OLIMEX/ESP32-C6-EVB read at 7b66d23cabba3c573a1e63d83363675b5fb74f06, the head on 2026-10-08, recorded in the row's comment and cite (the fetch takes the head); revision A, the only one HARDWARE/ publishes ("initial release"). Fetches revision A's .kicad_pcb and README.md; every other path skipped with a reason. LICENCE, graded as the C3 Lipo's: CERN-OHL-1.2, evidence stated, README.md "Hardware is released under CERN OHL v1.2 license"; HARDWARE/README.md says the same; Hardware-License-CERN_OHL_v_1_2.pdf, opened, is the licence's own text and names no work; LICENSE is the GPL-3.0 the README gives the software. Its obligations are recorded as found in PROVENANCE 2g (3.1: keep the notices and include a copy; 3.4: mark modified Documentation with the date and what changed, make it available, license it under the CERN OHL) and NOT decided: whether a board file written from the design is modified Documentation is the owner's call before anything is published. New test: a layout cell naming a KiCad version is held to the fetched file's own (version ...).



SLICE 2, manifest (a9fc000). Header EXT1 (HN1x10), the one through-hole header on the module's GPIOs; UEXT1 and UEXT2 are surface-mount, which import_board does not read as a header. Variant esp32c6-evb, no labels. U3 is OLIMEX_Cases-FP:ESP32-C6-WROOM-1-xx-UNIVERSAL_MODULE valued ESP32-C6-WROOM-1-N4; its table ESP32_C6_WROOM_1_OLIMEX replaces the cited ESP32_C6_WROOM_1 (ESP32-C6-WROOM-1 & WROOM-1U Datasheet v1.4, pp. 10-11, 3.2 and Table 3-1; the PDF re-downloaded today, sha256 163020762f..., identical) with the rows EXT1 reaches: pins 8, 10, 15, 24, 25 = GPIO0, 8, 9, 17, 16. EXT1: 1 +5V, 2 +3.3V and 3, 10 GND (supplies); 4 /ESP_EN -> U3 pad 3 = EN; 5 /GPIO0, 6 /GPIO8\USER_LED1, 7 /GPIO9\BUT1, 8 /GPIO16\U0TXD, 9 /GPIO17\U0RXD, each that GPIO by the trace. U3's eight paste apertures numbered Past (F.Paste only, no net): the KiCad tracer now numbers pads as KiCad does, none on an aperture or an unplated hole (PAD::CanHaveNumber at 7.0.0, whose reader clears such a number). Every other board file regenerates byte for byte. The second-statement test reads the part after Olimex's backslash and walks kicad.board_tree; a KiCad 5 pad has no pinfunction, so there the net's own name is the second statement. This commit alone left five composer tests failing (the new row is a composition with no tables yet); slice 4 restores them.



SLICE 3, runs (34e8eee). evb_blink.bin, 206 bytes, a LED_BUILTIN blink built for the board by name against esp32c6-evb, rebuilt byte for byte, drives GPIO8 on /GPIO8\USER_LED1: high 38, low 24063, high 48094, low 72119, high 96150. LED_BUILTIN in the siblings: Feather 15, XIAO 15, Qwiic Pocket 23, Glyph C6 14 -- never enabled or driven, and none a pad of EXT1, so a build against any moves no pad here; the Thing Plus C6's numbers none (an RGB LED past the GPIO count) and the sketch built for it is refused. Not SDA: GPIO6, the Thing Plus C6's SDA, on a net that reaches only the SMD UEXT connectors. Not TX: 16, the XIAO's. BOARD_FIRMWARE_VERIFIED holds it; check_board_claims OK, 19 claims; board-claims 13 names it.



SLICE 4, composition (cf66216). kicad_statements reads through kicad.board_tree: walked as written the KiCad 5 file places no footprint and stated nothing (every passive refused); it now states its 118 references as the KiCad 7 copy does. Colour BOARD_MASK, A JUDGEMENT, its source saying a KiCad 5 file has no stackup and states no layer colour (KiCad 5.1's writer and parser never mention one); thickness 1.6 (MANIFEST_THICKNESS_MM; (general (thickness 1.6)) agrees). Kind as the KiCad rows' rule: 38 passives drawn, all by the reference's letters. FITTING: (attr virtual) is NOT read as not fitted -- KiCad 5.1 reads it only to skip a part in the position file, MOD_VIRTUAL is "created by copper shapes on board", KiCad 7's exclude_from_bom is its own translation, and the ESP32-PoE's KiCad 5 revisions B1 to I mark LAN_CON1, the RJ45, virtual; no virtual part is on the C6-EVB. NA, Olimex's not assembled, IS read as not fitted (NOT_ASSEMBLED: leading word, any part, capitals only), cited from the ESP32-PoE's own Revision-changes.txt ("R16(NA(10k/R0402)) added just in case"); that the C6-EVB means the same is A JUDGEMENT. Rows: R_0603_5MIL_DWS, R_1206_5MIL_DWS, SMA-KA (KiCad's D_SMA stands for Olimex's DO-214AC_SMA), SM10B-SRSS-TB (KiCad's model of the same JST part stands for Olimex's); KiCad's 0603 LED now stands for Olimex's LED_0603_R too. DRAWN 66. REFUSED by ABSENT, 27 over 14 packages: U3 (value, land and Table 3-1 say C6-WROOM-1, its footprint places a model named for the ESP32-WROOM-32D: two statements, and drawing Espressif's would choose), REL1-4 (RAS-0515 against a TE ORWH model; KiCad's Relay_THT holds neither), IN1-4 and CON1-4 (DG306-5.0; KiCad's four TerminalBlock libraries hold none named DG306), PWR1 (land YDJ-1136, value YDJ-1134, model CUI PJ-102AH), OPT1-4 (rows 8.89 mm apart; KiCad's SMDIP-4 rows are 7.62, 9.53 and 11.48 wide), C1 (value 13 mm tall, land and model 16), C6 (value 6.0 mm across, land and model 6.3), L1 (DBS135/PD3316 and an AX97 model; none in Inductor_SMD), U1 (ESOIC-8, exposed pad 2.60 x 3.50; KiCad's two SOIC-8-1EP are 2.29 x 3.00 and 2.41 x 3.81), and the lands the Lipo shares, L2 (CD32), UEXT1, USB-OTG1, BUT1 and RST1, whose reasons now speak of both boards. REFUSED by NA, 8: R9, R10, R18, R33, R34, EXT1, ESP-PROG1, PWR2. BODYLESS 9: FID1-3, MH1-4, 3.3V_E1, GND1. Padless ink 11. Unexplained 0. BEFORE/AFTER --check (miniconda, every board): md5 a7f4beefdd39abcea34a75263a9d5581 before the first composer edit, 20f1b55f686fdb04d888bd042dc03918 after slices 4 and 5; identical but the Lipo's seven printed ABSENT lines, whose shared reasons were reworded for both boards, and the C6-EVB's own section.



SLICE 5, reader edges (ea11208, fa25075). A model is hidden by a bare hide (KiCad 6 and 7 write it so), (hide), (hide yes) or (hide true) (KiCad 8's reader), and shown by (hide no); a path named hide is not a flag. Every arc of a file up to version 20210925 (LEGACY_ARC_FORMATTING at 7.0.0) is respelled from centre, start and sweep as KiCad 7 reads it; after it, an arc with no mid is refused by name (KiCad errors; this dropped it). An arc of zero or NaN sweep is refused by name (KiCad 5.1.6+ drops such an fp_arc). pad_on_board is held by real copper on a KiCad 5 board: all twenty back-side EXT1/EXT2 pads of each of the ESP32-PoE's thirteen KiCad 5 files sit on a track end or via of their own net; mirrored, they miss by up to 22.86 mm. Every .kicad_pcb on this disk (36) reads to the same Board, hashed before and after; none hides a model the KiCad 6/7 way, so no board changed.



RED ON PURPOSE, each restored and checked by sha256: slice 1, the C6-EVB's layout cell naming 20221018; slice 2, the name check not splitting a backslash, the committed GPIO8 pad given chip_index 18, the one-net check counting an aperture's number, _numbered numbering an aperture, a committed net renamed /GPIO19\BUT1; slice 3, the sketch's delay doubled, the sketch numbering GPIO8 itself, the image swapped for the Glyph C6's, the LED pad's chip_index moved, a sibling's GPIO15 made an EXT1 pad, the catalogue entry removed, the entry naming another board's test; slice 4, kicad_statements walking the file as written (three tests), NA never read, NA read in any case, NA read as any word's start, NA never read for the C6-EVB's refusals, virtual read as not fitted, the KiCad 5 colour branch removed, the 1206 row lost, the red LED's stands_for dropped, U3's ABSENT key misspelled; slice 5, a bare hide unread, (hide) unread, a path read as the flag, 20210925 not legacy, only KiCad 5's arcs respelled, the no-mid refusal removed, a zero sweep read, a NaN sweep read, a back-side pad mirrored.



FINDINGS, not fixed here. (1) The SMA row turned a quarter composes with every composer check passing: on a two-pad land whose pads span 5 mm the span check's 3 mm tolerance and silk_miss's centre comparison cannot see a quarter turn, so a two-pad part's turn rests on its row alone (each such placement is on the printed turn line). (2) tools/model_from_datasheet.py (OH-163's) walks (footprint ...) itself and cannot open a KiCad 5 board; the composer test's slab sweep now treats a KiCad 5 layout as it treats an EAGLE one. (3) U3 is refused, not drawn: drawing Espressif's C6-WROOM-1 there would need a ruling that a model of one module may stand for a footprint placing another's.



TWINS in lane4, models composed with miniconda: "26 of 38 boards hold all four; by layer: geometry 38, model 37, pins 35, runs 26".


VERIFIED. The ten named rule and webui files under python 3.14: 692 passed, 25 skipped; with OH_KICAD5_BOARDS pointing at the KiCad 7 copy, 698 passed, 19 skipped. Composer and importer rule files under miniconda: 249 passed, 1 skipped. checkall: every row PASS but "the test suites pass", which is the OCP pair. Full suite: "2 failed, 2510 passed, 44 skipped in 471.79s (0:07:51)" -- test_import_3d_model.py's test_a_part_that_names_a_lens_it_has_lost_still_refuses_to_convert and test_the_tessellator_welds_what_it_meshes, "No module named 'OCP'" under python 3.14, as before.
