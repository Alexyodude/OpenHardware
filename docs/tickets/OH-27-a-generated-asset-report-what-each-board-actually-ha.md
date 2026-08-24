---
id: OH-27
title: 'A generated asset report: what each board actually has, and what is only a
  picture'
status: open
priority: P2
created: '2026-08-25'
touches:
- tools/inventory.py
- tests/rules/test_inventory.py
---

The completion bar for board research is 'schematic, 3D files, pin definitions, design files found'. That is five yes/no cells per board, which is exactly the hand-maintained list CLAUDE.md forbids -- so generate it, the way OH-13 generated the board list.

Add a collector to tools/inventory.py: per board, whether there is a schematic (and whether it is source or a PDF), PCB design files, a 3D model, a pin definition, and a licence covering them. Each cell carries an evidence class in the manner of docs/architectures.md, because 'a schematic exists' and 'a schematic was opened and parsed' are different claims and the gap between them is where a survey stops being useful.

The report must be able to say a board is incomplete. OH-13 hit this exact problem and its note is the precedent: 'The generated list must not call 25 unwired boards supported.'

Watch the parametrise trap. CLAUDE.md forbids @pytest.mark.parametrize because collect_tests counts def test_* with ast; the drift test here loops inside one test.

Done when the report is generated from the filesystem, no cell is hand-typed, and adding a board with no schematic shows up as no schematic without anyone editing the report.
