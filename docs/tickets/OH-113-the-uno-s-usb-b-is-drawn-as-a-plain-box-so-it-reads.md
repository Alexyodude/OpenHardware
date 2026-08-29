---
id: OH-113
title: The Uno's USB-B is drawn as a plain box, so it reads as an ethernet jack
status: done
priority: P1
created: '2026-08-30'
touches:
- tools/blender/usb_b_receptacle.py
- tools/model_from_datasheet.py
- tests/rules/test_compose_board_3d.py
---

Reported by the user: **"uno ethernet port is poor."**

There is no ethernet on an Arduino Uno. The large metal socket is its USB-B --
and the fact that a reader took it for an RJ45 IS the defect, stated exactly.

## WHY IT READS AS ONE

`tools/blender/usb_b_receptacle.py` drew the shell as five plates forming a
plain rectangular tube, with the mouth as a dark box 0.4 mm behind the front
face. That is a painted rectangle on a box, which is what an ethernet jack
looks like.

**The two upper corners of a Series-B opening are cut off at 45 degrees**, and
the bevel is not decoration: it is the KEY. A Series-B plug's shell has the
same two corners cut, which is what makes the pair mate one way up. A socket
drawn without them is a socket that would take the plug upside down -- and it
is the one feature that tells a USB-B from an RJ45 at a glance.

Arduino's own EAGLE package cannot help: `PN61729` draws four silkscreen wires
forming a plain 11.8 x 15.75 mm rectangle, six pads and nothing else. The
shape of the opening is the standard's or it is nowhere.

## AND TWO THINGS THE FIRST ATTEMPT GOT WRONG

Both found by rendering the part on its own rather than on the board:

  * **The cavity started at the front plane**, coplanar with the frame around
    it, so the two chamfer triangles fought it for the same surface and only
    one of them won. One bevelled corner and one square is worse than none.
  * **The cavity was a solid box filling the interior**, which swallowed the
    tongue whole. What a plug goes into is a metal box with a dark end; the
    shell's own plates already line the sides.

## AND ONE MATERIAL CLAIM THAT WAS FALSE

The tongue was given the pin colour and rendered as a gold wedge filling the
socket. The paddle is an insulator; the four contacts on it are half a
millimetre wide and are not drawn at all.

## DONE WHEN

The opening is a hole rather than a picture of one, with both corners cut; the
tongue is visible inside it and is not metal; and the chamfer's SIZE is
declared a drawing quantity, because only its presence is the standard's.

## NOT IN SCOPE

The four contacts on the paddle, and the stepped shell profile some Series-B
receptacles have -- neither is in Arduino's package and neither is fixed by
the standard.

**Note 2026-08-30:** DONE in 8e495ab. The front face is a frame of six polygons around a hexagonal hole, both upper corners cut. New panel() primitive: no boolean, the hole is the space the polygons do not cover. Two further defects found by rendering the part ALONE rather than on the board -- the cavity was coplanar with the frame so one chamfer lost the depth test, and it was a solid box that swallowed the tongue. The paddle is an insulator now, not brass. Arduino's PN61729 draws a plain rectangle and six pads, so the opening's shape is the standard's or nowhere.
