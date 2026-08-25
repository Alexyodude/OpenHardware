---
id: OH-41
title: Retire import_kicad_board.py now that the generic importer reproduces it
status: done
priority: P3
created: '2026-08-25'
touches:
- tools/import_kicad_board.py
- tests/rules/test_kicad.py
- tests/rules/test_board_sources.py
- tests/rules/test_inventory.py
- tools/import_pindefs.py
- README.md
- tools/import_board.py
---

OH-25 built tools/import_board.py, whose KiCad path reproduces the committed webui/boards/XIAO-RP2040-DIP.json exactly -- same image size, same 14 pads, every coordinate identical to 0.0 px, same labels and groups -- from a different tool than the one that produced it. That makes import_kicad_board.py redundant.

It is not deleted yet for the same reason get_seeed_hardware.sh is not (OH-40): it is referenced from tools/inventory.py, the board-source survey, and two tests. Deleting one file is a change across several owned by other tickets.

Sequence it after OH-40, since the two retirements touch overlapping files and doing them together avoids two rounds of the same edits.

Note while doing it: this tool is the origin of the XIAO-XIAO STM32C5-SMD naming bug, though the typo itself is the vendor's -- the .kicad_mod declares that name internally. The tool used footprint.name for both the board name and source.footprint and never noticed the disagreement. import_board.py records source.file as well, which is what makes an asset search work; carry that forward rather than the name-only behaviour.

**Note 2026-08-25:** Carry-over from OH-40, which found these but could not touch them: tools/import_pindefs.py lines 35 and 841 carry two PRESENT-TENSE prose citations of get_seeed_hardware.sh's fetch-don't-vendor argument. The script is gone as of 08f3beb, so those sentences are now stale in a way the past-tense citations in board_sources.py are not. They were outside OH-40's touches and are outside yours too -- import_pindefs.py belongs to OH-26, which is closed, so the file is unclaimed and you may take it with --touch. Also: test_nothing_tells_anyone_to_run_the_retired_fetcher pins tools/import_kicad_board.py as its single exemption, so removing that file means removing the exemption in the same change or the test starts guarding nothing.

**Note 2026-08-25:** Partial work landed as 18d7ab8 by a session that then died mid-response (API connection lost). What it completed: the missing-vendor-tree error message now names get_board_sources.py and its registry key, closing OH-40's single remaining exemption. What it recorded, in the file itself: the deletion is blocked by two imports OUTSIDE the original claim -- tests/rules/test_kicad.py:29 takes build and header_pads from this module, tests/rules/test_board_sources.py:125 takes VENDOR. Both are now added to this ticket's touches, so whoever resumes can finish it. IMPORTANT and not obvious: the 50 webui/boards/*.json and *.svg files naming this tool in their 'derivation' field are NOT a blocker and MUST NOT be rewritten. derivation records how a file was made, and those files really were made by this tool; renaming it to the replacement would falsify provenance to tidy a reference. Only test_kicad.py's assertion on the current generator's name moves when the boards are regenerated. Lock released -- the holding session is gone.

**Note 2026-08-26:** CLOSED 2026-08-26. tools/import_kicad_board.py is gone.

WHY IT IS A RETIREMENT AND NOT A DELETION: tools/import_board.py's KiCad path reproduces the committed webui/boards/XIAO-RP2040-DIP.json exactly -- same image size, same 14 pads, every coordinate identical to 0.0 px -- from a different tool than the one that produced it. That comparison, which OH-25 built, is the whole warrant.

THE THREE NAMED BLOCKERS. tests/rules/test_kicad.py imported build and header_pads; tests/rules/test_board_sources.py imported VENDOR. Both rewritten. The third needed NO EDIT: test_nothing_tells_anyone_to_run_the_retired_fetcher was already a SUBSET assertion with a comment explaining why -- an exact list would have been 'a tripwire whose only possible instruction is delete this line'. It emptied out on its own, which is exactly what its author intended.

SIX TESTS WENT WITH THE TOOL. Their coverage did not: tests/rules/test_import_board.py has 27 over the replacement, including the reproduction test. What remains in test_kicad.py is tools/kicad.py, the parser BOTH importers used and only one of which is gone. Verified: 406 rules tests pass, and the vendor-library test was rewritten onto read_geometry rather than dropped.

ONE THING THE REWRITE ALMOST GOT WRONG. PadSpec measures from the top-left with Y increasing DOWN; the retired tool measured from the footprint origin and put the top header row at NEGATIVE Y. The old test selected a row with 'p.y_mm < 0', which under the new convention selects nothing and would have asserted an empty gap set -- vacuously true. Grouped by Y value instead, and the reason is written in the test.

THE 25 BOARD JSONs NAMING IT IN derivation ARE UNTOUCHED, as the ticket demanded. derivation records how a file was MADE and those files really were made by this tool; renaming it would falsify provenance to tidy a reference.

FOUR PRESENT-TENSE CITATIONS of a now-absent file cleared: README.md, two in tools/import_board.py, one in tools/import_pindefs.py. Plus the two stale get_seeed_hardware.sh citations OH-40 found and could not reach, which was carried here as a note. A past-tense citation of a retired tool is history; a present-tense one is an instruction nobody can follow.

Gate: 1,437 passed, 17 skipped; all eight checkers exit 0.
