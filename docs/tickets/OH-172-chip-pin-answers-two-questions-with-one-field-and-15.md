---
id: OH-172
title: chip_pin answers two questions with one field, and 153 pads are answered by
  the half nobody meant
status: in-review
priority: P2
created: '2026-09-06'
touches:
- webui/static/board3d-panel.js
- tests/webui/test_pin_view.py
- tests/webui/test_board3d.py
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- tools/inventory.py
- webui/boards/XIAO-MG24-SMD.json
- webui/boards/XIAO-nRF54l15-SMD.json
- webui/boards/XIAO-nRF54LM20A-SMD.json
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

**Note 2026-10-13:** 2026-10-13, SLICE 2 DESIGN, written before any code.

SCOPE. The gate move, and the first captions it lets through. tools/import_pindefs.py's read_seeed_traced stops dropping a pad outside the part's GPIO numbering and returns it as a caption; header_table applies _CHIP_PIN_NAME, so the decision of what may be a HEADER row sits where the answer lands; the board file's unnumbered sentence counts only pins that pass the same gate, and a new sentence says which pads carry a caption. The pads that change are the ones Seeed's own board files already trace to exactly one pad of the MCU, measured before any code as the pinfunction of every pad of the part on the label's net:

    XIAO-MG24-SMD        MG24_EN      net '~{MG24_RESET}'   ['RESET']
    XIAO-nRF54l15-SMD    nRF54_EN     net '~{nRF54_RESET}'  ['~{RESET}']
    XIAO-nRF54LM20A-SMD  nRF54_SWDIO  net 'nRF54_SWDIO'     ['SWDIO_G2']
    XIAO-nRF54LM20A-SMD  nRF54_SWCLK  net 'nRF54_SWCLK'     ['SWDCLK_G1']

Every other label read_seeed_traced follows already reaches a GPIO. None of these boards has a chip module, so no HEADER block changes and no level is read for any of them.

NOT IN SLICE 2: _trace's captions on the manifest rows; SUPPLY_LABELS; plural captions; the RP2350 SMD's EN and the C3, C5 and C6 SMD EN pads; how "not modelled" reads beside a caption. Why each is out is under LEAST CONFIDENT and LEFT below.

SHAPE.

    # tools/import_pindefs.py
    _CHIP_PIN_NAME   # the regex is unchanged. Its comment now names it as the
                     # decision of what may be a HEADER row, applied in header_table
                     # and filled_board rather than in the tracer.

    def read_seeed_traced(texts, *, part, labels, nets=None) -> dict[str, ChipPin | Traced]:
        # the pads of `part` on the label's net, by pinfunction:
        #   one name passes _CHIP_PIN_NAME     -> ChipPin(name, flat)             unchanged
        #   two names pass                     -> PindefError                     unchanged
        #   none passes, exactly one pad       -> ChipPin(<its function>, None)   NEW: a caption
        #   none passes, two or more pads      -> nothing                         unchanged
        # a typed net (`nets`) still comes back Traced, with the caption in it

    def header_table(chip, bsp_dir=BSP_DIR, boards_dir=BOARDS_DIR) -> HeaderTable:
        # NEW: an entry whose chip_pin fails _CHIP_PIN_NAME is skipped before it is
        # keyed or cited. A caption is no row: no level is read through a pin
        # outside the numbering, and its source is not a citation of the block.

    def assumption_for(chip, described, covered, unnumbered=None, resolved=0,
                       unresolved=0, keyed_by=(), manifest=False, cad=(), answered=(),
                       captions: tuple[tuple[str, str], ...] = ()) -> str:
        # NEW `captions`: (label, chip_pin) for each pad whose chip_pin fails the
        # gate, and one sentence saying each is a caption, chip_index null, no level read

    def filled_board(name, bsp_dir=BSP_DIR, boards_dir=BOARDS_DIR, modules_dir=None) -> dict:
        # `unnumbered`: chip_pin passes the gate and chip_index is None (was: any chip_pin)
        # `captions`:   chip_pin fails the gate

    REMOVED: _LANDED_RESET, _MG24_RESET, _NRF54L15_RESET, _NRF54LM20A_DEBUG. A reason
    never overrides an answer, so each would be text nothing reads.

CALL STACK, unchanged:

    --write-boards  -> filled_board -> board_report -> resolve -> published_pins
                    -> Source.pins -> read_seeed_traced
    --write-headers -> header_table -> board_report -> ...; render_header
    the page        -> api.pad_view -> chip_pin_of (the file's chip_pin, on a board with
                       no module) and level_keys (HEADER keys, or a row's chip_index pads)

So the panel shows a caption in the Chip pin column and reads it "not modelled".

TESTS, each to be seen red first:
- New, on _fake_tree: a CAD source answering EN -> ChipPin("RUN", None) on the fake SMD. Before: render_header(header_table("FAKE")) raises "no flat number". After: EN is not in table.pins, the CAD source is not cited, and the SMD's assumption has the caption sentence and no "NO flat number" sentence.
- New: read_seeed_traced on MG24.kicad_pcb gives MG24_EN Traced(ChipPin("RESET", None), ...), and the MG24's GND, on several pads of the part, gives nothing.
- Restated: the underside-pads answer test's reset branch asserts the caption, read off the footprint; the LM20A tracer test asserts SWDIO_G2 and SWDCLK_G1; the typed-net test asserts RESET for MG24_EN.
- Restated: test_the_committed_files_with_unnumbered_pins_are_the_ones_oh_26_named counts pins that pass the gate.
- Restated: test_every_pad_either_names_its_pin_or_says_why_it_has_none, where the four pads move from specific to naming, with a ladder line.
- New, in tests/webui/test_pin_view.py: on every catalogue board, a pad whose chip_pin fails the gate is modelled False, and at least one such pad exists.

LEAST CONFIDENT.
1. A caption is the vendor's pad function verbatim. '~{RESET}' is KiCad's overbar markup, and 'SWDIO_G2' keeps the ball suffix that the gate strips from 'P0.00_K3'. Normalising either would mean guessing what the vendor meant.
2. "Exactly one pad" is counted by pinfunction, because _footprints keeps no pad number. A pin split into two pads would read as two and get no caption. That is conservative, and no traced label hits it.
3. _trace is left for slice 3, although the design pass proposed it here. Measured from the committed files' why_null, the same rule there would caption the 3.3V pad of every row whose module puts the rail on one 3V3 pin, the QT Py's GND (its pad 33 alone), the KB2040's D+ and D- (USB_DP, USB_DM) and !RESET (RUN), and each row's EN or RESET pad that reaches the module's EN. It would also displace the Thing Plus ESP32-C6's typed ESP_EN reason: _trace reaches U1 pad 3 = EN there, and test_every_reason_is_on_a_pad_and_carried_by_it and both pilot-reason tests would need restating. Supplies with captions are the SUPPLY_LABELS question, which the decision note keeps apart.
4. The RP2350 SMD's EN (pad 25 -> TP4, net '/04 RP2350/RUN', RP2350 pad 26 'RUN', OH-209) is left out. Tracing it adds seeed-pcb to both RP2350 files' packages. test_the_two_artefacts_cite_the_same_revisions_as_each_other would then want webui/boards/rp2350.py's block, which OH-161 holds, to cite a source the gate correctly keeps out of it. That test, and the module-agreement test, need restating with the first caption on a board that has a module.

LEFT, for a later slice:
- _trace's captions (3 above), with SUPPLY_LABELS and plural captions. A GND net on many pads all named GND, or on GND and TESTEN as on the KB2040, is a supply question and not this slice's.
- The XIAO SMD EN pads nothing here traces yet: the RP2350's (4 above), whose landing OH-209 measured, and the C3's, C5's and C6's, whose board files are in third_party/seeed-pcb and whose EN pads nobody has joined to a net. Their chips have modules, so the module-agreement test needs restating first.
- The panel's wording beside a caption: "not modelled" next to RESET.

**Note 2026-10-13:** 2026-10-13, SLICE 2 LANDED in lane4 at 8e74efd (with 3fda7f3, the inventory docstring), as the design note above planned it.

WHAT CHANGED. In tools/import_pindefs.py, read_seeed_traced no longer drops a pad outside the part's GPIO numbering. Where the label's net reaches exactly one pad of the part and its function fails _CHIP_PIN_NAME, it returns ChipPin(<that function>, None), a caption, and as Traced where the net was typed in `nets`. A net on two or more such pads still names none: the MG24's GND reaches RFVSS, VREFN, CREGVSS and PAD. _CHIP_PIN_NAME is unchanged and is now applied where the answer lands. header_table skips an entry whose chip_pin fails it before keying or citing it. filled_board counts only gate-passing pins in the unnumbered sentence and passes the rest to assumption_for's new `captions`, which says each is a caption, with chip_index null and no level read through it. The reasons the captions displaced are removed: _LANDED_RESET, _MG24_RESET, _NRF54L15_RESET and _NRF54LM20A_DEBUG. A reason never overrides an answer, so each would have been text nothing reads. tools/inventory.py's collect_boards docstring, slice 1's LOW-6, now calls chip_pin a caption rather than the pin a module reads a level through.

REGENERATED with python tools/import_pindefs.py --write-headers --write-boards. Three files were written: XIAO-MG24-SMD.json, XIAO-nRF54l15-SMD.json and XIAO-nRF54LM20A-SMD.json. No module block changed, and a second run reported all 42 unchanged. The four pads, from the files:
    XIAO-MG24-SMD        MG24_EN      chip_pin RESET
    XIAO-nRF54l15-SMD    nRF54_EN     chip_pin ~{RESET}
    XIAO-nRF54LM20A-SMD  nRF54_SWDIO  chip_pin SWDIO_G2
    XIAO-nRF54LM20A-SMD  nRF54_SWCLK  chip_pin SWDCLK_G1
Each has chip_index null and no why_null. Each file's assumption ends with the caption sentence, and its derivation lists the pad among those the vendor's CAD answered.

NOTHING CLAIMS A LEVEL FOR A CAPTION. Over catalogue.board_names(), picked: every pad whose chip_pin fails _CHIP_PIN_NAME, with its modelled flag:
    python -c "from webui import api; from webui.boards import catalogue; from tools.import_pindefs import _CHIP_PIN_NAME; rows=[(b, p['label'], p['chip_pin'], p['modelled']) for b in catalogue.board_names() for p in api.pad_view(b, api.description_for(b), None)['pads'] if p['chip_pin'] is not None and not _CHIP_PIN_NAME.match(p['chip_pin'])]; [print(*r) for r in rows]"
    XIAO-MG24-SMD MG24_EN RESET False
    XIAO-nRF54LM20A-SMD nRF54_SWDIO SWDIO_G2 False
    XIAO-nRF54LM20A-SMD nRF54_SWCLK SWDCLK_G1 False
    XIAO-nRF54l15-SMD nRF54_EN ~{RESET} False
Slice 1's measure, rerun: 187 pads on 12 boards carry a caption and are not modelled, and 0 are modelled without one. It was 180 at slice 1. OH-224 added three GPIO captions and this slice added four.

IN A BROWSER. python webui/emulator_server.py --bind 127.0.0.1 --port 8089, driven with Playwright and stopped by its listening PID. With XIAO-MG24-SMD picked, the Pins table reads "MG24_EN | RESET | not modelled", and D0 reads "PC0 | not modelled". With XIAO-nRF54l15-SMD picked, it reads "nRF54_EN | ~{RESET} | not modelled" and "54L15_TX20 | P1.08 | not modelled". The page's console shows one 400 from GET /api/board/pins with no board loaded. Earlier sessions' logs show the same 400, so this slice did not cause it. The screenshots were moved out of the checkout.

TESTS. Each was red before the change and is green after.
- test_a_pin_outside_the_numbering_is_a_caption_and_never_a_header_row (new, on _fake_tree): a CAD source answers EN -> ChipPin("RUN", None) on the fake SMD. Red: EN was in table.pins. A probe of the same tree showed render_header raising "FAKE: ['EN'] name a chip pin with no flat number (RUN)". The assumption also said "1 pins on this board are named with NO flat number -- RUN".
- test_a_traced_pad_on_one_pad_of_the_part_outside_its_numbering_is_a_caption (new): MG24_EN gives Traced(ChipPin("RESET", None), ...), the MG24's GND gives nothing, and SWCLK is still PA01. Red: {} == {...}.
- test_a_traced_label_that_reaches_nothing_is_refused_rather_than_silent (restated): the nRF54LM20A's SWD pads give SWDIO_G2 and SWDCLK_G1. Red: {} == {...}.
- test_a_net_typed_for_a_traced_label_must_reach_the_part (restated): MG24_EN's pin is RESET. Red: KeyError 'MG24_EN'.
- test_the_mg24_and_nrf54l15_underside_pads_answer_from_seeeds_own_board_file (restated): each landed pad's chip_pin is the footprint's pad function, the GPIO through the gate or the reset verbatim, with no why_null and no reason in the registry. Red: MG24_EN (None, None) != ('RESET', None).
- tests/webui/test_pin_view.py test_a_caption_outside_the_gpio_numbering_is_shown_and_never_modelled (new): on every catalogue board, picked and running on a zero bus, a pad whose chip_pin fails the gate is modelled False, and the MG24's MG24_EN is among them. Red: the list was empty.
- Restated by the counts moving, with a ladder line each: test_every_pad_either_names_its_pin_or_says_why_it_has_none (naming 565 -> 569, specific 69 -> 65), and test_a_generated_reason_reads_the_supplies_the_crystal_and_the_debugger (crystals 6 -> 4).
- test_the_committed_files_with_unnumbered_pins_are_the_ones_oh_26_named counts only gate-passing pins and still holds 136.

BREAKS. Each was applied alone and each turned its test red. Every file was restored and checked by sha256.
- M1, header_table's gate removed: the fake-tree test.
- M2, the unnumbered sentence's gate removed: the fake-tree test, and test_the_committed_board_files_match_the_generator.
- M3, the caption branch removed from read_seeed_traced: the three tracer tests, and the generator-equality test.
- M4, a caption taken from the first pad however many: the new tracer test, on GND.
- M5, the caption sentence dropped: the fake-tree test, and the generator-equality test.
- M6, MG24_EN hand-edited to RST in its board file: the underside answer test, and the generator-equality test.
- M7, a reason left in the registry for MG24_EN: the underside answer test.
- M8, the unnumbered test's filter without the gate: that test.
- M9, api.level_keys monkeypatched in memory to answer every captioned pad (webui/api.py is OH-161's and was not edited): the pin view test, on MG24_EN.

INVENTORY, python tools/inventory.py, before at 4bcd540 and after:
    TWINS: 26 of 38 boards hold all four; by layer: geometry 38, model 37, pins 37, runs 26     (unchanged)
    XIAO-MG24-SMD        pins 21+4/25 -> 22+3/25
    XIAO-nRF54LM20A-SMD  pins 30+7/37 -> 32+5/37
    XIAO-nRF54l15-SMD    pins 21+6/27 -> 22+5/27
Nothing else moved except the test counts.

VERIFIED.
- python -m pytest -q -p no:cacheprovider tests/rules/test_import_pindefs.py tests/rules/test_inventory.py tests/rules/test_board_manifest.py tests/webui/test_pin_view.py tests/webui/test_board3d.py tests/webui/test_board_catalogue.py: 485 passed, 1 skipped (OH_SLOW's variant survey), at 3fda7f3. Before the change: 482 passed, 1 skipped.
- Checker rows, each run on its own, each exit 0 and OK: check_layering, check_board_contract, check_part_schemas, check_licenses, check_deltas, check_banned_symbols, check_board_claims, check_ticket_claims, ticket_guard --self-test 6/6, check_facts, and board-sources render.py --check. checkall.missing_from_table() is empty.
- Neither checkall.py nor the full suite was run.

LEFT, for a later slice:
(1) _trace's captions on the manifest rows: 3.3V on a module's one 3V3 pin, the QT Py's GND, the KB2040's D+, D- and !RESET, and each row's EN or RESET pad. This displaces the Thing Plus ESP32-C6's typed ESP_EN reason, because _trace reaches U1 pad 3 = EN there. It goes with SUPPLY_LABELS, and with plural captions such as GND on GND and TESTEN.
(2) The XIAO SMD EN pads nothing traces yet. The RP2350's needs webui/boards/rp2350.py (OH-161) or a restated test_the_two_artefacts_cite_the_same_revisions_as_each_other. The C3's, C5's and C6's have not been joined to a net. All four boards have modules, so test_the_board_file_and_the_module_agree_on_every_labelled_pad needs restating to "a key in HEADER means chip_pin == PIN_NAMES[key]; otherwise chip_pin is null or fails the gate", and the Uno test's equality needs restricting to HEADER keys.
(3) assumption_for's described-board sentence, "a pad with a `chip_pin` answers for itself in the pin view", would contradict the caption sentence on the first described board with a caption. No such board exists yet.
(4) The panel's wording beside a caption: "not modelled" next to RESET.
(5) README.md:86-90's count, which slice 1 recorded and which is unclaimed.

STATUS. in-review, for slice 2's review. The ticket is not done: LEFT above is its next slice. Its claims grew by tools/import_pindefs.py, tests/rules/test_import_pindefs.py, tools/inventory.py and the three regenerated board files, and tests/webui/test_board3d.py is still borrowed from OH-215.

**Note 2026-10-13:** 2026-10-13, SLICE 2 REVIEW FIX ROUND. The verdict was COMMENT (mergeable). Fixes are in 28f8050 (pindefs and its tests), d1404d4 (the panel) and 546614a (inventory's prose), on top of 97f1b86. The ticket stays in-review.

MEDIUM-1. Failing _CHIP_PIN_NAME is not the same as "outside the GPIO numbering". On Espressif footprints the caption branch would caption real GPIOs: the C6's GPIO4{slash}MTMS reaches a pad named MTMS, the C5's D1{slash}GPIO0 reaches XTAL_32K_P, and the C5's D7{slash}RX{slash}GPIO12 reaches U0RXD.
- FIX. In read_seeed_traced's one-pad branch, the net's own name is split on {slash}, / and _. If any part is a pin by _CHIP_PIN_NAME or _NAMED_GPIO, the label is refused, with an error naming the net, the pad function and the token.
- WHY REFUSE AND NOT ANSWER. Answering from the name would make the tracer a second net-name reader, whose answer the copper does not confirm. _trace has the same rule: a name is a cross-check and never the source. read_seeed_net_names (seeed_pcb) is the reader that takes pins from names, and the C6's entry already reads MTMS that way.
- THE GENERATED SENTENCE now says only what is known: "`MG24_EN` reaches a pad the vendor's footprint names `RESET`, with no GPIO number, so its `chip_pin` is a caption only: `chip_index` is null and no level is read through it." The comments that said "outside the numbering" in general now say the same, and say why: an ESP32's MTMS pad is GPIO4.
- TEST, new: test_a_pad_with_no_gpio_number_on_a_net_named_for_a_gpio_is_refused. It uses the C6's MTMS, then checks that read_seeed_net_names gives GPIO4 and that BOOT is still GPIO9. Red first: DID NOT RAISE.
- BREAK B1: the refusal disabled. The test went red.
- MEASURED after the fix: the review's three cases are refused. The C6's D7{slash}RX would still caption U0RXD, because no part of that net's name is a pin. The sentence claims only "no GPIO number", which is true. And on that board a package's GPIO beside the caption disputes the pad rather than letting the caption stand.

LOW-1. New test_every_registry_reason_is_carried_by_a_pad_nothing_answered. On every non-manifest board, a pad whose label has a reason in BOARDS has no chip_pin, and its why_null is that reason. This mirrors test_board_manifest.py's test for the rows.
- BREAK B2, the review's probe G1: a reason put back on the nRF54LM20A's nRF54_SWDIO. The test went red; before this round, nothing did.

LOW-2. read_seeed_traced now gathers every net's answer for a label, and refuses a label when two nets answer it differently. Two nets with one answer are one answer. It also refuses a net that reaches a GPIO pad and another pad of the part, as _trace does; the GPIO used to win silently. No real board hits either case: no traced part has two nets ending in one label.
- TEST, new: test_a_label_answered_two_ways_by_its_copper_is_refused, on a three-line KiCad fixture, _seeed_board. Red first: DID NOT RAISE, on both refusals.
- BREAK B3: the two-nets refusal disabled. BREAK B4: the GPIO-plus-another-pad refusal disabled. Each went red.

LOW-3. New test_a_net_on_several_pads_of_one_function_names_none_of_them, on the nRF54L15's VSYS_3V3 (VDD, VDD) and the C5's GND (four GND pads). Both give {}. This is a control and held before the fix.
- BREAK B5: the reviewer's surviving mutant, len(set(functions)) == 1. It is now killed.

LOW-4. The Chip pin column draws KiCad's ~{X} as X with a CSS overline, and keeps the verbatim caption in the cell's title. The data is unchanged. captionParts, in webui/static/board3d-panel.js, splits a caption into plain runs and overlined runs.
- TEST, new: test_a_caption_in_kicad_overbar_markup_is_drawn_overlined_and_kept_verbatim, in tests/webui/test_board3d.py. It runs captionParts under node on seven captions, ~11 among them, and checks that renderTable uses it. Red first: the caption was printed raw.
- BREAK B9: the overbar read as plain text. The test went red.
- BALL SUFFIX, NOT STRIPPED, and why. The gate drops whatever follows a GPIO name, because the GPIO name is what it reads. A pad with no GPIO number has no name to anchor on. A generic rule for a trailing _<letter><digit> would also cut a function such as ADC1_CH1, and which suffix is a ball is a fact about the package. So SWDIO_G2 stays as the vendor wrote it. pinOrder's tilde handling is unchanged: it sorts labels, and no caption reaches it.

LOW-5.
(a) The sentence for a board no package covers counts only gate-passing pins: "Of those, N is/are the only pad(s) ...". With no captions the output is byte for byte what it was; the STM32C5's file did not change.
(b) header_table's on_board list is gated as rows are.
(c) filled_board refuses a caption that carries a chip_index, naming the pad, the pin and the number.
- TESTS, new: test_a_board_no_package_covers_counts_only_the_pins_the_gate_takes, red first because "Those 2 pads" was there; and test_a_caption_never_sits_in_the_on_board_rows_or_carries_an_index, red first because on_board was ('LED',).
- BREAKS: B6, the old count restored, turned the first red. B7, on_board ungated, and B8, the index refusal disabled, each turned the second red.

LOW-6. The nRF54L15 SMD's nRF54_SWDIO and nRF54_SWCLK are traced now, as the nRF54LM20A's are, and _NRF54L15_DEBUG is removed. Each net reaches one pad of the part, SWDIO and SWDCLK, and they become captions. The RP2350's pair is untraced and keeps its reason.
- TEST, restated: test_a_dedicated_debug_pad_says_so_rather_than_that_nobody_named_it now holds the RP2350's reason, and holds the nRF54L15's captions against the footprint.
- COUNTS, restated with a ladder line each: naming 569 -> 571, specific 65 -> 63, crystals 4 -> 2.
- BREAK B10: nRF54_SWDIO hand-edited to SWD in the board file. This test and the generator-match test went red.

NOTE-ONLY. tools/inventory.py's markdown sentence about chip_pin no longer says every pin came from a board-support package and levels come "through the same table". It now says chip_pin is a caption, and that `modelled` says where a level is read. The per-pad position join is still printed by `python tools/import_pindefs.py <board>` and not stored in the file.

Every break was applied alone, and every file was restored and checked by sha256.

REGENERATED with python tools/import_pindefs.py --write-headers --write-boards. It wrote XIAO-MG24-SMD.json, XIAO-nRF54l15-SMD.json and XIAO-nRF54LM20A-SMD.json, whose assumption sentences changed. The nRF54L15 file also gained two captions. A second run reported all 42 unchanged.

CAPTIONS NOW, via api.pad_view over the catalogue, picked. Each has modelled False:
    XIAO-MG24-SMD        MG24_EN      RESET
    XIAO-nRF54LM20A-SMD  nRF54_SWDIO  SWDIO_G2
    XIAO-nRF54LM20A-SMD  nRF54_SWCLK  SWDCLK_G1
    XIAO-nRF54l15-SMD    nRF54_EN     ~{RESET}
    XIAO-nRF54l15-SMD    nRF54_SWDIO  SWDIO
    XIAO-nRF54l15-SMD    nRF54_SWCLK  SWDCLK

INVENTORY, python tools/inventory.py:
    TWINS: 26 of 38 boards hold all four; by layer: geometry 38, model 37, pins 37, runs 26     (unchanged)
    XIAO-nRF54l15-SMD    pins 22+5/27 -> 24+3/27
Nothing else moved except the test counts.

VERIFIED.
- python -m pytest -q -p no:cacheprovider tests/rules/test_import_pindefs.py tests/rules/test_inventory.py tests/rules/test_board_manifest.py tests/webui/test_pin_view.py tests/webui/test_board3d.py tests/webui/test_board_catalogue.py: 492 passed, 1 skipped (OH_SLOW's variant survey), on the tree committed as 546614a. Slice 2 was 485 passed.
- Checker rows, each run on its own, each exit 0 and OK: check_layering, check_board_contract, check_part_schemas, check_licenses, check_deltas, check_banned_symbols, check_board_claims, check_ticket_claims, ticket_guard --self-test 6/6, check_facts, and board-sources render.py --check. checkall.missing_from_table() is empty.
- Neither checkall.py nor the full suite was run.

LEFT is as the slice 2 note says, with one item added. A pad its footprint names by function, on a net whose name carries no pin -- the C6's D7{slash}RX to U0RXD, which is GPIO17 -- would still be captioned if traced. On a covered board a package's GPIO beside that caption disputes the pad. A board no package covers would show the caption alone.
