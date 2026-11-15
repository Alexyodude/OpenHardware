---
id: OH-205
title: 'heypcb.ai reached 11,030 boards by searching one host for one format: intake
  takes the search, not its keyword tags, and is scored against the eleven hand-written
  manifest rows'
status: open
priority: P1
created: '2026-10-08'
touches:
- docs/research/heypcb/**
- docs/features/intake.md
- docs/superpowers/plans/2026-10-08-intake.md
---

The user asked how heypcb.ai assembled so many open-source boards, and to build emulators for all of them. This ticket records how (docs/research/heypcb/), derives the intake ledger with the feature-strategy skill (docs/features/intake.md) and writes the strategy (docs/superpowers/plans/2026-10-08-intake.md). It is the 'discovery at vendor scale' slice OH-174 names and never filed, widened from vendor to host. It writes no code: each ledger slice is its own ticket. Emulators are per chip, so the cores the catalogue waits on are a recommendation in the plan's §2 for whoever holds OH-159, OH-38 and OH-64, not cells here; a ticket's file is its own (tools/tickets.py owners_of), so this one edits none of theirs.

**Note 2026-10-08:** Research, ledger (15 cells, all planned) and plan written; fact-checked by an independent verifier pass, which caught a BSP count taken with a pattern that dropped hyphenated board ids (359 for 407) and five smaller misstatements, all corrected. Not committed. Next: S1 (the chip from the board file alone), whose proposed shape is plan §8 and waits on the user's confirmation per .claude/CLAUDE.md rule 2.
