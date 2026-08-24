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
