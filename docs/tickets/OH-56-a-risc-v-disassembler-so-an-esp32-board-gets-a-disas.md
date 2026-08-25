---
id: OH-56
title: A RISC-V disassembler, so an ESP32 board gets a Disassembly pane instead of
  a note
status: open
priority: P2
created: '2026-08-25'
touches:
- core/riscv32/disasm.py
- tests/riscv32/test_disasm.py
---

webui/api.py's listing_view resolves core.<core>.disasm and answers {present: false, note} when it does not exist. riscv32 is the live case that comment names: the board steps and its registers read, and the Disassembly pane says why it is empty.

That is the honest answer and it is not the finished one. Three of the four panes a person expects work on a RISC-V board; this is the fourth.

Shape: the same one core/cortexm0/disasm.py has, which webui/api.py already knows how to call -- Line(address, width, encoding, text), decode(...), disassemble_range(cpu, address, count). The flat form, since no RISC-V board is segmented.

Width matters here in a way it does not on Armv6-M: an RV32 listing interleaves 16-bit and 32-bit instructions, so disassemble_range must advance by what it decoded rather than by a constant. Getting that wrong does not fault, it produces a plausible listing offset by two bytes from the second instruction onward -- the silent class.

VERIFICATION, and it is the good part: riscv32-esp-elf-objdump is installed. core/cortexm0/disasm.py was checked by laying every encoding it claims end to end into one binary and comparing a single objdump pass -- 56,551 encodings, three real bugs that four real firmware images could not find. The 16-bit RVC space is 65,536 encodings and can be swept whole. The 32-bit space cannot, so sweep the claimed encodings the way cortexm0 did.

Watch for the same trap cortexm0 hit: objdump decodes a WIDER architecture than it is told. It will render RV64 and extension encodings this core deliberately refuses, so a divergence there is objdump being broader, not this being wrong -- the same reasoning docs/HANDOFF_2026-08-25_a-fourth-core-and-a-usable-page.md 9 records for and.w and bxns.

Depends on OH-54 for nothing structurally, but a disassembler that cannot render compressed instructions is useless on a part where two thirds of the image is compressed, so it lands after.

Done when a loaded ESP32-C3 board shows a Thumb-equivalent listing around its program counter in the browser, and the sweep agrees with objdump on every encoding this core claims.
