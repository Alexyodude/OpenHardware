---
id: OH-228
title: Adafruit's USB-C socket is left off three boards for want of a KiCad model,
  and the manufacturer's own STEP was never looked for
status: open
priority: P3
created: '2026-10-12'
touches:
- tools/import_3d_model.py
- tests/rules/test_import_3d_model.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

Seen in the page 2026-10-12: the Adafruit QT Py ESP32-C3 draws with no USB-C socket at its end, and so do the Feather ESP32-C6 and the KB2040. The composer says why (`--check`: `absent X6 (USB_C_CUSB31-CFM2AX-01-X)`), and the reason in `tools/compose_board_3d.py`'s `ABSENT` is about one library only: "KiCad's Connector_USB, 12 models listed 2026-09-29, holds nothing of CUI's".

CLAUDE.md lists four geometry sources in order, and the third is "the manufacturer's own STEP". The part is named exactly -- Adafruit's package name is the part number, CUI Devices' (now Same Sky's) CUSB31-CFM2AX-01-X -- and a manufacturer of USB-C receptacles normally publishes a 3D model of each on the product page. That source was not checked.

STEPS:
1. Find whether Same Sky publishes a STEP for CUSB31-CFM2AX-01-X, on what terms, and whether it can be fetched by a tool the way `tools/import_3d_model.py` fetches the others (pinned by size and sha256, gitignored, never committed -- see that file for the licence reason). Record the URL, the terms read, and the date.
2. If it can: add it as the manufacturer's-STEP source for that package, placed on Adafruit's land and checked as every other placement is (span, contact landing, pin-1 marker where the model has an asymmetric feature), on all three boards.
3. If it cannot (no model, a login wall, terms that forbid it): say so in the ABSENT reason, dated, so the reason names every source that was tried and not only KiCad's.

SparkFun's USB-C socket (`USB-C-16P_4LAYER-PADS`) is not this ticket: SparkFun's files name no maker for it, only their PROD_ID, so there is no part number to look up.

**Note 2026-10-13:** 2026-10-13, research (WebSearch/WebFetch, read-only): THE PREMISE IS WRONG -- CUSB31-CFM2AX-01-X is not a CUI or Same Sky part. Same Sky's own site search answers 'No match found for "CUSB31-CFM2AX-01-X"' (https://www.sameskydevices.com/SiteSearch/SearchByPartialMatch?partnumber=CUSB31-CFM2AX-01-X; 'CUSB31' alone the same), none of the 254 parts in its USB-connector catalogue carries the number, Digi-Key has none, and Adafruit's files name no maker (the package comes from the public-domain microBuilder.eu library; the deviceset says only 'USB Type-C USB 2.0 Connector'). The 'CUI' in compose_board_3d.py's ABSENT reason is this repository's own attribution and is wrong. (Same Sky's CAD terms, recorded in case they matter elsewhere: models 'remain the exclusive property of Same Sky' and 'may not be copied, modified, or reproduced without prior written consent'; downloads go through a click-through form with a one-off redirect URL, so nothing there is pinnable.) WHAT DOES EXIST: Adafruit's own MIT-licensed Adafruit_CAD_Parts (https://github.com/adafruit/Adafruit_CAD_Parts, main c128bceb1f96b6ea8b68f250bda986ba85da24ea) models this socket on this land as a separate named body, PRODUCT('USB TYPE C'), identical inside its QT Py ESP32-C3 STEP (1,877,611 bytes, sha256 a220e20d...ebe8) and its KB2040 STEP (2,161,058 bytes, sha256 bc990ea6...ae57). Measured from the STEP's vertices as text: 8.94 x 7.90 x 4.20 mm, its width the package's own outline exactly, its four shell legs on Adafruit's tabs to 0.04 mm and its twelve tails on the pads (wide tails 0.05 mm outboard, within the pad). SCOPE, decided for the owner while away: this ticket now draws X6/X3 on the three boards from Adafruit's 'USB TYPE C' body, pinned by commit, size and sha256 (the vendor's own mechanical model of its own part, CLAUDE.md's first-ranked source), which needs one new mechanism -- one named product out of an assembly STEP (OCP's XCAF reader); and corrects the ABSENT reason either way. The whole-board STEPs are OH-229.

**Note 2026-10-13:** 2026-10-13: borrows tools/import_3d_model.py, tools/compose_board_3d.py and their tests from OH-163.
