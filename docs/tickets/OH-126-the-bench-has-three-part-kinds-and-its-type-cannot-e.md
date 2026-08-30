---
id: OH-126
title: The bench has three part kinds and its type cannot express a third terminal
status: open
priority: P2
created: '2026-08-30'
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
