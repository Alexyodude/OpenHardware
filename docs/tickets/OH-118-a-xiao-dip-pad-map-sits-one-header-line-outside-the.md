---
id: OH-118
title: A XIAO DIP pad map sits one header line outside the composed SMD model
status: done
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

## DONE, 2026-08-30

Both sub-fixes landed, and the browser numbers are total:

    board                 real pins, before -> after      model scale
    Arduino Uno                     32 -> 32 (OH-115)         5.64 px/mm
    XIAO-RP2350-DIP                 11 -> 24 of 24            6.86 -> 8.00
    XIAO-ESP32-C3-DIP                0 -> 14 of 14            6.86 -> 8.00
    XIAO-ESP32-C6-DIP                        14 of 14
    XIAO-ESP32-C5-DIP                        14 of 14
    XIAO-nRF54l15-DIP                        14 of 14

**Every pad on every composed DIP board now finds its own pin.**

  * `Component.flip` and `place(..., flip=)`: half a turn about a horizontal
    axis -- x negated with z, a PROPER rotation, one axis alone would be the
    mirror class OH-115 was -- resting the body against the board's underside.
    The tails come out proud of the top face on the pads (max +3.0 mm) and the
    pins descend to -8.5, which is what makes the module read as the
    breadboard part it is.
  * `dip_header_elements`: two synthetic elements from the vendor's own
    numbers (rows +/-7.62 from the module centre, seven pins at 2.54), placed
    relative to the castellation field the composer already has and composed
    exactly as real elements -- `confirm` measures them, `place` anchors them
    on their own pads.
  * **The variants stopped sharing one file.** An SMD board has no headers, so
    the file that served both was right for neither; the SMD compositions are
    DERIVED from their DIP siblings with `dataclasses.replace`, so the two
    cannot drift. `-DIP-SMD` keeps the DIP file: its pad map is identical to
    the DIP's, measured pad for pad.
  * `pad_span` for a DIP board is the DIP field, both axes 15.24 -- the page
    was dividing pixels of one field by millimetres of another and drawing
    every XIAO DIP model 14% too small.

Two mutation survivors were worth their trouble: the row offset was asserted
via the module's own constant (self-referential; now the literal 7.62), and
the injection call site had no unit-level cover at all (the shipped-mesh tests
read a `.glb` no mutation recomposes; now a stripped-source assertion, the
OH-117 lesson applied).

Gate 1,886 -> 1,893 passed. Five mutations, all killed. Frame
`.playwright-mcp/oh118-rp2350-dip.png`: shrouds under the board, breadboard
legs down, tails proud on top -- the product photo.
