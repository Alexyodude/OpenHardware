---
id: OH-188
title: 'Two more ESP32 boards through the manifest path end to end: SparkFun Pro Micro
  ESP32-C3 and Qwiic Pocket ESP32-C6'
status: in-review
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-188-*
- tools/board_sources.py
- tools/board_manifest.py
- webui/boards/SparkFun Pro Micro ESP32-C3.json
- webui/boards/SparkFun Qwiic Pocket ESP32-C6.json
- README.md
- tests/rules/test_board_manifest.py
- tests/rules/test_board_sources.py
- webui/boards/catalogue.py
- tests/webui/test_board_catalogue.py
- tests/webui/test_sparkfun_pro_micro_esp32c3_board.py
- tests/webui/sparkfun_pro_micro_esp32c3/**
- tests/webui/test_sparkfun_qwiic_pocket_esp32c6_board.py
- tests/webui/sparkfun_qwiic_pocket_esp32c6/**
- tests/rules/test_import_pindefs.py
- tests/webui/test_pin_view.py
- PROVENANCE.md
- tests/rules/test_board_claims.py
- rules/board-claims.md
---

Part of OH-174. Three boards now hold all four layers through the manifest path (OH-176 to OH-185): a row, pins from the variant and the traced copper, a composed model, and a run test compiled against the board's own variant. This ticket runs two more boards through that path end to end, both ESP32 chips with EAGLE files and variants on disk (surveyed 2026-09-29, .omc/research/twin-candidates.md in the main checkout):

| board | chip | CAD | variant | licence as surveyed |
|---|---|---|---|---|
| SparkFun Pro Micro ESP32-C3 | ESP32-C3 | sparkfun/SparkFun_Pro_Micro-ESP32C3, `Hardware/SparkFun_Dev_ESP32_C3_MINI.brd` | arduino-esp32/variants/sparkfun_pro_micro_esp32c3 | CC BY-SA 4.0, License.md opened |
| SparkFun Qwiic Pocket ESP32-C6 | ESP32-C6 | sparkfun/SparkFun_Qwiic_Pocket_Dev_Board_ESP32_C6, `Hardware/Qwiic_Pocket_Dev_ESP32_C6.brd` | arduino-esp32/variants/sparkfun_esp32c6_qwiic_pocket | no licence file in the tree; README pointer only |

The Qwiic Pocket's licence is not established by the survey. The SparkFun Thing Plus ESP32-C6's `.brd` states its licence in its own frame element (OH-176's `licence_statement`); read the Pocket's `.brd` for the same. If neither the board file nor a licence file in the repository states one, the Pocket is not fetched and this ticket says so.

Each board: registry row (sparse: board file, schematic, licence evidence), manifest row, pins from the variant and the traced copper (OH-178's datasheet tables cover the C3 and the C6 modules already in use; a module not yet in a table is transcribed from its datasheet with the page cited), composed model, and a run test like `tests/webui/test_sparkfun_esp32c6_board.py` with a `BOARD_FIRMWARE_VERIFIED` entry. README board list and TWINS follow.

Done when each board either holds all four layers in TWINS or stops at a named layer with the reason.

**Note 2026-09-30:** 2026-09-30: both boards hold geometry, pins and runs; the model layer composes in lane2 and stops on the composer's own tests, whose file is not this ticket's. PRO MICRO (6ce31e1, d18c0f2, bc74e07). Registry row sparkfun-pro-micro-esp32-c3 fetches Hardware/SparkFun_Dev_ESP32_C3_MINI.brd and .sch (EAGLE 9.6.2) and License.md, whose sentence is quoted and checked: "SparkFun hardware is released under [Creative Commons Share-alike 4.0 International](...by-sa/4.0/)". Manifest row: J6, J7 (1X09_CASTELLATED, 18 castellations merged by the .sch's connects), ESP32-C3, variants/sparkfun_pro_micro_esp32c3, labels SDA and SCL. ESP32_C3_MINI_1 transcribed from ESP32-C3-MINI-1 & MINI-1U Datasheet v2.2 pp. 10-11 Table 3-1, url esp32-c3-mini-1_datasheet_en.pdf, sha256 de7361381348d82a1abd337f10170be7a420675987568f71fe3c5b100deed270: 12 GPIO rows a header reaches, every no-GPIO pad, footprint 49.1-49.9 as the page's 49. 18 pads: 12 traced, 5 supplies, !RESET! to EN. SparkFun names five nets IOA0-IOA4, which carry no IO<n> and no variant label, so test_every_resolved_pin_is_the_gpio_a_second_vendor_statement_names now also reads IOA<n> as IO on the label A<n>, numbered by the variant (a reading of SparkFun's spelling that can only fail a pad; red with IOA0's chip_index 1 and with the rule removed). Run: promicro_blink.bin, an SDA blink built for the board by name (206 bytes; byte-identical to qtpy_blink.bin, both variants putting SDA on GPIO5), IO5/SDA/I2S_SDI/MTDI input, then high at step 38, low 24063, high 48094, low 72119, high 96150; the XIAO's SDA, GPIO6, is this board's IO6/SCL pad, never enabled or driven, read input throughout. POCKET (765cf84, c45c87f, 0d745b2). No licence file in the repository and its README points at a LICENSE.md it does not hold; the .brd's FRAME1 package SparkFun-Aesthetics/CREATIVE_COMMONS reads "Released under the Creative Commons Attribution Share-Alike 4.0 License", so Licence.file is the .brd and the row's licence_statement is FRAME1, as the Thing Plus's. Row: J2, J3 (1X06_NO_SILK), ESP32-C6, variants/sparkfun_esp32c6_qwiic_pocket, labels TX and RX. SparkFun's library places the module as ESP32-C6-MINI-1/ESP32-C6-MINI-1, so ESP32_C6_MINI_1_SPARKFUN is the same page as the Feather's table (v1.5, sha256 26691033..., re-downloaded today and identical) with the 8 rows its headers reach; a new test holds two tables off one page to one another (red with pad 24 as GPIO20, and with pins 54). 12 pads: 8 traced, 4 supplies; V_BATT stays NOT_TRACED (a divider). Its SDA reaches no header pad and its TX is the XIAO's, so the run test watches MOSI (GPIO3, the XIAO's 18) and asserts both reasons: pocket_blink.bin 206 bytes, IO3 input then high 38, low 24063, high 48094, low 72119, high 96150; IO18 never enabled or driven, read input. Both entries in BOARD_FIRMWARE_VERIFIED; check_board_claims OK listing both; board-claims s10. Red on purpose for each run test: the image built against the XIAO's variant, the watched pad's chip_index off by one, the test loading the XIAO, the entry removed, the other pad's level read off the watched one; and for the Pocket a header pad given SDA's GPIO. TWINS (lane2, meshes built here): 11 of 32 hold all four; geometry 31, model 27, pins 26, runs 17. Pro Micro: file, composed, 12+1/13, ESP32-C3. Pocket: file, composed, 8/8, ESP32-C6. Before composing, each model cell read footprint:no source. MODEL: compose_board_3d.py --board composes both with no edit. Pro Micro drawn 5 (U2 SOT-23-5, D1/D2 LED_0603, RESET/BOOT SW_Push_1P1T_NO_CK_KMR2), refused J1 (USB-C, ABSENT), bodyless 8, no model 23 (U1 the module, J5 Qwiic, J6/J7, 0402-TIGHT passives, TP1-6, JP14). Pocket drawn 10 (J4 JST_SH_SM04B horizontal, U2/U3 SOT-23-5, Q1 SOT-23-3, D3 D_SOD-323, D1/D2/D4 LED_0603, RESET/BOOT), refused J1, J5 (ABSENT), bodyless 8, no model 27 (U1, J2/J3, 0402-TIGHT, TP1-4). COMPOSER TESTS RED in lane2 and not fixable here: test_the_two_lists_of_composed_boards_agree and test_each_board_explains_the_parts_it_leaves_off (KB2040 already, now both rows; OH-186's derived COMPOSED closes the first, EXPLAINS needs each board's omissions stated), and two OH-186 does not close: test_a_manifest_boards_colour_is_read_where_its_file_states_one and test_a_manifest_boards_thickness_is_its_own_note_or_the_unos_stack. Both boards' <plain> notes state "Board thickness: 0.8mm" (Pro Micro) and "1.6mm" (Pocket) and "Soldermask: Red", previews 0xC8AA0000 and 0xC8FF0000; each needs a MANIFEST_STATED entry of the Thing Plus's shape (thickness_mm, FROM_PREVIEW) in tools/compose_board_3d.py. Until then both are drawn in BOARD_MASK, not red, and the Pro Micro at the Uno's 1.6 mm, not its 0.8, so neither model cell is a claim to keep; the meshes are gitignored and nothing composer-side is committed. Counts moved in test_import_pindefs and test_pin_view (32 files). SUITE on 0d745b2 with both boards composed: 4 failed (the four composer tests named above), 2364 passed, 21 skipped; the OCP pair in test_import_3d_model did not fail here. Every CLAUDE.md checker, check_facts and ticket_guard --self-test (6/6) OK.
