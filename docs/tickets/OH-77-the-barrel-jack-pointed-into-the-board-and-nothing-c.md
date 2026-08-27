---
id: OH-77
title: 'The barrel jack pointed into the board, and nothing could see it: check placements
  against the vendor''s silkscreen'
status: open
priority: P2
created: '2026-08-27'
touches:
- tools/compose_board_3d.py
- tools/eagle.py
- tests/rules/test_compose_board_3d.py
---

FOUND BY THE USER SAYING "check your placements", 2026-08-27, hours after OH-76 landed. The Arduino Uno's barrel jack was drawn 7.50 mm from where Arduino's own silkscreen puts it, with its barrel pointing INTO the board instead of out over the left edge. Every check written up to that point passed.

WHY EVERY CHECK PASSED, which is the whole content of this ticket. Three had been written and all three are blind to the same thing:

  * `confirm` measures a model's footprint against the element's pads. A jack turned 180 degrees has the same footprint.
  * `place` anchors a through-hole part on its legs, matched to the pad centre. A jack turned 180 degrees has the same leg centre, because a pin field is very often symmetric about its own.
  * `test_every_components_legs_land_on_the_board` and the tighter `..._on_its_own_pads` both compare the placement against the pads. Same symmetry, same blindness.

**A part whose pins are symmetric about their centre can be 180 degrees out and satisfy every measurement taken from those pins.** That is the general statement, and it is why the check had to come from somewhere else.

THE SILKSCREEN IS THAT SOMEWHERE ELSE. The pads say where a part's PINS are; the silkscreen says where its BODY is. Both are in the vendor's file, both go through the same placement transform, and neither comes from a table written here. Against it the four candidate turns for X1 miss by 5.36, 7.50, 5.35 and 0.01 mm -- so the right one is not a matter of taste, and the wrong one is not a near miss.

MEASURED ACROSS THE WHOLE BOARD, before the fix: fourteen of fifteen components agreed with the vendor's silk to 0.40 mm or better, and X1 was at 7.50. After: the worst is 0.40, and that one is X2, the USB socket modelled in OH-76 -- whose body is this project's drawing rather than a published mesh, so it is measured against the vendor's courtyard rather than against itself.

THE SIGN OF THE FLIP WAS ALSO CHECKED, and separately, because the silk check and `place` could in principle share an error. The board JSON's pad map is in ARTWORK pixels and was verified against the vendor's file to 0.008 mm in 2a80c94; putting those pads in the scene's frame WITHOUT reusing `place`'s flip and asking whether each header encloses the pads the page draws on it: IOL spans x 3.30..23.62 and pad 0 is at 22.35, IOH spans -23.62..1.78 and pad 13 is at -12.20, AD and POWER likewise. Two transforms that share no code agreeing is what makes the flip right rather than consistently wrong.

Done when `silk_miss` is computed for every placed component, a placement more than 1.5 mm from the vendor's drawn body is refused by name rather than drawn, X1 is at turn 270 and the Uno's barrel jack overhangs its left edge in a browser.

NOT IN THIS TICKET: packages that draw no silkscreen, which get no check and say so by returning None -- every one on this board draws one; and circles or rectangles on the silk layers, which no package in this tree uses for a body and which would give a partial extent that looks complete.
