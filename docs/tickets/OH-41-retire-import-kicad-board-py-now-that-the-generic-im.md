---
id: OH-41
title: Retire import_kicad_board.py now that the generic importer reproduces it
status: open
priority: P3
created: '2026-08-25'
touches:
- tools/import_kicad_board.py
- tests/rules/test_kicad.py
- tests/rules/test_board_sources.py
---

OH-25 built tools/import_board.py, whose KiCad path reproduces the committed webui/boards/XIAO-RP2040-DIP.json exactly -- same image size, same 14 pads, every coordinate identical to 0.0 px, same labels and groups -- from a different tool than the one that produced it. That makes import_kicad_board.py redundant.

It is not deleted yet for the same reason get_seeed_hardware.sh is not (OH-40): it is referenced from tools/inventory.py, the board-source survey, and two tests. Deleting one file is a change across several owned by other tickets.

Sequence it after OH-40, since the two retirements touch overlapping files and doing them together avoids two rounds of the same edits.

Note while doing it: this tool is the origin of the XIAO-XIAO STM32C5-SMD naming bug, though the typo itself is the vendor's -- the .kicad_mod declares that name internally. The tool used footprint.name for both the board name and source.footprint and never noticed the disagreement. import_board.py records source.file as well, which is what makes an asset search work; carry that forward rather than the name-only behaviour.

**Note 2026-08-25:** Carry-over from OH-40, which found these but could not touch them: tools/import_pindefs.py lines 35 and 841 carry two PRESENT-TENSE prose citations of get_seeed_hardware.sh's fetch-don't-vendor argument. The script is gone as of 08f3beb, so those sentences are now stale in a way the past-tense citations in board_sources.py are not. They were outside OH-40's touches and are outside yours too -- import_pindefs.py belongs to OH-26, which is closed, so the file is unclaimed and you may take it with --touch. Also: test_nothing_tells_anyone_to_run_the_retired_fetcher pins tools/import_kicad_board.py as its single exemption, so removing that file means removing the exemption in the same change or the test starts guarding nothing.

**Note 2026-08-25:** Partial work landed as 18d7ab8 by a session that then died mid-response (API connection lost). What it completed: the missing-vendor-tree error message now names get_board_sources.py and its registry key, closing OH-40's single remaining exemption. What it recorded, in the file itself: the deletion is blocked by two imports OUTSIDE the original claim -- tests/rules/test_kicad.py:29 takes build and header_pads from this module, tests/rules/test_board_sources.py:125 takes VENDOR. Both are now added to this ticket's touches, so whoever resumes can finish it. IMPORTANT and not obvious: the 50 webui/boards/*.json and *.svg files naming this tool in their 'derivation' field are NOT a blocker and MUST NOT be rewritten. derivation records how a file was made, and those files really were made by this tool; renaming it to the replacement would falsify provenance to tidy a reference. Only test_kicad.py's assertion on the current generator's name moves when the boards are regenerated. Lock released -- the holding session is gone.
