---
id: OH-198
title: A KiCad 5 board file reads, so the Olimex ESP32-C6-EVB and Olimex's older boards
  can be rows
status: in-progress
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-198-*
- tools/kicad.py
- tests/rules/test_kicad.py
- tests/rules/kicad5/**
---

Part of OH-174, found by OH-194. The Olimex ESP32-C6-EVB stopped before a registry row because its only board file, `HARDWARE/Hardware-revision-A/ESP32-C6-EVB_Rev_A.kicad_pcb`, is KiCad 5: `kicad.read_board` refuses a board that places its parts as `(module ...)` (OH-182 made that refusal name the format). The survey found Olimex is the strongest KiCad source with real variants, and earlier Olimex revisions are KiCad 5 too (OH-182's review).

Read KiCad 5 boards. The differences that matter to this repository are known and finite: `(module ...)` instead of `(footprint ...)`, `(fp_text reference ...)` and `(fp_text value ...)` instead of properties, the pad and net syntax of that version, and layer names. Read them into the same structures `tools/kicad.py` already returns, so import_board, the trace and the composer need no second path. Parse, do not convert with a tool: a converter's output is not the vendor's file.

The OH-194 worker also found a KiCad 7 copy of the same board in the repository's `HARDWARE/Dimensions/` folder (title block rev A, the same 121 footprints and net references plus dimension annotations). Do not use it in place of the board file: it is a drawing derived from the board, and whether it is kept in step is not stated. It can serve as a cross-check that the KiCad 5 reading is right.

Done when the ESP32-C6-EVB's board file reads, its headers import and trace like the other KiCad rows, and a KiCad 5 construct this reader does not handle is refused by name rather than skipped.
