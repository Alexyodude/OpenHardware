---
id: OH-120
title: Composed copper and silkscreen are declared dielectrics and cannot be carved
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet; re-claims tools/compose_board_3d.py and
tools/import_3d_model.py when it starts.

**From the 2026-08-30 model survey; two findings, one cause.**

`compose_board_3d.COPPER = "#c8a253"` has no `FINISHES` entry, so every pad of
exposed copper on every composed board ships at DEFAULT_FINISH -- metallic
0.10, rough 0.60, "nothing here can say what this surface is". Read back out
of the shipped .glb files: the composed pad colour is 0.10 while the fetched
header-pin golds (#b58136, #a5a392, #c6c4a0) are all 1.00. `SILKSCREEN`
"#e9e9e4" is in the same state. 203-400 pads a board render matte tan when on
a real board the pads are the shiniest thing on it -- a direct "poor 3d
model" symptom. OH-82 built FINISHES and is closed; these colours were added
after it, bypassing it.

**And the same number gates the carve**: `carvePins` takes only
`material.metalness > 0.5` (board3d.js), so composed copper is not candidate
geometry. On an SMD XIAO the pads ARE castellated copper -- there is no
header part -- so its pads have nothing to carve BY MATERIAL, before any
geometry question.

`report_finishes` exists so the assignment "can be audited against the
picture" and the composer never calls it -- which is how this sat unnoticed.

DONE WHEN copper and silkscreen carry FINISHES entries with the evidence rule
satisfied; the composer calls report_finishes before write; and the SMD
boards' castellation copper becomes carveable, measured in the browser.
