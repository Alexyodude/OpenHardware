---
id: OH-219
title: One constant names the RP2350's modelled ISA, rv32zcb is asserted, and the
  Hazard3's own extensions are refused in the right words
status: open
priority: P3
created: '2026-10-09'
touches:
- tests/rv32/**
- tools/gen_rv32_tests.py
- tests/webui/xiao_rp2350/blink.c
---

Follow-ups from OH-208 and its review (2026-10-09). OH-208 made core/riscv32 execute every RV32 Zbb and Zbkb instruction and turned them on for the RP2350 only, as `abi.RP2350 = RP2350_MODELLED | EXT_ZBB | EXT_ZBKB`. Two names for one part remain, and some files outside OH-208's claims now say something false.

1. Fold `RP2350_MODELLED` into `RP2350`. `tests/rv32/test_gating.py`'s `test_the_extension_letters_match_the_abi_bitmasks` asserts `RP2350_MODELLED` equals the RP2350's datasheet set intersected with `MODELLED` in `tests/rv32/conftest.py`, which names neither Zbb nor Zbkb. Add both to `MODELLED` and to `extension_mask`'s map, fold the two constants into one, and move `tests/riscv32/test_lockstep.py` and `test_extension_gating.py` off the old name. After the fold only Zca (which kExtC stands for) is unmodelled, so `test_gating.py` ~390-394's message will mislead: revisit it. OH-208's review ran this in memory: on `abi.RP2350` all 96 `rv32zcb` cases execute and match rvcpp's recorded writes, and the C5 refuses exactly the 24 that need Zbb.
2. `rv32zcb.json` is generated but never asserted: the family was never added to `FAMILIES` (left from OH-146), and `conftest.py` ~78 still says "FAMILIES having no Zc family". Add it.
3. Statements made false by OH-208: `tests/rv32/conftest.py` ~90-95 ("cannot be told that it has Zbb yet"), `tools/gen_rv32_tests.py` ~366-370 ("no target has Zbb: every part must refuse them"), `tests/webui/xiao_rp2350/blink.c` ~58-59 ("the two groups ... core/riscv32 does not model"). Correct each; blink.c's comment change must leave blink.bin's bytes unchanged.
4. The Hazard3's custom extensions (docs/architectures.md ~776: Xh3bextm, Xh3power, Xh3irq, Xh3pmpm) answer `Illegal` on `abi.RP2350`, the word for "the silicon lacks this": a custom-0 word of h3.bextm's shape (0x00c5850b) shows it. That is the class of wrong word OH-208 fixed for Zbb. Refuse them as unimplemented by this model rather than absent from the part, or implement Xh3bextm under lockstep with rvcpp if rvcpp has it.
5. LOW: the MSVC shim's `__popcnt` assumes a POPCNT-capable CPU (it faults loudly on an old one, never answers wrong).

Done when one constant names the RP2350's modelled ISA and the gating test holds it, rv32zcb is asserted, no file says Zbb is unmodelled, and the Hazard3's custom extensions are refused in the right words.
