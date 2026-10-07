---
id: OH-200
title: The XIAO ESP32-C5 and C6 SMD boards' JTAG and BOOT pads name their pins from
  Seeed's own board file
status: open
priority: P1
created: '2026-10-08'
---

Part of OH-174. The XIAO-ESP32-C5-SMD and XIAO-ESP32-C6-SMD hold three of the four layers on the TWINS scorecard and miss the fourth, pins, on the same five pads each: MTMS, MTDI, MTDO, MTCK and BOOT. `python tools/inventory.py` prints them as 11/16.

These are not unknown. OH-170 read every one of them from Seeed's own board files in `third_party/seeed-pcb/` and left them unwritten on purpose: the comments on `_ESP32C5` and `_ESP32C6` in `tools/import_pindefs.py` say so, and `test_the_c5_and_c6_jtag_values_are_held_by_a_test_and_not_only_a_comment` asserts the values from the vendor's files (C5: MTMS 2, MTDI 3, MTDO 5, MTCK 4, BOOT 28; C6: MTMS 4, MTDI 5, MTDO 7, MTCK 6, BOOT 9). The JTAG four come off the net names on both boards; the C6's BOOT needs `read_seeed_traced`, because its net is called simply `BOOT` and only the module pad on it names `GPIO9`. The stop was ownership: writing them changes what `webui/boards/esp32c5.py` and `esp32c6.py` must state, and those are OH-161's.

Wire Seeed's board file into `_ESP32C5` and `_ESP32C6` as a source for those five labels, regenerate the board files and the generated HEADER blocks, and replace the comment and the hold-the-values test with the wiring and whatever test the wiring makes meaningful. The C5 and the C6 disagree on every one of the five, so neither may be copied to the other. The DIP boards carry none of these pads; what the shared module states must stay true of both the DIP and the SMD board it serves, and `test_the_board_file_and_the_module_agree_on_every_labelled_pad` holds that in both directions.

Starts after OH-194 merges, which claims `tools/import_pindefs.py` and `tests/rules/test_import_pindefs.py` until then. `webui/boards/esp32c5.py` and `esp32c6.py` are lent from OH-161, which nobody holds.

Done when the two SMD boards' five pads each name a `chip_pin` read from Seeed's own board file, the scorecard shows both boards holding all four layers, and the comment that said these were waiting is gone.
