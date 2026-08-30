---
id: OH-118
title: A XIAO DIP pad map sits one header line outside the composed SMD model
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet; the work would touch `tools/compose_board_3d.py` and
possibly `webui/static/board3d.js`, and it re-claims when it starts.

**Measured 2026-08-30 while verifying OH-115's mirror fix**, offline against
`XIAO-RP2350-DIP.glb`'s own metal (16,591 vertices above the board), in the
model's frame with the page's own scale:

    10 pads within 1.1 mm     D11-D18, VBAT, one GND  -- the B-side pads
    14 pads at 3.25-3.95 mm   D0-D10, 3V3_OUT, VBUS, GND -- BOTH header rows,
                              offset together

A whole group offset together is a component placed elsewhere, not noise --
the same signature OH-96 recorded for the Uno's two headers. Here the group is
the DIP variant's two HEADER ROWS: the pad map (24 pads, two rows of twelve,
from the vendor's own DIP footprint) puts them on the header line, and the
composed model is the bare SMD board, whose metal stops at the castellations
one header line inboard.

**The model is honest and incomplete**: a physical XIAO DIP has pin headers,
and the composed board draws none -- `CORRESPONDENCE` has no entry for them
because the SMD `.kicad_pcb` places no header footprint. So on every XIAO DIP
board the D-pads are invisible colliders with no pin, which after OH-115 is
the largest remaining reason `realPins` is low: RP2350-DIP finds 11 of 24,
the C3 and nRF54l15 DIP find 0 of 14.

## WHAT WOULD FIX IT

Compose the DIP variants WITH their headers: the pad map knows the header
positions (it was generated from the vendor's DIP footprint), KiCad publishes
`PinHeader_1x07_P2.54mm_Vertical`, and the composer already places headers on
the Uno by exactly this mechanism. The work is wiring the DIP board specs to
place two header models at the pad map's own rows -- geometry the SMD compose
does not want, so it is per-variant, not per-PCB.

## WHAT MUST NOT HAPPEN

Do not move the PAD MAP inboard to the castellations. The pads are the
vendor's own DIP footprint and they are where the physical pins are; the model
is the thing missing geometry.

## CORRECTION, 2026-08-30, same day -- the geometry read the wrong way round

The title says the pad map sits "outside" the model. Measured against the
vendor's own footprints, it is INBOARD, and the map is right:

    XIAO-RP2350-DIP.kicad_mod   58 pads, through-hole rows at y = +/-7.62
                                -> 15.24 mm apart, the breadboard 0.6" DIP
                                   convention, Seeed's own statement
    XIAO-RP2350-SMD.kicad_mod   30 pads, castellation rows at y = +/-8.08
                                -> 16.16 mm apart, at the board edge

So the DIP variant's pins are on a 0.6" grid inboard of the castellations,
the pad map (generated from the DIP footprint at 8 px/mm, self-consistent) is
where the physical pins are, and the composed model -- built from the
published SMD `.kicad_pcb`, which places no DIP holes -- has no metal within
3.25 mm of any of them. The fix direction stands: the MODEL lacks the DIP
variant's headers; the pad map must not move.

## AND A SECOND DEFECT FELL OUT OF THE ARITHMETIC

`pad_span` in the composed `.glb` is measured off the SMD castellation field
(15.24 x 17.78 for the RP2350), but on a DIP board the page's pads are the
DIP footprint's field (15.24 x 15.24). `scaleFromPads` then divides the page's
121.9 px -- which is the 15.24 mm axis -- by the model's LONGER span, 17.78,
and draws the model at 6.86 px/mm where the map is 8. **Every XIAO DIP model
is drawn ~17% too small**, which compounds the missing-headers offset and
scatters even the castellation pads.

Two sub-fixes, then:
  1. compose the DIP variants with two `PinHeader` models on the pad map's own
     0.6" rows (KiCad publishes `PinHeader_1x07_P2.54mm_Vertical`; the Uno
     already composes headers by this exact mechanism);
  2. make the scale comparison compare like with like -- either emit
     `pad_span` for the pad field the page actually shows, or fit the scale
     from paired pads rather than from two bounding boxes of two different
     fields.
