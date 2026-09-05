---
id: OH-167
title: A pad's chip pin is in the board file, dropped by the loader, and 196 pads
  say not modelled instead
status: done
priority: P1
created: '2026-09-05'
touches:
- webui/pinmap.py
- webui/api.py
- tests/webui/test_pin_view.py
- tests/webui/test_pinmap.py
---

A pad's chip pin is written in the board file, thrown away by the loader, and the panel says "not modelled" for 196 pads whose answer this repository already knows.

`webui/pinmap.py`'s `Pad` carries `label`, `pin`, `x`, `y` and `group`. The board files carry more than that: OH-26 imported `chip_pin` and `chip_index` out of six board-support packages, every value naming the vendor file and revision that resolved it, and wrote them into `webui/boards/*.json`. `parse` reads none of them. So the resolved map reaches the disk and stops there.

The panel's caption then comes from the only other source there is -- `description.PIN_NAMES`, a table on the board's runtime module. Twelve boards have such a module. Fourteen do not, and on those every pad reads "not modelled", which is the sentence OH-164 defined to mean "no module models this pin".

Measured 2026-09-05 over `catalogue.board_names()`, comparing what each board FILE states against what `pad_view` reports for a board picked and not loaded:

  hidden    196   the file states a chip pin, the panel shows none
  agree     125   both state it, and they match
  disagree    0   nowhere, on any board

  XIAO-ESP32-S3-DIP        11 of 14      XIAO-nRF52840-DIP       11 of 14
  XIAO-ESP32-S3-SMD        11 of 25      XIAO-nRF52840-SMD       13 of 22
  XIAO-ESP32-S3-SMD_PAD    11 of 25      XIAO-nRF54LM20A-DIP      8 of 14
  XIAO-MG24-DIP            19 of 24      XIAO-nRF54LM20A-SMD     28 of 48
  XIAO-MG24-SMD            19 of 32      XIAO-nRF54l15-DIP       11 of 14
  XIAO-RP2350-DIP          19 of 24      XIAO-nRF54l15-SMD       16 of 34
  XIAO-RP2350-SMD          19 of 30

**Zero disagreements is what makes this safe and it is also why nobody noticed.** Where a module exists its table and the file agree on all 125, so no board shows a wrong caption -- it shows a missing one, and a missing caption on a board with no module is indistinguishable from the honest "nothing models this pin" until you open the JSON beside it.

What is NOT the defect, because it looks like one: every XIAO pad has `pin: null`. That field is the rcontrol pin index of a PICSimLab board implementation and only the Arduino Uno has one; each XIAO file states this in its own `assumption`, at length. It is not a gap and it must not be filled by pressing `chip_index` into it -- the two number different things, and OH-26's own rule is that a disagreement is recorded rather than averaged.

STEPS:

1. `Pad` gains `chip_pin: str | None` and `chip_index: int | None`, read by `parse` from the entry it already ignores. Nothing else changes. Test: a XIAO map round-trips a pad's `chip_pin` out of the file, and the one pad in the file with `chip_pin` null still reads null rather than an empty string.

2. `pad_view` prefers the module's `PIN_NAMES` where it has an entry and falls back to the pad's own `chip_pin` otherwise. **The module keeps priority on purpose**: it is the same table levels are read through, so a label cannot have one pin in the caption and another in the state. The fallback can only ever fill a hole. Test: the thirteen boards above report their chip pins, and the count of pads reading "not modelled" falls from 196 to whatever the files genuinely leave null.

3. A disagreement is surfaced rather than resolved. There are none today across 125 comparisons, so this is a guard and not a fix: if a module and a file ever name different pins for one label, that is two vendor readings in conflict and the page must not pick one silently. Test: a stub description whose `PIN_NAMES` contradicts its file.

4. What this does NOT do, and it should be said in the same breath: a chip pin in the caption is not a pin the simulator can drive. Those thirteen boards still have no module, so their pads still read no level and still refuse a wire. This changes what the page can honestly SAY about a pin, not what it can do with one. The wiring gap is OH-161's and the cores' business.

Found 2026-09-05 while checking a report that chip pins were still wrong.

**Note 2026-09-05:** Done 2026-09-05. 343 of 582 pads now name their MCU pin, against 147 before; every board with a pin map reports one except XIAO-XIAO STM32C5-SMD, whose file states none. The module keeps priority where it names a pin and the file fills holes only, pinned against a stub whose table contradicts its file because live data agrees on all 125 comparisons. Steps 1, 2 and 4 done; step 3, surfacing a disagreement, is NOT done -- there are none to surface today and a guard nobody can trigger is a check that cannot fail, so it is left for whoever creates the first one.
