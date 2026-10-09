---
id: OH-208
title: 'Zbb and Zbkb on the RP2350''s Hazard3: the core refuses what the chip executes'
status: done
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

**Note 2026-10-09 (review fixes):** An independent review returned MERGE AFTER FIXES; four statements were false or overstated, and each is corrected. Status stays in-review.

* **`set_isa` names Zba, Zbb, Zbs and Zbkb** (3bced0b). It called ZBB a group "this core cannot represent" after `EXT_ZBB` existed, and had said the same of ZBA and ZBS since they had bits. Option (1) was taken over rewording the refusal, because every caller stays correct: the C3 and C6 pass `RV32IMC`/`RV32IMAC`, the C5 `EXECUTES`, `test_disasm` `RV32IMC`, and `test_esp32c5_board`'s refusal of the datasheet's prose string still raises on its space. Every `EXT_*` bit now has a letter or a group name, so the refusal is true of every group it raises on.
  * `test_zc`'s refused example is now `RV32IMAC_ZBC`. Zbc has no bit and no part here has it.
  * Two new tests in `test_zbb_zbkb.py`: each of the four names sets its own bit alone, and `RV32IMAC_ZBA_ZBB_ZBS_ZBKB_ZCB_ZCMP` comes to `abi.RP2350`. Both were red before the change (`'RV32I_ZBA' names extension group 'ZBA', which this core cannot represent`).
  * `webui/boards/rp2350.py` keeps its bitmask, and its reason now says what is still true: `ISA` cannot be handed to `set_isa` (Zicsr and Zifencei have no bit, and Zca is `C` in its grammar), and `abi.RP2350` already spells the part.
  * Breaks, each red: `set_isa` dropping an unknown group instead of refusing it (the `test_zc` test); ZBB and ZBKB swapped in the map (the per-name test, while the RP2350 test stays green, which is why there are two); ZBS mapped to Zba's bit (both new tests).
* **cpu.h no longer says M is refused** (9f1495c). Only `kExtA` is classified and then refused: `Unimplemented` with the bit, `Illegal` without. M and every other bit execute. Comment only, no rebuild.
* **The zip/unzip rs2 field is settled, not disputed** (243da56). The 20240411 release's figures in chapters 28 and 32 drew 0x1e and 0x1f. riscv-isa-manual 698e64ae7 (2024-09-09, "Fix descriptions/encodings of zip/unzip instructions (#1635)") changed both chapters to 0xf, restoring the ratified encoding. sail-riscv's `model/extensions/K/zbkb_insts.sail:66-67` (zip) and `:89-90` (unzip), at master 549e723, encode both with rs2 0b01111. Both sources were fetched and read for this note. This supersedes the "Where the spec and everything else disagree" bullet above. exec.cc's comments and `test_zbb_zbkb.py`'s header now say so; comments only, no rebuild.
* **The ESP32 parts lack Zb\* because their datasheets say so** (1961e8c). `test_no_esp32_part_runs_any_zbb_or_zbkb_encoding` now cites the datasheets: the C3's "RV32IMC ISA" (v2.4), the C6's "RV32IMAC ISA" (v1.5), and the C5 HP CPU's "RV32IMAC ISA" with "Zc extensions (Zcb, Zcmp, and Zcmt)" and Xhwlp (v1.5, §4.1.1.1). None of the three names a Zb\* group anywhere; the PDFs were downloaded and searched for this note. The Arduino core's `-march` stays, labelled as what it shows: no stock image contains them. That also corrects the "Gating" bullet above, which gave both sources equal weight. Break: `abi.ESP32_C5` given `EXT_ZBB` turns the test red.
* **Verification.** `python -m pytest -q -p no:cacheprovider tests/riscv32 tests/rv32 tests/webui/test_xiao_rp2350_board.py`: `247 passed`. `python tools/check_ticket_claims.py`: OK. No C++ behaviour changed (the two .cc/.h edits are comments), so the full suite was not rerun.

**Note 2026-10-09:** DONE 2026-10-09. Merged to master by fast-forward at d6a8b9c (lane4); the core rebuilt in main with tools/build_core.py. VERIFIED on master at d6a8b9c: full suite 2 failed (the OCP pair), 2609 passed, 41 skipped. REVIEW: an independent review, MERGE AFTER FIXES (no defect in semantics, encoding or gating: 655,360 decode verdicts and 1,497,360 value checks against its own reference models, 0 wrong; the zip/unzip encoding 0b01111 ruled correct, the 20240411 figure being a published erratum fixed upstream), and its small fix round (set_isa names the bitmanip groups; comments corrected and cited). Follow-ups (fold RP2350_MODELLED into RP2350 with tests/rv32, assert rv32zcb, correct three files outside this ticket, the Hazard3's custom extensions refused as Illegal) are filed as their own ticket. core/riscv32/** and tests/riscv32/** return to OH-161.
