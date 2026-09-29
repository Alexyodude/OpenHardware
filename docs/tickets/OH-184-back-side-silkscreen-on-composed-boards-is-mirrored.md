---
id: OH-184
title: Back-side silkscreen on composed boards is mirrored twice, and the vendor's
  own Gerber says so
status: open
priority: P2
created: '2026-09-29'
touches:
- docs/tickets/OH-184-*
---

Found by OH-182's approving re-review, 2026-09-29. KiCad stores a flipped footprint's graphics already flipped, the same as its pads, and `kicad._on_board` mirrors them a second time. OH-182 fixed this for pads (`kicad.pad_on_board`) and deliberately kept the graphics mirror because removing it changes composed output. The evidence now says the composed output is what is wrong.

Measured against each vendor's own back-silkscreen Gerber, back-side footprint strokes (`fp_line` and `fp_poly` edges, both ends and the midpoint, 0.02 mm tolerance):

    Seeed XIAO ESP32-C6       1505 of 1505 land as stored, 0 land mirrored   (the .kicad_pcb md5 matches the copy in the vendor zip; the Gerber is from the same zip)
    Olimex ESP32-PoE Rev M2   615 strokes on 81 footprints: 280 land only as stored, 0 only mirrored, 333 symmetric, 2 nowhere

Front-side strokes land as stored on both boards (109/109 and 272/272), and board-level back silk lines land (3/3 and 9/9), which is what makes the comparison trustworthy.

So the composed XIAO models draw back-side footprint silkscreen mirrored today. OH-182 counted what dropping the mirror would change: 1505 of 1635 back strokes on the C3, 1505 of 1761 on the C6, 942 of 1174 on the nRF54L15. `compose_board_3d.from_kicad` also mirrors back-side pads, which moves nothing today only because every back-side pad on a composed board sits at local x 0.

Remove the second mirror for graphics and for the composer's pads, and hold it with a test that reads the vendor's own Gerber: the C6's back-silkscreen strokes land as the composer places them. Recompose the affected boards. The `_on_board` docstring says the question is "not settled here"; this settles it.

Also from that review, LOW: an unnumbered plated pad comes through the `.kicad_pcb` reader with label "" and pad "", and nothing refuses an empty label.

tools/compose_board_3d.py is lent to OH-180 and returns to OH-163 when OH-180 closes. Run this after OH-180 merges, and coordinate the claim with OH-163.

**Note 2026-09-29:** From OH-180's approving re-review, 2026-09-29, for whoever next edits the composer: (1) the exposed-pad rule's tie-break ('nearest pad') lets the land decide after saying the pad decides nothing; 0.20 vs 0.22 mm between two DFN-8 candidates is a coin toss. The principled tie-break is the chip's own exposed pad from its package outline (Maxim 21-0168 for the MAX17048; analog.com timed out for the reviewer, unverified). (2) Nothing enforces the refuse-near-misses line: confirm checks spans with loose tolerances, so a QFN-56 row on a QFN-60 land would pass. Guard that the pin count in the KiCad model's name equals the vendor's pad count minus the exposed pad, and carry a judgement marker into the drawn list the page shows. (3) from_kicad marks back-side KiCad parts mirrored and lane3's underside path in place() applies to them; no KiCad back-side part draws a model today, so add a real back-side footprint test before one does - same root as this ticket.
