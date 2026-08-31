---
id: OH-146
title: 'The core learns the C5''s three Zc groups: Zcb, Zcmp, and Zcmt with the JVT
  that table jumps are'
status: done
priority: P2
created: '2026-08-31'
touches:
- core/riscv32/cpu.h
- core/riscv32/cpu.cc
- core/riscv32/exec.cc
- core/riscv32/abi.py
- core/riscv32/disasm.py
- tests/rv32/conftest.py
- tests/rv32/corpus/rv32zcb.json
- tests/riscv32/test_disasm.py
- tests/riscv32/test_zc.py
- tools/gen_rv32_tests.py
- tests/rv32/test_gating.py
- webui/boards/esp32c5.py
- tests/riscv32/test_esp32c5_board.py
---

From "complete all devboards" (2026-08-31). The one unblocked gap in the
board matrix is the ESP32-C5 pair, and `tests/riscv32/test_esp32c5_board.py`
states the blocker exactly: the part is `RV32IMAC + Zcb/Zcmp/Zcmt` and
`core/riscv32` implements none of the three Zc groups, so `EXECUTES` is a
stated subset and no image compiled with the part's own extensions has
been watched. `core/riscv32/cpu.h` names the same gap from the other side:
the RP2350's RISC-V half wants Zcb and Zcmp too, and
`tests/rv32/conftest.py` already carries both parts' TARGETS with
`MODELLED` waiting to be extended.

The three groups, and where each hooks:

  * **Zcb** lives in slots the current decoder already refuses: quadrant 0
    funct3=100 (byte and halfword loads and stores), and quadrant 1's
    bit12=1 register group where RV64 keeps c.subw/c.addw. All of it
    expands to 32-bit instructions the core already executes — except
    c.sext.b/c.zext.h/c.sext.h, which the spec gives only to parts WITH
    Zbb, and no part here has Zbb, so those stay refused with the reason
    named. c.mul rides the M gate the 32-bit mul already has.
  * **Zcmp** takes quadrant 2 funct3=101 — the c.fsdsp slot, dead on every
    FPU-less part — for cm.push/cm.pop/cm.popret/cm.popretz and the two
    a0/a1 move pairs. These write several registers and several words, so
    they are executed directly rather than expanded.
  * **Zcmt** shares that slot (bits[12:10]=000) for cm.jt/cm.jalt, whose
    semantics ARE a CSR: the jump table lives where JVT points. The core's
    "no CSRs" rule gets its one exception here, stated: csrrw/csrrs/csrrc
    reach exactly JVT (0x017) and exactly under kExtZcmt; every other
    Zicsr encoding keeps its Unimplemented answer.

DONE WHEN `set_isa` parses `RV32IMAC_ZCB_ZCMP_ZCMT` (underscore groups,
refusing unknown names as it refuses unknown letters); a core configured
with the groups executes their defined encodings with the spec's
semantics, proven by a conformance corpus whose verdicts cite the Zc
spec, with cm.push/cm.pop stack images hand-worked; a core configured
without them — a C3, a C6 — still refuses every one of the 4,224
encodings the C5 board test sweeps; reserved encodings inside the Zc
spaces refuse on every configuration; the disassembler names what the
core executes; the DLL rebuilds and every existing riscv32 and rv32
suite stays green.

---

**CLOSED 2026-08-31.** Everything the DONE WHEN names, plus the coupled
flips it implied:

  * **exec.cc**: Zcb expands to base instructions in quadrant 0's 100 slot
    and quadrant 1's bit12=1 group (the offset bits SWAPPED — bit 6 is
    uimm[0] — with a test that proves the swap); Zcmp and Zcmt execute
    directly (`execute_zc`) since a push writes several words and a table
    jump reads through JVT. The pops load into temporaries first, so a
    faulting pop reloads nothing; a faulting push moves no sp. The Zbb-only
    unaries refuse even on the C5 (no part here has Zbb), c.mul rides the
    32-bit mul's own M gate, and the spec's reserved rows refuse on every
    configuration.
  * **The one-CSR exception**: JVT (0x017), reachable only under Zcmt,
    WARL with its mode bits forced to zero. Every other Zicsr encoding
    keeps its honest `Unimplemented`.
  * **The oracle where it can see**: the vendored Hazard3 rvcpp implements
    Zcb and Zcmp, and the regenerated corpus carries its recorded verdicts
    for 96 Zcb cases (`rv32zcb.json`; every existing family byte-identical
    under the fixed seed). What its one-writeback trace CANNOT carry is
    Zcmp's multi-register transfers — measured: cm.pop's ra and s0 reloads
    appear nowhere in the trace — and Zcmt at all, so those semantics are
    hand-worked in `tests/riscv32/test_zc.py` (20 tests) with the probe
    that matched rvcpp's sp arithmetic recorded here: -16/+16 for
    `cm.push/cm.pop {ra,s0}`, s0's value round-tripping through the pushed
    frame.
  * **The couplings this flip pulled with it, all in one commit because
    tests/rv32/test_gating.py asserts them against each other**:
    `esp32c5.py`'s `EXECUTES` grew to the whole ISA in `set_isa`'s
    grammar, `ABSENT` emptied, and the board test that promised to fail
    when the bits arrived became the test of the flip — the same cm.push
    encoding that once stopped `Illegal`-with-the-wrong-word now
    round-trips through the board's own SRAM. `RP2350_MODELLED` grew Zcb
    and Zcmp. The 4,224-encoding sweep now runs TWICE: on the C5 nothing
    answers `Unimplemented` and exactly 160 encodings execute (derivably:
    120 move pairs + 32 c.mul + 8 unaries — the register-only work, since
    a zeroed register file faults every memory-touching row); on a C6
    every one of the 4,224 answers `Illegal` and nothing else.
  * **Disasm**: renders all sixteen new mnemonics plus the JVT csr forms
    in objdump's own spelling; the full 49,152-encoding objdump sweep is
    green with one new excuse CLASS — `OVERLAY_SPELLINGS`, pair-checked
    like the RV128 hints, for the slot objdump reads as c.fsdsp and this
    part reads as Zc.
  * Three mutations, all killed: the offset swap undone (the swap test),
    the push order reversed (both stack-image tests), the Zcb gate
    dropped (the C6 sweep and gating suite).

`FIRMWARE_VERIFIED` still does not name the C5 — deliberately. Executing
hand-placed encodings is not a compiled image being watched; OH-147 is
the blink.
