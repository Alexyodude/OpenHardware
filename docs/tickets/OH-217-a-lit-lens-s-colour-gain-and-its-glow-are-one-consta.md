---
id: OH-217
title: 'A lit lens''s colour gain and its glow are one constant: split them so the
  colour stays an albedo'
status: open
priority: P3
created: '2026-10-09'
---

Found by OH-214's review (2026-10-09). `webui/static/parts.js`'s `LIT_GAIN` scales both a lit lens's `color` (an albedo, which cannot pass 1.0) and its `emissive` (radiance, which can, up to the clip-to-white `LIT`'s comment describes). At 3.0, chosen in fcce44c, the lit colour passes 1.0: 1.34 for KiCad's LED lens (#b2190d, 0.445 linear red) and 1.85 for the buzzer's mark (#ce6d26, 0.617). OH-214 briefly cut the shared gain to 1.6 to bound the colour; its review showed that also halves the glow and the on/off contrast, and nobody could see the new look, so 3.0 was restored.

Split the gain: a colour gain bounded so no lens channel passes 1.0 (derived from the brightest lens any part names), and an emissive gain chosen for the glow; look at a lit and an unlit LED and the buzzer in both themes in a browser before choosing, and say what was seen. Hold the colour bound with a test.

From the same review, LOW, for whoever next touches these colours (no change required by them alone):
- BOARD_MASK's reason (tools/import_3d_model.py) says the mask sits above the epoxy; since OH-214 the epoxy is #262525 (1.9% linear) and the mask #1b1b1b (1.1%), so that sentence is false. The board still differs from the chips by coat and roughness.
- The QFN moulding #0f0f12 ("moulded epoxy, as #262525 is") is now about four times darker in linear than KiCad's epoxy; the modelled TD1183SA and SW4 switches moved #0f0f0f -> #464646 with OH-163's CAP-CERAMIC-05 grouping, while TD1183SA's colour source says it draws KiCad's switch black body, which is #262525 on every cached KiCad switch.
- The die, lid and diffuser slabs (#272b27, #4e4e4e, #ebebe5) each equal a vendor STEP's old linear key; "this repository's own" is weaker than stated.

Done when a lit lens's colour stays within 1.0 by a test, its glow is chosen on its own, and both are seen in the page.

**Note 2026-10-12:** 2026-10-12, a browser look at the board's own LED, which is not this ticket's lens: OH-227. The bench LED part this ticket is about (parts.js, LIT_GAIN) was not looked at: placing one on the bench and wiring it needs drags on the canvas that were not driven. Still to see.
