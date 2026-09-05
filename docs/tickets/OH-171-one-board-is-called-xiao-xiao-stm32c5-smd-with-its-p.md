---
id: OH-171
title: One board is called XIAO-XIAO STM32C5-SMD, with its prefix doubled, and the
  name is the key everything joins on
status: open
priority: P3
created: '2026-09-06'
---

One board is called `XIAO-XIAO STM32C5-SMD`, with the prefix doubled and a space where every sibling has a hyphen.

Every other XIAO file is `XIAO-<part>-<footprint>`: `XIAO-ESP32-C3-SMD`, `XIAO-RP2350-DIP`, `XIAO-nRF54LM20A-SMD`. This one reads `XIAO-XIAO STM32C5-SMD`, so its part is recorded as `XIAO STM32C5` rather than `STM32C5`.

OH-26 flagged it on 2026-08-25 -- "webui/boards/XIAO-XIAO STM32C5-SMD.json has a doubled name prefix, likely an OH-25 import bug" -- and nobody has picked it up in the twelve days since. OH-170 met it again from the other end and is filing it rather than carrying it a third time.

It is not cosmetic. The name is the key everything joins on:

  the file          webui/boards/XIAO-XIAO STM32C5-SMD.json
  the artwork       webui/boards/XIAO-XIAO STM32C5-SMD.svg, named to match
  the JSON's own    "board": "XIAO-XIAO STM32C5-SMD"
  `catalogue.chip_for` parses the name after `XIAO-` to get the part, so this
                    board's chip is the string `XIAO STM32C5`
  the 3D model      `docs/research/board-models` records this as the one board
                    with no mesh; the index is keyed by the same name

So a rename touches the file, the SVG, the JSON field, whatever `catalogue` and `IRREGULAR` say about it, `webui/static/models/index.json`, and any test naming it. That is why this is a ticket rather than a `git mv`.

**What is NOT claimed: which name is right.** Seeed's own wiki calls the part the XIAO STM32C5 in prose. Whether the file should be `XIAO-STM32C5-SMD` -- consistent with its twenty-five siblings -- or whether the vendor really does name this one differently is a question for whoever fixes it, and the answer belongs beside the change. Renaming it to match the pattern and finding the vendor calls it something else would be trading one wrong name for another.

STEPS:

1. Establish what Seeed call it, from a source rather than from the pattern. The board has no wiki page that `tools/get_board_sources.py` can name and no board-support package anywhere, which is the same absence that leaves all 26 of its non-power pads unresolved (OH-170 step 3) and leaves it the only board with no 3D model. If nothing states the name, say so and rename for consistency with a note that the consistency is the only argument.

2. Rename the file, the SVG, and the `board` field together, and check `catalogue.chip_for` gives the part the rest of the catalogue expects.

3. Grep the tree for the old string. `tests/rules/test_import_pindefs.py` names it in `test_the_boards_with_no_source_are_deliberate`, and OH-170's own counting test asserts twenty-six files exist.

4. A test that no board file's name repeats its own prefix, so the next importer that does this is caught by the suite rather than by a reader twelve days later.

Found while finishing OH-170. Not fixed there: a rename is not a pin definition, and OH-170's claim is on the pin data.
