---
id: OH-65
title: Identify the part XIAO-XIAO STM32C5-SMD actually carries
status: open
priority: P3
created: '2026-08-26'
touches:
- webui/boards/catalogue.py
- docs/research/*
- tests/webui/test_board_catalogue.py
---

THE LAST OF THE FOURTEEN BOARDS THAT DO NOT RUN, and the only one whose blocker is not a core. Its chip is recorded as 'unknown -- part not confirmed to exist' in webui/boards/catalogue.py:104, so it cannot be assigned a core at all, let alone run.

WHAT IS KNOWN. The board comes from Seeed's own KiCad library and the doubled prefix is faithful -- the file really is XIAO-XIAO STM32C5-SMD.kicad_mod, and webui/boards/catalogue.py's IRREGULAR table names it explicitly rather than parsing it into something plausible and wrong. 'STM32C5' is not an ST family anyone could find a product page for: ST ships STM32C0 and STM32C0x1, and the C5 designation appears nowhere in their catalogue. Recorded in docs/HANDOFF_2026-08-24_boards-firmware-and-the-armv6m-oracle.md around line 493.

SO THE QUESTION IS NOT 'WRITE A CORE'. It is: what silicon is on that footprint? Three answers are possible and they lead to different work:

  * A typo or an early name for a part that does exist -- most likely STM32C0, which is Cortex-M0+ and would therefore be reachable with core/cortexm0 as it stands, alongside the SAMD21 and RP2040. That is the cheap outcome and it is worth ruling in or out first.
  * A real part that was announced and withdrawn, in which case the footprint stays and the board stays undescribed with a citation saying so.
  * An error in Seeed's library, in which case the honest move is to record that and leave the board unrunnable on purpose.

WHERE TO LOOK, and none of it is guesswork on the name: the .kicad_mod's own pad count and pitch against the STM32C0 packages; Seeed's wiki and product pages for a XIAO with that marking; the KiCad library's git history, which may show the file renamed from something identifiable.

WHY IT IS P3. It is one board of twenty-six, it blocks nothing else, and the current state is already honest -- the catalogue says the part is not confirmed to exist rather than guessing a core. This ticket exists so that 'fourteen boards do not run' has fourteen reasons on file rather than thirteen and a shrug.

Done when the chip is either named with a citation and given a core, or recorded as unidentifiable with the evidence that was checked -- and either way test_board_catalogue.py pins the answer so nobody re-opens the question from scratch.
