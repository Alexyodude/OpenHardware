---
id: OH-127
title: Seeed's DIP footprint and PCB disagree about a XIAO's row spacing by 1.27 mm
status: done
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING; a RECORD, filed so the number is not rediscovered. From the
2026-08-30 model survey.

Seeed's `XIAO-ESP32-C3-DIP.kicad_mod` (New_XIAO_Series_Footprints.zip) puts
its two pad rows 15.240 mm apart; Seeed's own `ESP32-C3.kicad_pcb` puts the
castellation row centres 16.510 mm apart. Same vendor, same board, 1.27 mm
apart -- one header pitch. This is the residual behind OH-121's 0.52-0.73 mm
after its fix, and it is OH-96's question asked of the other twenty-four
boards: WHICH source is where the physical pins are. OH-118 sided with the
DIP footprint for the DIP variants (rows at +/-7.62) and the browser now
finds every pin, which is evidence but not proof.

What would settle it: a caliper on a real XIAO with pre-soldered headers.
Until then nothing further is built on this ticket.

**Note 2026-09-04:** RESOLVED BY MEASUREMENT, 2026-09-04: the two numbers are two FEATURES of one pin, not two opinions about one feature. Every Seeed-authored row spacing in the tree, re-measured from the files rather than quoted:

    third_party/seeed-xiao/Seeed Studio XIAO Series Library/XIAO-ESP32-C3-DIP.kicad_mod
        thru_hole pads 1-14, rows at y = +/-7.620          15.240 apart
        its own smd pads,     rows at y = +/-8.455          16.910 apart
    .../XIAO-ESP32-C3-SMD.kicad_mod
        smd pads, rows at x = 0.835 and 17.000              16.165 apart
    .../XIAO-ESP32-C3-DIP-SMD.kicad_mod   (the union of the two above; same numbers)
    third_party/seeed-pcb/New_XIAO_Series_Footprints.zip  (byte-for-byte the same three files)

    third_party/seeed-pcb/ESP32-C3.kicad_pcb, footprint H7-HALF-HOLE-2.54, two instances at
    (148.4376, 97.3836) rot -90 and (148.4376, 112.6236) rot +90:
        pads 1-7   thru_hole 1.5 mm, drill 0.85, local x = 0       rows at y 97.384 / 112.624   15.240 apart
        pads 13-19 thru_hole 1.27 mm, drill 0.70, local x = -1.27  rows at y 96.114 / 113.894   17.780 apart
        Edge.Cuts                                                   y 96.114 .. 113.894          17.780 high
        pad 1 and pad 13 are on net 27 "D0"; 2/14 on D1; ... 7/19 on TX_D6 -- each castellation and
        the header hole 1.27 mm inboard of it are ONE pin.

So on Seeed's own PCB the castellation half-holes sit ON the board edge (their row spacing equals the outline's 17.780) and the header through-holes sit 1.27 mm inside that edge on each side: 15.240 apart. The DIP footprint's through-holes at +/-7.62 are those header holes, and the two vendor sources AGREE on them. What the SMD-side numbers (16.910, 16.165) describe is the host board's LAND for a castellation, which extends inward from the edge and so has its centre inside it -- a pad on somebody else's board, not a pin on this one. The ticket's original 16.510 was read the same way, off castellation copper; it was never a hole position and I did not re-derive it.

Consequence: OH-118's choice of +/-7.62 for the DIP variants is where Seeed drills the header holes, and no pin position changes. A caliper on a real XIAO would confirm it and is no longer needed to proceed. Nothing was built on this ticket and nothing needs to be; it closes as a record.
