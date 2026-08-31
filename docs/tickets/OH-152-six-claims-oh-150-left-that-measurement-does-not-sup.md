---
id: OH-152
title: Six claims OH-150 left that measurement does not support
status: done
priority: P2
created: '2026-08-31'
touches:
- tools/model_from_datasheet.py
- tools/compose_board_3d.py
---

Six claims OH-150 left in tools/model_from_datasheet.py and
tools/compose_board_3d.py that measurement does not support. None changes
what is drawn; all of them are read by the next person deciding whether a
part may be modelled, which is what makes them worth the same standard as
the code.

Each was verified by listing rather than by matching, because the last
correction commit in this area introduced a false claim by trusting an
empty regex result that could never have matched.

1. tools/model_from_datasheet.py:305-317 says NAMED_BODY_TOLERANCE_MM is
   what makes widening _NAMED_BODY safe, and then that the optional unit
   carries the same protection. slab_geometry compares two numbers, not
   three: drawn and claimed are both sorted PAIRS of length and width. The
   height is compared to nothing, and cannot be -- it is the one dimension
   no layer carries, which is the premise the whole file rests on. What the
   tolerance actually protects is that the pattern locked onto the right
   substring; that the third number is a THICKNESS rides on the vendor,
   not on any check here.

2. The same comment says every one of "the eleven names this file holds"
   parses identically with the unit optional as with it required. There are
   16 SLABS rows, 15 of whose names parse (the CAF states no dimensions in
   its name and comes from its Description), and the sentence is not merely
   miscounted but self-defeating: making the unit optional changes exactly
   ONE name, the RP2350 DFN6-0.5-1.45X1X0.6, which with MM required matches
   nothing at all. That name is the entire reason the unit is optional.

3. _BARE_DIE (line 357) reads "as the WLCSP-47 and WLCSP-20 above". Its
   three use sites are lines 407, 425 and 443; the two rows it names are at
   570 and 584. They are below.

4. The DFN6-0.5 row (line 486) claims to be "the only name in this file
   that states no unit at all". The CAF at line 370 states no unit either,
   nor any dimension. True as intended, false as written: it is the only
   name that states three dimensions AND no unit.

5. The X2SON4 row (line 521) calls itself "the first name here to spell its
   unit in lower case". SOT8_0d5_2_1x1_2x0_6mm is at line 496, sixteen
   lines above it, and ends in a lower-case mm. It is the second.

6. tools/compose_board_3d.py:658-660 says the five DFN1006-2L placements
   share footprint UUIDs, "so one drawing rather than five". Four do: the
   ESP32-C6 and RP2350 D3 are both 74280228-6770-4ef7-a3f6-1b9b72be3acb
   and both D1 are ca26a40d-c599-4020-9350-0c2ef85f72bb. The nRF54L15 D4 is
   e5be19e4-a645-439b-a8a4-b4bedcd14edb and is drawn differently -- F.Fab
   1.321 x 0.711 against the others' 0.749 x 0.508. Nothing drawn changes,
   because this row borrows a KiCad body at its own size rather than
   measuring the footprint, but the sentence is wrong by one placement.

Also in scope, same class: slab_geometry's refusal message reports "its
name says ..." on both branches, so a Description-sourced mismatch names
the wrong field. socket_geometry already gets this right.

**Note 2026-08-31:** CLOSED 2026-08-31. All six corrected, each against a listing rather than a
pattern match.

1 and 2 are one rewritten comment. It now says what the tolerance actually
proves -- that the pattern locked onto the right substring -- and states
plainly that the height is compared to nothing and cannot be, since no
layer carries it. The unit-optional paragraph now gives the real numbers:
16 SLABS rows, 15 parsing from their name, and making MM optional changes
exactly ONE of them. It also records that the old sentence argued against
its own change, because if all names had parsed identically either way
there would have been no reason to make the unit optional.

3, 4 and 5 are one word, one narrowing and one ordinal: "above" -> "below";
"the only name that states no unit at all" -> "the only name that states
three dimensions and no unit", the CAF stating neither; and X2SON4 is the
second name in lower case, not the first, with the SOT8 sixteen lines above
it named as the one it follows.

6 now gives both shared uuids in full and says the nRF54L15's D4 is its
own, drawn to 1.321 x 0.711 against the others' 0.749 x 0.508, and why
nothing drawn changes for it.

The refusal-message fix is the only CODE change here, and it was exercised
rather than eyeballed: forcing NAMED_BODY_TOLERANCE_MM negative makes all
sixteen refuse, and the messages split 15 naming "its name" and 1 naming
"its Description" -- the CAF, which agrees to 0.000 mm and could not be
reached any other way. That 15/1 split is also an independent confirmation
of the count now in the comment.

Verified: model --check exit 0, compose --check exit 0, tests/rules 648
passed, `python tools/checkall.py` -> all 12 checks pass with 2,006 passed
/ 17 skipped. ruff reports the same six RUF100 findings before and after,
compared stash-vs-unstash, so none is new.
