---
id: OH-84
title: Two parts cannot be wired to each other, so a series circuit borrows a pin
status: done
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

## DONE, 2026-08-30 -- the SECOND option was chosen, and here is why

**The page now tells a reader why two parts cannot be joined and what to do
instead**, which is this ticket's own second Done-when. The wire itself is
OH-116.

`webui/static/circuit.js`'s `analyse` returns a bench-level note when there
are two or more parts and at least one has a leg in mid-air -- which is what
somebody trying to chain them is looking at:

> A wire runs from a board pad to a part terminal, so two parts cannot be
> joined to each other directly. To put parts in series, use a pad the
> firmware leaves as an INPUT as the junction -- an input is high impedance
> and stamps nothing into the netlist, so it is exactly a floating node.
> D13 -> resistor -> D12 -> LED -> GND is a current-limited LED wired that way.

**It says WHY the borrowed pin works**, which is the half that makes it advice
rather than a workaround: this ticket's own text argues the input is a genuine
floating node, and a reader who is not told that will reasonably assume they
are being asked to fake something.

**Shown narrowly on purpose.** One part on the bench cannot be in series with
anything, so the mid-air reason is already the whole story and the note would
be noise; a complete circuit gets nothing at all. Both are asserted, because a
note that appeared on a working bench would train a reader to ignore the
notes.

## WHY NOT THE FIRST OPTION HERE

This ticket says "the netlist already copes ... so the change is a wire model
with a nullable pad". The union-find does cope; **five other readers in
`analyse` do not**, because they are all `wire.part === index` and a
part-to-part wire touches two parts. `board3d.js` adds five more. The honest
shape is a wire with two ENDS, and that is a data-model change across two
large files -- with the drag half not testable by any harness here, while the
netlist half is testable under node. Landing only the half that can be checked
would leave a netlist supporting a wire the UI cannot create.

Written up as OH-116 with all ten call sites listed, so the option stays open
and costed rather than being re-discovered.

Four mutations, all killed.
