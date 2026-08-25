---
id: OH-56
title: A RISC-V disassembler, so an ESP32 board gets a Disassembly pane instead of
  a note
status: done
priority: P2
created: '2026-08-25'
touches:
- core/riscv32/disasm.py
- tests/riscv32/test_disasm.py
- tests/webui/test_emulator_session.py
- tests/riscv32/test_esp32c3_board.py
---

webui/api.py's listing_view resolves core.<core>.disasm and answers {present: false, note} when it does not exist. riscv32 is the live case that comment names: the board steps and its registers read, and the Disassembly pane says why it is empty.

That is the honest answer and it is not the finished one. Three of the four panes a person expects work on a RISC-V board; this is the fourth.

Shape: the same one core/cortexm0/disasm.py has, which webui/api.py already knows how to call -- Line(address, width, encoding, text), decode(...), disassemble_range(cpu, address, count). The flat form, since no RISC-V board is segmented.

Width matters here in a way it does not on Armv6-M: an RV32 listing interleaves 16-bit and 32-bit instructions, so disassemble_range must advance by what it decoded rather than by a constant. Getting that wrong does not fault, it produces a plausible listing offset by two bytes from the second instruction onward -- the silent class.

VERIFICATION, and it is the good part: riscv32-esp-elf-objdump is installed. core/cortexm0/disasm.py was checked by laying every encoding it claims end to end into one binary and comparing a single objdump pass -- 56,551 encodings, three real bugs that four real firmware images could not find. The 16-bit RVC space is 65,536 encodings and can be swept whole. The 32-bit space cannot, so sweep the claimed encodings the way cortexm0 did.

Watch for the same trap cortexm0 hit: objdump decodes a WIDER architecture than it is told. It will render RV64 and extension encodings this core deliberately refuses, so a divergence there is objdump being broader, not this being wrong -- the same reasoning docs/HANDOFF_2026-08-25_a-fourth-core-and-a-usable-page.md 9 records for and.w and bxns.

Depends on OH-54 for nothing structurally, but a disassembler that cannot render compressed instructions is useless on a part where two thirds of the image is compressed, so it lands after.

Done when a loaded ESP32-C3 board shows a Thumb-equivalent listing around its program counter in the browser, and the sweep agrees with objdump on every encoding this core claims.

**Note 2026-08-25:** Delivered. The ESP32-C3 boards now have all four panes -- Registers, Flags, Disassembly, Memory -- which is what the seven-board programme was for.

THREE SWEEPS AGAINST OBJDUMP, because they catch different things:
 - every compressed encoding: all 49,152 halfwords with (c&3)!=3
 - every opcode x funct3 x funct7: 32,768, which checks every mnemonic decision
 - every field of every form: 27,904, registers across all 32 and immediates across a spread including both sign bits

The third is the one the others cannot replace: a transposed immediate leaves the mnemonic right and the offset wrong, which reads perfectly and points somewhere else.

FOUR THINGS THE SWEEPS TAUGHT ME ABOUT THE ORACLE, all of which cost a round:

 1. objdump RE-SYNCS ON HALFWORDS when it cannot decode a word, printing `009f 0000 000f` as one six-byte blob where this module renders three entries. Comparing the two outputs line-for-line therefore drifts the moment either meets something it does not know -- which is exactly the region a sweep is for. The harness now compares BY ADDRESS and treats a missing line as a refusal.

 2. objdump appends `# 0x1234` when a base register is zero and it can compute the absolute address. 522 lines of the field sweep differed by only that. Reading them as decode failures would have wasted a day.

 3. objdump is NARROWER as well as wider. Its default riscv:rv32 does not know Zba or Zbs at all, both of which this core implements and gates per part. The cortexm0 note says objdump decodes a wider architecture; here it does both, in the same run.

 4. The atomics spell themselves eight ways once .aq/.rl/.aqrl are counted and the FP families more than fifty. Accounting by MNEMONIC was listing objdump's vocabulary; accounting by OPCODE states what core/riscv32/exec.cc implements, which is the fact that actually decides it.

ONE REAL GAP THE SWEEP FOUND IN THE MODULE: `fence` rendered bare, ignoring its pred/succ operands. objdump prints `fence rw,rw`, and no image in this repository contains a fence -- so nothing but a sweep would ever have said so.

EIGHT MUTATIONS, and the first round left a SURVIVOR that was a hole this test file dug itself: reversing the fence pred/succ bit order passed all three sweeps, because every fence they contain has non-zero rd/rs1, objdump refuses to render those, and ACCOUNTED_MINE excused the difference. An accounting entry that excuses a whole mnemonic excuses its bugs with it. Two direct fence tests now assert the orderings, one against a transcribed table and one against objdump itself so a transcription cannot be wrong in the same direction twice.

TWO TRIPWIRES FIRED, both asserting riscv32 has no disassembler. The webui one used riscv32 as its stand-in for a core without one; it is `avr` now, which is better because the Arduino Uno is a real board that shows exactly that note -- and the docstring's claim that "every board that runs happens to have one" had already been false since OH-52 and nobody noticed.

Browser-verified with one listener checked first. After load the pane shows the `_start` this ticket's sibling wrote -- lui sp,0x3fce0 / c.addi sp,-16 / jal zero,0x4200000a -- with widths 4, 2, 4 interleaved. After 200,000 instructions it shows the delay loop with the current line marked. 0 console messages.

1,250 passed, 17 skipped.
