---
id: OH-224
title: The XIAO MG24 and nRF54L15 SMD boards are four pads short of the pins layer,
  and Seeed's own board files answer them
status: in-review
priority: P2
created: '2026-10-12'
touches:
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- webui/boards/XIAO-MG24-SMD.json
- webui/boards/XIAO-nRF54l15-SMD.json
---

Measured 2026-10-12 from `python tools/inventory.py` on master: the TWINS pins layer fails on three boards, and two of them are short only a few pads that Seeed's own board files can answer.

    XIAO-MG24-SMD        unanswered on MG24_EN
    XIAO-nRF54l15-SMD    unanswered on nRF54_EN, 54L15_RX20, 54L15_TX20
    XIAO-XIAO STM32C5-SMD  no vendor source at all (OH-163 step 4, OH-26); not this ticket

Each of the four carries the generic `why_null` "no board-support package covering this board defines this label", which the pins layer counts as unanswered. But `tools/import_pindefs.py` already reads `MG24.kicad_pcb` (seeed_pcb_traced, SWDIO and SWCLK) and `nRF54L15.kicad_pcb` (seeed_pcb, NFC1 and NFC2) out of `third_party/seeed-pcb`, and OH-200 answered the XIAO C5 and C6 SMD pads the same way.

STEPS:
1. Trace each of the four pads' nets in Seeed's own board file to the MCU's own pad. Where the net reaches a GPIO in the chip's numbering (RX20/TX20 look like P1/P2 UART pins), the pad gains that `chip_pin`, read from the file, not typed. Where it reaches a dedicated pin (an EN pad most likely reaches the chip's reset/enable pin), the pad gets a specific `why_null` naming that pin and the net, in the shape the board files already use for "a dedicated debug pad of the nRF54L15, not a GPIO".
2. The `_CHIP_PIN_NAME` gate stays where it is: OH-172's slice 2 is where a non-GPIO pin may become a caption; this ticket only answers the pads within today's rules, and says so in its note so OH-172 can pick them up.
3. Regenerate the two board files with the importer, held by the existing test that the committed files reproduce exactly; nothing hand-edited.
4. Check what else reads those pads (pin view, inventory, the 3D panel) and that nothing claims a level for them: neither chip has a module, so OH-172's `modelled` is false for every pad on both boards regardless.

Done when `python tools/inventory.py` shows the pins layer holding on both boards, every new answer cites the board file's net, and the regeneration test holds the files.

**Note 2026-10-12:** Done in lane4 at 185bf3c, in review.

PADS. None of the four is on a net named for it. Each lands, by position, on one of the module's underside test points, and that point's net is traced to the MCU's own pad in Seeed's board file:
  XIAO-MG24-SMD      MG24_EN     pad 24 -> TP4,  net '~{MG24_RESET}'          -> EFR32MG24 pad 13 'RESET'                  why_null (a reset pad, not a GPIO)
  XIAO-nRF54l15-SMD  nRF54_EN    pad 25 -> TP4,  net '~{nRF54_RESET}'         -> nRF54L15 pad D2 '~{RESET}'                why_null (a reset pad, not a GPIO)
  XIAO-nRF54l15-SMD  54L15_TX20  pad 15 -> TP11, net 'P1.08{slash}SAMD11_TX'  -> nRF54L15 pad F7 'P1.08/EXTREF/CLK16M/CK'  chip_pin P1.08
  XIAO-nRF54l15-SMD  54L15_RX20  pad 16 -> TP12, net 'P1.09{slash}SAMD11_RX'  -> nRF54L15 pad B3 'P1.09'                   chip_pin P1.09
Both reset nets also carry the reset button, an RC and the MOSFET the on-board SAMD11 pulls reset through. The TX20 and RX20 nets also carry a pad of the SAMD11 debugger, which the tracer leaves out because it matches the part by value.

HOW. seeed_pcb_traced takes `nets`: a label and the net its pad lands on, traced exactly as a net named for the label is. The pin is read off the MCU's footprint, never typed; a typed net that reaches no pad of the part raises, naming the net. The label-to-net join is by position and is not in the generator. It needs the footprint from the seeed-xiao tree beside the board file from seeed-pcb, which a Source cannot cite together, and the nRF54L15's test points sit further off the footprint's frame than the RP2350's 0.01 mm. So the generator gets the net names typed, and a test reads both files to hold them. The four answers come from the existing tracer with that one parameter; there is no table of answers. The two reasons use a new template, _LANDED_RESET, in the shape of _DEDICATED_RESET. Unlike _DEDICATED_RESET, it says the pad is on the net, because the net was followed. It cites the board file, the test point, the net, the chip's pad and its name, and the span of numbered pads, with no count. _CHIP_PIN_NAME is unchanged. RESET and ~{RESET} becoming captions is OH-172 slice 2's to decide.

TESTS, each red before the change. test_the_mg24_and_nrf54l15_underside_pads_land_on_the_nets_the_registry_traces was red with "registry names a net by position for [], not for ['MG24_EN']". test_the_mg24_and_nrf54l15_underside_pads_answer_from_seeeds_own_board_file was red because MG24_EN still had the generic sentence. test_a_net_typed_for_a_traced_label_must_reach_the_part was red with a TypeError (unexpected keyword 'nets'). The helper _underside_landings sets the frame from the castellated edge. A pad lands on a test point whose centre is inside the pad's own copper (nearer than half its narrower side), exactly one point per pad and one pad per point. Every pad whose label is a {slash} part of a net must land on that net or one 0R link from it; that is how the nRF54L15 brings out D11 and D12 through R16 and R17.

BREAKS, each turned a test red:
- TX20 and RX20 nets swapped in the registry: the landing test and test_the_committed_board_files_match_the_generator.
- MG24_EN typed onto '/04 ATSAMD11D14A/MGM_RST_CTL': the landing test; the generator raised.
- The tracer made to ignore `nets`: the typed-net test.
- 54L15_TX20 hand-edited to P1.09 in the board file: the answer test.
- These reason clauses changed in the registry and the file alike: TP4->TP5, PD05->PD04, pad 13->pad 12, '~{nRF54_RESET}'->'~{SAMD11_RESET}', nRF54L15.kicad_pcb->MG24.kicad_pcb. Each turned the answer test red.
- D13<->D14 and D11<->D12 swapped on the nRF54L15, and D16<->D17 on the MG24: the frame witness.
The counted states moved by exactly the four: test_every_pad_either_names_its_pin_or_says_why_it_has_none now holds 564 naming, 70 specific, 0 generic. test_the_committed_files_with_unnumbered_pins_are_the_ones_oh_26_named holds 135. Each count carries its ladder line. The negative control in test_a_dedicated_debug_pad_says_so_rather_than_that_nobody_named_it used to assert that some non-supply pad still had the generic sentence. Now it asserts that the phrase still matches the supply pads, which keeps the filter from matching nothing, and that no non-supply XIAO pad carries it.

REGENERATED with python tools/import_pindefs.py --write-headers --write-boards. Only XIAO-MG24-SMD.json and XIAO-nRF54l15-SMD.json were written; a second run reported all 42 files unchanged. Before the change, the generator reproduced every committed board file and HEADER block exactly. Both files' seeed-pcb revision is unchanged, because the file is hashed once. OH-172: description_for is None for both boards, and api.pad_view reports read_levels False and modelled False on every pad of both, the four included.

INVENTORY, python tools/inventory.py. Before, at 47b5e36:
  TWINS — 26 of 38 boards hold all four; by layer: geometry 38, model 37, pins 35, runs 26
  footprint                vendor               21+3/25  MG24:no        XIAO-MG24-SMD
  footprint                composed             18+6/27  nRF54l15:no    XIAO-nRF54l15-SMD
After:
  TWINS — 26 of 38 boards hold all four; by layer: geometry 38, model 37, pins 37, runs 26
  footprint                vendor               21+4/25  MG24:no        XIAO-MG24-SMD
  footprint                composed             20+7/27  nRF54l15:no    XIAO-nRF54l15-SMD
The pins layer now holds on both boards. Neither board holds all four layers, because both lack firmware evidence (runs). The inventory changed nowhere else except its test counts.

VERIFIED. python -m pytest -q -p no:cacheprovider tests/rules/test_import_pindefs.py tests/rules/test_inventory.py tests/rules/test_board_manifest.py tests/webui/test_pin_view.py tests/webui/test_board_catalogue.py: 376 passed, 1 skipped (the OH_SLOW variant survey). On the first run, test_a_running_manifest_board_lists_its_own_pads_and_no_xiao_label failed because this worktree's build/lib/riscv32.dll was a stale Debug build missing riscv32_map_input. python tools/build_core.py rebuilt it (build/ is ignored), and that test passed after. Checker rows, each run on its own and each OK: check_layering, check_board_contract, check_part_schemas, check_licenses, check_deltas, check_banned_symbols, check_board_claims, check_ticket_claims, ticket_guard --self-test, check_facts, and board-sources render.py --check. Neither checkall.py nor the full suite was run.

LEFT, not this ticket's:
(1) The pad Seeed labels 54L15_TX20 reaches P1.08. Zephyr's xiao_nrf54l15-pinctrl.dtsi at 0a2e408 sets uart20_default UART_TX on P1.09 and UART_RX on P1.08. chip_pin states the copper; the direction question is recorded in the _NRF54L15 comment and not resolved.
(2) The same position join puts the nRF54L15 SMD's USER_LED (pad 22) on TP18, whose net is 'P2.00{slash}USR_LED'. That answers the join _NRF54L15_USER_LED's reason says no file makes, and test_the_user_led_reports_the_pin_two_sources_name_and_writes_neither asserts the same thing. Untouched here.
(3) The nRF54LM20A's nRF54_RST might be joinable the same way; its edge footprint is XIAO-Add-On-PRO, not a HALF-HOLE, and that has not been checked.
(4) The RP2350 SMD's EN is still a supply by SUPPLY_LABELS, per OH-172's note.
(5) test_the_rp2350_smd_boot_pad_is_the_flash_chip_select_in_seeeds_own_board_file has its own copy of the frame-and-landing code. It could share _underside_landings; not done here.

**Note 2026-10-12:** Review fix round, MERGE AFTER SMALL FIXES. All fixes are in 8f482f2. Still in review.

MEDIUM, USER_LED. The pad's old reason said no file joins it to its net. But _underside_landings put pad 22 on TP18, net 'P2.00{slash}USR_LED', and then discarded the result. Now:
- that net is in _NRF54L15's `nets`;
- _NRF54L15_USER_LED and its comment are removed;
- USER_LED is in LANDED_BY_POSITION;
- the board file is regenerated, and USER_LED's chip_pin is P2.00, read off the nRF54L15's own pad.
The test is now test_the_user_led_names_the_pin_its_test_point_reaches_and_zephyr_agrees. It checks that the net carries only the MCU's pad, the green LED D3 and the test point. It checks that chip_pin equals the pin read off the vendor's file. Zephyr's led0 is a cross-check, derived from its node: P2.00. The counts moved by what the failures printed: naming 565, specific 69, unnumbered 136. No webui code reads the reason's text, so the pin view simply shows the pin now. In api.pad_view, both SMD boards (and both DIPs) show modelled False on every pad and read_levels False.
Breaks:
- USER_LED dropped from `nets`: the landing test and the committed-files test went red.
- The old reason left in the registry: the answer test and the USER_LED test went red.
- USER_LED's chip_pin edited to P2.01 in the board file: the USER_LED test went red.

LOW 1. _underside_landings now keys by pad number and asserts that no point takes two pads on that key; the label view keeps only labels that one pad wears alone. Break: footprint pad 32 (GND) moved onto pad 29 (GND). The old helper stayed green; the new one goes red.

LOW 2. The landing test now asserts that the boards the registry types a net for equal LANDED_BY_POSITION, counting each board by the labels its own file carries. Break: an in-memory seeed_pcb_traced on XIAO-RP2350-SMD with nets {"BOOT": "/04 RP2350/QSPI_SS"}. The old test stayed green; the new one goes red, naming XIAO-RP2350-SMD.

LOW 3. The TX20 comment now lists each source that says P1.08 is the nRF54L15's receive line, and says the pad's label is what disagrees:
- the board file names that net SAMD11_TX;
- silabs-arduino variants/xiao_mg24/pins_arduino.h at 6128e93, line 70, "#define PIN_SERIAL_RX (D11) // PA9", where the MG24's D11 net is that debugger's SAMD11_TX;
- Zephyr's uart20_default at 0a2e408 has UART_RX on P1.08, with bias-pull-up on that group alone.
chip_pin stays P1.08, where the copper goes.

LOW 4. A pin traced by a typed net now comes back from read_seeed_traced as Traced. So the report printed by python tools/import_pindefs.py <board> cites the net, for example: "seeed-pcb nRF54L15.kicad_pcb @ sha256:2e524f78f222: the net 'P1.08{slash}SAMD11_TX', joined to this pad by position, reaches the nRF54L15's P1.08". The EN pads cite their nets in why_null. The XIAO board files themselves still carry no per-pad sources, so a chip_pin answer cites its net in the printed report and not in the JSON. test_a_pin_traced_by_a_typed_net_is_cited_with_that_net was red first, with the citation lacking the net. Break: the tracer returning a bare pin turns it red.

LOW 5. Removed unchecked counts in prose: "Three underside pads", "Four pads", "The four pads answered", "Three sources", and "two underside GND pads".

LOW 6. A label given in both `labels` and `nets` now raises. test_a_label_given_both_by_name_and_by_typed_net_is_refused was red first (DID NOT RAISE). Break: the refusal removed turns it red again.

LOW 7, for OH-172 slice 2. board3d-panel.js's pin table shows a pad's label, then its chip_pin in the Chip pin column (or "—"), then its state. On these boards that now includes 54L15_TX20 beside P1.08, the pin Zephyr receives on, and USER_LED beside P2.00. The EN pads still show "—" and not modelled, because RESET and ~{RESET} are not pin names under _CHIP_PIN_NAME. board3d-panel.js is unchanged.

REGENERATED with python tools/import_pindefs.py --write-headers --write-boards. Only XIAO-nRF54l15-SMD.json was written; a second run reported all 42 files unchanged.

INVENTORY, python tools/inventory.py at fa3a473 plus this change:
  TWINS — 26 of 38 boards hold all four; by layer: geometry 38, model 37, pins 37, runs 26
  footprint                vendor               21+4/25  MG24:no        XIAO-MG24-SMD
  footprint                composed             21+6/27  nRF54l15:no    XIAO-nRF54l15-SMD
Against the first round, only the nRF54L15 SMD's cell and the test counts changed.

VERIFIED at 8f482f2:
- python -m pytest -q -p no:cacheprovider tests/rules/test_import_pindefs.py tests/rules/test_inventory.py tests/rules/test_board_manifest.py tests/webui/test_pin_view.py tests/webui/test_board_catalogue.py: 378 passed, 1 skipped (the OH_SLOW variant survey).
- Checker rows, each run on its own, each exit 0 and OK: check_layering, check_board_contract, check_part_schemas, check_licenses, check_deltas, check_banned_symbols, check_board_claims, check_ticket_claims, ticket_guard --self-test, check_facts, and board-sources render.py --check.
- Neither checkall.py nor the full suite was run.
