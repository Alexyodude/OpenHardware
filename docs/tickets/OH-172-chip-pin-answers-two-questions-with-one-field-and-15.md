---
id: OH-172
title: chip_pin answers two questions with one field, and 153 pads are answered by
  the half nobody meant
status: open
priority: P2
created: '2026-09-06'
---

`chip_pin` answers two different questions with one field, and 153 pads are answered wrongly by the half nobody meant.

The field's own docstring says it is "which MCU pin each label reaches -- `D6` -> `PB08`". That is a caption. But `webui/static/board3d-panel.js`'s `unknownWords` also reads it as the test for whether a pin is modelled at all: a pad whose `chip_pin` is null renders as "not modelled", and one with a value renders as "in use elsewhere" or "no program running" depending on whether a program is loaded.

So a pad gets a chip pin only if the page may also claim a LEVEL for it. Those are not the same question, and the boards say so.

Measured 2026-09-06 against Seeed's own board files, tracing a pad's net to the part's own footprint:

  the C6's `EN`        reaches the ESP32-C6's `CHIP_PU`
  the RP2350's `SWDIO` reaches the RP2350's `SWDIO` pad
  the MG24's `GND`     reaches `RFVSS`, `VREFN`, `CREGVSS` and `PAD`
  the C6's `GND`       reaches `GND`

Every one of those is an MCU pin the vendor names. By the docstring's sentence they qualify; by the page's use of the field they must not, because none of them can report high or low and a board sitting there claiming "no program running" for its ground pin would be OH-164's defect returning through a different door.

**So the field is doing two jobs and the second one wins**, which is why 153 supply and ground pads carry a null that OH-170 counts as "correctly null". Correct for the page. Not correct as a statement about the board, which is what the column is captioned.

WHAT IS NOT WRONG TODAY. Nothing renders incorrectly. This is a design fault rather than a defect: the page is right, the counts are right, and a reader who asks "which pin does GND reach" gets no answer from a table that is captioned as if it would give one.

STEPS:

1. Decide whether the page wants a second field or a second meaning. Two shapes, and the choice is the whole ticket:
   - `chip_pin` keeps its meaning and gains company: a `pin_kind` of `gpio` / `function` / `supply`, so the page can show the name and still refuse to claim a level. Costs a field everywhere and a branch in `unknownWords`.
   - `chip_pin` becomes the caption it is documented as, and the page's modelled test moves to what it actually means -- whether the board module's `HEADER` has an entry for the label, which is already the thing `pin_states` reads levels through.
   The second is smaller and truer. It also makes `chip_pin` and `PIN_NAMES` stop being two sources for one decision, which OH-167 already found had drifted for fourteen boards.

2. Whichever is chosen, `read_seeed_traced`'s `_CHIP_PIN_NAME` gate is where the line currently sits: it accepts `GPIO4`, `PA02` and `P1.02` and rejects `CHIP_PU`, `SWDIO` and `RFVSS`. That gate is the design decision, made in a regex, and it should be named as one wherever the answer lands.

3. `test_every_pad_either_names_its_pin_or_says_why_it_has_none` counts 153 pads as "supply, with no MCU pin by construction". If a supply pad gains a name, that sentence is wrong and the count moves; both should change together.

Found while OH-170 was checking whether its own supply-label set was too broad. It is not -- no source resolves any label in it -- but the reason no source resolves them turned out to be a rule this repository imposed rather than a fact about the boards.
