---
id: OH-84
title: Two parts cannot be wired to each other, so a series circuit borrows a pin
status: open
priority: P3
created: '2026-08-28'
---

FOUND WHILE VERIFYING OH-80, WHICH IS THE TICKET THAT MADE IT MATTER. Every
wire on this bench runs from a BOARD PAD to a part terminal:
`webui/static/board3d.js`'s `connect(pin, part, terminalName)` looks the pin up
in `view.pads` and refuses anything it cannot find, and `analyse` in
`webui/static/circuit.js` reads wires as `{pad, part, terminal}`. There is no
shape in either file for a wire between two parts.

SO A SERIES CIRCUIT HAS TO BORROW A PIN. The circuit OH-80 exists to make
possible -- a resistor limiting the current through an LED -- was verified as
D13 -> resistor -> **D12** -> LED -> GND, using a pad the firmware leaves as an
input as the junction. That works and it is not a trick: an input pin is high
impedance, stamps nothing into the netlist, and is exactly a floating node. But
nobody wiring this on a breadboard would do it, and nothing on the page says it
is what you have to do.

It did not matter before OH-80 because there was nothing to put in series. Two
LEDs was the only pair worth chaining and the answer was 6 mA either way. A
current-limiting resistor is a part whose whole purpose is to be in series with
something, so the gap is now in front of the first thing a reader will try.

WHAT MIGHT BE DONE, unranked and none of them obviously right:

  * **A wire whose ends are both terminals.** The netlist already copes -- the
    union-find in `analyse` joins keys and does not care what they name -- so
    the change is a wire model with a nullable pad, a drag that can start on a
    terminal, and the report's `blind` and `reaching` checks taught to read it.
  * **Say the borrowed-pin trick out loud** in the bench hint, which is a
    sentence rather than a feature and is honest about the shape of the tool.
  * **Nothing, deliberately**, if the page is about what a pin does rather than
    about building circuits. That is a real answer and should be written down
    if it is the one chosen.

DONE WHEN either a reader can join two parts without naming a pad, or the page
tells them why they cannot and what to do instead -- and either way the choice
is recorded rather than left as a shape nobody decided on.

CLAIMS NOTHING ON PURPOSE. OH-80's own history is the reason: it was filed
claiming `tools/import_3d_model.py`, OH-81 then needed that file, and the claim
check failed on a lock nobody was using. A ticket that is not being started yet
claims nothing, and re-claims when it starts.
