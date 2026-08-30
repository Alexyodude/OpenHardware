---
id: OH-123
title: Two vendor layouts sit on disk unread, and composing them reverses a stated
  preference
status: open
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
