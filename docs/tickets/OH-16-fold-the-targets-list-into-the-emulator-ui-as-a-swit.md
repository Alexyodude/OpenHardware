---
id: OH-16
title: Fold the targets list into the emulator UI as a switchable view
status: open
priority: P2
created: '2026-08-24'
touches:
- webui/static/emulator.html
- webui/static/emulator.css
- webui/static/emulator.js
- webui/static/targets.html
---

targets.html was added as a standalone page. It should be part of the UI that already exists, not a second page beside it: one toolbar, one theme toggle, one palette. Fold it into emulator.html as a view the toolbar switches to, move its rules into emulator.css -- most of them are duplicates of tokens already there, since it was written to match -- and delete targets.html so two copies cannot drift.
