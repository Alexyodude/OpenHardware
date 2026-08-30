---
id: OH-127
title: Seeed's DIP footprint and PCB disagree about a XIAO's row spacing by 1.27 mm
status: open
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
