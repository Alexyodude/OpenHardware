---
id: OH-165
title: A wire segment passes between two nodes through a pin header, and inside, proud
  and stretch all read clean
status: open
priority: P2
created: '2026-09-05'
---

A jumper lead passes clean through an Arduino Uno pin header and every number this repository watches reads zero.

`outOfBox` pushes NODES out of a solid. A lead is a chain of nodes with segments between them, and a segment is not tested against anything -- so a solid narrower than the gap between two nodes falls BETWEEN them, and the lead threads through it. `contact()` reports `inside` 0 and `proud` 0, because both nodes really are outside; `worstStretch` reports a couple of per cent, because the two nodes are only slightly further apart than their rest length. Nothing is wrong with any of those numbers. They are all about nodes.

Measured 2026-09-05 on the shipped solver, a lead pinned at y 8 at both ends and draped over one Arduino Uno header -- 2.54 mm across and 11.54 mm tall, which at the Uno's own `mmScale` of 0.5638 is 1.432 by 6.506 scene units. `segmentThroughSolid` is how far the closest point of the worst segment lies inside the box; the header's half-width is 0.716.

  span   segment   stretch free   stretch over it   through the solid   of the half-width   inside   proud
    3     0.193       0.58%           0.58%              0.0000              0.000            0        0
    5     0.321       0.36%           0.92%              0.0000              0.000            0        0
    8     0.514       0.30%           1.99%              0.0000              0.000            0        0
   12     0.771       0.26%           1.67%              0.0592              0.083            0        0
   20     1.286       0.24%           1.33%              0.2385              0.334            0        0
   28     1.800       0.65%           1.46%              0.7150              1.000            0        0

At 28 units the segment passes through the exact centre of the header while stretch reads 1.46% and all three contact numbers read zero.

The condition is `segment > solid width`, and it is met by ordinary geometry rather than a contrived case. A lead's segment is its span times SLACK over 21, so the header's 1.432 units is crossed once the span exceeds about 22 units -- a 39 mm lead on a 68 mm board. And the shape is everywhere. Of the 775 solids the eleven shipped board models carry, 211 are strictly narrower than they are tall and 687 have half their narrow axis under their height, which is the criterion that matters because a node goes out by its nearest face. Fourteen tie for the worst at nine times the half-width -- the Uno's four headers and ten XIAO DIP headers, all 2.54 by 11.54 mm; an everyday bench part is an LED at about 5 by 8 mm, which is 2.8 by 4.5 scene units.

**This is the third instance of one blindness, and OH-132 named the first.** That ticket found `penetration` unable to see a contact the collider had resolved. OH-162 step 1 found `proudOfBox` answering 0 at a box EDGE, because it is a slab test and a corner satisfies neither axis. This is the same shape again: a probe that asks about nodes cannot see what happens between them, and the file's answer looks clean in all three.

**A related failure of the same function, from the other side.** Where the solid is narrower than the lead DIPS into it, `outOfBox` ejects each node by its nearest face and two neighbours leave by opposite ones, so the lead is pulled into the part and held across it. Measured on the shipped solver with a box 3 units across under a lead dipping 2.5 into it: 417% over rest, held static, with `inside`, `proud` and the tube's `inside` all reading 0 and `energy()` at 3.7e-28. It recovers completely when the solid goes -- worst stretch returns to 0.0027481622459, digit for digit the untouched wire -- so it is a wrong picture rather than a corrupted one. `outOfBox`'s own docstring defends nearest-face because it "makes a wire drape over a board rather than squirt out of its side", and that argument is written for a wide flat slab; it inverts for a tall narrow one and the file does not say so.

What is NOT claimed here: that this is easy to fix. Testing a segment against a box is a different function from testing a point against one, and pushing a segment out has to choose what moves. The point of this ticket is that nothing measures it, so a fix cannot be checked and a regression cannot be caught.

STEPS:

1. A probe that answers how far a lead's worst SEGMENT lies inside a solid, beside `contact()`'s three node numbers, so the quantity has a name. Test: the table above, reproduced from the fixtures that produced it, with the 3-unit span as the fixture that must report nothing.
2. A test that a lead over the narrowest real solid on a real board does not pass through it. It will fail on filing; that is the point, and it should be marked so a reader knows it is a statement of the defect and not a broken test.
3. Then, and only then, whatever the fix is: segment-against-box in `collide`, or a node count that scales with span so a segment is never longer than the thinnest solid, or a swept test. Each of those changes the drape of every lead on every board, which is what OH-162 step 4's photograph exists to justify.

Found while measuring OH-162 step 3, which was declined; that ticket's note carries the same numbers. It needs `webui/static/wires.js` and `tests/webui/test_wires.py`, which OH-162 claims until its step 4 is done, so this ticket claims nothing yet.
