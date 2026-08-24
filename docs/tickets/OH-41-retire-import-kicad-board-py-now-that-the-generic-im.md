---
id: OH-41
title: Retire import_kicad_board.py now that the generic importer reproduces it
status: open
priority: P3
created: '2026-08-25'
touches:
- tools/import_kicad_board.py
---

OH-25 built tools/import_board.py, whose KiCad path reproduces the committed webui/boards/XIAO-RP2040-DIP.json exactly -- same image size, same 14 pads, every coordinate identical to 0.0 px, same labels and groups -- from a different tool than the one that produced it. That makes import_kicad_board.py redundant.

It is not deleted yet for the same reason get_seeed_hardware.sh is not (OH-40): it is referenced from tools/inventory.py, the board-source survey, and two tests. Deleting one file is a change across several owned by other tickets.

Sequence it after OH-40, since the two retirements touch overlapping files and doing them together avoids two rounds of the same edits.

Note while doing it: this tool is the origin of the XIAO-XIAO STM32C5-SMD naming bug, though the typo itself is the vendor's -- the .kicad_mod declares that name internally. The tool used footprint.name for both the board name and source.footprint and never noticed the disagreement. import_board.py records source.file as well, which is what makes an asset search work; carry that forward rather than the name-only behaviour.
