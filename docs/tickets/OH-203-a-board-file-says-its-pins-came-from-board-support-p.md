---
id: OH-203
title: A board file says its pins came from board-support packages while some rest
  on the vendor's board CAD
status: open
priority: P2
created: '2026-10-08'
---

Found by OH-200's review (2026-10-08). A board file's `pindefs.derivation` and `assumption` say where its `chip_pin` values came from, and on eight XIAO board files they say something false.

`BOARD_DERIVATION` in `tools/import_pindefs.py` says the file was generated "from the board-support packages in `packages`", that "Nothing was inferred from the CAD", and that a label resolves only when every package covering the board names the same pin. `assumption_for` says `chip_pin` was "read out of the board-support packages named in `pindefs`". Both are written onto every board a board-support package covers.

Some of those boards also read the vendor's own board CAD, `seeed-pcb`, for pads no package names: the MG24, nRF54L15 and nRF54LM20A XIAOs (DIP and SMD) before OH-200, and since OH-200 the XIAO ESP32-C5-SMD and C6-SMD, whose MTMS, MTDI, MTDO, MTCK and BOOT come from Seeed's board file alone. On those files the derivation and the assumption contradict the pads they describe, and contradict the HEADER block OH-200 generates for the same pads, which says that source "is not a board-support package".

`BOARD_DERIVATION_UNCOVERED` and `MANIFEST_DERIVATION` already describe a CAD source truthfully. Give a covered board that also reads a non-firmware source a derivation and an assumption that name what the CAD answered, generated rather than typed, and regenerate the board files. A covered board that reads only packages keeps today's sentence.

While in `header_table`, two readability edges from OH-200's confirm review: the local set called `cad_rows` means "any CAD source named the row" while the `HeaderTable.cad_rows` field it filters into means "only the CAD named it" (rename the locals, e.g. `cad_named` / `package_named`); and the F3 test's docstring does not say that its fake `D6/MTDI` pad is what exercises the `alternatives` keying, so a later simplification could remove it unnoticed.

Done when no board file says its pins came only from board-support packages while a pad on it rests on the vendor's CAD, a test fails if one does, and the generated files regenerate byte for byte.
