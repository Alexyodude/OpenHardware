---
id: OH-208
title: 'Zbb and Zbkb on the RP2350''s Hazard3: the core refuses what the chip executes'
status: open
priority: P2
created: '2026-10-08'
touches:
- core/riscv32/**
- tests/riscv32/**
- webui/boards/rp2350.py
- tests/webui/test_xiao_rp2350_board.py
---

Found by OH-157's review (2026-10-08). The RP2350 now runs on its Hazard3 half through core/riscv32, and the Hazard3 implements Zbb and Zbkb (RP2350 Datasheet §3.8.9, the ISA string `core/riscv32/abi.py` already carries). core/riscv32 decodes neither, so `clz`, `rev8` and `minu` on a XIAO RP2350 raise "is illegal for extensions", where silicon executes them; `sh1add` (Zba) does execute.

`core/riscv32/abi.py`'s note on the Hazard3 constant says it is safe because nothing derives "the RP2350 must refuse X" from it. Since OH-157 something does: the RP2350 board.

Model Zbb and Zbkb in core/riscv32, each instruction held in lockstep against rvcpp, Hazard3's own golden model and this core's oracle (docs/architectures.md §2.1b), the way Zcb and Zcmp were at OH-146; or, until then, correct abi.py's note and make a load on an RP2350 say which extensions it refuses. GCC emits Zbb for ordinary code under the full Hazard3 `-march` (OH-157 measured `clz`, `minu` and `rev8` from a small probe), so a sketch built for the chip's real ISA will hit this.

core/riscv32/** and tests/riscv32/** are OH-161's; take them from it or lend them.

Done when a Zbb or Zbkb instruction on the RP2350 executes as the Hazard3 does, under lockstep, or is refused with a statement that says the refusal is this model's and not the chip's.
