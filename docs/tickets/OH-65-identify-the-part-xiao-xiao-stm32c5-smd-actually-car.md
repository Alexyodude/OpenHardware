---
id: OH-65
title: Identify the part XIAO-XIAO STM32C5-SMD actually carries
status: done
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

**Note 2026-08-26:** CLOSED 2026-08-26. The part is real and it is a Cortex-M33.

THE OLD ENTRY WAS NOT WRONG, IT WAS OUT OF DATE. 'unknown -- part not confirmed to exist' was written 2026-08-24 and was an honest report of a search: nobody could place STM32C5 among ST's families, so the catalogue refused to guess a core. ST announced the STM32C5 in MARCH 2026 -- a Cortex-M33 part sold as low-cost with more performance than the Cortex-M0+ STM32C0.

EVIDENCE, and which piece carries the weight. Wikipedia's STM32 article says it twice and independently: the comparison table gives the core as 'Cortex-M33F', and the history timeline reads 'March 2026 STM32C5 with Cortex-M33, increased performance with cost efficiency and enhanced end-device capabilities'. That is one source saying it twice. The corroboration that actually matters is that SEEED'S OWN KiCad library ships XIAO-STM32C5-SMD.kicad_mod in a commit dated 2026-07-15 -- four months after the announcement, from the vendor who would build the board. A vendor does not draw a footprint for a part that does not exist.

WHAT WAS NOT REACHED: st.com. Two WebFetch attempts timed out. Recorded in the catalogue comment so the next reader knows which source is missing rather than assuming it was checked.

WHAT LOCAL EVIDENCE COULD NOT DO, and the ticket proposed all three lines: (1) the .kicad_mod is the MODULE's footprint and not the die's, so its 35 pads and 2.54 mm pitch describe the XIAO form factor and say nothing about the MCU inside -- that line of enquiry cannot work in principle, not merely here; (2) the symbol carries no MPN, no datasheet and no description, and no STM32 part number appears anywhere in the vendor tree; (3) the clone is shallow (one commit), so there is no rename history to read.

THE DOUBLED NAME IS THE VENDOR'S OWN, confirmed: the footprint declares itself as 'XIAO-XIAO STM32C5-SMD' internally. IRREGULAR was right to name it explicitly.

CONSEQUENCE: the board is no longer blocked on identification, it is blocked on OH-36's oracle like the other eight Armv8-M boards -- and it makes that NINE. The fourteen boards that do not run now have three reasons rather than four. test_the_cortex_m33_boards_are_nine_and_wait_on_one_oracle counts them rather than listing them, so adding an Armv8-M board moves it.

Gate: 1,439 passed, 17 skipped; all eight checkers exit 0.
