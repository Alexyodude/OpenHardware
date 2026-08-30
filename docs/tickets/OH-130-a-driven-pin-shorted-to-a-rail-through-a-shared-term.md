---
id: OH-130
title: A driven pin shorted to a rail through a shared terminal is neither solved
  nor reported
status: open
priority: P2
created: '2026-08-30'
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
