---
id: OH-114
title: The modelled USB-C is a square box and a Type-C shell is an obround
status: done
priority: P1
created: '2026-08-30'
touches:
- tools/blender/usb_c_receptacle.py
- tools/model_from_datasheet.py
- tests/rules/test_compose_board_3d.py
---

Reported by the user: **"c5 usb port is bloccky."**

It was. `tools/blender/usb_c_receptacle.py` drew the shell as five flat plates
-- top, bottom, two sides and a back -- which is a rectangular tube with sharp
corners.

**A Type-C connector's cross-section is an obround**: a rectangle with a
SEMICIRCLE at each end, radius half its height. That pill is the most
recognisable thing about the part -- it is why the plug is reversible, and it
is why nobody mistakes one for anything else. Square-cornered, it is a
different connector.

This is the same defect OH-113 fixed on the Uno's USB-B one ticket earlier,
in the other direction: there the opening was rectangular where the standard
cuts two corners; here the whole section is rectangular where the standard
rounds two ends. Both were "a box with a dark patch on it", and both were
reported by somebody looking at the picture.

## NOTHING NEW IS CITED FOR IT

The radius IS half the height, so the shape follows from dimensions this part
already had:

    the shell     8.94 x 3.25 mm, Seeed's own Description; radius 1.625
    the opening   8.34 x 2.56 mm, the USB Type-C specification; radius 1.28

## AND IT MUST NOT MOVE THE PART

`confirm` compares spans, `silk_miss` compares body centres and the overhang
test compares vertices against the outline. Rounding the ends changes the
cross-section and must leave the bounding box exactly where it was.

## DONE WHEN

Both land patterns' shells are tubes of obround section with an obround
opening; no metal comes near a corner of the envelope the vendor states; and
the drawn width still equals the `F.Fab` rectangle it is built from.

## NOT IN SCOPE

The moulded latch bumps inside a real Type-C shell, and the mid-plate: the
first is not in any file here and the second is inside a 2.56 mm slot.

**Note 2026-08-30:** DONE in 7e49503. Both shells are tubes of obround section with an obround opening -- radius half the height, so nothing new is cited: the shape follows from Seeed's 8.94x3.25 envelope and the standard's 8.34x2.56 aperture. Lip, outer skin, inner skin, back cap, dark end panel, paddle. The bounding box is unchanged and asserted against F.Fab to a thousandth, so confirm/silk_miss/the overhang test are untouched. mouth_depth went away with the plates.
