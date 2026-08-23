---
id: OH-13
title: 'Board inventory: generate the board list instead of maintaining it'
status: done
priority: P2
created: '2026-08-24'
touches:
- tools/inventory.py
- tests/rules/test_inventory.py
- README.md
---

The README needs a list of the boards this repository carries. A hand-typed list is exactly the document CLAUDE.md forbids -- an inventory rots fastest, and this repo has already caught two rule files describing code they no longer matched. tools/inventory.py already computes tests, mechanisms, files and ledgers from the repository; boards are the one thing it does not know about (grep for 'board' in it returns nothing). Add a fifth collector and a drift test so the README list cannot silently diverge from webui/boards/. Note the honesty problem the data forces: of 582 pads across 26 boards, only 28 carry a simulator pin index, and all 28 are on Arduino Uno -- every XIAO file states in its own 'assumption' field that a pad with pin null draws and refuses a wire. The generated list must not call 25 unwired boards 'supported'.
