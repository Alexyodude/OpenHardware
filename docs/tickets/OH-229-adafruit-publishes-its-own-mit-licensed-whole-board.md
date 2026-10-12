---
id: OH-229
title: 'Adafruit publishes its own MIT-licensed whole-board models for the QT Py ESP32-C3
  and KB2040: decide whether they draw instead of the composed ones'
status: open
priority: P3
created: '2026-10-13'
---

Found while researching OH-228 (2026-10-13): Adafruit publishes its own mechanical models, MIT-licensed, at https://github.com/adafruit/Adafruit_CAD_Parts (LICENSE "MIT License, Copyright (c) 2016 Adafruit Industries"; main at c128bceb1f96b6ea8b68f250bda986ba85da24ea on 2026-10-01). Nothing in this repository references it.

It holds whole-board STEPs for three boards this repository has:

    5405 QTPy ESP32 C3/5405 QTPy ESP32 C3.step   1,877,611 bytes  sha256 a220e20db7132d044a640680df0789c24ee89d7aa55e74a156cecac4bc25ebe8  (last changed 2022-05-19)
    5302 KB2040/5302 KB2040.step                 2,161,058 bytes  sha256 bc990ea632850b47e18d6c8fcf9ffe5ca101bacc450d628d4d366b0a7890ae57  (last changed 2021-12-06)
    3405 ESP32 Feather HUZZAH/...                (not measured)

AP214, millimetres, exported by Autodesk Translation Framework (Fusion 360). No Feather ESP32-C6 model is there.

CLAUDE.md ranks geometry sources with "the vendor's own mechanical model" first, ahead of anything composed. The QT Py ESP32-C3 and the KB2040 are composed today from Adafruit's EAGLE board files, which draw the vendor's own copper, routing and silkscreen; a Fusion export of the assembly may carry none of those, or carry them as flat colour. So the ranking is not obviously the right answer for these two, and this ticket is the decision, not an assumption either way.

STEPS:
1. Fetch both STEPs (pinned by commit, size and sha256, gitignored, as tools/import_3d_model.py fetches others) and look at what each actually models: board outline and thickness, every part on it and which are named, whether copper, mask and silkscreen exist as bodies or colours, and how each placement compares with the composed model's (the same position, the same part?).
2. Look at both in the page side by side with the composed model (Playwright against webui/emulator_server.py), and say what each shows that the other does not.
3. Decide per board, with the evidence: draw the vendor's model, keep the composed one, or compose with the vendor's bodies substituted where the composer has none (OH-228 does that for the USB-C socket). Record the decision where the next reader will look -- the board's own manifest or model reason.

Claims: tools/import_3d_model.py and tools/compose_board_3d.py are OH-163's; borrow them when this starts.
