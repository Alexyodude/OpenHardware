---
id: OH-168
title: Remove the geometry caption under the 3D board, keeping the two things it says
  that are not geometry
status: done
priority: P2
created: '2026-09-05'
touches:
- webui/static/emulator.html
- webui/static/board3d-panel.js
- tests/webui/test_board3d.py
---

The paragraph under the 3D board goes, at the user's request, and the two things it says that are not about geometry have to survive it.

`board-pins-caption` is a `<p>` under the canvas carrying one of three sentences about where the geometry came from: the vendor's own mechanical model, a board composed here from two libraries, or a KiCad footprint extruded because nobody publishes a model of that board. That is OH-30's honest-degradation rule as a sentence on the page, and removing it is a deliberate loss, asked for and confirmed 2026-09-05.

**What must not go with it.** The same element is also the only place the page says why the canvas is blank:

  "Nothing is loaded yet, so there is no board to draw. Pick one above, choose a compiled image, and it appears here -- a raw .bin also needs the load address beside it, because a .bin cannot say where it belongs."

and, for a board whose description has no header pins, the server's own `note`. The panel's own comments record that this silence was reported twice as "no 3D model on 127.0.0.1:8088", and `test_a_board_picked_but_not_loaded_says_so_rather_than_showing_nothing` exists to keep it spoken. Deleting the element without moving those would re-file a bug this repository has already paid for twice.

`board-pins-note` is the line that remains -- it already carries "no board loaded" and "22 of 32 pads answerable · <board>" -- and it is where they go.

STEPS:

1. Remove the `<p id="board-pins-caption">` from `webui/static/emulator.html`, and the `<div class="prose">` around it if it holds nothing else.

2. Remove from `webui/static/board3d-panel.js`: the `CAPTION` id, `FOOTPRINT_CAPTION`, `MODEL_CAPTION`, `COMPOSED_CAPTION`, the `caption(model)` function and every `$(CAPTION).textContent = ...`. The model index is still fetched for `showBoard`, so nothing else in that path changes.

3. The two non-geometry messages move to `board-pins-note`: the waiting sentence on both no-board exits, and the server's `note` on a board with no header pins. Test: the same assertion that guards it today, redirected -- the refusal branch still says the sentence and still hides the canvas, and the sentence still names the load address, which is the step people actually miss.

4. Delete the three tests that assert the caption's content and position, and say in the commit that they are deleted rather than let them rot: `test_the_panel_says_it_is_a_footprint_and_not_a_model_of_the_board`, `test_the_caption_stops_disclaiming_a_model_once_there_is_one`, and `test_the_canvas_comes_before_the_caption_that_describes_it`.

5. `docs/features/webui.md` or any rule text that promises the caption is checked and corrected if it names it, because a ledger describing a removed element is the rot this repository has caught twice.

**What is knowingly given up**, recorded here because a future session will otherwise re-derive it: the page will draw a footprint extrusion and a vendor's own assembly with nothing to tell them apart. Twelve of the twenty-six boards are composed and one is a bare footprint, so this is not a hypothetical difference. If it comes back, it belongs somewhere less prominent rather than in the same words.

**Note 2026-09-05:** Done 2026-09-05. Four tests removed, not three: test_the_panel_shows_the_composers_own_gaps also guarded the caption, since the composed sentence named what the composer could not draw from model.not_drawn. Consequence worth someone's attention: every board model still SHIPS not_drawn in its extras and nothing reads it now, so it either finds a new reader or becomes dead data the composer is still computing.
