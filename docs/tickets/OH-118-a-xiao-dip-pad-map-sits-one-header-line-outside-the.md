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
