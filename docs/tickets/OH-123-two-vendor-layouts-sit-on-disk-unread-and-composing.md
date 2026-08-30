---
id: OH-123
title: Two vendor layouts sit on disk unread, and composing them reverses a stated
  preference
status: done
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 model survey.

`third_party/seeed-pcb/MG24.zip` and `nRF54LM20A.zip` each hold exactly one
`.kicad_pcb`; neither chip is in `PCB_SOURCES`, neither board in
`COMPOSITIONS`. The importer fetches THESE SAME ARCHIVES and uses only the
`.step` inside. So MG24-DIP/-SMD and nRF54LM20A-DIP/-SMD render as imported
meshes with no copper, routing or silkscreen while their own layouts sit
unread beside them. Mechanically: two PCB_SOURCES rows + two Composition rows,
no new fetch.

**AND IT IS A JUDGEMENT, NOT JUST A GAP -- which is why this is not simply
done.** The stated preference order (CLAUDE.md) is: vendor's own mechanical
model FIRST, composed LAST. These four boards HAVE the vendor's mechanical
model -- the best source -- and composing them would trade real part fidelity
for artwork. The options are: keep the imported mesh (status quo, no
artwork); switch to composed (artwork, worse parts); or teach the page/model
pipeline to prefer imported geometry WITH composed artwork, which nothing
supports today. Decide first, then build; record the decision here either way.

---

**DECIDED 2026-08-31: option one -- the imported mesh stays, and the two
layouts stay unread BY CHOICE.** Nothing is built, which is what the
decision requires, and this note is the record the ticket asked for.

The reasoning, in the order it decides:

  1. **The stated preference order is the decision, already made.**
     CLAUDE.md ranks geometry sources: the vendor's own mechanical model
     FIRST, composed LAST -- and it ranks them that way because a
     composition stands generic package models on a pad map, while the
     vendor's STEP is the vendor's own statement of the assembled board.
     MG24 and nRF54LM20A HAVE the vendor's model. Composing them would
     read the preference order backwards for two boards while thirteen
     others honour it -- the exact inversion this ticket's title names.
  2. **What composing would buy is artwork; what it would cost is parts.**
     The imported meshes carry the vendor's own bodies, colours and
     connector geometry. A composition would swap those for KiCad
     stand-ins to gain copper, routing and silkscreen -- trading the
     board's best-sourced facts for its most decorative ones.
  3. **The middle option is real but is not this ticket.** Preferring
     imported geometry WITH composed artwork overlaid is the only path
     that adds the artwork without the trade, and nothing in the pipeline
     supports a hybrid today: the composer builds whole boards, the
     importer imports whole files, and the page draws exactly one model
     per board. If the artwork is ever wanted on these four boards, that
     hybrid is its own designed feature with its own ticket -- filed then,
     not smuggled in as a side effect of "two files sit unread".

What changes on disk: nothing. `PCB_SOURCES` and `COMPOSITIONS` do not
grow the two rows precisely because mechanics were never the blocker --
the ticket itself says "two rows, no new fetch". The blocker was this
judgement, and it is now recorded where the next survey will find it.
