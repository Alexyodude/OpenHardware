---
id: OH-154
title: The load switch is refused for want of a model, while its name states its body
status: done
priority: P2
created: '2026-08-31'
touches:
- tools/model_from_datasheet.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

The load switch is refused for want of a published model, which is the
precondition for modelling a slab rather than a reason to refuse one. Its
footprint name states all three dimensions and the vendor's own F.Fab agrees
with them.

Found by sweeping every ABSENT package through slab_geometry -- the general
form of the bug OH-153 fixed for the buttons. Measured 2026-08-31:

    PMOS_1.0X0.6X0.35MM   <<< the only remaining false absence
        ESP32-C6:  would draw [1.0, 0.6, 0.35] from its name, 0.000 mm apart
        RP2350:    would draw [1.0, 0.6, 0.35] from its name, 0.238 mm apart
        nRF54L15:  would draw [1.0, 0.6, 0.35] from its name, 0.238 mm apart

Every other refused package came back genuinely refused: the mis-named BGA6
disagrees with its outline, the logos and H7 and TP-80X40MIL state no
height, and TP-D45MIL, TP-1.6MM-ROUND and both MOUDLE14P footprints draw no
F.Fab at all. So this is the last one.

Its stated reason (_NO_CHIP_SCALE_MOSFET) reads: "the load switch. Three
pads spanning 0.650 x 0.350 mm -- a chip-scale MOSFET one millimetre long.
The nRF54L15's own board file names the package: SOT-883.STEP, which settles
what it is. KiCad's Package_TO_SOT_SMD has no SOT-883 among its 79 files,
and its smallest SOT-23 is 2.9 mm long -- three times the part, and still
inside confirm's size tolerance, so the check would not have caught it."

Every word of that is a why_not_fetched, which is the field a ModelledSlab
carries for exactly this situation. A part nobody publishes, whose vendor
states its envelope, is the case the file exists for.

TWO SPELLINGS, AND ONLY ONE CAN BE DRAWN. Seeed write the C3's copy
PMOS_1.0_0.6_0.35MM, with underscores where the other three boards write x.
_NAMED_BODY reads x and not underscore, and widening it would be actively
wrong: SOT8_0d5_2_1x1_2x0_6mm would parse into nonsense. The C3's copy
therefore stays refused, and its reason has to say so -- the same part the
other three boards draw, under a spelling this file cannot read -- rather
than continuing to imply nothing can be drawn at all. It is also the subject
of test_a_package_that_states_no_height_is_not_modelled_as_a_slab, which
must keep passing.

The sweep itself belongs in the suite as a standing guard: no package in
ABSENT may be one slab_geometry could read. That test cannot pass until this
is done, which is why it lands here and not with OH-153.

**Note 2026-08-31:** CLOSED 2026-08-31. All eight load-switch placements are drawn: Q1 to Q3 on
the ESP32-C6, Q1 and Q2 on the RP2350 and the nRF54L15, and Q1 on the
ESP32-C3. compose --check exits 0 with no "no model" line and the C3 goes
58 -> 59 drawn.

**This ticket's own plan was wrong about the C3, and in the better
direction.** The body above says only one of Seeed's two spellings can be
drawn and that the C3's copy "therefore stays refused". It is drawn. No new
mechanism was needed: `Component` has always held a footprint name and a
MODEL name as separate fields -- that is how ESD-0402 borrows the 0402
resistor -- so the C3's `PMOS_1.0_0.6_0.35MM` names the model built for
`PMOS_1.0X0.6X0.35MM`, whose F.Fab is the same 0.600 x 1.000 rectangle. The
indirection lives in CORRESPONDENCE, where it costs nothing, instead of in
the parser, where it would cost correctness.

The parser must not learn that spelling, and the reason is now a
measurement rather than an assertion. Allowing an underscore separator makes
`SOT8_0d5_2_1x1_2x0_6mm` parse as **8 x 0.5 x 2.1 mm** -- it takes the `8`
out of `SOT8` itself. (I predicted 0.5 x 2 x 1 before running it, which was
also wrong; the real answer is worse and makes the point better.)

Seeed drew the same footprint two sizes, which decided which board to read.
The C6's three copies and the RP2350's Q1 give F.Fab 0.600 x 1.000, agreeing
with the name to 0.000 mm; the nRF54L15's two and the RP2350's Q2 give
0.508 x 0.762, which is 0.238 mm off. The C6 is named in the row because
1.0 x 0.6 is what the vendor's own NAME says the part is.

EVERY XIAO'S EXPLAINS SET IS NOW EMPTY. Those sets held the antennas and the
coaxial socket until OH-104, the RP2350's processor until OH-100, the
buttons until OH-153 and the load switch until now. Only the Arduino Uno
still names two, and they are the honest kind: a crystal can and a resonator
KiCad publishes no model of.

THE SWEEP IS NOW A STANDING TEST, which is the part of this worth keeping.
test_nothing_refused_is_a_part_this_file_could_have_drawn asks the data the
question that found both false absences: for every (package, board) pair
where the package is in ABSENT and the board places it, building a slab must
FAIL. Every pair, not one board per package -- that is exactly where the
button hid, its C3 copies stating nothing while the C5's and nRF54L15's
state the height.

Mutation-proved, and the interesting result is the one that survived first.
Putting BUTTON_TD1183SA or PMOS_1.0X0.6X0.35MM back into ABSENT fails the
sweep; putting PMOS_1.0_0.6_0.35MM back did NOT, because slab_geometry
genuinely cannot read that spelling -- it is drawn by borrowing a model, a
fact about CORRESPONDENCE rather than the parser. That blind spot is closed
by the cheaper question, asserted first in the same test: a package cannot
be in ABSENT and CORRESPONDENCE at once. 3 of 3 caught now, and the docstring
records which half catches which.

Verified: model --check exit 0, compose --check exit 0 over 11 boards,
`python tools/checkall.py` -> all 12 checks pass, 2,007 passed / 17 skipped.
ruff reports the same 17 findings on the three touched files before and
after, compared stash-vs-unstash.
