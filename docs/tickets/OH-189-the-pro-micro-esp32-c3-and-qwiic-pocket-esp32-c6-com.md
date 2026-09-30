---
id: OH-189
title: 'The Pro Micro ESP32-C3 and Qwiic Pocket ESP32-C6 composed whole: their own
  colour and thickness, every part drawn or reasoned'
status: open
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-189-*
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tools/import_3d_model.py
---

Part of OH-174, from OH-188. OH-188 made the SparkFun Pro Micro ESP32-C3 and the SparkFun Qwiic Pocket ESP32-C6 manifest rows with geometry, pins and runs, and left the model layer to the composer's owner. With OH-186's derived COMPOSED list, both boards compose with no edit, and OH-188 reports four things still wrong with the result:

1. Neither board has a MANIFEST_STATED entry, so both are drawn in the default mask colour at 1.6 mm, and test_a_manifest_boards_colour_is_read_where_its_file_states_one and test_a_manifest_boards_thickness_is_its_own_note_or_the_unos_stack fail. OH-188's report records board notes stating a red mask and a thickness (0.8 mm on the Pro Micro, 1.6 mm on the Pocket) and preview colours; read them from the files, as the Thing Plus's are read, rather than from that report.
2. Most placements on both boards are neither drawn nor refused with a reason: the modules (the Pro Micro's ESP32-C3-MINI-1; the Pocket's C6-MINI-1 under SparkFun's own package name), the pin headers, the 0402 passives and the test points. Each is drawn from a published model or refused with its own reason, and test_each_board_explains_the_parts_it_leaves_off holds both boards.
3. The refusal texts printed for J1 and J5 are the Thing Plus's wording; each board's refusal names its own part.
4. Passives follow OH-187's rule for kind.

Run after OH-187, on a branch that carries OH-188's rows. Done when both boards' model cells read composed on master with every placement drawn or reasoned, their own colour and thickness, and the composer and importer test files pass.
