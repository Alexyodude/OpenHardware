---
id: OH-25
title: Import a board from any vendor's CAD, not only KiCad footprints from Seeed
status: done
priority: P1
created: '2026-08-25'
touches:
- tools/import_board.py
- tools/eagle.py
- tests/rules/test_import_board.py
avoid:
- webui/boards/**
---

tools/import_kicad_board.py joins a .kicad_mod footprint to a .kicad_sym symbol and emits pads with exact millimetre centres. That works because Seeed publishes KiCad. Adafruit and SparkFun publish EAGLE; Arduino publishes EAGLE and KiCad; ST publishes PDF and Altium; several vendors publish nothing but a picture.

Generalise the front half: one importer, a parser per CAD format behind it, the same Board JSON out. tools/kicad.py stays as the KiCad parser and is not rewritten.

The honest failure mode matters more than the coverage. A vendor with no machine-readable geometry must fail loudly with the reason -- webui/pinmap.py records that the Arduino Uno's pad centres had to be extracted from board.svg by hand, and that is the outcome to avoid repeating silently. Every board JSON already carries a 'derivation' field claiming 'Nothing here was measured off an image'; an importer that guesses would make that sentence a lie in 26 files at once.

Done when a board imports from EAGLE with pad centres traceable to the vendor's own coordinates, and a vendor with only a PDF is refused with a message naming what was missing.

Note: the JSON it writes lands under webui/boards/, which OH-22 currently claims wholesale. Either OH-22 narrows its claim or this waits.

**Note 2026-08-25:** Found by OH-27 and verified: webui/boards/'XIAO-XIAO STM32C5-SMD'.json records source.footprint = 'XIAO-XIAO STM32C5-SMD', but the vendor file is 'Seeed Studio XIAO Series Library/XIAO-STM32C5-SMD.kicad_mod'. The doubled XIAO- prefix was carried into the footprint field, so that name matches nothing in the vendor tree. It changes no asset cell today because every vendor cell for that board is absent anyway, but it will silently suppress the board's assets the moment anything is published for it. catalogue.py already names this board as irregular; the footprint field did not get the same treatment.

**Note 2026-08-25:** CORRECTION to note 3 above, verified against the vendor library. The doubled prefix is the VENDOR'S bug, not this project's. XIAO-STM32C5-SMD.kicad_mod internally declares (footprint "XIAO-XIAO STM32C5-SMD"), and import_kicad_board.py uses footprint.name for both 'board' and source.footprint, so it copied the typo faithfully rather than inventing it. Checked all 37 footprints in the library: TWO declare a name differing from their filename -- this one, and 'XIAO Landing page' which declares 'LOGO'. OH-25's report said one; it is two, though the second is a logo rather than a board. The durable fix is that every import now records source.file, a path, not only a declared name -- an asset search keyed on a declared name finds nothing, while a path is always right.
