---
id: OH-81
title: A part past its absolute maximum is destroyed, and the bench still draws it
  lit
status: done
priority: P2
created: '2026-08-27'
touches:
- webui/static/circuit.js
- webui/static/board3d.js
- webui/static/parts.js
- webui/static/board3d-panel.js
- webui/static/emulator.css
- tools/import_3d_model.py
- tests/webui/test_circuit.py
- tests/webui/test_board3d.py
---

REQUESTED BY THE USER 2026-08-27, straight after OH-79 landed: "you should
calculate the current that's flowing through and put a broken indicator for the
broken item according to the datasheet."

WHAT OH-79 LEFT HALF DONE. The current IS calculated -- an LED across an
Arduino UNO pin reports "at least 40 mA through it" -- and the part is still
drawn LIT, brightly, with a red sentence beside it. That is a picture of a
working LED next to a paragraph saying it would be destroyed, and when the
picture and the words disagree the picture wins. It is a milder version of the
same defect OH-79 fixed.

THE DISTINCTION THAT DECIDES THIS, AND IT IS A DATASHEET DISTINCTION. A rated
continuous current and an absolute maximum are different claims:

  * over the RATED current is a warning. It is outside what the part is sold
    against; it is not destruction, and plenty of circuits sit there.
  * over the ABSOLUTE MAXIMUM is destruction. DS40002061B's own words above
    that table: "Stresses beyond those listed under Absolute Maximum Ratings
    may cause permanent damage to the device."

So `damaged` is a fourth word beside `lit`, `off` and `unanswerable`, and it is
raised only by an absolute maximum. A part that publishes no absolute maximum
can be warned about and can never be declared destroyed.

WHAT HAS TO BE ADDED TO SAY IT. The LED carries `rated_amps` 0.020 today and no
absolute maximum, so nothing can currently be declared destroyed at all. It
gets `absolute_amps` as a class value like its other two -- but taken at the
GENEROUS end of the band rather than the pessimistic one, and that inversion is
deliberate and is the whole rigour of the claim:

  * OH-79's parameters are each chosen to make the CURRENT a lower bound.
  * this one is chosen to make the LIMIT an upper bound.
  * so "lower bound current exceeds upper bound limit" is destruction under
    every reading of both, and the bench cannot cry wolf.

30 mA is the top of the 20-30 mA DC absolute maximum a 5 mm indicator LED is
built to. Against a lower-bound 40.0 mA -- (5.0 - 2.2) / (40 + 30) exactly --
the LED is destroyed under any reading. The PIN at that same 40.0 mA is exactly
AT the ATmega328P's 40.0 mA absolute maximum and not past it, so it is warned
about and not declared dead, which is the honest edge.

IT HAS TO LATCH, and this is the design decision worth arguing before code. A
blink drives pin 13 high, then low. An indicator that cleared on the next poll
would show a destroyed LED as healthy half a second later, which is the lie
this whole area exists to stop -- and it is what an absolute maximum MEANS:
exceeding it is not reversible. So a part that has once been over its absolute
maximum stays `damaged` until it is removed from the bench, which is the same
thing a person does with a burnt LED.

`analyse` stays PURE. The latch lives in `board3d.js`, which owns the part
objects across polls; the bench handed to `analyse` carries `destroyed` per
part and gets it back. That keeps `tests/webui/test_circuit.py` able to assert
both a fresh verdict and a latched one without a clock.

WHAT IS DELIBERATELY NOT MODELLED: what a destroyed part does electrically.
A burnt LED fails open or short depending on how it died and this cannot say
which, so the netlist is unchanged and the reported circuit is still the intact
one. The panel says that in words rather than quietly solving a circuit whose
component is fictional.

AND THE PAD IS DELIBERATELY NOT RECOLOURED. When the PIN passes its own
absolute maximum the warning names it, and the pad marker stays the colour of
the register this repository read. `board3d.js`'s header makes that promise in
its first paragraph -- "a pad drawn bright here is only ever a picture of a
register this repository read" -- and a fifth pad colour standing for a
conclusion rather than a measurement would break it. `webui/api.py`'s
`PIN_STATES` is four words for the same reason.

LEAST CONFIDENT: what a destroyed part should LOOK like in three dimensions.
`off` is already dark, so dark is taken. The plan is the palette's `--halt`,
flat and unlit, because that is what every other "this went wrong" on the page
is -- but a red LED that is broken and a red LED that is lit are both red, and
this may need a second cue.

DONE WHEN an LED wired D13 -> GND on a running blink is drawn destroyed rather
than lit, says which datasheet limit killed it, stays destroyed when the pin
goes low, and a two-LED series circuit at 6 mA is not touched.

**Note 2026-08-27:** CLOSED 2026-08-27 in 480a206. A part past its datasheet's absolute maximum is drawn destroyed, says which limit killed it, and stays destroyed when the pin goes low -- verified in Chromium against a real 300 ms blink, in both themes.

THE ONE NUMBER TAKEN AT THE GENEROUS END, AND IT IS THE RIGOUR OF THE CLAIM. Every parameter OH-79 added is chosen to make the computed CURRENT a lower bound. `absolute_amps` is chosen to make the LIMIT an upper bound. 'A lower-bound current exceeds an upper-bound limit' then holds under every reading of both, which is what makes it safe to print the word destroyed. Picking the pessimistic end here instead would have condemned parts a more generous datasheet allows.

A REAL BUG THE TEST FOUND BEFORE THE CODE SHIPPED: the warning compared the PART's current against the PIN's ratings. Two LEDs across one pad draw 25 mA each and the pad delivers 51 mA, so a pin a quarter past its absolute maximum was being reported as inside it. This is the OH-79 generalisation again from the other side -- a check that reads one input cannot notice a second one exists -- and it was invisible until a bench had two parts on one pin.

IT SURVIVED THE FIRST MUTATION PASS TOO, because with two LEDs the correct and the mutated code fire the same clause: 25 mA is over the pin's 20 mA rating whichever current you measure. Killing it needed THREE LEDs, where each part draws 18.7 mA -- inside every rating it has -- while the pin carries 56 mA. A case that distinguishes the fault, not a case that exercises the line.

THE LATCH IS THE DESIGN DECISION. A blink drives a pin high then low; a verdict recomputed from the circuit alone would clear half a second later. Past an absolute maximum is permanent, so the indicator has to be. `analyse` stays PURE -- the bench carries `destroyed` in and the report carries it out, and `board3d.js` owns the memory because it owns the part objects. That is what lets a test assert both a fresh verdict and a latched one without a clock.

KNOWN LIMITATION, AND IT WAS THE 'least confident' NOTE IN THIS TICKET'S BODY: colour is the only channel the 3D view has, and at the size a 5 mm LED is drawn a broken red one and a lit red one are both red. `--halt` reads clearly in the dark theme and less so in the light one, where it is a maroon against the LED's own dark red. The panel carries the unambiguous statement -- the word DESTROYED and the limit that killed it -- and the mesh is a cue. A second cue in the 3D view is worth having and is nobody's ticket yet.

AND WHAT THIS COSTS, WHICH IS NOT SMALL: there is now no way to light an LED on an Arduino Uno without destroying it. Two in series at 6 mA is the only intact circuit this bench can build, because there is no resistor on it. That is the physically correct answer and it makes OH-80 load-bearing rather than a nicety.

A PROCESS FINDING: OH-80 was filed claiming `tools/import_3d_model.py` for work nobody had started, and this ticket then needed the same file. The collision failed the gate and was fixed in 9670b71 by narrowing OH-80 off every path. A claim is a lock; a lock held for work nobody is doing only ever blocks work somebody is.

---

**CORRECTION 2026-08-30 (OH-131).** The latch's justification above -- the
only thing that undoes `destroyed` is `removePart`, "which is what a person
does with a burnt LED" -- described a hatch that did not exist: `removePart`
was exported and nothing in the page called it, so a burnt part sat on the
bench for the life of the tab. OH-131 put a remove control on every part
row, wired to it. The latch design itself is unchanged and right.
