---
id: OH-200
title: The XIAO ESP32-C5 and C6 SMD boards' JTAG and BOOT pads name their pins from
  Seeed's own board file
status: in-review
priority: P1
created: '2026-10-08'
touches:
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- webui/boards/esp32c5.py
- webui/boards/esp32c6.py
- webui/boards/XIAO-ESP32-C5-*.json
- webui/boards/XIAO-ESP32-C6-*.json
- webui/boards/XIAO-nRF54LM20A-*.json
- tests/webui/test_pin_view.py
---

Part of OH-174. The XIAO-ESP32-C5-SMD and XIAO-ESP32-C6-SMD hold three of the four layers on the TWINS scorecard and miss the fourth, pins, on the same five pads each: MTMS, MTDI, MTDO, MTCK and BOOT. `python tools/inventory.py` prints them as 11/16.

These are not unknown. OH-170 read every one of them from Seeed's own board files in `third_party/seeed-pcb/` and left them unwritten on purpose: the comments on `_ESP32C5` and `_ESP32C6` in `tools/import_pindefs.py` say so, and `test_the_c5_and_c6_jtag_values_are_held_by_a_test_and_not_only_a_comment` asserts the values from the vendor's files (C5: MTMS 2, MTDI 3, MTDO 5, MTCK 4, BOOT 28; C6: MTMS 4, MTDI 5, MTDO 7, MTCK 6, BOOT 9). The JTAG four come off the net names on both boards; the C6's BOOT needs `read_seeed_traced`, because its net is called simply `BOOT` and only the module pad on it names `GPIO9`. The stop was ownership: writing them changes what `webui/boards/esp32c5.py` and `esp32c6.py` must state, and those are OH-161's.

Wire Seeed's board file into `_ESP32C5` and `_ESP32C6` as a source for those five labels, regenerate the board files and the generated HEADER blocks, and replace the comment and the hold-the-values test with the wiring and whatever test the wiring makes meaningful. The C5 and the C6 disagree on every one of the five, so neither may be copied to the other. The DIP boards carry none of these pads; what the shared module states must stay true of both the DIP and the SMD board it serves, and `test_the_board_file_and_the_module_agree_on_every_labelled_pad` holds that in both directions.

Starts after OH-194 merges, which claims `tools/import_pindefs.py` and `tests/rules/test_import_pindefs.py` until then. `webui/boards/esp32c5.py` and `esp32c6.py` are lent from OH-161, which nobody holds.

Done when the two SMD boards' five pads each name a `chip_pin` read from Seeed's own board file, the scorecard shows both boards holding all four layers, and the comment that said these were waiting is gone.

**Note 2026-10-08:** 2026-10-08: started in lane3. webui/boards/esp32c5.py and esp32c6.py are lent from OH-161 and go back when this closes.

**Note 2026-10-08:** Done in lane3, in review. Three commits: 40b885d (a board file that two sources read is hashed once in `pindefs.packages[].revision`), 4cf7975 (a HEADER block lists board CAD apart from the board-support packages, naming the rows it answered, and names rows only one of a chip's files has a pad for), 43f301e (the wiring, the two regenerated HEADER blocks, the four regenerated board files, the tests).

PADS. Each one is read from that board's own Seeed board file, and `python tools/import_pindefs.py <board>` cites each one as `seeed-pcb <file> @ sha256:<digest>` and nothing else:
  XIAO-ESP32-C5-SMD  ESP32-C5.kicad_pcb, net names: MTMS GPIO2, MTDI GPIO3, MTDO GPIO5, MTCK GPIO4, BOOT GPIO28
  XIAO-ESP32-C6-SMD  ESP32-C6.kicad_pcb, net names for the JTAG four, BOOT traced to the module pad named GPIO9: MTMS GPIO4, MTDI GPIO5, MTDO GPIO7, MTCK GPIO6, BOOT GPIO9
The two boards disagree on every one of the five. `test_the_c5_and_c6_smd_jtag_and_boot_pads_are_read_from_each_boards_own_file` goes red when the C6 is wired to the C5's file.

DIP AND SMD. The sources are shared, as `_S3_FIXED` and the MG24's traced pair already are. The DIP files carry none of these pads, and the only change to them is that `seeed-pcb` now appears in `pindefs.packages`. The module's HEADER is the union, which is `header_table`'s existing rule, and the block now says the five rows are pads of the SMD file alone. One result is visible: on a running DIP board the pin view lists the five as padless "on board" rows beside LED, each with its GPIO and level, because `api.pad_view` lists every `pin_states` key that no pad carries. Both footprints describe one physical XIAO, so these rows are true of the board. They are still new on the DIP view.

GPIO28 AND GPIO9. In ESP-IDF v5.5 (8c750b0), soc_caps.h gives SOC_GPIO_PIN_COUNT as 29 for the C5 and 31 for the C6. Both modules read OUT and ENABLE as [31:0]. In tests/webui/test_pin_view.py, the width test and the enable-before-out test pass with the new rows.

TWINS, from `python tools/inventory.py`: "15 of 37 boards hold all four; by layer: geometry 36, model 29 (7 not built here), pins 33, runs 23". Before this it was 13 boards and 31 pins. XIAO-ESP32-C5-SMD and XIAO-ESP32-C6-SMD are both 16/16.

LEFT FOR ANOTHER TICKET. 40b885d changes what the generator writes for XIAO-nRF54LM20A-DIP.json and XIAO-nRF54LM20A-SMD.json, which are unclaimed and not OH-200's. Only one field changes: the `seeed-pcb` revision goes from 905c6be61ddc (the file hashed twice) to 348d87a79f07 (the file's own digest). Both files were left as committed. `test_the_committed_board_files_match_the_generator` normalises revisions, so nothing goes red, but `--write-boards` will rewrite those two files until somebody who holds them regenerates them.

ALSO. `python tools/check_ticket_claims.py` reports that docs/tickets/OH-161-*.md changed on this branch while it holds OH-200. That change is bc15955, OH-161's own lend commit, and not this ticket's work. docs/HANDOFF_2026-09-06_the-pins-that-were-published.md and OH-170's closing note still name the removed test `test_the_c5_and_c6_jtag_values_are_held_by_a_test_and_not_only_a_comment`. Both are historical records and were left alone.

Full suite in lane3, python 3.14: "2 failed, 2447 passed, 38 skipped in 519.63s (0:08:39)". The two failures are the OCP tests in tests/rules/test_import_3d_model.py ("No module named 'OCP'").
