---
id: OH-208
title: 'Zbb and Zbkb on the RP2350''s Hazard3: the core refuses what the chip executes'
status: in-review
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

**Note 2026-10-09:** **Done in lane4: Zbb and Zbkb are modelled, held in lockstep with rvcpp, and enabled on the RP2350 board only** (295277b core and tests, 77b8078 board and probe).

* **What was added, and where each one is defined.** The ratified unprivileged ISA 20240411, ch. 28 ("B" Extension for Bit Manipulation 1.0.0: sections `Zbb` and `Zbkb`, plus each instruction's own page) and ch. 32 (Scalar Cryptography 1.0.1, section `Zbkb`).
  * Zbb only: clz, ctz, cpop, min, minu, max, maxu, sext.b, sext.h, zext.h, orc.b.
  * In both groups: andn, orn, xnor, rol, ror, rori, rev8.
  * Zbkb only: pack, packh, brev8 (ch. 28 spells it `rev.b`), zip, unzip.
  * RV32-only encodings: rev8 is 0x698 (RV64's is 0x6b8); zext.h is `pack rd, rs1, x0` (RV64 uses OP-32); zip and unzip exist on RV32 only; rori takes a five-bit amount, so funct7 0b0110001 is refused.
  * The Zcb compressed forms c.sext.b, c.zext.h and c.sext.h. Their ch. 27 pages say "Zbb is also required", so they now run on the RP2350 and are still refused on the C5.
  * Zbc's clmul, clmulh and clmulr share a funct7 with min and max. The RP2350's string does not name Zbc, so they are refused on every part.
  * **Where the spec and everything else disagree:** both chapters' encoding figures show zip's and unzip's rs2 field as 0x1e and 0x1f. riscv-opcodes `extensions/rv32_zbkb` (`24..20=15`), rvcpp's `RVOPC_ZIP_BITS` and GNU as 2.43 (`zip a0,a1` = 0x08f59513) all use 0b01111, so that is what was implemented.
* **Gating.** There are two bits, `EXT_ZBB` and `EXT_ZBKB`. The seven shared instructions open to either bit, and so does zext.h. `abi.RP2350` is the part's whole mask and is what `webui/boards/rp2350.py` now configures. The ESP32-C3, C5 and C6 are unchanged and run neither group:
  * Espressif's datasheets (docs/architectures.md 4.2) give no Zb* for any of them.
  * ESP32 Arduino core 3.3.11's `flags/c_flags` uses `-march=rv32imc_zicsr_zifencei` for the C3 and `rv32imac_zicsr_zifencei` for the C5 and C6.
* **`RP2350_MODELLED` is unchanged on purpose.** `tests/rv32/test_gating.py` asserts that it equals the RP2350's datasheet set intersected with `MODELLED` in `tests/rv32/conftest.py`. That list names neither group, and tests/rv32 is not this ticket's to edit.
  * Follow-up: add Zbb and Zbkb to `MODELLED` and to `extension_mask`'s map, then fold `RP2350_MODELLED` into `RP2350`.
  * `tests/rv32/conftest.py:95` ("cannot be told that it has Zbb yet") is stale now.
* **The oracle.** rvcpp at 8af9929 implements every instruction above. In `rv_core.cpp`: lines 248, 252 and 254; 271-287 (zext.h runs through PACK, which has no branch of its own); 337-379; and 849-855. `tests/riscv32/test_zbb_zbkb.py` runs each in lockstep with every register and the PC compared after every instruction:
  * all eleven one-operand forms over every single bit, every single-bit hole, the sign edges and the byte patterns;
  * all eleven register forms over every ordered pair of the edge values;
  * rol and ror at every amount 0..31, plus 32, 33, 63 and 0xFFFFFFE1, and rori at 0..31;
  * the three compressed forms on all eight registers they can name.
  * **Caveat:** this machine has no g++, so rvcpp is built with MSVC through `tests/riscv32/oracle/rvcpp_msvc_shim.h`. That makes the oracle's arithmetic for clz, ctz, cpop and rev8 the shim's MSVC intrinsics. Those four are also checked against the spec's Sail, transcribed into Python.
  * A test shows rvcpp running clmul, which this core refuses, so lockstep cannot see gating. A 65,536-word sweep checks that the executor runs exactly what the disassembler names on an RP2350, with no Unimplemented answers.
* **Disassembler.** `core/riscv32/disasm.py` renders every new instruction. The binutils 2.35 sweeps name each one as unknown to that version.
  * A new sweep compares against objdump 2.43, which reads the ELF's arch attribute. It covers every OP and OP-IMM funct3 x funct7 x rs2 field, plus the compressed three. It is green, and its only excuse class is the RV64 six-bit immediates, counted at 256.
* **The probe.** It is built at test time under the Hazard3's whole `-march`: `clz`, `minu` and `rev8` over inputs the compiler cannot fold, linked with blink.ld, IMAGE_DEF included. `blink.bin` is untouched.
  * On XIAO-RP2350-DIP it leaves 0x8, 0x12345678, 0x78563412 and its 0x600df00d marker in SRAM after 17 steps.
  * Moved into rvcpp's testbench, it agrees with the oracle for 200 traced instructions.
  * With the board put back on `RP2350_MODELLED`, it stops at `pc=0x1000001a: encoding 0x60069693 is illegal for extensions 0x7f`. That is `clz a3,a3`, the bug as it was.
* **Each new test was seen red under a named break** (the full list is in the hand-off):
  * clz counting from bit 30;
  * min comparing unsigned;
  * rol rotating right;
  * c.sext.b expanding to sext.h;
  * clmul running as min;
  * min and max losing their Zbb gate;
  * the unaries opening to Zbkb;
  * packh opening to Zbb;
  * rol and ror needing Zbb alone;
  * zext.h losing its Zbb route;
  * the compressed unaries losing their Zbb check;
  * zip opening its whole rs2 field;
  * the encoder's ctz written as clz;
  * the disassembler swapping clz and ctz;
  * the board configuring `RP2350_MODELLED` again;
  * minu answering the larger value.
* **Verification.**
  * `pytest tests/riscv32 tests/webui/test_xiao_rp2350_board.py`: 233 passed (245 with tests/rv32 included).
  * `tools/checkall.py`: every checker row PASS; the suite row FAIL, from the same 16 tests as the full run.
  * Full suite: `16 failed, 2593 passed, 41 skipped in 573.00s (0:09:32)`. All 16 are in test_compose_board_3d, test_import_3d_model and test_board3d. The causes are `No module named 'OCP'` under Python 3.14, and lane4's gitignored meshes, which were composed before OH-216. None of the 16 imports anything this ticket changed.
