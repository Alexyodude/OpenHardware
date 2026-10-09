---
id: OH-172
title: chip_pin answers two questions with one field, and 153 pads are answered by
  the half nobody meant
status: in-progress
priority: P2
created: '2026-09-06'
touches:
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

**Note 2026-10-09:** 2026-10-09, slice 1 landed at ee21ae0.

WHAT CHANGED. `pad_view` gives every pad a `modelled` bool, true where the board's own level reader answers under the pad's name. webui/api.py's new `level_keys(board, description, layout)` answers that without a CPU: the module's `HEADER` where it has `pin_states`, and a manifest row's `chip_index` pads where its chip module names `GPIO`, `GPIO_ENABLE` and `GPIO_OUT`. A padless row the reader lists (a XIAO's `LED`) is modelled. `chip_pin` is unchanged and is the caption only. The comments that said otherwise now say so: `chip_pin_of`'s docstring, the `PIN_STATES` comment, `pin_view`'s comment on a module with names and no reader, and the panel's "if and only if" comment. In webui/static/board3d-panel.js, `unknownWords` returns "not modelled" unless `pad.modelled === true`, and the Chip pin column still shows `pad.chip_pin ?? "—"`. `level_keys` restates `row_levels`' word check instead of sharing it. `row_levels` needs the words' values and `level_keys` only needs to know they exist, so a shared predicate would be a second lookup with one caller each. The new test holds the two equal on every catalogue board.

MEASURED 2026-10-09 over catalogue.board_names(), every board picked and not loaded, after the change:

    python -c "from webui import api; from webui.boards import catalogue; v=[(b, p['chip_pin'] is not None, p['modelled']) for b in catalogue.board_names() for p in api.pad_view(b, api.description_for(b), None)['pads']]; c=[b for b, named, m in v if named and not m]; u=[b for b, named, m in v if m and not named]; print(len(c), len(set(c)), len(u))"
    -> 180 12 0

So 180 pads on 12 boards carry a caption and are not modelled, and no pad is modelled without one. Those 180 are exactly the pads whose words moved, all from "no program running" to "not modelled". A scratch script applied unknownWords' rule to every pad, using chip_pin at f1c8623 and modelled at ee21ae0, both picked and running on a zero bus. The diff was 180 picked pads on 12 boards and 0 running pads. By board: XIAO-ESP32-S3-DIP 11, XIAO-ESP32-S3-SMD 17, XIAO-ESP32-S3-SMD_PAD 17, XIAO-MG24-DIP 19, XIAO-MG24-SMD 21, XIAO-XIAO STM32C5-SMD 2, XIAO-nRF52840-DIP 11, XIAO-nRF52840-SMD 13, XIAO-nRF54LM20A-DIP 10, XIAO-nRF54LM20A-SMD 30, XIAO-nRF54l15-DIP 11, XIAO-nRF54l15-SMD 18. Picked pads reading "no program running" went from 562 to 382. No board with a reader changed, which the design pass predicted and this measures.

TESTS. Each one was red against f1c8623's api.py and board3d-panel.js and is green now.
- tests/webui/test_pin_view.py test_a_pad_is_modelled_exactly_where_its_board_reads_a_level (new). On every catalogue board, picked, and also running wherever the board reads, each pad's `modelled` is a bool and equals `pad["pin"] in` what pin_levels answers on a zero bus. The XIAO-MG24-SMD's D0 is (PC0, False). Red before the change: KeyError 'modelled'. Mutations it kills: modelled = chip_pin is not None; a padless reader row with modelled False; a row pad without chip_index counted as modelled.
- test_a_view_says_whether_any_levels_were_read_at_all (rewritten, OH-164). would_have_lied now asks for a pad that is unknown and modelled. silent is named: it is the twelve boards above, so the MG24 is now in silent and the Uno in would_have_lied. Red: KeyError. Kills: modelled = chip_pin is not None.
- test_a_running_board_whose_module_reads_no_pins_still_says_one_is_running (one assertion added). A stub with PIN_NAMES and no pin_states models no pad. Red: KeyError. Kills: level_keys answering PIN_NAMES' keys whether or not a reader exists.
- test_a_row_whose_chip_module_names_no_gpio_words_reports_no_levels (one assertion added). A row whose stand-in module names no GPIO words models no pad. Red: KeyError. Kills: level_keys' row branch without the words check.
- tests/webui/test_board3d.py test_not_modelled_is_decided_by_the_modelled_flag_and_not_by_the_caption. It replaces test_the_two_sentences_are_told_apart_by_the_pin_and_not_by_a_guess, which asserted "chip_pin" in the chooser. The test extracts unknownWords and its three sentences from the panel and runs them under node on six pads. {modelled:false, chip_pin:"PC0"} gives "not modelled" both picked and running. {modelled:true, chip_pin:"GPIO2"} picked gives "no program running". {modelled:true} running gives "in use elsewhere". A pad carrying only chip_pin gives "not modelled" both ways. Red: three of the six were wrong against master. Kills: the chip_pin test restored, and `modelled === false`, which lets a pad without the field through.
Seven mutations were run and all seven were killed. Every file was restored and checked by sha256.

END TO END. python webui/emulator_server.py --port 8099 on loopback, driven with urllib, then stopped:

    GET /api/board/pins?board=XIAO-MG24-SMD -> 200, read_levels false
      {"label": "D0", "pin": "D0", "chip_pin": "PC0", "modelled": false, "state": "unknown"}
      {"label": "GND", "pin": "GND", "chip_pin": null, "modelled": false, "state": "unknown"}
    GET /api/board/pins?board=Arduino Uno -> 200, read_levels false
      {"label": "13", "pin": "13", "chip_pin": "PB5", "modelled": true, "state": "unknown"}
      {"label": "GND", "pin": "GND", "chip_pin": null, "modelled": false, "state": "unknown"}

Nobody has looked at it in a browser.

VERIFIED.
- python tools/build_core.py built avr, cortexm0, i8086 and riscv32.
- python -m pytest -q -p no:cacheprovider tests/webui/test_pin_view.py tests/webui/test_board3d.py: 148 passed, none skipped.
- python tools/checkall.py: eleven rows PASS and "the test suites pass" FAIL. checkall cuts off pytest's output, so the failures are named from the full run below.
- python -m pytest -q -p no:cacheprovider -rfE: 3 failed, 2650 passed, 41 skipped in 522.69s. Two of the failures are the OCP pair, test_a_part_that_names_a_lens_it_has_lost_still_refuses_to_convert and test_the_tessellator_welds_what_it_meshes. The third, tests/webui/test_compile.py::test_a_failed_build_leaves_nothing_behind, found an openhardware-build-* directory in the shared temp folder while lane2 was building at the same time. It passed when run alone.

LEFT, as the 2026-10-09 decision says: everything after slice 1. That is captions for EN, RUN, GND and other non-GPIO pins; moving the _CHIP_PIN_NAME gate; plural captions for supply nets; EN, RESET and RST leaving SUPPLY_LABELS; and how "not modelled" reads beside a named chip pin. The ticket stays in progress.

**Note 2026-10-09:** 2026-10-09, slice 1's review: MERGE AFTER SMALL FIXES. The fixes are at d9d1c6b.

FIXES, each in d9d1c6b.
- MEDIUM-1. Nothing tested level_keys' reader guard. The stub named_but_silent in test_a_running_board_whose_module_reads_no_pins_still_says_one_is_running now has HEADER={"D0": (0, 2), "D1": (0, 4)}, samd21's shape. KILL: the reviewer's mutant replaces the non-row half with `return frozenset(getattr(description, "HEADER", ()))`. At be64bfa it passed all 148 tests. At d9d1c6b it fails the stub test, with D1 modelled True, and the new refusal test, with DID NOT RAISE. Take the stub's HEADER out again and only the refusal test fails, so the HEADER is what lets the stub test see this mutant. A guard that asks for HEADER instead of pin_states fails the same two tests.
- LOW-2. pin_view's coalesce comment, the stub test's docstring and its assertion message all said that without `or {}` every modelled pad would read "no program running". All three now say this: where pin_levels answers None, level_keys is empty, so every pad reads "not modelled" with or without the coalesce. The coalesce keeps read_levels true for a running board and changes no word on the page. Only the panel's row loop reads read_levels, and it passes it to unknownWords, which asks modelled first.
- LOW-3. The docstring of test_a_running_board_still_reports_the_pins_its_timers_took now says "modelled pads that are still unknown".
- LOW-4. test_a_pad_is_modelled_exactly_where_its_board_reads_a_level now asserts `api.level_keys(board, description, pinmap.load(board)) == frozenset(levels)` on every catalogue board. pinmap.load(board) is the layout pad_view passes. KILL: a row branch that also answers the chip module's HEADER (`... | frozenset(getattr(description, "HEADER", ()))`) fails it on the Adafruit Feather ESP32-C6, with BOOT, D0 and more as extra keys. With the new line taken out, the same mutant passes all 149 tests.
- LOW-5. Option (a). level_keys' docstring names the three things its row half restates from row_levels: the word names GPIO, GPIO_ENABLE and GPIO_OUT; the chip_index filter; and the header_key(pad.label, {}) key spelling. It names pad_view's empty names for a row as a third copy of that spelling. Why not (b): a helper serving both callers would return the words and a keyed index map. That interface is no simpler than the lines it hides, and it would have two callers in one file (.claude/CLAUDE.md rules 6 to 8). LOW-4's assertion keeps the copies equal.
- LOW-7. When a module has pin_states and no HEADER, level_keys now raises contract.RuntimeContractError naming the module: "<module> has pin_states and no HEADER, so nothing names the pins it reads a level for: ...". The new test test_a_module_with_a_reader_and_no_header_is_refused_by_name goes through pad_view on XIAO-SAMD21-DIP. KILLS: removing the refusal (be64bfa's behaviour) raises AttributeError and fails it. A refusal that drops the module's name fails its name assertion.
- Open question. The docstring of test_a_pad_names_its_chip_pin_on_a_board_with_no_module_at_all now says the defect was the missing caption, not those words: OH-167 restored the caption and OH-172 restored the words.
Every mutant ran against tests/webui/test_pin_view.py and tests/webui/test_board3d.py. Each file was restored afterwards and checked by sha256.

OUTSIDE OH-172'S CLAIMS. These are left for whoever holds the files and were not edited.
- LOW-6, tools/inventory.py:250-251, held by OH-213. collect_boards' docstring calls a file's chip_pin "the MCU pin the board's own module reads a level through". Since OH-172 chip_pin is a caption. That sentence is false for a board with no module, where chip_pin comes from the board file and nothing reads it. It is also false for a manifest row, where row_levels reads at chip_index.
- README.md:86-90, unclaimed according to `tools/tickets.py owner README.md`, says "the eleven files whose chip has a board module" report levels "through the same table". Measured 2026-10-09: 26 of the 38 board files have a chip with a board module, and 12 of those 26 are manifest rows whose levels row_levels reads at chip_index, not through the module's table. Command: python -c "from webui import api; from webui.boards import catalogue; b=catalogue.board_names(); m=[x for x in b if api.description_for(x) is not None]; print(len(b), len(m), len([x for x in m if api.is_row(x)]))" -> 38 26 12

VERIFIED at d9d1c6b.
- python -m pytest -q -p no:cacheprovider tests/webui/test_pin_view.py tests/webui/test_board3d.py: 149 passed in 37.77s.
- Every row of tools/checkall.py's table except the test-suite row, each run on its own: check_layering OK, check_board_contract OK, check_part_schemas OK, check_licenses OK, check_deltas OK, check_banned_symbols OK, check_board_claims OK, check_ticket_claims OK, ticket_guard --self-test 6/6 OK, check_facts OK, and render.py --check reports survey.md is current. checkall.missing_from_table() is empty.
- The full suite was not run here, because other worktrees are running theirs. It runs on master after the merge.

The ticket stays in progress. Slice 2 onward is as the 2026-10-09 decision lists it.

**Note 2026-10-10:** SLICE 1 MERGED to master by fast-forward at 1e551db (lane4): the page's 'not modelled' reads a per-pad modelled flag from api.level_keys, chip_pin is a caption only. REVIEW: an independent review (MERGE AFTER SMALL FIXES), its fix round, and a verification (PASS). VERIFIED on master at 1e551db with OH-161's delay() work: full suite 2 failed (the OCP pair), 2669 passed, 41 skipped. Not seen in a browser. The verification also found the pins route answers a RuntimeContractError with a dropped connection rather than an HTTP status (unchanged by this slice, unreachable by any shipped module; webui/emulator_server.py is not this ticket's). tests/webui/test_board3d.py stays borrowed from OH-215 until this ticket closes. Slice 2 onward remains.

**Note 2026-10-10:** 2026-10-10: webui/api.py lent to OH-161, whose step 3 adds BoardSession.drive (a recorded input level per pad) on the path from the bench to an ESP32's GPIO_IN. Slice 2 here starts in tools/import_pindefs.py and does not need it yet. Return it when OH-161's step 3 lands.
