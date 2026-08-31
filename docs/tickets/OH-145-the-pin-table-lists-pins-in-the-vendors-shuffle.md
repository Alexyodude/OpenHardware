---
id: OH-145
title: 'The pin table lists pins in the vendor''s shuffle'
status: done
priority: P3
created: '2026-08-31'
touches:
- webui/static/board3d-panel.js
- tests/webui/test_board3d.py
---

Reported 2026-08-31: "pin for all is not sorted." The table beside the 3D
view lists rows in whatever order the layout walked the vendor's file:
the XIAO ESP32-C3 reads `D6, D5, D4, D3, D2, D1, D0, D7, D8, D9/BOOT,
D10, …` — descending, then ascending, then rails. The Uno happens to
read as the physical header walk, which is defensible on that one board
and an accident everywhere else. The table is the one place a reader
looks a pin UP, and a lookup wants an order.

DONE WHEN the table shows numbered pins first in numeric order — the
pins a sketch drives — then everything else in natural alphabetical
order with digit runs compared as numbers, so D10 follows D9 rather
than D1; the sort is display-only (the layout's own order feeds the 3D
view and the solver, which never cared); and the comparator's behaviour
is proven by running it, not by grepping it.

---

**CLOSED 2026-08-31.** `renderTable` sorts a copy — `layout.pads` keeps
the vendor's order for everything that never cared — through
`pinOrder`, a self-contained comparator: purely numeric labels first,
numerically; then natural alphabetical with digit runs compared as
numbers. **A leading `~` is stripped for ordering only** — the tilde is
Arduino's PWM mark, part of `~11`'s label and not of its place — a rule
the first browser run taught, having exiled all six PWM pins past VIN.

Measured in a real browser, both boards' first columns whole: the Uno
reads `0, 1, 2, ~3, 4, ~5, ~6, 7, 8, ~9, ~10, ~11, 12, 13` and then
`3V3, 5V, A0..A5, AREF, GND, GND, GND, IOREF, NC, RESET, SCL, SDA, VIN`
— duplicates intact; the C3 reads `3V3_OUT, D0..D9/BOOT, D10, GND,
VBUS`, digit-leading rails following the bare numbers exactly as the
rule says.

Verified by running, as the ticket demanded: the comparator's own text
is extracted from the panel source and executed under node against a
mixed sample (numerics, tildes, rails, `D9/BOOT` vs `D10`), and the
sorted answer asserted whole. A source pin holds `renderTable` to
sorting through `pinOrder`. Two mutations killed: the sort dropped from
`renderTable` (source pin), and the numeric compare replaced with a
string compare (node run — `13` slid before `2`).
