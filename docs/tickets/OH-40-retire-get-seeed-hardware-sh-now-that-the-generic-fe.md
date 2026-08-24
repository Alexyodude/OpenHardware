---
id: OH-40
title: Retire get_seeed_hardware.sh now that the generic fetcher exists
status: in-review
priority: P3
created: '2026-08-25'
touches:
- tools/get_seeed_hardware.sh
- tools/kicad.py
- tools/inventory.py
- tests/rules/test_kicad.py
- tests/rules/test_inventory.py
---

OH-24 replaced this script with tools/board_sources.py plus a generic fetcher, and its own done-criterion said the old script should be deleted rather than left beside its replacement. OH-24 refused, correctly, and the refusal is the reason this ticket exists.

There are live references across at least six files. Two of them would actively mislead a user if the file vanished, because they are error messages telling someone to run it: tools/import_kicad_board.py's failure path, and the skip message in tests/rules/test_kicad.py. The rest are in tools/inventory.py, tools/kicad.py, tests/rules/test_inventory.py -- one of which asserts on the string -- and tools/import_pindefs.py from OH-26.

So deleting one file is a six-file change spanning four tickets, which is precisely the adjacent-cleanup that .claude/CLAUDE.md says to note rather than do. Doing it inside OH-24 would have meant editing files three other sessions were holding.

Sequence it after OH-26 and OH-39 have landed, so the reference list is stable while it is being rewritten.

Done when nothing outside third_party/ mentions get_seeed_hardware, every error and skip message names the new fetcher and its argument instead, and 'python tools/get_board_sources.py seeed-xiao' reproduces the tree the old script produced.

**Note 2026-08-25:** Claim on tools/import_kicad_board.py removed: it collided with OH-41, whose entire subject is that file. OH-40 retires get_seeed_hardware.sh; OH-41 retires import_kicad_board.py. They still share tools/inventory.py and the two tests, so sequence them together -- but the file each is named after belongs to it alone.

**Note 2026-08-25:** Done. tools/get_seeed_hardware.sh deleted; 10 references rewritten across tools/kicad.py (1), tools/inventory.py (6), tests/rules/test_kicad.py (1) and tests/rules/test_inventory.py (2). Every rewritten surface names the replacement AND its argument: 'python tools/get_board_sources.py seeed-xiao'. Verified by rendering, not by grep: the absent-tree message, the asset cell detail, the git-ls-tree failure message, the text report line and the markdown report line all now read the new invocation. The two that would have actively misled someone were the inventory absent-tree message and test_kicad.py's skip; both fixed. REPRODUCTION CHECKED: snapshotted third_party/seeed-xiao before touching anything (147 files, 27M), ran 'python tools/get_board_sources.py seeed-xiao', diffed - identical file set, same size, no damage. OH-26's extractor still resolves 11 of 14 pads on XIAO-RP2040-DIP off that tree and test_kicad.py's real-vendor test still passes, so OH-27's collector and OH-26's extractor both still have their data. tests/rules 374 passed. check_licenses, check_layering, check_banned_symbols, check_deltas, check_board_claims all OK. CONTRADICTION, and the done-criterion is corrected rather than met: 'nothing outside third_party/ mentions get_seeed_hardware' is both unachievable and partly wrong. Unachievable because a test that checks for the string must contain it. Wrong because tools/board_sources.py and tools/get_board_sources.py name it in the PAST TENSE to record what they replaced and which precedent they kept - that reasoning is the most useful thing in either docstring - and because docs/ holds a dated handoff plus closed tickets OH-23, OH-24 and OH-41, where rewriting a reference to name a tool that did not exist at the time would falsify a record rather than fix anything. The criterion that is actually true and worth enforcing is: NOTHING INSTRUCTS ANYONE TO RUN A FILE THAT IS GONE. test_nothing_tells_anyone_to_run_the_retired_fetcher enforces that form, searching tools/ and tests/ for the invocation rather than the name, and it pins tools/import_kicad_board.py as the single remaining exemption so OH-41 cannot forget it. Live references left, all outside OH-40's touches: tools/import_kicad_board.py (an instruction, OH-41's, exempted in the test), tools/import_pindefs.py lines 35 and 841 (two prose citations of the script's fetch-don't-vendor argument, written present tense and now stale - NOT on OH-40's touches so left alone; worth a line in OH-41 or a follow-up), tools/board_sources.py and tools/get_board_sources.py (past tense, should stay), and eight docs files (history, should stay). ALSO: inventory.py's VENDOR_DIR comment promised 'this becomes a lookup on that day and not before', meaning when OH-24 replaced the fetcher. That day arrived. I did not make it an import-time lookup, because source() raises on a missing entry and inventory.py is imported by every --markdown run, so a registry typo would become a module that will not load. Bound it with test_the_vendor_dir_is_the_registry_s_own_path instead, asserting VENDOR_DIR == source('seeed-xiao').dest(Path('.')), which is what Source.name being documented as stable is for.
