---
id: OH-39
title: A SAMD21 board description, and a blink that proves it
status: open
priority: P1
created: '2026-08-25'
touches:
- webui/boards/samd21.py
- tests/cortexm0/test_board_samd21.py
- tests/cortexm0/test_samd21_blink.py
- tests/cortexm0/samd21/*
- webui/boards/catalogue.py
- tests/webui/test_board_catalogue.py
- webui/static/emulator.html
- webui/static/emulator.js
---

The SAMD21 already reports core_built=True in the catalogue, because it shares core/cortexm0 with the RP2040. It reads NO BOARD DESCRIPTION for one reason only: webui/boards/samd21.py does not exist. This is the cheapest remaining board win in the repository -- a memory map and one peripheral, not an instruction set.

The map is the interesting half. SAMD21 puts flash at 0x00000000, not 0x10000000, and that difference is exactly why the memory map was moved out of the core in the first place; test_the_same_core_serves_a_board_with_a_different_memory_map already proves the core can take it, using a SAMD21-shaped map, but no board supplies one.

PORT at 0x41004400 carries DIRSET/OUTSET/OUTCLR/OUTTGL, which are write-only registers rather than alias windows -- the same distinction that took a round to get right on SIO, so map_alias(..., readable=False).

Which further peripherals a blink needs is a question to MEASURE rather than guess: write a bare-metal SAMD21 blink, run it, and add whatever the fault address names.

Do NOT add an empty samd21.py. It would flip two boards to CORE+BOARD on the strength of a filename, which is the mistake rules/board-claims.md check 3 exists to name.

Done when a real compiled SAMD21 image is watched toggling a pin, SAMD21 is in FIRMWARE_VERIFIED, and test_only_the_board_a_real_image_ran_on_claims_to_have_run_one is updated deliberately rather than incidentally.

**Note 2026-08-25:** The handoff's design guess was wrong on one point, and the vendor header is what caught it. HANDOFF_2026-08-25 6.1 said PORT's DIRSET/OUTSET/OUTCLR/OUTTGL are 'write-only registers like SIO's, so use map_alias(..., readable=False)'. Microchip's generated CMSIS header marks all six __IO ... (R/W 32), and marks WRCONFIG __O ... ( /W 32) in the same struct -- so the header does draw the write-only distinction and declines to draw it for these. Modelled readable, with the departure and its evidence written down in install_port's docstring and pinned by test_the_set_registers_read_back_their_target_unlike_sios.

Residual, stated rather than buried: no code in the fetched tree ever READS these registers -- all ~20 uses across the Arduino core, the bootloaders and ASF's port.h driver are writes. So the read-back value rests on the header's access type and is exercised by no driver here.
