---
id: OH-79
title: An LED lights while ungrounded, because nothing here solves a circuit
status: done
priority: P2
created: '2026-08-27'
touches:
- webui/static/circuit.js
- webui/static/board3d.js
- webui/static/parts.js
- webui/static/board3d-panel.js
- webui/boards/atmega328p.py
- webui/boards/samd21.py
- webui/api.py
- tools/import_3d_model.py
- tests/webui/test_circuit.py
- tests/webui/test_board3d.py
- tests/webui/test_pin_view.py
- tests/rules/test_import_3d_model.py
- webui/static/emulator.css
- webui/static/emulator.html
---

REPORTED BY THE USER 2026-08-27: "the led is lighting up even though not
grounded. This issue stems from not physcially simulating the properties of the
datasheet and components." Asked whether to build a complete-circuit rule, a
full nodal solver with datasheet parameters, or the rule now and the solver
later, they chose SOLVER NOW, DATASHEET PARTS.

THE DEFECT, EXACTLY. `webui/static/board3d.js`'s `applyState` is four lines:
read the pad the wire came from, read its logic level, hand that to
`parts.js`'s `setPartState`, which maps `high` to `lit` through `DRIVE`. There
is no second terminal, no ground and no current anywhere in that path. An LED
with one leg on D13 and the other in mid-air lights; so does one wired
backwards. The picture is not a measurement, which is the failure this
repository ranks worst.

`CLAUDE.md`'s opening already names "analog circuit solving" as a goal of the
project, so this is on the roadmap rather than a detour.

WHAT IS ALREADY THERE, verified 2026-08-27. `connections()` reports
`{id, pin, kind, label, terminal}` per wire, so the topology is in the browser.
`view.pads` is keyed by the pad name `webui/api.py` sends, which is the
silkscreen label without its PWM tilde -- so `GND`, `5V` and `3V3` arrive as
themselves. The Uno's three GND pads collapse to one entry in that Map, which
is exactly right for a circuit and wrong for nothing. `dressPart` already
builds `userData.terminals` as name -> anchor off the mesh.

THE DESIGN, following the house pattern that `wires.js` and `clock.js` set.

    webui/static/circuit.js          -- imports NOTHING, so node can run it
      export const RAILS             -- pad label -> volts, and why
      export const LIT_AMPS          -- the current a red LED is visible at
      export const GMIN, MAX_PASSES
      export function solve(net)     -- MNA, PWL diodes: {volts, amps, ok}
      export function analyse(bench) -- the whole bench: per part a verdict

    tests/webui/test_circuit.py      -- runs it under node, as test_wires.py does

Modified nodal analysis: unknowns are the node voltages plus one current per
ideal voltage source, Gaussian elimination with partial pivoting, GMIN from
every node to ground so an island cannot make the matrix singular -- which is
SPICE's own trick and is here for the same reason. A diode is piecewise
linear: OFF is a leakage conductance, ON is `forward_volts` in series with
`series_ohms`, and the states are iterated to consistency. A solve that does
not converge SAYS SO and the page reports nothing rather than guessing.

EVERY NUMBER IS THE WORST CASE THE DATASHEET GUARANTEES, WHICH MAKES EVERY
CURRENT A LOWER BOUND. This is the property that makes the warning sound: a
lower bound over the rating is a fact, and a lower bound under it is not a
clean bill of health -- so the page may say "this is too much" and may never
say "this is fine". Read out of the PDFs on 2026-08-27, not from memory:

  ATmega328P, DS40002061B (Microchip, 2020)
    p.322  Absolute Maximum Ratings: DC Current per I/O Pin 40.0mA
    p.323  Table 30-1 VOH min 4.2V at IOH = -20mA, VCC = 5V, TA = 85C
           -> source resistance at most (5.0-4.2)/0.020 = 40 ohm
    p.322  Table 30-1 VOL max 0.9V at IOL = 20mA, VCC = 5V, TA = 85C
           -> sink resistance at most 0.9/0.020 = 45 ohm
  Arduino UNO R3, arduino/docs-content tech-specs.yml
    I/O Voltage: 5V .  DC Current per I/O Pin: 20 mA
  SAM D21, DS40001882L (Microchip, 2026)
    p.916  Table 37-15 VOH min 0.8*VDD at IOH max 2mA, VDD 3-3.63V, DRVSTR=0
           -> source resistance at most 0.66/0.002 = 330 ohm
    p.916  VOL max 0.2*VDD at IOL max 2.5mA, same conditions
           -> sink resistance at most 0.66/0.0025 = 264 ohm
    p.906  Table 37-2 note 1: 46mA source and 65mA sink PER CLUSTER, and no
           per-pin absolute maximum at all -- so that field is absent rather
           than filled in with a plausible number.

DRVSTR = 0 is the reset value of `PORT.PINCFG` and `webui/boards/samd21.py`
stores that byte without interpreting the bit, so the model says which
assumption it is making rather than hiding it.

WHERE THE PART'S NUMBERS GO: with the part, in `tools/import_3d_model.py`'s
`PARTS`, into the GLB extras, each with its provenance -- the pattern
`tools/model_from_datasheet.py`'s `SPECS` sets and the reason its docstring
gives.

AND HERE IS THE HONEST PROBLEM WITH THE LED, stated rather than papered over.
KiCad's mesh is a GENERIC 5 mm through-hole LED. It carries no part number, so
there is no datasheet to read -- unlike the two chips above, whose PDFs are
cited to the page. So the LED's forward drop and series resistance are class
values for a red indicator LED, and each is taken at the end of its range that
makes the computed current a LOWER bound: 2.2V of 1.8-2.2, and 30 ohm of
10-30. Named as class values in the file, not dressed up as measurements. A
specific part number would be strictly better and should replace them.

THE BUZZER GETS NO ELECTRICAL MODEL AT ALL, and that is the honest answer: a
12 mm buzzer is either a magnetic coil of a few tens of ohms or a piezo element
that is an open circuit at DC, and a generic mesh does not say which. It is a
conductor of unknown value, so it still needs a complete circuit to do
anything, and no current is reported for a circuit containing one.

WHAT THE PAGE SHOULD THEN BE ABLE TO SAY, and this is what earns the exercise:
an LED straight across a pin with no series resistor draws far more than the
20mA Arduino rates a pin for, so the bench should say "no current limiting"
instead of lighting it prettily. There is no resistor on this bench to fix that
with -- see NOT IN THIS TICKET.

NOT IN THIS TICKET.
  * A resistor part, so a reader can BUILD the circuit the warning asks for.
    It needs a mesh fetch, a lens-less part and a story about which value, and
    it is the obvious follow-up. Filed separately or it swallows this one.
  * A part driving a pin. Still needs PINB/PINC/PIND and PORT_IN, still its own
    ticket -- but note a solver is the natural place for a switch to close a
    node, which OH-73 predicted.
  * AC, capacitance, and therefore a buzzer that sounds.
  * Boards that report no pin states at all. Nine of the ten boards with a 3D
    model cannot answer for a pin, so nothing there changes.

LEAST CONFIDENT, while changing it still costs a sentence.
  1. `analyse` returning a verdict per part rather than the caller reading node
     voltages. It hides the netlist, which is the point, but it is also the
     interface that will have to grow when a part has three terminals.
  2. Flagging EVERY current in a bench that contains one unmodelled part,
     rather than only the ones actually in series with it. Over-cautious by
     construction; the alternative is a connectivity walk that is more code
     than the thing it refines.
  3. LIT_AMPS as a single threshold. A red LED is visible well below 1mA and
     unambiguous above it; anything between is a judgement this makes once.

DONE WHEN, and each of these is a browser check as well as a test: an LED wired
from D13 with its other leg in mid-air does NOT light; wiring that leg to GND
lights it; reversing the two legs stops it; and the page states the current
with the rating it is measured against.

**Note 2026-08-27:** CLOSED 2026-08-27 in 08b1fb7. An LED needs a complete circuit, in the right direction, before it lights -- verified in Chromium against a running blink with pin 13 genuinely high, not against a stopped board where every pad reads `input` and an LED would be dark either way.

THE GENERALISATION: a check that reads ONE input cannot notice that a second one is missing. `applyState` looked up the pad a wire came from and drove the part with its level; every case it was ever tried on had both legs wired, so it was right for a year by the shape of its inputs rather than by anything in it. The one-legged case was not a corner it handled badly -- it was a question it never asked.

THE DESIGN THAT MADE THE NUMBERS SAFE, and it is the transferable part. Every resistance is derived from the WORST corner a datasheet guarantees: a minimum output voltage is a maximum output resistance, so the current computed through it is a LOWER bound on the real one. That asymmetry decides what may be said. A lower bound over a rating is a fact; a lower bound under one is not a clean bill of health. So the page warns and never reassures, and `circuit.js`'s header says so before any code.

READ, NOT RECALLED. DS40002061B pages 322-323 for the ATmega328P's 40.0 mA absolute maximum and its VOL/VOH at 20 mA; DS40001882L page 916 for the SAM D21's, and page 906 for the fact that it states no per-pin absolute maximum AT ALL -- its limit is 46 mA source per CLUSTER, so that field is null rather than filled in with something plausible. Arduino's own `tech-specs.yml` in `arduino/docs-content` for the UNO's 5 V and 20 mA. Both PDFs were downloaded and read; `pdftotext -layout` and `grep` is enough and took four minutes.

AND THE ONE NUMBER THAT COULD NOT BE SOURCED SAYS SO. KiCad's LED mesh is generic -- no manufacturer, no order code, no datasheet. Its forward drop and series resistance are CLASS values for a red indicator LED, each taken at the end of its range that keeps the bound a lower one (2.2 V of 1.8-2.2, 30 ohm of 10-30), and labelled as class values beside citations that are not. A part number would be strictly better.

MUTATION TESTING FOUND TWO REAL WEAK TESTS out of 23 mutations, and both were the same shape: a circuit that cannot distinguish the fault. An LED from an INPUT pin to GROUND is dark whether that pin is high impedance or a dead short, and a reversed diode reads off through its current's sign whether or not the model blocks it. Both are wired from the RAIL now, where the two answers differ. The other two survivors were greps that matched a name inside a branch the mutation had turned off.

NOT IN THIS TICKET, and the first is what a reader will want next: OH-80, a resistor on the bench, so the circuit the warning asks for can actually be built. Also unchanged: a part driving a pin, which still needs PINB/PINC/PIND and PORT_IN; AC, so no buzzer that sounds; and the lighting, which is still two lights and no shadows on a scene with fifteen objects.
