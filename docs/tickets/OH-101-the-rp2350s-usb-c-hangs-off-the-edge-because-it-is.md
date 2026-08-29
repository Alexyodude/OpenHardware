---
id: OH-101
title: The RP2350's USB-C hangs off the edge because it is the wrong receptacle
status: done
priority: P1
created: '2026-08-29'
touches:
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

Reported by the user looking at the board: "it still looks broken". It is.

The XIAO RP2350 and the nRF54L15 draw their USB-C receptacle **half a
millimetre too far out over the board edge**, and its row of gold contacts
ends up past the edge, hanging in mid-air. It reads as a connector levitating
off the end of the board, which is exactly what it looks like.

## MEASURED, AGAINST THE BOARD THAT IS RIGHT

Same model, same code, two boards. The PCB edge is at x 10.541 on both:

    board      shell reaches   contacts reach       overhang
    ESP32-C3        11.525        10.480  ON BOARD     0.984 mm
    RP2350          12.010        10.965  PAST EDGE    1.469 mm

`tools/import_3d_model.py` records a 1.3 mm overhang measured on Seeed's own
meshes for sibling boards, so the C3's 0.98 is right and the RP2350's 1.47 is
not.

## THE CAUSE: TWO LAND PATTERNS, ONE MODEL

Seeed use two different USB-C footprints, and OH-93 5.1 gave both the same
KiCad model:

    footprint                       pads                     given
    USB2.0-TYPE-C                   4 TH + 16 SMD    GCT USB4105 16P
    USB2.0-TYPE-C_USB-31C-F-16P     2 TH + 16 SMD    GCT USB4105 16P   <-- wrong

**The GCT part has four shell tabs and the second footprint has two.** Where
they sit is the whole problem:

    ESP32-C3   TH x 153.708..157.899 (4, spread front to back)
    RP2350     TH x 118.200..118.200 (2, both at the BACK), contacts 3.5 mm away

`place` anchors a through-hole part on the centre of its LEGS matched to the
centre of the element's pad extent. That is right when both describe the same
feature. Here the model's four tabs and the vendor's two rear board-locks are
different features, so the two centres are not the same point and the part
slides forward.

## WHY `confirm` DID NOT CATCH IT

It measures the model's footprint against the pad span, and:

    GCT USB4105   spans 8.940 x  7.780  vs pads 4.525 x 10.240   -> 2.46 mm short
    SPAN_TOLERANCE_MM = 3.0

**2.46 mm short of a 10.240 mm land, and the tolerance is 3.0.** It passed by
half a millimetre. The tolerance is deliberately generous because a body and
its pads are legitimately different sizes -- so this is not a case for
tightening it, it is a case for the table being right.

## THE PART THAT IS ACTUALLY PUBLISHED

KiCad's `Connector_USB` holds thirteen models and **two** are 16-pin USB-C
receptacles, not one:

    USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal   502 leg points
    USB_C_Receptacle_Amphenol_12401610E4-2A                    56 leg points

Fifty-six against five hundred is four shell tabs against two board locks, and
two is what this footprint has. Measured:

    Amphenol   spans 9.200 x 10.500  vs pads 4.525 x 10.240   -> 0.26 mm out

Against the GCT's 2.46. That is the part.

## DONE WHEN

The RP2350 and the nRF54L15 draw a USB-C whose contacts land on the board, at
an overhang near the C3's 0.98 mm and the 1.3 mm the vendor's own meshes show;
the two footprints have two entries because they are two land patterns; and
the overhang is a test over every composed board rather than a number somebody
measured once.

## DONE, 2026-08-29

`USB2.0-TYPE-C_USB-31C-F-16P` takes `USB_C_Receptacle_Amphenol_12401610E4-2A`.
The two land patterns now have two entries, because they are two parts.

**Measured on the shipped meshes**, worst gold vertex outside the PCB outline:

    Arduino Uno         0.000 mm
    XIAO-ESP32-C3-DIP   0.000
    XIAO-ESP32-C6-DIP   0.000
    XIAO-RP2350-DIP     0.099   (was 0.424)
    XIAO-nRF54l15-DIP   0.206   (was 0.42)

Three boards have no gold beyond their board at all, which is what makes 0.25
a tolerance rather than a wish.

### THE ANCHOR WAS NOT THE BUG, AND THAT WAS CHECKED

The obvious other fix -- anchor a through-hole part on its THROUGH-HOLE pads
only, since the legs go in the holes -- is worse, and measurably:

    ESP32-C3   all-pad centre 155.493   TH-only 155.804   shift 0.311 mm
    RP2350     all-pad centre 115.938   TH-only 118.200   shift 2.263 mm

The RP2350's two board locks are both at one x, so a TH-only centre is that
single point and the part moves 2.3 mm. `place` is right; the table was wrong.

### THE TEST THAT SHOULD HAVE EXISTED

`test_no_soldered_contact_hangs_off_the_board`, over every shipped composed
mesh: **a pin is soldered to a pad and a pad is on the board.** Verified by
putting the bug back and rebuilding, which is the only way a shipped-mesh test
can be shown to fail -- a mutation alone does not regenerate the artefact:

    XIAO-RP2350-DIP: #b58136 at (10.965, 2.237) is 0.424 mm outside the PCB

### WHAT IS STILL NOT RIGHT, AND IT IS COSMETIC

**The Amphenol model's shell is `#1d1d1d`** in its own STEP, where the GCT's
is `#a5a392` and a real receptacle is bright stainless. So the connector is
now correctly placed and reads as a dark slab rather than a metal socket. The
colour is the model author's and OH-97's rule is that a face the vendor DID
colour is untouched, so it stays.

What would retire it, and this is the same sentence as the geometry's: the
real part. **Seeed name it and do not publish it** -- `USB-31C-F-16P-L7.35`
on the RP2350 and `320011419_ST-USB-3316T` on the nRF54L15. `L7.35` says the
body is 7.35 mm long, against 8.94 for the GCT and 9.20 for the Amphenol, so
BOTH published receptacles are too long and the overhang is a fraction large
on every composed board. A modelled part -- the land pattern gives the plan,
and a USB-C receptacle's outside is fixed by the standard that lets any cable
fit any socket, which is the same argument the USB-B's height rests on --
would be exact. Filed as OH-102.

2 new tests. Gate: 1,790 -> 1,792 passed, 17 skipped; all eight checkers
exit 0.
