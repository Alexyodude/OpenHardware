---
id: OH-172
title: chip_pin answers two questions with one field, and 153 pads are answered by
  the half nobody meant
status: open
priority: P2
created: '2026-09-06'
touches:
- webui/api.py
- webui/static/board3d-panel.js
- tests/webui/test_pin_view.py
- tests/webui/test_board3d.py
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

**Note 2026-10-08:** 2026-10-08, from OH-209's work and review: EN is in SUPPLY_LABELS, so the EN pad of every XIAO SMD keeps the generic why_null and no layer counts it, while it is a real signal: on XIAO-RP2350-SMD pad 25 lands on underside test point TP4, net '/04 RP2350/RUN', which carries the RP2350's RUN pad (U4 pad 26), the reset button K2, R12 and C25 (Seeed's RP2350.kicad_pcb). Whether EN belongs among the supplies is this ticket's question; nine XIAO SMD boards carry the same sentence.

**Note 2026-10-09:** 2026-10-09: claims webui/api.py, webui/static/board3d-panel.js and tests/webui/test_pin_view.py (unclaimed), and borrows tests/webui/test_board3d.py from OH-215 (in review, waiting only on a browser look). DECISION, made for the owner while they are away, from a read-only design pass: the ticket's second shape. chip_pin becomes only the caption it is documented as; the page's modelled test becomes a per-pad 'modelled' boolean that webui/api.py computes from the keys the board's own level reader answers under -- the module's HEADER where it has pin_states, a manifest row's chip_index pads where it reads GPIO words -- because the page cannot see HEADER and a board file cannot state what a simulator reads. pin_kind was not chosen: the pads it would get wrong are real GPIOs on boards with no module, which a file-level kind would still call gpio. The design pass found the ticket's 'nothing renders incorrectly' out of date: since OH-167 made chip_pin_of fall back to the board file, every pad that names a chip pin on a board with no module renders 'no program running' where OH-164's own ordering says 'not modelled'; on every board with a reader, chip_pin non-null and 'the reader has a key' agree on every pad, so slice 1 changes exactly those pads. SLICE 1 (this ticket now): the API's modelled flag, the panel reading it, the tests. NOT IN SLICE 1: a caption for EN/RUN/GND and other non-GPIO pins, moving the _CHIP_PIN_NAME gate to header_table, plural captions for supply nets, EN/RESET/RST leaving SUPPLY_LABELS (which moves the TWINS pins layer and needs OH-213's files), and the wording of 'not modelled' beside a named chip pin.
