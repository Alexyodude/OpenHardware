---
id: OH-126
title: The bench has three part kinds and its type cannot express a third terminal
status: done
priority: P2
created: '2026-08-30'
touches:
- tools/import_3d_model.py
- webui/static/parts.js
- webui/static/circuit.js
- tests/rules/test_import_3d_model.py
- tests/webui/test_circuit.py
- tests/webui/test_board3d.py
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 model survey; sized for the
"peripheral modules" ask.

`PARTS` is five entries -- three LED sizes on one die, a buzzer whose
electrical is None (it can never carry a current claim), one 220R resistor.
`Part.terminals` is a hard 2-tuple and circuit.js stamps only
resistor/diode/current/source, so no potentiometer, transistor, servo,
seven-segment or Grove module is expressible without widening the type.

The INPUT half is genuinely blocked and stays out of scope here:
`import_3d_model.py` refuses a switch because it would drive a pin, and
`webui/boards/atmega328p.py` PIN reads still return the stored zero -- a
button needs readable PINx first, which is its own core change.

DONE WHEN the terminal type admits N-terminal parts, one three-terminal part
(a potentiometer is the natural first: passive, no pin-drive question) exists
end to end -- model, electrical stamp, solver, report -- and OH-116 stays the
owner of part-to-part wiring.

---

**CLOSED 2026-08-31.** The type admits N, and the 5 kΩ trimmer exists end
to end: KiCad's Bourns 3266W vertical mesh, an electrical stamp, the
solver, and the report.

  * **`Part.terminals` is a tuple of N** -- the hard 2-tuple was the single
    line that made a third terminal inexpressible; every reader downstream
    (the extras, `dressPart`'s loop, `terminalsOf`, the mid-air sentence)
    was already generic, verified by the tests that now drive them with
    three.
  * **`lead_tips` clusters on (x, z) instead of splitting on the sign of
    x**: the 3266W's three pins zig-zag -- x at -2.54, 0, +2.54 with z
    alternating, measured off the vendor's mesh -- and the middle pin has
    no side. Each cluster keeps its own floor ring, so the five two-lead
    parts' tips did not move (regenerated and their tests hold).
  * **The electrical model is two resistors sharing the wiper node**, the
    wiper standing at `POT_TRAVEL = 0.5` -- a stated constant with its
    argument, because the bench has no knob to turn yet; solving any
    position already works. 5,500 Ω is the TOP of the '502' code's ±10%
    band, the 220 Ω resistor's own lower-bound argument, and no current
    limit is cited because the 3266's limit is a quarter watt no 5 V bench
    reaches through 5.5 kΩ -- `destroys` can never claim it.
  * **The report answers the busiest leg**, which the asymmetric
    half-wired case makes meaningful: 5 V to lead A and ground to the
    wiper is 1.818 mA through one half and nothing through the other.

Four runtime cases under node, hand-worked throughout (5/5500, the
1375/1415 divider, 5/2750, and the two-name mid-air sentence). Five
mutations, all killed -- the stamp collapsed to two terminals, the wiper
moved off the middle pin, the report pinned to one half, the travel
constant drifted, and the third terminal dropped.

The INPUT half stays out of scope exactly as filed: a button still needs
readable PINx first, and OH-116 stays the owner of part-to-part wiring.
