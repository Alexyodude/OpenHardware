---
id: OH-89
title: The 3D view says nothing while it waits, and sits two screens below the fold
status: done
priority: P1
created: '2026-08-28'
touches:
- webui/static/emulator.html
- webui/static/board3d-panel.js
- tests/webui/test_board3d.py
---

ASKED FOR BY THE USER after reporting twice that no 3D model appeared. Nothing
was broken: the server serves every asset, the renderer starts on their GPU, and
the board draws. Two properties of the page made "nothing there" the expected
sight, and both are this repository's fault rather than theirs.

## 1. THE PANEL SAYS NOTHING WHILE IT WAITS

`reload()` in `webui/static/board3d-panel.js` fetches `/api/board/pins`, and on
a response that is not ok it sets `layout = null` AND RETURNS. No caption, no
note, no message: the canvas keeps its 300 x 150 default and draws nothing, and
the page offers no clue that an image has to be loaded first. Picking a board
from the selector is not enough and nothing says so.

The neighbouring case is already handled properly -- a board whose description
has no header pins gets `view.note` in the caption -- so this is the one exit
that forgot to speak.

## 2. THE CANVAS IS UP TO TWO SCREENS BELOW THE FOLD

Measured 2026-08-28 with the board loaded, canvas offset from the top of the
document:

    1366 x 768    1,584 px down (2.06 screens)   BELOW THE FOLD
    1600 x 900      908 px down (1.01)           BELOW THE FOLD
    1920 x 1080     871 px down (0.81)           on screen
    2560 x 1440     814 px down (0.57)           on screen
    3440 x 1440     811 px down (0.56)           on screen

What is above it is the `h2`, a paragraph of caption prose, the bench bar and
the bench list. On a 1366 x 768 laptop -- the commonest size there is -- a
reader loads the page and the 3D view is nowhere on their screen.

`docs/HANDOFF_2026-08-27_the-circuit-and-the-layout.md` residual 2 already
records the board panel as 1,548 px tall, "mostly its own caption prose", and
says the question is whether the caption can be SHORTER rather than HIDDEN.
There is a third answer it did not consider: the caption can stay exactly as it
is and go BELOW the thing it captions. A caption under its figure is where a
caption belongs, and it costs the prose nothing.

## DONE WHEN

A page with no image loaded says what it is waiting for, in the caption, where
the explanation of the picture already lives -- and the canvas is on screen at
1366 x 768 without scrolling, measured the same way it was measured above.

## NOT IN THIS TICKET

Shortening the caption. It is the honest-degradation statement about a composed
model and the last session refused to hide it; moving it is not shortening it,
and this ticket does not touch a word.
