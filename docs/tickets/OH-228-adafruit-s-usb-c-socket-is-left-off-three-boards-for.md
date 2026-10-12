---
id: OH-228
title: Adafruit's USB-C socket is left off three boards for want of a KiCad model,
  and the manufacturer's own STEP was never looked for
status: open
priority: P3
created: '2026-10-12'
---

Seen in the page 2026-10-12: the Adafruit QT Py ESP32-C3 draws with no USB-C socket at its end, and so do the Feather ESP32-C6 and the KB2040. The composer says why (`--check`: `absent X6 (USB_C_CUSB31-CFM2AX-01-X)`), and the reason in `tools/compose_board_3d.py`'s `ABSENT` is about one library only: "KiCad's Connector_USB, 12 models listed 2026-09-29, holds nothing of CUI's".

CLAUDE.md lists four geometry sources in order, and the third is "the manufacturer's own STEP". The part is named exactly -- Adafruit's package name is the part number, CUI Devices' (now Same Sky's) CUSB31-CFM2AX-01-X -- and a manufacturer of USB-C receptacles normally publishes a 3D model of each on the product page. That source was not checked.

STEPS:
1. Find whether Same Sky publishes a STEP for CUSB31-CFM2AX-01-X, on what terms, and whether it can be fetched by a tool the way `tools/import_3d_model.py` fetches the others (pinned by size and sha256, gitignored, never committed -- see that file for the licence reason). Record the URL, the terms read, and the date.
2. If it can: add it as the manufacturer's-STEP source for that package, placed on Adafruit's land and checked as every other placement is (span, contact landing, pin-1 marker where the model has an asymmetric feature), on all three boards.
3. If it cannot (no model, a login wall, terms that forbid it): say so in the ABSENT reason, dated, so the reason names every source that was tried and not only KiCad's.

SparkFun's USB-C socket (`USB-C-16P_4LAYER-PADS`) is not this ticket: SparkFun's files name no maker for it, only their PROD_ID, so there is no part number to look up.
