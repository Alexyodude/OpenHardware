---
id: OH-188
title: 'Two more ESP32 boards through the manifest path end to end: SparkFun Pro Micro
  ESP32-C3 and Qwiic Pocket ESP32-C6'
status: open
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-188-*
---

Part of OH-174. Three boards now hold all four layers through the manifest path (OH-176 to OH-185): a row, pins from the variant and the traced copper, a composed model, and a run test compiled against the board's own variant. This ticket runs two more boards through that path end to end, both ESP32 chips with EAGLE files and variants on disk (surveyed 2026-09-29, .omc/research/twin-candidates.md in the main checkout):

| board | chip | CAD | variant | licence as surveyed |
|---|---|---|---|---|
| SparkFun Pro Micro ESP32-C3 | ESP32-C3 | sparkfun/SparkFun_Pro_Micro-ESP32C3, `Hardware/SparkFun_Dev_ESP32_C3_MINI.brd` | arduino-esp32/variants/sparkfun_pro_micro_esp32c3 | CC BY-SA 4.0, License.md opened |
| SparkFun Qwiic Pocket ESP32-C6 | ESP32-C6 | sparkfun/SparkFun_Qwiic_Pocket_Dev_Board_ESP32_C6, `Hardware/Qwiic_Pocket_Dev_ESP32_C6.brd` | arduino-esp32/variants/sparkfun_esp32c6_qwiic_pocket | no licence file in the tree; README pointer only |

The Qwiic Pocket's licence is not established by the survey. The SparkFun Thing Plus ESP32-C6's `.brd` states its licence in its own frame element (OH-176's `licence_statement`); read the Pocket's `.brd` for the same. If neither the board file nor a licence file in the repository states one, the Pocket is not fetched and this ticket says so.

Each board: registry row (sparse: board file, schematic, licence evidence), manifest row, pins from the variant and the traced copper (OH-178's datasheet tables cover the C3 and the C6 modules already in use; a module not yet in a table is transcribed from its datasheet with the page cited), composed model, and a run test like `tests/webui/test_sparkfun_esp32c6_board.py` with a `BOARD_FIRMWARE_VERIFIED` entry. README board list and TWINS follow.

Done when each board either holds all four layers in TWINS or stops at a named layer with the reason.
