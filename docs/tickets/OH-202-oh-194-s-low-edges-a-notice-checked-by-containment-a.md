---
id: OH-202
title: 'OH-194''s low edges: a notice checked by containment, a PROVENANCE trace no
  tool repeats, a dispute side with no source'
status: open
priority: P3
created: '2026-10-08'
---

Three low-severity edges the confirm review of OH-194 found (2026-10-08). None changes a board file or a run today.

1. "Reads in full" is checked by containment. `tools/board_manifest.py` (the PCBCUPID notice check) and `test_board_sources.py` (the notice against the fetched README) both ask whether the notice appears somewhere in the README, whitespace-normalised. The board files say the notice is the README in full. If PCBCUPID add text above it, both checks still pass and that sentence becomes false. Assert the whitespace-normalised README equals the notice.

2. PROVENANCE §2g says the Olimex ESP32-C3-DevKit-Lipo's pins were "traced 2026-09-30 in all three files" (revisions B, C and D). Revision B is KiCad 5, which `kicad.read_board` refuses (OH-198), and B and C are not fetched, so no committed tool can repeat those traces. Say how B and C were read, or narrow the claim to D. The source row's comment also says GPIO1 and GPIO5 sense the other way round on revision C from D's net labels; PROVENANCE says only that the labels are D's.

3. The dispute record that `tools/import_pindefs.py` writes when a variant names a pad the vendor's copper does not reach gives its "no pin" side `"sources": []`, while `disputed_by` names the board file for it. `pad_report` lists who claimed each side, so `python tools/import_pindefs.py <board>` prints a "no pin" side nobody stated. Board files are unaffected (the writer copies only `disputed_by`). Fill that side's sources from the row's board-file source.

Done when each of the three is fixed with a test that fails when it is reverted, or, for 2, the sentence says only what a committed tool can repeat.
