---
id: OH-137
title: The i8086 toolbar stays live over a loaded board and overwrites its panes
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 API/IDE survey.

The i8086 toolbar (#step/#run/#stop/#reset) and the #at memory box stay live
when a BOARD is loaded, and they drive the 8086 routes: press Step over an
Uno and the AVR's 34 named registers silently become ax/bx/cx/dx, the
disassembly becomes 8086, the hexdump jumps -- the panel-desync case.
#status/#counter never update for a board at all.

DONE WHEN loading a board disables or rebinds the 8086-only controls, the
panes always say which machine they are showing, and a test drives the
desync case.
