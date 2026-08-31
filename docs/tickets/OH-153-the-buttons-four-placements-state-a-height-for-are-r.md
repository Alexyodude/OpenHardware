---
id: OH-153
title: The buttons four placements state a height for are refused as if none did
status: done
priority: P2
created: '2026-08-31'
touches:
- tools/model_from_datasheet.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

The boot and reset buttons are refused on the ground that the vendor states
no height for them. Four of their six placements state it in the footprint's
own Description, and OH-150 already decided what to do about exactly this.

Measured 2026-08-31, every BUTTON_TD1183SA placement in third_party/seeed-pcb:

    ESP32-C3   BOOT0  F.Fab 3.000 x 2.600   Description ''
    ESP32-C3   RST0   F.Fab 3.000 x 2.600   Description ''
    ESP32-C5   K1     F.Fab 3.010 x 2.610   'SMD Top Button 160gf;2P-L3.0*W2.5*H1.5mm'
    ESP32-C5   K2     F.Fab 3.010 x 2.610   same, byte for byte
    nRF54L15   K1     F.Fab 3.010 x 2.610   same
    nRF54L15   K2     F.Fab 3.010 x 2.610   same

So the refusal is true for the C3 and false for the other two boards. It is
also stated on three boards while the surrounding comment names only two --
tools/compose_board_3d.py:861 says the buttons are BUTTON_TD1183SA "on the
C3 and the nRF54L15" and omits the C5 entirely.

What keeps it refused today is a regex, not a judgement. _STATED_ENVELOPE is

    (\d+(?:\.\d+)?)\*(\d+(?:\.\d+)?)\*(\d+(?:\.\d+)?)\s*mm

which reads the CAF's `1.6*0.8*0.7mm` and cannot read `L3.0*W2.5*H1.5mm`,
because of the letters. The labels are not noise: L, W and H say WHICH
number is which, which is more than the CAF's Description does.

This matters because OH-150 wrote the argument down while drawing the CAF:
"Refusing a part every dimension of which the vendor states, because the
third one is one property to the left, would be a false absence." The button
is the next instance of that sentence, and refusing it is now inconsistent
with the file's own stated principle.

The plan cross-checks. Stated 3.0 x 2.5 against the C5's F.Fab 3.010 x
2.610 is 0.110 mm apart, well inside NAMED_BODY_TOLERANCE_MM of 0.5.

A load-bearing test is wrong in the same way and must move with it.
tests/rules/test_compose_board_3d.py's
test_a_package_that_states_no_height_is_not_modelled_as_a_slab says
BUTTON_TD1183SA "has an F.Fab outline and no height anywhere", and reads the
nRF54L15 board file to prove it -- the very file that states H1.5mm. It
passes only because _STATED_ENVELOPE cannot parse the letters. Its subject
has to become a package whose premise is actually true; a survey of every
ABSENT key found TP-80X40MIL (12 placements, F.Fab on all, nothing stating a
height anywhere) as the honest replacement.

The C3's two placements have no Description of their own and would be drawn
from the C5's statement about the same vendor footprint for the same vendor
part number, their F.Fab differing by 0.010 mm. That is the mechanism
ModelledSlab.pcb already exists for -- it names which board file to read a
package out of, precisely because boards differ in what they state -- and it
is the same one-drawing-for-several-placements the DFN1006-2L row uses. It
must be said out loud in the row rather than left implied.

Out of scope, filed separately if confirmed: the same survey shows
PMOS_1.0X0.6X0.35MM refused across 7 placements while its NAME states
1.0 x 0.6 x 0.35, its refusal reason being that KiCad publishes no SOT-883
-- which is the precondition for modelling a slab, not a reason to refuse
one.

**Note 2026-08-31:** CLOSED 2026-08-31. All six BUTTON_TD1183SA placements are drawn: BOOT0 and
RST0 on the ESP32-C3, K1 and K2 on the ESP32-C5 and the nRF54L15. compose
--check exits 0 with no "no model" line, and the C3 goes 56 -> 58 drawn, the
C5 86 -> 88, the nRF54L15 78 -> 80.

_LABELLED_ENVELOPE is a SECOND pattern rather than a widening of
_STATED_ENVELOPE, and that is the whole design: L, W and H state which
number is which, while an `[A-Z]?` before each number would also accept
H1.5*W2.5*L3.0 and read a height as a length. The labels are required, in
that order, and a vendor who writes them differently is refused rather than
guessed at.

Proved rather than assumed: with the labelled reader removed, --check exits
1 and refuses the button with a message that quotes the very Description
stating its height -- so the new pattern is what draws it, and the file
restores byte-for-byte afterwards. The shipped .glb was then read rather
than trusted: XIAO-ESP32-C3-DIP.glb and XIAO-ESP32-C5-DIP.glb both carry
#0f0f0f bodies exactly 1.500 mm tall with their base at y = 1.200, which is
the board's own top face. The button stands proud, which is the point of a
button.

The C3's two copies have empty Descriptions and are drawn from the C5's
statement about the same vendor footprint name and part number, F.Fab
differing by 0.010 mm. Said in the row rather than left to be noticed.

The test that pinned the old refusal was green on a premise the vendor
contradicted: it asserted the button had no height "anywhere" while reading
the nRF54L15, the board whose Description states it, and passed only because
_STATED_ENVELOPE could not parse letters. Its subject is now
PMOS_1.0_0.6_0.35MM, the C3's spelling of the load switch, whose underscores
_NAMED_BODY genuinely cannot read and whose Description states nothing --
true today and unaffected by OH-154.

Two things found while doing this, by listing every placement instead of
trusting the note beside them:

* the comment in compose_board_3d.py said the buttons were on "the C3 and
  the nRF54L15". The C5 places two as well. Corrected.
* the --check listing said "its own name says ..." for every part, the same
  misattribution OH-152 fixed in the refusal message and missed here. The
  button is the first part to make it visibly false, its name stating
  nothing at all. slab_geometry now returns `stated` and `stated_by` (the
  key was called `named`, which had exactly one reader) and the listing
  names the field: fifteen rows say "its name", the CAF and the button say
  "its Description".

FOLLOW-UP, FILED AS OH-154 AND NOT DONE HERE: a sweep of every ABSENT
package against slab_geometry -- the general form of this bug -- found one
more false absence. PMOS_1.0X0.6X0.35MM is refused across 7 placements while
its NAME states 1.0 x 0.6 x 0.35 and the F.Fab agrees to 0.000 mm on the C6
and 0.238 mm on the RP2350 and nRF54L15. Its stated reason is that KiCad
publishes no SOT-883, which is the precondition for modelling a slab rather
than a reason to refuse one. That sweep belongs in the suite as a standing
guard, and lands with OH-154 because it cannot pass until the PMOS is drawn.

Verified: model --check exit 0, compose --check exit 0 over 11 boards,
tests/rules 648 passed, `python tools/checkall.py` -> all 12 checks pass,
2,006 passed / 17 skipped.
