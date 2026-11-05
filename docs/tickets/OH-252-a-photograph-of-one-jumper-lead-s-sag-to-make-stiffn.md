---
id: OH-252
title: A photograph of one jumper lead's sag, to make STIFFNESS a measurement
status: blocked
priority: P3
created: '2026-11-05'
---

OH-162 step 4 asked for one photograph of one lead of known length on one board, and said its sag would retire GRAVITY, DAMPING and SLACK as judgements. Measured 2026-11-05, it cannot: the resting shape of a flexible lead holds none of the three. A limp lead in webui/static/wires.js hangs within 0.3% of the hand-worked chain of its own length at the shipped gravity, ten times it and a tenth of it, and the shipped lead stops in the same place, to 1e-12, at DAMPING 0.9 and 0.995. SLACK is which length of lead was picked up, not a property of one.

What a still CAN measure is the bending: STIFFNESS, and NODES, which sets how far apart the bent pairs are. The shipped lead hangs shallower than the chain of its own length by 0.25% at slack 1.35, 0.91% at 1.6 and 2.43% at 2.0, and tests/webui/test_wires.py now holds both the chain (discrete_catenary_sag, which needs no solver) and that margin.

The work: photograph a real jumper lead, of a length measured with a ruler, hanging between two pins whose spacing is also measured, at a slack of 1.6 or more (below 1.35 bending cannot be told from the solver's own stretch). Read its sag off the photograph against a scale in the frame. Compare that with discrete_catenary_sag(span, length, 21). If the real lead sags like the chain, STIFFNESS is too high; if it sags short of it, the shortfall is the number STIFFNESS should reproduce.

Blocked on the owner: it needs a lead, a ruler and a phone. Nothing here can take the picture.

One hazard for whoever tunes STIFFNESS from it: weaker bending can let a slack lead fold and hold the fold. With the bend correction cut to a tenth, a slack 2.0 lead at DAMPING 0.995 settles 3.07 units from the one at 0.982. With the shipped stiffness and a tenth of the gravity, it stays folded with 0.21 of sag where the chain has 7.93. test_how_long_a_lead_swings_is_not_in_the_shape_it_stops_in fails if a new value makes that the shipped lead.

A second: a STIFFNESS fitted this way is fitted at the shipped GRAVITY and holds only there, because with bending on weight is what the bend is measured against. Measured 2026-11-05 at slack 1.35, the shipped lead is 1.27% shallower than its chain at a tenth of the gravity, 0.25% at the shipped value and 0.04% deeper at ten times it. Retuning GRAVITY (from a video of a fall, say) means fitting STIFFNESS again after it.

When taken, this will claim webui/static/wires.js and tests/webui/test_wires.py; it claims nothing while OH-162 holds them.
