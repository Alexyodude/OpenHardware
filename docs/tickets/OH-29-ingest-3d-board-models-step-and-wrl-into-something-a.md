---
id: OH-29
title: 'Ingest 3D board models: STEP and WRL into something a browser can draw'
status: open
priority: P2
created: '2026-08-25'
touches:
- tools/import_3d.py
- tests/rules/test_import_3d.py
---

Vendors ship board 3D as STEP (boundary representation, parametric, not drawable) or WRL/VRML (already a mesh). A browser draws triangles, so STEP needs tessellation and WRL needs conversion, and the two paths have nothing in common but their output.

Emit one mesh format -- glTF is the one browsers load without a converter -- plus the board's real extent in millimetres, so the 3D model and the existing 2D pad map are in the same coordinate system. That alignment is the whole point: the pad at (30.4, 20.8) in XIAO-RP2040-DIP.json has to be the same pad in 3D, or the two views are separate pictures of nothing in particular.

Size will decide what is stored. A tessellated board with every component is tens of megabytes; a board outline with headers and the MCU package is small. Fetch-do-not-vendor applies here more sharply than anywhere else in the repository.

Done when one board renders from the vendor's own STEP with pad positions agreeing with the existing JSON to the tolerance the tessellation allows, and that tolerance is stated rather than assumed.

Scope: ingestion only. The view is a separate ticket.

**Note 2026-08-25:** Verified against the vendor tree by full git ls-tree census, not a sparse checkout: Seeed's OSHW-XIAO-Series publishes ZERO board 3D models -- 0 .step, 0 .stp, 0 .wrl. The only 13 .stl are enclosure parts for a community NTP-clock project (cases, lids, diffuser masks), not boards. So this ticket has no source material for 25 of the 26 boards here and cannot start until OH-23 finds a vendor that publishes board 3D. Do not begin by writing a STEP tessellator.

**Note 2026-08-25:** CORRECTION to the note above, from OH-23's completed survey. That note said this ticket has no source material and cannot start until a vendor publishing board 3D is found. One has -- five have. model_3d = yes for: Raspberry Pi's Pico design files (datasheets.raspberrypi.com), Raspberry Pi's Product Information Portal (CM5 IO board), Waveshare's per-board wiki, m5stack/M5_Hardware, and OLIMEX/ESP32-POE. What stays true is that Seeed publishes none, so none of the 26 boards currently in this repository has a 3D model; a board that does must be imported first. Establish which FORMAT each of those five publishes before choosing an approach: a WRL or STL is already a mesh and needs no tessellator, while STEP is boundary representation and needs one. Do not commit to a STEP tessellator until the survey's format cells say one is required.
