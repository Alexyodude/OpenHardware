---
id: OH-210
title: 'The RP2350''s edges after OH-157: one half shown as both, an unchecked IMAGE_DEF,
  RESETS stored not obeyed'
status: open
priority: P3
created: '2026-10-08'
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
