---
id: OH-224
title: The XIAO MG24 and nRF54L15 SMD boards are four pads short of the pins layer,
  and Seeed's own board files answer them
status: open
priority: P2
created: '2026-10-12'
touches:
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- webui/boards/XIAO-MG24-SMD.json
- webui/boards/XIAO-nRF54l15-SMD.json
---

Measured 2026-10-12 from `python tools/inventory.py` on master: the TWINS pins layer fails on three boards, and two of them are short only a few pads that Seeed's own board files can answer.

    XIAO-MG24-SMD        unanswered on MG24_EN
    XIAO-nRF54l15-SMD    unanswered on nRF54_EN, 54L15_RX20, 54L15_TX20
    XIAO-XIAO STM32C5-SMD  no vendor source at all (OH-163 step 4, OH-26); not this ticket

Each of the four carries the generic `why_null` "no board-support package covering this board defines this label", which the pins layer counts as unanswered. But `tools/import_pindefs.py` already reads `MG24.kicad_pcb` (seeed_pcb_traced, SWDIO and SWCLK) and `nRF54L15.kicad_pcb` (seeed_pcb, NFC1 and NFC2) out of `third_party/seeed-pcb`, and OH-200 answered the XIAO C5 and C6 SMD pads the same way.

STEPS:
1. Trace each of the four pads' nets in Seeed's own board file to the MCU's own pad. Where the net reaches a GPIO in the chip's numbering (RX20/TX20 look like P1/P2 UART pins), the pad gains that `chip_pin`, read from the file, not typed. Where it reaches a dedicated pin (an EN pad most likely reaches the chip's reset/enable pin), the pad gets a specific `why_null` naming that pin and the net, in the shape the board files already use for "a dedicated debug pad of the nRF54L15, not a GPIO".
2. The `_CHIP_PIN_NAME` gate stays where it is: OH-172's slice 2 is where a non-GPIO pin may become a caption; this ticket only answers the pads within today's rules, and says so in its note so OH-172 can pick them up.
3. Regenerate the two board files with the importer, held by the existing test that the committed files reproduce exactly; nothing hand-edited.
4. Check what else reads those pads (pin view, inventory, the 3D panel) and that nothing claims a level for them: neither chip has a module, so OH-172's `modelled` is false for every pad on both boards regardless.

Done when `python tools/inventory.py` shows the pins layer holding on both boards, every new answer cites the board file's net, and the regeneration test holds the files.
