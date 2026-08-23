---
id: OH-11
title: Microcode-exact IMUL, DIV and IDIV
status: open
priority: P2
owner: session/muldiv
created: '2026-08-23'
touches:
- core/i8086/muldiv.*
- tests/i8086/test_muldiv.py
---

IMUL, DIV and IDIV produce correct results and correct CF/OF but do not reproduce two things that need the 8088's CORX/CORD microcode emulated step by step rather than a C++ divide.

1. The documented-undefined flags. SF, ZF, PF and AF after IMUL, and every arithmetic flag after DIV and IDIV, are intermediates of the shift-and-add loop. A single internal byte does explain SF, ZF and PF jointly in all 10,000 IMUL cases -- so the value exists and is recoverable -- but it is not the product's high half (which fits ZF 96%, SF 98%, PF only 69%), nor the magnitude product, nor any simple function of either that was tried. MUL is not affected: its flags come from the high half exactly, and it is at 100%.

2. IDIV's quotient sign. 33 of 569 non-trapping register-form cases (5.8%) want exactly the negation of the correctly-signed quotient, with the remainder correct in every one. Neither operand's sign, the quotient's sign, nor a zero remainder separates the two groups, so this is a quirk of the correction step and not a sign-handling mistake that can be reasoned out.

Where this bites: the pushed FLAGS word on a divide-error trap contains the undefined bits, so it reaches memory and no register-side flag mask can hide it. That is why the DIV and IDIV floors in tests/i8086/test_conformance.py are stated over non-trapping cases.

Measured 2026-08-23 against SST8088 v2, F6.5 F6.6 F6.7 F7.5 F7.6 F7.7.

**Note 2026-08-23:** Blocked behind nothing: OH-4 is closed and released core/i8086/muldiv.*. Also rename the claimed test file if a different name is used -- tests/i8086/test_muldiv.py does not exist yet.
