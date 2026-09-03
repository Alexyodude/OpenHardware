---
id: OH-155
title: Two ceramic parts are shaded as metal, because FINISHES has no ceramic to read
status: done
priority: P3
created: '2026-08-31'
touches:
- tools/import_3d_model.py
- tools/model_from_datasheet.py
- tests/rules/test_import_3d_model.py
- tests/rules/test_compose_board_3d.py
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

**Note 2026-09-04:** DONE 2026-09-04. The "narrow fix" the ticket offered -- re-declare #c6c4a0 at metalness 0 -- was NOT safe, and measuring is what showed it: tallied across the shipped .glb files, #c6c4a0 is on 13 of 17 boards, the two ESP32-C3s carrying 604 triangles of it with neither a TS42 nor a ceramic part on them. FINISHES is keyed by colour, so the entry would have turned vendor-styled faces on eleven other boards into dielectrics along with the two it was meant for. The wider version is therefore the only version.

What landed:

* tools/import_3d_model.py: CERAMIC = "#d9d3c0", the second judged colour in the file, with a comment in BOARD_MASK's voice recording what was searched (the three Murata LFD datasheets: no colour, appearance or material stated; Seeed's ANT_KH5220-A36: no datasheet in tree) and what would retire it. FINISHES[CERAMIC] = Finish(0.0, 0.60): metalness 0 argued from what the parameter means (a fired ceramic is a dielectric); roughness 0.60 labelled a judgement, placed between silkscreen ink 0.55 and moulded epoxy 0.70. The #c6c4a0 entry now records that it is not only on TS42, and BOARD_MASK's "only judgement in this file" is corrected.
* tools/model_from_datasheet.py: CAF-50P160X80-6N and ANT2P-5.2x2x1.1MM draw in CERAMIC, and their colour_source strings say what they borrowed before and why it was wrong.
* Both parts rebuilt in Blender 4.5 and the four boards recomposed. Re-read from the files:

      before                         after
      XIAO-ESP32-C5-*     #c6c4a0 823 tri      #c6c4a0 811, #d9d3c0 12 tri metal 0.0 rough 0.6
      XIAO-nRF54l15-*     #c6c4a0 412 tri      #c6c4a0 400, #d9d3c0 12 tri metal 0.0 rough 0.6
      XIAO-ESP32-C3-*     #c6c4a0 604 tri      unchanged

  Twelve triangles is one box, which is what a slab is.

* Two tests, both shown able to fail: test_a_ceramic_block_is_a_dielectric_in_its_own_colour (table) and test_the_ceramic_parts_reach_the_shipped_boards_as_dielectrics (the file). Four mutations -- antenna back to #c6c4a0, ceramic declared a metal, table roughness 0.61 against a 0.60 file, CERAMIC keyed on the cover's hex -- each turned at least one red; sources restored byte-for-byte.

The render was looked at only through the file: the material is what the page will shade with, and a screenshot of a 1.6 x 0.8 mm part at page scale would not have shown the difference between steel and ceramic anyway.
