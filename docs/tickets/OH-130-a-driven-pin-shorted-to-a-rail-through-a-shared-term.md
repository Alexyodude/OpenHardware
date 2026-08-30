---
id: OH-130
title: A driven pin shorted to a rail through a shared terminal is neither solved
  nor reported
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/static/circuit.js
- tests/webui/test_circuit.py
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 wire survey; verified by running the
real circuit.js under node with the Uno's own supply constants.

Wire D13(high) and GND both to an LED's ANODE: the pin is shorted to ground
-- 5 V / 40 ohm = 125 mA, past the 20 mA rating and the 40 mA absolute
maximum -- and the report says only "off ... cathode is in mid-air". Complete
the part with GND->cathode and it says "no current: nothing is driving it".
Same short, still silent. The machinery works when the part happens to light
(the D13+D12 case names its 63 mA), so this is a reporting hole, not a solver
hole: `analyse` joins a second wire onto a taken terminal without comment,
stamps the short into self-loops that vanish, and `warn` is only reached in
the `lit` branch.

DONE WHEN a pin-to-rail short through any topology is named with its current,
whether or not a part lights -- the existing rail-vs-rail refusal text is the
model -- and the three probed cases are tests.

---

**CLOSED 2026-08-30.** A reporting hole, exactly as filed: `pinAmps` had the
125 mA all along -- the pin's current comes straight out of the solve
whatever the parts do -- but the only reader of it was `warn`, and `warn`
was reachable only through a lit part.

The fix, in `webui/static/circuit.js`:

  * `pinSentence(name, amps, supply)` extracted from `warn`'s second half --
    one function for the two places the sentence is said, so they cannot
    drift.
  * `analyse` keeps a `named` set: driven pins a SURVIVING part warning
    names. A warning `destroys` nulled is not in it -- the destroyed verdict
    names the part's current, not the pin's.
  * A bench-level pass over `pinAmps`, FIRST in the notes: every over-limit
    pin not already named gets its sentence, whether or not anything lights.

The three probed cases are tests, plus a fourth:

  * D13+GND on the anode, cathode mid-air: still "off ... mid-air", and the
    note now says "Pin 13 carries at least 125 mA, past the 20 mA this board
    rates a pin for and past the 40 mA absolute maximum in the ATmega328P's
    datasheet, which is permanent."
  * The same short with GND->cathode completing the loop: the part's "no
    current: nothing is driving it" is true of the PART and stays; the note
    names the same 125 mA.
  * Two LEDs straight across D13 (~25 mA each, pin ~51 mA): both surviving
    warnings name Pin 13 and the note does NOT -- one sentence per fact.
  * One LED straight across D13: destroyed at 40 mA, warning nulled, and the
    pin's own fact moves to the note.

`test_a_bench_whose_parts_are_all_completely_wired_gets_no_junction_note`
moved from the bare LED to the 9.3 mA series pair, with the docstring saying
why: its old bench was never "nothing needs explaining" -- it was a 40 mA
pin nobody mentioned, which is this ticket's whole point.

**Recorded, not changed**: at exactly the limit the strict `>` rides
floating-point noise -- the direct-LED bench solves the pin at
40 mA + ~5e-11, so "past the 40 mA absolute maximum" appears for a current
whose exact value is the boundary. The comparison semantics are `warn`'s
own, unchanged; no test pins that clause at the boundary.

Suites: tests/webui/test_circuit.py 44 -> 48 passed; wires/board3d/editor
neighbours 106 passed. Five mutations, all killed: the note loop deleted,
the dedup dropped, the destroyed-warning exception widened, warn's pin
sentence dropped, the absolute clause deleted.
