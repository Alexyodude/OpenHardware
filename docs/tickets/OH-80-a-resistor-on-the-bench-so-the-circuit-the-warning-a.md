---
id: OH-80
title: A resistor on the bench, so the circuit the warning asks for can be built
status: done
priority: P3
created: '2026-08-27'
touches:
- tools/import_3d_model.py
- tests/rules/test_import_3d_model.py
- webui/static/circuit.js
- webui/static/parts.js
- tests/webui/test_circuit.py
---

WHAT OH-79 LEFT, AND IT IS VISIBLE ON EVERY BENCH. `webui/static/circuit.js`
now says, correctly, that an LED across an Arduino UNO pin draws at least 40 mA
against the 20 mA Arduino rates a pin for -- and there is nothing on the bench
to fix that with. Every LED circuit a reader can build is one the page warns
about, which makes the warning noise rather than information.

THE PART. KiCad's `Resistor_THT` library, whose axial through-hole models are
the same class of thing as the LEDs already fetched from `LED_THT`. It needs
three small changes to `tools/import_3d_model.py`:

  * `Part.lens` becomes optional. A resistor does not light, `dressPart`
    already copes with `extras.lens` being absent, and `convert_part` raises
    today if the named colour is not in the mesh.
  * an `Electrical` of kind `resistor`, which `circuit.js` already stamps --
    `analyse` reads `model.ohms` for a non-diode part and the netlist path is
    exercised by `test_current_is_conserved_at_every_node`.
  * one entry per value offered.

WHICH VALUE, AND THIS IS THE ONLY REAL QUESTION. One fixed 220 ohm part is the
concrete answer and the classic Arduino LED resistor: (5.0 - 2.2) / (40 + 30 +
220) = 9.7 mA, comfortably under both of the UNO's ratings, and it makes the
warning stop. A menu of values is a configuration option with one call site
today, which `.claude/CLAUDE.md` rule 6 says not to build.

**But a fixed value has an honesty problem worth deciding before writing code.**
KiCad's mesh carries painted colour bands, and they are the model's own -- they
will not read 220 ohm. Calling a part `220 ohm` while its picture says
otherwise is a small version of exactly the defect this area keeps
re-learning. Either the label says the bands are the model's and not the value,
or the value comes off the bands, or the part is named for its package and
carries its value in the panel rather than on the mesh.

DONE WHEN a 5 mm LED wired D13 -> resistor -> GND lights, the page reports a
current inside every rating the board publishes, and no warning is raised --
and when the part's own label does not claim a value its picture contradicts.

**Note 2026-08-27:** NARROWED OFF EVERY PATH, and this ticket re-claims them the
day it starts: `tools/import_3d_model.py` and `tests/rules/test_import_3d_model.py`.

It was filed claiming both, and OH-81 then needed the first of them to give the
LED an absolute maximum -- so two open tickets claimed one file and
`test_this_repositorys_tickets_parse_and_do_not_collide` failed the gate. That
is the check working: the collision was latent from the moment this was filed
and nothing would have surfaced it until a second ticket wanted the file.

**The general shape, worth remembering when filing a follow-up:** a ticket that
is not going to be started yet should claim nothing. A claim is a lock, and a
lock taken for work nobody is doing only ever blocks work somebody is.

**Note 2026-08-28:** **CLOSED 2026-08-28, and the open question dissolved on measurement rather
than being decided.** This ticket said the only real question was that KiCad's
resistor mesh carries painted colour bands which will not read 220 ohm, so a
part labelled with a value its picture contradicts would be a small version of
the defect this area keeps re-learning. Tessellated on 2026-08-28,
`R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal` has exactly TWO styled
colours -- `#a5a392` on the leads and `#c07635` on the body -- and NO BANDS.
The STEP itself defines two `COLOUR_RGB` entries and no more. The picture makes
no claim for the label to contradict, so the part is `220 Ω resistor` and the
question needed a `read()` call rather than a decision.

**THE ESTIMATE OF THREE CHANGES TO ONE FILE WAS WRONG, and the way it was wrong
is worth keeping.** `webui/static/circuit.js` counted EVERY non-diode part as
`assumed` -- a conductor of unknown value, which suppresses the reported
current through everything else on the bench. That branch was written when no
part had a stated resistance, so it was correct and untested at once. The first
resistor added would have deleted the current through the LED it was limiting,
which is the exact opposite of the point. `webui/static/parts.js` also dropped
`ohms` in transit, the same way it once dropped `absolute_amps`. Five files,
not two.

**THE MODELLED VALUE IS 231 AND NOT 220, and that is the one invariant here.**
Every resistance the solver is handed is a datasheet's worst corner, so every
current it computes is a lower bound and the page may warn but may never
reassure. A real 220 ohm +-5% part may be 209 ohm and 209 passes MORE current
than 220, so a bench modelled at nominal would print "at least 9.7 mA" about a
circuit carrying 10.0. 231 is the top of the band.

**Verified in Chrome against a running blink with pin 13 observed high**, not a
stopped board: D13 -> 220 ohm resistor -> D12 -> 5 mm LED -> GND reports "at
least 9.3 mA through it" on both rows, with no warning and no destroyed badge.
The negative control is the same LED with the resistor taken out, which is
DESTROYED. See `.playwright-mcp/resistor-limited-lit.png`.

**One limitation found while verifying, and it is nobody's ticket yet:** every
wire on this bench runs from a BOARD PAD to a part terminal, so two parts
cannot be joined directly and a series chain has to run through a spare pad the
firmware leaves as an input. That is why the circuit above goes through D12.
