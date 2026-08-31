---
id: OH-155
title: Two ceramic parts are shaded as metal, because FINISHES has no ceramic to read
status: open
priority: P3
created: '2026-08-31'
touches:
- tools/import_3d_model.py
- tools/model_from_datasheet.py
---

Two ceramic parts render as polished metal, because the only colour close to
ceramic in FINISHES is documented as a metal cover at metalness 1.0.

tools/model_from_datasheet.py lines 391 and 557 both set colour #c6c4a0: the
ESP32-C5's CAF-50P160X80-6N diplexer and the nRF54L15's ANT2P chip antenna.
Both are ceramic blocks. tools/import_3d_model.py's FINISHES gives that hex
Finish(metalness=1.0, roughness=0.30) and describes it as "the tactile
switch's metal cover", marking it "**the weakest entry here**: 440 triangles
on TS42 and nothing else, and which of its two colours is the steel cover
and which the moulded actuator is read off their values rather than off
anything named."

So a dielectric is being shaded as a conductor. Under the PBR model those
are not neighbouring values on a slider -- metalness selects between two
different reflectance models -- so this is not a matter of taste.

WHY IT HAS NOT SIMPLY BEEN FIXED, and why this wants deciding rather than
patching. Every entry in FINISHES is a READING taken from a published vendor
mesh, which is what makes the table defensible. There is no published
ceramic part anywhere in the tree to read: the diplexer and the chip antenna
are both modelled precisely because nobody publishes them. So a ceramic
entry cannot be sourced the way its neighbours were, and inventing one is
what this repository refuses hardest.

The narrow version of the fix does not have that problem. Metalness 0.0 for
a ceramic block is not a judgement about appearance; it is what the
parameter means. Roughness IS a judgement and would have to say so, as
BOARD_MASK's and the delay constant's do.

The wider version is worth weighing at the same time: whether a colour that
exists only as a borrow should keep the borrowed hex at all, or whether the
two ceramic parts should carry their own stated-judgement colour and leave
#c6c4a0 to the switch cover it was read from. The present arrangement makes
one hex mean two materials, which is the shape of the defect the nRF54LM20A
mask film had (OH-99): one missing fact answered two ways in one mesh.

Both parts and both boards are affected, so this changes shipped .glb
appearance and wants a look at the render, not only at the diff.

Recorded in the 2026-08-31 handoff as noted-but-not-filed, and carried
through OH-150, OH-152 and OH-153 without being acted on. Filed now so it
stops being carried.
