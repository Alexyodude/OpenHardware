---
id: OH-219
title: One constant names the RP2350's modelled ISA, rv32zcb is asserted, and the
  Hazard3's own extensions are refused in the right words
status: in-review
priority: P3
created: '2026-10-09'
touches:
- tests/rv32/**
- tools/gen_rv32_tests.py
- tests/webui/xiao_rp2350/blink.c
- core/riscv32/**
- tests/riscv32/**
---

Follow-ups from OH-208 and its review (2026-10-09). OH-208 made core/riscv32 execute every RV32 Zbb and Zbkb instruction and turned them on for the RP2350 only, as `abi.RP2350 = RP2350_MODELLED | EXT_ZBB | EXT_ZBKB`. Two names for one part remain, and some files outside OH-208's claims now say something false.

1. Fold `RP2350_MODELLED` into `RP2350`. `tests/rv32/test_gating.py`'s `test_the_extension_letters_match_the_abi_bitmasks` asserts `RP2350_MODELLED` equals the RP2350's datasheet set intersected with `MODELLED` in `tests/rv32/conftest.py`, which names neither Zbb nor Zbkb. Add both to `MODELLED` and to `extension_mask`'s map, fold the two constants into one, and move `tests/riscv32/test_lockstep.py` and `test_extension_gating.py` off the old name. After the fold only Zca (which kExtC stands for) is unmodelled, so `test_gating.py` ~390-394's message will mislead: revisit it. OH-208's review ran this in memory: on `abi.RP2350` all 96 `rv32zcb` cases execute and match rvcpp's recorded writes, and the C5 refuses exactly the 24 that need Zbb.
2. `rv32zcb.json` is generated but never asserted: the family was never added to `FAMILIES` (left from OH-146), and `conftest.py` ~78 still says "FAMILIES having no Zc family". Add it.
3. Statements made false by OH-208: `tests/rv32/conftest.py` ~90-95 ("cannot be told that it has Zbb yet"), `tools/gen_rv32_tests.py` ~366-370 ("no target has Zbb: every part must refuse them"), `tests/webui/xiao_rp2350/blink.c` ~58-59 ("the two groups ... core/riscv32 does not model"). Correct each; blink.c's comment change must leave blink.bin's bytes unchanged.
4. The Hazard3's custom extensions (docs/architectures.md ~776: Xh3bextm, Xh3power, Xh3irq, Xh3pmpm) answer `Illegal` on `abi.RP2350`, the word for "the silicon lacks this": a custom-0 word of h3.bextm's shape (0x00c5850b) shows it. That is the class of wrong word OH-208 fixed for Zbb. Refuse them as unimplemented by this model rather than absent from the part, or implement Xh3bextm under lockstep with rvcpp if rvcpp has it.
5. LOW: the MSVC shim's `__popcnt` assumes a POPCNT-capable CPU (it faults loudly on an old one, never answers wrong).

Done when one constant names the RP2350's modelled ISA and the gating test holds it, rv32zcb is asserted, no file says Zbb is unmodelled, and the Hazard3's custom extensions are refused in the right words.

**Note 2026-10-13:** 2026-10-13: borrows core/riscv32/** from OH-161 (via OH-225, done). Return it to OH-161 when this closes.

**Note 2026-10-13:** In review. Three commits in lane4: 2d7a92f (items 1-3), d8335fa (item 4), 78b24c1 (item 5).

Item 1. abi.RP2350_MODELLED is gone and abi.RP2350 is the one mask, the board's and the gating test's. tests/rv32's MODELLED and extension_mask's map name Zbb and Zbkb (and Xh3bextm, item 4). test_the_extension_letters_match_the_abi_bitmasks holds abi.RP2350 to the datasheet row. Its last assertion is now exact: the row exceeds MODELLED by {"Zca"}, the spelling kExtC stands for. test_lockstep.py and test_extension_gating.py run on abi.RP2350. Seen red first: mask 0x7f against abi.RP2350 0x37f.

Item 2. rv32zcb is in FAMILIES. A new test holds the generator's family names (build, run without the oracle), FAMILIES and the committed corpus equal, so a family that is generated and never read fails. A second new test re-runs OH-208's in-memory check from the corpus. Run here: all 96 cases execute on abi.RP2350 and match rvcpp's recorded writes, the C5 refuses exactly the 24 that need Zbb, and the C3 and C6 refuse all 96. Both were red first.
Break: c.sext.b expanded as c.zext.b turns that test and the absent-extension sweep red on the C5.
Found: the corpus gives those three unaries x8 = 0 and 1 only, so its agreement half cannot see sign- against zero-extension. test_zbb_zbkb.py's compressed lockstep can, and went red under the same break.

Item 3. The three statements are corrected: conftest.py ("cannot be told that it has Zbb yet", "FAMILIES having no Zc family"), gen_rv32_tests.py ("no target has Zbb") and blink.c ("the two groups core/riscv32 does not model"). Two more in conftest.py were also false and are corrected: the C5 row "exceeding MODELLED", untrue since OH-146, and a test name that did not exist.
blink.bin is unchanged. It was rebuilt the way test_the_committed_binary_matches_its_source builds it, and the sha256 is ea90feb7...6cd3 both before and after the edit.

Item 4. Decided on evidence. The RP2350 datasheet 80d627281ed5 (sha256 a638d678...2e39) says in 3.8, PDF p.227, "RP2350 enables the following Hazard3 custom extensions": Xh3power, Xh3bextm ("used in bootrom"), Xh3irq and Xh3pmpm. Table 387 (p.279) sets EXTENSION_XH3BEXTM 1. rvcpp implements both of Xh3bextm's instructions (rv_core.cpp:646-656), so Xh3bextm is implemented under lockstep.
Each extension's encoding space, per third_party/hazard3 8af9929 doc/sections/custom_extensions.adoc and csr.adoc:
- Xh3bextm is custom-0, opcode 0x0b. h3.bextm is funct3 000 and h3.bextmi is 100. Bits 31:29 and 25 are RES0. It gets a new bit, EXT_XH3BEXTM, set in abi.RP2350 only. Every other custom-0 word stays Illegal, as the HDL decodes it (hdl/rv_opcodes.vh:156-157).
- Xh3irq (CSRs 0xbe0-0xbe5), Xh3pmpm (0xbd0) and Xh3power's MSLEEP (0xbf0) are CSRs, so they answer Unimplemented like every CSR here.
- Xh3power's h3.block and h3.unblock are slt x0,x0,x0 and slt x0,x0,x1. They run as the base ISA's no-op, as they do in rvcpp. The sleep is not modelled.
The datasheet's Tables 379 and 380 print bits 6:2 as 0b01011. That is a misprint: the doc, the HDL, rvcpp and the datasheet's own .insn macros all say 0x0b.
tests/riscv32/test_xh3.py holds each of these. It includes a lockstep that traces 2,477 instructions against rvcpp. It was red first: "0x0062850b is illegal for extensions 0x37f". Seven breaks each turned a check red: width without +1, RES0 unchecked, h3.bextmi shifting by a register, the gate dropped, the Xh3 CSRs answering Illegal, slt to x0 refused, and the encoder's size at bit 25.

Item 5. The MSVC shim's popcount is std::bitset<32>::count. MSVC 14.44 checks __isa_available and falls back to plain arithmetic where POPCNT is absent. The oracle was rebuilt. Break: a popcount one too high turns the cpop lockstep red.

Verified: build_core; pytest tests/riscv32 tests/rv32 tests/webui/test_xiao_rp2350_board.py, 318 passed; each checker row from check_layering to check_facts, OK, run one by one. checkall.py and the full suite were not run.

Left:
(a) webui/boards/rp2350.py is OH-161's and now has three stale comments: ":103 abi.RP2350_MODELLED quote", ":107 every group of ISA" (abi.RP2350 now also has Xh3bextm), and ":113 RV32IMAC_ZBA_ZBB_ZBS_ZBKB_ZCB_ZCMP" (now ..._XH3BEXTM).
(b) disasm.py does not render h3.bextm or h3.bextmi. A listing shows the raw word.
(c) The rv32zcb corpus's narrow unary inputs (above).
(d) The C5's Xhwlp is a custom extension whose encodings nothing here has read. Wherever they live, the C5 answers them Illegal now, which may be the same wrong word.
core/riscv32/** and tests/riscv32/** go back to OH-161 when this closes.
