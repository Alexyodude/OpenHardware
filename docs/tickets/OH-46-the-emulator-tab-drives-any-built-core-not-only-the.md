---
id: OH-46
title: The Emulator tab drives any built core, not only the i8086
status: open
priority: P1
created: '2026-08-25'
touches:
- webui/emulator.py
- webui/emulator_server.py
- webui/static/emulator.js
- webui/static/emulator.html
- tests/webui/test_emulator_session.py
---

DRIVING = 'i8086' in webui/emulator_server.py is the last place a core is named. cortexm0 is built and four boards run real firmware through /api/board/load, and none of them can be opened in the debugger -- no registers, no disassembly, no memory view -- because webui/emulator.py is a Session over core.i8086 and there is only one session type.

The coupling is two lines: 'from core.i8086 import abi, disasm' and one call to disasm.disassemble_range. Everything else in that file is already about stepping a CPU rather than about x86.

A person thinks in boards, so selection should be board-first: pick XIAO-RP2040-DIP, not cortexm0. webui/api.py already resolves a board to a core and a memory map (runtime_for), and webui/boards/contract.py already states what a board must supply, so the resolution exists and this ticket is about driving it rather than rebuilding it.

Keep the refusals. targets.py's UNBUILT state and its message carry the command that fixes them, and a core that is built but has no session must say so rather than vanish.

Depends on the Armv6-M disassembler ticket: the listing pane needs one before cortexm0 can fill it.

Done when a person can open XIAO-RP2040-DIP in the Emulator tab, step it, and read Arm registers and a Thumb listing, with the i8086 unchanged in behaviour.
