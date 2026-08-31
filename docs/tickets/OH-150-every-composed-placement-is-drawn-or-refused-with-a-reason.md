---
id: OH-150
title: 'Every composed placement is drawn or refused with a reason'
status: done
priority: P2
created: '2026-08-31'
touches:
- tools/compose_board_3d.py
- tools/model_from_datasheet.py
- tests/rules/test_compose_board_3d.py
- tools/model_from_datasheet.py
- tests/rules/test_import_3d_model.py
---

From the ralph run "fix all not modelled" (2026-08-31). The composer's own
`--check` reports, per board, the placements "drawn as nothing, with no
ABSENT entry saying why" — 21 distinct packages across the ten composed
XIAO variants, from 36 bare test points to one unidentified 50-pad
connector. Every one must end the run in one of the two honest states the
codebase already defines: a model row `confirm` accepts, or an `ABSENT`
entry whose paragraph carries a measurement and names the library searched
(or states there is no body to look for — the Uno's TP-SP precedent).

Sixteen read-only scouts are producing the evidence under
`.omc/research/unmodelled/`; this ticket is the serial integration of
their findings into the two tables, plus whatever the SLABS name-parser
needs to accept the vendor spellings the inventory contains
(`DFN6-0.5-1.45X1X0.6` without the MM suffix; `SOT8_0d5_...` with `0d5`
and underscores; lowercase `mm`).

DONE WHEN `python tools/compose_board_3d.py --check` emits no
"no model ... with no ABSENT entry" line for any board; every new
Component/ModelledSlab row passes `confirm`/the named-body tolerance on
every board that places it; every new ABSENT entry satisfies the existing
mm-and-KiCad tests; all composed boards regenerate; and the full gate is
green.

---

**CLOSED 2026-08-31.** `compose --check` exits 0 over all eleven boards
with **no "no model" line anywhere** -- 191 unaccounted placements to
zero. Sixteen read-only scouts produced the evidence
(`.omc/research/unmodelled/`); the integration was serial because every
row lands in the same two tables.

**Ten refusals, each with its measurement.** Three test-point packages
(64 placements, each a bare pad sized to its own name -- 1.143 mm at 45
mil, 2.032 x 1.016 at 80x40), three logos (measured 9.571 x 1.070,
7.498 x 0.846 and 4.046 x 2.947 mm of silk, all already counted as ink
or as `not ink` by the composer itself), the two MOUDLE14P castellation
footprints and the C3's H7 pair (pads sitting exactly on the Edge.Cuts
they themselves draw -- `tools/kicad.py` had said so in a comment for
two tickets), and `BGA6-0.35-0.745X10.95X0.4MM`, whose own name states
10.95 mm for a part measuring 1.200 x 0.840: **a name wrong about the
dimension a layer can check cannot be trusted for the height no layer
carries**, which is `slab_geometry`'s own argument, and it refuses the
package by it.

**Eleven parts drawn.** Eight modelled slabs (WLCSP4, WLCSP-0.92,
BGA6-0.85, DFN6-0.4, DFN6-0.5, SOT8, X2SON4, CAF) and three chip diodes
in borrowed mouldings (ESD-0201 and ESD-0402 as resistors -- which is
what Seeed themselves name on all seven ESD-0201 placements, and the
trade this table already makes for Z1/Z2's varistor and F1's fuse --
plus DFN1006-2L as `D_SOD-882`, the outline the C6's own Description
names). Every slab states its plan twice and is cross-checked against
the vendor's F.Fab: agreement runs 0.000 to 0.020 mm, except DFN6-0.4's
0.260 where the name and the Description give the same rectangle the two
ways round.

**Two pieces of machinery, both minimal.** `_NAMED_BODY` learned the
three decimal points Seeed actually use (`0.6MM`, `0.6mm`, `0_6mm`) and
an optional unit, with `_named_float` defusing a genuine trap --
`float("2_1")` is 21.0 in Python, so a 2.1 mm body would have parsed as
21 mm. All ten pre-existing names parse to identical numbers, checked
rather than assumed. And `slab_geometry` falls back to the footprint's
own `Description` for a height its name omits, reusing the
`_STATED_ENVELOPE` reader `socket_geometry` already trusts -- the CAF
diplexer states its 1.6 x 0.8 plan three times over and its 0.7 mm
height only there.

**This re-decides OH-104 rather than filling its gap.** That ticket
named these parts and chose not to draw them: "not what a person
notices... each is another judgement to keep true." Two scouts flagged
independently that pushing them into ABSENT instead would misrepresent a
library search that never happened. The instruction here was to fix all
not modelled, so they are drawn, and the ones that genuinely cannot be
say why.

**Found on the way, deliberately not acted on:** `BUTTON_TD1183SA`'s
ABSENT text says Seeed "states no height for it, in the footprint name
or on any layer" -- but its own Description reads `2P-L3.0*W2.5*H1.5mm`.
`_STATED_ENVELOPE` cannot parse that form, so nothing changed silently
and the button stays refused; the justification wants its own ticket.
