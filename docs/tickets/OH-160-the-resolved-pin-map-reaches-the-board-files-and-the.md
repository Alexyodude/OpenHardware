---
id: OH-160
title: The resolved pin map reaches the board files and the board modules, so a XIAO
  pad answers a wire
status: done
priority: P1
created: '2026-09-04'
touches:
- tools/import_pindefs.py
- webui/boards/*.json
- webui/boards/esp32c3.py
- webui/boards/esp32c5.py
- webui/boards/esp32c6.py
- webui/boards/rp2040.py
- tests/rules/test_import_pindefs.py
- tests/riscv32/test_esp32c*_board.py
- webui/api.py
- tests/webui/test_pin_view.py
- tools/inventory.py
- tools/import_board.py
- .github/workflows/rules.yml
- README.md
---

On 25 of 26 boards a pad still refuses a wire, and the answer has been sitting in a report nobody consumes since OH-26.

Measured 2026-09-04:

    webui/boards/*.json          582 pads, 28 carry a `pin` -- all 28 on the Arduino Uno.
                                 Every XIAO file has `pin: null` on every pad, and says
                                 in its own `assumption` field that such a pad "draws and
                                 refuses a wire".
    tools/import_pindefs.py      resolves 321 of 550 XIAO pads from six fetched vendor
    --all --summary              packages (0 disputed; 229 null with a stated reason:
                                 GND, VBUS, 3V3_OUT, EN, SWD, PAD -- not GPIOs).
    webui/api.py (the pad listing) reads `PIN_NAMES` off the board MODULE, not the
                                 JSON, and only atmega328p.py and samd21.py publish one.

So the join OH-26 built is never made. OH-26 left the JSON writes to OH-22, which is done and never made them either, and recorded the one real blocker: on 8 boards (SAMD21, MG24, nRF54L15, nRF54LM20A) 123 resolved pads name a chip pin with no flat integer -- PA02, PC0, P2.08 -- so "the simulator's integer pin" is undefined there and `chip_pin` is the answer. That question was left undecided and this ticket decides it: **the board module's own table is the join**, not the JSON. samd21.py already shows the shape -- a `HEADER` table (label -> the pin the model reads levels through) with `PIN_NAMES` derived from it -- so a label has one meaning in the register read and in the tooltip. What is missing is the same table on the boards that have a description and no HEADER: esp32c3.py, esp32c5.py, esp32c6.py, rp2040.py (a flat GPIO number each), and the label -> GPIO facts already exist in third_party/bsp at a recorded revision (2787dab for arduino-esp32; the C3's D10 = GPIO10, the C6's D10 = GPIO18, the C5's D10 = GPIO10, per OH-156).

For comparison, sim86.com publishes a per-board pin table (its XIAO ESP32-C3 page: D0 -> GPIO2 ... D10 -> GPIO10, "those bus functions are defaults, not fixed wiring") and Xplora3D snaps a wire to a pin by name; neither has more information than this repository already fetched.

STEPS, each checkable:

1. Generate, do not transcribe. Extend tools/import_pindefs.py to EMIT a HEADER table per described board (label -> GPIO number, or -> chip pin string where the vendor has no flat number), with the source file and revision in the generated header, the way the pindefs report already names them. A hand-typed table is the drift CLAUDE.md forbids.
2. Each described board module imports or embeds that table and derives PIN_NAMES from it, as samd21.py does; api.py needs no change.
3. Fill `pin` in the board JSONs from the same generator, so a XIAO pad carries the number its module reads -- and a test asserts JSON pin == module HEADER for every labelled pad, so the two cannot drift. Pads the report leaves null stay null WITH the reason string, not silently.
4. Done when: `import_pindefs.py --all --summary` and the JSON counts agree (generated, both), a wire from a XIAO ESP32-C3 D10 pad reaches GPIO10 in the model (a watched test, the OH-148 shape: the pad's level follows the register), and the 8 no-flat-number boards say in their module which string their pins are and that a wire to them is refused by statement until their core exists.

NOT this ticket: the 229 pads with no GPIO (they are correctly null), and the XIAO-XIAO STM32C5-SMD, which has no board-support package anywhere (0 of 35 pads, OH-26).

**Note 2026-09-04:** Done, with one decision step 3 did not foresee and two sentences this ticket itself got wrong. (1) `pin` STAYS null in every XIAO file. webui/pinmap.py defines that field as the rcontrol pin index of a PICSimLab board, 1..99 -- its validator refuses 0, and the XIAO RP2040's D6 IS GPIO0 -- and tools/inventory.py's `wired` count and README's "Wired to the simulator" list are built on it, so a GPIO number there would be a second fact in a field that has one. The join landed beside it instead: every pad of all 25 registered files now carries `chip_pin` (the vendor's own name -- GPIO10, PA02, P2.08) and `chip_index` (the flat number where a vendor publishes one), a `why_null` on every null pad, and a `pindefs` object naming the packages and their revisions after a regenerated `assumption`. (2) "api.py needs no change" was wrong: the C3's pads are silkscreened `D9/BOOT` and its SMD's underside `D3/MTDI`, the packages define `D9` and `D3`, and pad_view joined on the raw label -- so `api.header_key` joins a compound label onto the half the module defines and pad_view emits `pin` as the module's key; webui/api.py, tests/webui/test_pin_view.py, tools/inventory.py, tools/import_board.py, README.md and .github/workflows/rules.yml were added to this ticket's claims. (3) The ticket's own count "582 pads, 28 carry a pin" is unchanged and still true; what changed is that 321 of them now carry a chip pin as well.

GENERATED, NOT TRANSCRIBED. `--write-headers` rewrites a HEADER block between two markers in every module carrying them (the chips are read off the modules, not listed anywhere), and `--write-boards` fills all 25 files; both are idempotent (second run: 4 and 25 unchanged). esp32c3/esp32c5/esp32c6/rp2040 derive PIN_NAMES from that block and gained a `pin_states` reading ENABLE (or OE) before OUT, each register read once with the header line and bit range cited. samd21.py keeps its own hand-written (group, bit) table: render_header REFUSES to emit a block for a chip whose vendor publishes no flat number, naming the pin and the file. Counts, all generated: 550 XIAO pads, 321 resolved, 229 null, 0 disputed -- unchanged -- plus 3 board LEDs read from the vendors' own variant files (RP2040 PIN_LED = GPIO17, C5 LED_BUILTIN = 27, C6 = 15; the C3's variant defines none, which esp32c3.py had already measured).

WATCHED. tests/riscv32/test_esp32c3_board.py: the C3 blink's GPIO8 is the pad `D8` and the pin view follows it at every transition, with the three power pads unanswerable; and a compiled sketch naming `D10` reads input, low, high, low, high through api.pin_levels. Twenty-one mutations across three rounds each failed the test named for it, including the C3's D10 sent to GPIO11, ENABLE and OUT swapped, a JSON pad's chip_pin altered, and a HEADER row put outside its own part's register width.

REVIEWED, and twelve findings came back. Fixed here: the XIAO STM32C5 (no package covers it at all) no longer borrows the per-label "no package defines this label" sentence, cites an empty `packages` list as though it had been read, or claims a join is "ready, not made" when there is nothing to join; the eight boards whose vendors publish no flat number now say so, with the count of such pins and three real spellings off that board (123 pads across the 8, OH-26's number, recomputed); render_header states the agreement rule instead of claiming every package names every row (false: only arduino-esp32 names the C5's and C6's LED, only arduino-pico the RP2040's, and no Zephyr connector names any); the module docstring's "a pad with pin null draws and refuses a wire" no longer describes files this tool has since rewritten; tools/import_board.py says that re-importing a registered board strips this join until --write-boards is run; select_labels' refusal names all three spellings it tries; the per-part register width in each pin_states docstring is now the bound its test enforces (C3 26, C5/C6 32, RP2040 30) instead of a shared 32; two guards in filled_board that could not fail became one `strict=True`; the fetch-skip in tests is one helper taking the packages its caller reads; and README.md and both of tools/inventory.py's outputs say that "wired" counts the PICSimLab index only and that chip_pin is a different join with a different count.

NOT FIXED HERE, filed as OH-164 (P2): a board you have picked but not loaded labels its modelled pads "in use elsewhere" while nothing is running -- 22 pads on the Arduino Uno, 11 each on the SAMD21, C3 and RP2040 files, 0 where no module exists. It has been true for 3 board files since OH-70 and this ticket widened it to 12. The fix is in webui/static/board3d-panel.js and its test belongs in tests/webui/test_board3d.py, which OH-162 claims.

ALSO CORRECTED ON THE WAY, each a false sentence found while working in the file: esp32c5.py's docstring still said the chip was deliberately not in FIRMWARE_VERIFIED (it has been since test_esp32c5_board.py watched c5blink); esp32c6.py's LED_PIN comment said no Seeed variant file for a C6 was installed (OH-26 fetched one); and api.pad_view's "twenty-four of the twenty-six boards report no pin states" was one too many when written -- samd21.py already had a pin_states, so it was twenty-three, and it is fourteen now.

CI, AND THE BLOCKER THAT CAME WITH IT. .github/workflows/rules.yml gained a "Fetch the board-support packages" step. Without it the only two tests that hold the committed blocks and files against the packages they were generated from skip in every CI run -- the vacuous green this repository's own comments keep naming. The two checks that need no network (every file carries the join; every file agrees with its module across 11 files) catch the two artefacts drifting apart, but not both drifting together away from upstream.

That step then broke the two tests it was added to enable, and the second review round caught it before it ever ran. A CI runner clones each package --depth 1 at today's HEAD, while the committed artefacts cite the revision they were read at, so ANY commit to ANY of the six repositories -- to any file, for any reason -- failed all four modules and all 25 board files at once while every pin still agreed. Reproduced by holding the files identical and returning a different revision: pads identical, only `pindefs` differing. Fixed by comparing the pins with the revision normalised (`_pins_only` and `_document_pins_only`), NOT by checking out the cited revisions -- that would verify the tables against the very commits that produced them, so a pin moving upstream could never fail, which is the only reason the step exists. The revision lives in two places and the first attempt blanked one: the ` @ <rev>` inside each `on_board` pin's `sources` is the second, and the C5 file caught it. What normalisation gives up is taken back by test_the_two_artefacts_cite_the_same_revisions_as_each_other, which needs no network and holds the modules and the files to the same provenance, so running one writer without the other is still caught. Verified with a plugin that reports a revision no artefact cites: revision moved alone, 50 passed; revision moved plus the C3's D10 sent to GPIO11, or the C5's board LED to GPIO28, each fails the artefact tests. The reviewer reproduced all three independently with its own plugin that moves a pin upstream rather than in the file, and returned APPROVE.

LEFT UNDONE AND DELIBERATE: the 229 pads with no GPIO stay null with their reason; tools/import_board.py still writes `pin: null` and its own assumption when re-run, so --write-boards must follow it (test_the_committed_board_files_match_the_generator names the file if it does not); and no wire refusal exists in the 3D view to change -- a pad without a chip_pin is drawn and worded "not modelled", which is what the assumption now says.
