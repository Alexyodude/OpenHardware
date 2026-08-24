---
id: OH-30
title: A 3D board view, sharing the pad map's coordinates and the UI's palette
status: open
priority: P3
created: '2026-08-25'
touches:
- webui/static/board3d.js
- webui/static/board3d.css
- tests/webui/test_board3d.py
parent: OH-29
---

Draw the ingested mesh in the emulator UI, with pads live: hovering a pin in 3D is the same selection as hovering it in the 2D map, because both read the same board JSON.

Two constraints the repository has already paid for. OH-16 folded targets.html back into emulator.html precisely so there would not be two pages with two palettes drifting apart -- so this is a view the existing toolbar switches to, not a second page, and its rules go in emulator.css rather than beside them. And a WebGL renderer is a new dependency in a project that currently has none; whether it is vendored, fetched, or hand-written against raw WebGL is a decision this ticket makes explicitly rather than by npm install.

Degrade honestly. A board with no 3D model shows the 2D map and says no model was published for this board -- it does not show a generic rectangle. The repository's habit is that an absent thing is reported absent.

Done when one board renders in both themes, pin selection is shared between the 2D and 3D views, and a board without a model is visibly a board without a model.

Depends on the 3D ingest ticket for meshes, and on OH-22 for the emulator.html and emulator.js hook it needs.
