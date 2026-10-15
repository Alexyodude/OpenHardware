---
id: OH-210
title: 'The RP2350''s edges after OH-157: one half shown as both, an unchecked IMAGE_DEF,
  RESETS stored not obeyed'
status: open
priority: P3
created: '2026-10-08'
touches:
- rules/board-claims.md
- webui/boards/catalogue.py
---

The edges OH-157's reviews left (2026-10-08), none of which changes what the XIAO RP2350 blink shows today.

1. `webui/static/emulator.js` shows the RP2350's ISA as "Armv8-M (Cortex-M33) + RV32 (Hazard3)" beside RUNS FIRMWARE. Only the core column, `riscv32`, says which half runs, and the evidence sentence names just "RP2350". Say on the page that the RISC-V half runs and the Arm half does not.
2. `rules/board-claims.md` has no dated section for the first chip with two ISAs whose evidence covers one of them, and its §3 still pins `{"RP2040"}`.
3. `webui/boards/catalogue.py`'s `missing_cores` would attribute the M33 ISA string to `riscv32` whenever a `riscv32` row appears, e.g. on an unbuilt checkout.
4. Nothing checks an IMAGE_DEF at load. An image silicon would not boot, or one carrying an Arm IMAGE_DEF, runs here. An `absolute`-only or universal UF2 is refused with a headline saying it holds nothing for an RP2350, though silicon could boot such a file by its IMAGE_DEF (RP2350 Datasheet §5.5.3, §5.5.3.2). Cite §5.1.20 (automatic architecture switching) as what makes a real XIAO run a RISC-V image.
5. RESETS is stored, not obeyed, and RESET_DONE is unmapped because core/riscv32 cannot model a mirrored register, so the blink skips the canonical RESET_DONE wait. The headline now asserts the image released IO_BANK0 and PADS_BANK0; mapping RESET_DONE as all-done would let a blink keep the wait.
6. GPIO_CTRL's OUTOVER and OEOVER (pico-sdk io_bank0.h) sit between FUNCSEL and the pad and are not read; rp2040.py says so of the RP2040, rp2350.py does not.
7. OH-36, held by another session, still lists the XIAO RP2350 among boards where nothing runs and hands the RP2350 to OH-42; rp2350.py and catalogue.py say the M33 half is OH-36's. Its holder should note which is true.

Done when each is fixed with a test that fails when reverted where it is behaviour, or the sentence says only what the files show.

**Note 2026-10-15:** 2026-10-15: items 2 and 3 taken in this session's lane3; claims rules/board-claims.md, webui/boards/catalogue.py and its test. Items 1, 4, 5, 6 and 7 are not in this pass.

**Note 2026-10-15:** items 2 and 3 done in lane3 (eef2767, 58206ce). Item 3: catalogue.CORE_ISA maps the RP2350 to 'RV32 (Hazard3)' and missing_cores reads each row's isas from the boards waiting on that core, so a riscv32 row no longer names the M33 half or a runnable board's ISA; two tests in test_board_catalogue.py failed before the fix. Item 2: rules/board-claims.md section 14 records the first chip with two ISAs and evidence for one (tests/webui/test_xiao_rp2350_board.py, the Hazard3 half), and section 3 now points at the test that holds the verified set instead of {RP2040}. Items 1, 4, 5, 6, 7 untouched.

**Note 2026-10-15:** 2026-10-15: review follow-ups in 7eb6669 (FIRMWARE_VERIFIED's comment no longer restates a set; CORE_ISA held to CHIPS by a test). Items 2 and 3 done; back to open for items 1, 4, 5, 6 and 7.

**Note 2026-10-15:** 2026-10-15: borrows webui/static/emulator.js and webui/boards/rp2350.py from OH-161 for items 1 and 6.

**Note 2026-10-15:** items 1 and 6 done in lane3. Item 1: /api/boards carries core_isa (catalogue.CORE_ISA, else the whole ISA string) and emulator.js's boards table adds 'Only RV32 (Hazard3) runs here, on core riscv32. The rest has no core.' to the ISA cell where they differ; test_the_boards_table_says_which_half_of_the_isa_runs runs the real emulator.js under node and failed with emulator.js reverted; board-claims.md section 14 updated. The evidence sentence still names just RP2350. Item 6: pin_states' docstring in rp2350.py says only FUNCSEL is read from GPIO_CTRL, citing io_bank0.h lines read in the pinned pico-sdk checkout. Items 4, 5, 7 still open.

**Note 2026-10-15:** review follow-ups to items 1 and 6: test_the_page_sentence_the_rest_has_no_core_stays_true fails when a core exists for a split chip's other half (shown by patching build_core.cores to add cortexm33); the boards-table probe polls up to 5 s and fails by name instead of sleeping 100 ms.

**Note 2026-10-15:** 2026-10-15: items 1 and 6 reviewed (merge) with the guard and the probe poll as follow-ups; returns webui/static/emulator.js and webui/boards/rp2350.py to OH-161, back to open for items 4, 5 and 7.

**Note 2026-10-15:** 2026-10-15: lends tests/webui/test_board_catalogue.py to OH-166 (the board-listing lock test's wall-clock budget); it comes back when that lands.
