---
id: OH-40
title: Retire get_seeed_hardware.sh now that the generic fetcher exists
status: open
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
