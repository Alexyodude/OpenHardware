---
id: OH-80
title: A resistor on the bench, so the circuit the warning asks for can be built
status: open
priority: P3
created: '2026-08-27'
touches:
- tools/import_3d_model.py
- tests/rules/test_import_3d_model.py
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
