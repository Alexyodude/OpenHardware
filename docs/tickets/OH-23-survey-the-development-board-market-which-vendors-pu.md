---
id: OH-23
title: 'Survey the development-board market: which vendors publish what, and under
  which licence'
status: open
priority: P1
created: '2026-08-25'
touches:
- docs/research/board-sources/**
---

"Every MCU development board" is thousands of boards, and CLAUDE.md forbids the artefact that would list them -- an inventory is the document that rots fastest. So the entry point is not a board list but a survey of *sources*: per vendor, whether hardware files are published at all, where, under what licence, and in which formats.

Record per vendor, with a citation for each cell: repository or download URL; licence, and whether it covers the design files or only the documentation; which artefact classes exist -- schematic source vs schematic PDF, PCB layout, footprint and symbol libraries, STEP/WRL 3D, board-support pin definitions; and repository size, because tools/get_seeed_hardware.sh already established that size decides vendoring, not licence (Seeed's is 196 MB, and almost all of it is two marketing PNGs per board).

Vendors worth covering: Seeed (done -- the 25 XIAO boards here came from it), Raspberry Pi, Espressif, Nordic, Adafruit, SparkFun, Arduino, ST (Nucleo and Discovery), TI LaunchPad, PJRC Teensy, WCH, Waveshare, M5Stack, Olimex, Pimoroni.

Output lands in docs/research/board-sources/ marked **unadopted**, the way docs/research/peripheral-layer/ is. A survey is evidence; turning it into a registry is the next ticket's decision, not this one's.

Done when every vendor row carries an evidence class, no row asserts an artefact nobody opened, and vendors that publish nothing machine-readable are listed as publishing nothing rather than omitted.
