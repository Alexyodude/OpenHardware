---
id: OH-263
title: BOARD_MASK is darker than the epoxy it was set above, and two more judged colours
  say what they no longer are
status: open
priority: P3
created: '2026-11-05'
---

Three judged colours that OH-214's reread left saying something false, carried from OH-217 through OH-163 (OH-163 fixed the fourth, the modelled switches). (1) BOARD_MASK's comment in tools/import_3d_model.py says the mask sits above the epoxy; since OH-214 the epoxy is #262525 (1.9% linear) and BOARD_MASK #1b1b1b (1.1%), so the board is darker than the chips it was set above -- it still differs from them by coat and roughness. Choosing another value is a judgement; the comment's 'choosing another is OH-217's' now names this ticket. (2) The QFN moulding #0f0f12 that tools/blender/qfn_flatpack.py builds is described as 'moulded epoxy, as #262525 is' and is about four times darker in linear than KiCad's epoxy. (3) The die, lid and diffuser slabs (#272b27, #4e4e4e, #ebebe5) each equal a vendor STEP's old linear key, so the '... this repository's own' wording near tools/import_3d_model.py's 'Those three pairs were one key each until OH-214' paragraph is weaker than stated. Each needs either a sourced value or a comment that says what it is.

Paths it will want, claimed when it is started rather than now (open tickets may not share a claim): `tools/import_3d_model.py`, `tests/rules/test_import_3d_model.py`, `tools/blender/qfn_flatpack.py`, `tools/model_from_datasheet.py`.
