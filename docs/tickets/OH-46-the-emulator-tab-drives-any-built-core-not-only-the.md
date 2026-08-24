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
- webui/static/emulator.css
- tests/webui/test_emulator_session.py
---

DRIVING = 'i8086' in webui/emulator_server.py is the last place a core is named. cortexm0 is built and four boards run real firmware through /api/board/load, and none of them can be opened in the debugger -- no registers, no disassembly, no memory view -- because webui/emulator.py is a Session over core.i8086 and there is only one session type.

The coupling is two lines: 'from core.i8086 import abi, disasm' and one call to disasm.disassemble_range. Everything else in that file is already about stepping a CPU rather than about x86.

A person thinks in boards, so selection should be board-first: pick XIAO-RP2040-DIP, not cortexm0. webui/api.py already resolves a board to a core and a memory map (runtime_for), and webui/boards/contract.py already states what a board must supply, so the resolution exists and this ticket is about driving it rather than rebuilding it.

Keep the refusals. targets.py's UNBUILT state and its message carry the command that fixes them, and a core that is built but has no session must say so rather than vanish.

Depends on the Armv6-M disassembler ticket: the listing pane needs one before cortexm0 can fill it.

Done when a person can open XIAO-RP2040-DIP in the Emulator tab, step it, and read Arm registers and a Thumb listing, with the i8086 unchanged in behaviour.

**Note 2026-08-25:** The UX finding that sharpens this, from using the page rather than reading it: the workflow is in the wrong tab, not merely the selector.

webui/static/emulator.html:115 puts the whole program-and-upload flow -- board picker, file input, load base, Load, Run, and the UART console -- inside the Targets view, underneath the progress tables and the architecture survey. Meanwhile the Emulator view's toolbar carries a #target selector whose options come from /api/targets and which, with DRIVING = 'i8086', can only ever offer one thing.

So the research tracker owns the workflow and the workflow tab owns a one-item dropdown. That is backwards, and it is why someone asks why they are choosing a target on the Targets tab.

The #target selector sits outside .only-emulator deliberately -- the comment says 'which machine you are driving is true in both views, and hiding it on the Targets tab would hide it exactly where someone went looking for it.' That reasoning was right while Targets owned the upload flow and stops being right the moment it does not.

Intended end state: the Emulator tab carries ONE machine picker listing the i8086 sample machine and each runnable board, plus upload, run and the debug panes. The Targets tab becomes read-only -- what has progressed, and nothing to operate.
