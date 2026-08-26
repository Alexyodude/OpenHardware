// OpenHardware — the pin panel: what it fetches, and what it says when it cannot.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Why this is a second file and not the bottom of board3d.js
//
// `board3d.js` knows three.js and knows nothing about this page. This knows
// the page and does not import three.js at the top level. That split is what
// lets a browser with no WebGL, or a vendored three.js that failed to parse,
// still get the table -- the numbers are the part somebody debugging a sketch
// actually needs, and losing them because a canvas could not be created would
// be the worst possible trade.
//
// ## Why it attaches to `window` rather than being imported
//
// `emulator.js` is a classic script, not a module, and making it one would
// mean touching every function in a 45 KB file to no end. So this module
// publishes two functions on `window.boardPins` and `emulator.js` calls them
// with `?.` -- which means a page where this file failed to load behaves
// exactly as it did before it existed.

const CANVAS = "board-pins-canvas";
const ROWS = "board-pins-rows";
const NOTE = "board-pins-note";
const FALLBACK = "board-pins-fallback";
const CAPTION = "board-pins-caption";

//: What each state reads as in the table. The 3D view paints the same four
//: from the same stylesheet; this spells them because a colour alone is not a
//: readable answer, and one of the four is not a state at all.
//:
//: `unknown` is missing on purpose -- see `unknownWords` below, because it is
//: the one state that needs two different sentences.
const WORDS = {
  high: "high",
  low: "low",
  input: "input",
};

//: The two ways a pad can be `unknown`, and they are not the same fact.
//:
//: **Found in a browser and by nothing else** (2026-08-26): a `Serial` sketch
//: on an Arduino Uno makes pins 0 and 1 `unknown`, because the USART has taken
//: PD0 and PD1 and the direction register has no trace of it. The row then
//: read `1 | PD1 | not modelled`, which contradicts itself -- the pin is named
//: in the same row that says nothing models it. Every assertion passed: the
//: state really was `unknown`, and the words were what was wrong.
//:
//: `chip_pin` is the discriminator and it is exact rather than convenient.
//: `webui/api.py` fills `chip_pin` from the board's `PIN_NAMES`, which is
//: derived from the same `HEADER` its `pin_states` walks -- so a pad has a
//: chip pin **if and only if** the board answered for it. A pad with none was
//: never in the board's table at all.
const NOT_MODELLED = "not modelled";
const IN_USE = "in use elsewhere";

/** Which of the two sentences an `unknown` pad gets. */
function unknownWords(pad) {
  return pad.chip_pin === null || pad.chip_pin === undefined
    ? NOT_MODELLED
    : IN_USE;
}

let scene = null;      // the board3d module, once it has loaded
let layout = null;     // the last /api/board/pins answer

const $ = (id) => document.getElementById(id);

/** Load three.js and the renderer, once, and only if a board wants drawing. */
async function renderer() {
  if (scene !== null) return scene;
  try {
    scene = await import("/board3d.js");
    scene.mount($(CANVAS));
  } catch (error) {
    // **Reported in the page, not only in the console.** A blank rectangle
    // where a board should be is the kind of thing a person retries three
    // times before opening devtools.
    scene = false;
    const fallback = $(FALLBACK);
    fallback.hidden = false;
    fallback.textContent =
      `The 3D view could not start: ${error}. The table beside it is the same ` +
      `data and does not need WebGL.`;
    $(CANVAS).hidden = true;
  }
  return scene;
}

function renderTable(pads) {
  const body = $(ROWS);
  body.textContent = "";
  for (const pad of pads) {
    const row = document.createElement("tr");
    row.dataset.state = pad.state;
    row.dataset.pin = pad.pin;

    const label = document.createElement("td");
    label.textContent = pad.label;
    // A pin with no coordinate is on the board rather than on the header, and
    // saying so in the row is the whole reason it is listed at all: the XIAO's
    // user LED is the pin a stock Blink drives, and it is not a pad.
    if (pad.x === null) {
      const aside = document.createElement("span");
      aside.className = "note";
      aside.textContent = " on board";
      label.append(aside);
    }

    const pin = document.createElement("td");
    pin.className = "mono";
    pin.textContent = pad.chip_pin ?? "—";

    const state = document.createElement("td");
    // Only `unknown` takes the two-sentence path. Anything else falls back to
    // its own name, which is what makes a state this panel has never heard of
    // show up as itself rather than as one of these sentences.
    state.textContent = pad.state === "unknown"
      ? unknownWords(pad)
      : WORDS[pad.state] ?? pad.state;

    row.append(label, pin, state);
    body.append(row);
  }
}

/** Fetch the layout for whatever board is loaded, and draw it. */
async function reload() {
  const response = await fetch("/api/board/pins");
  if (!response.ok) {
    layout = null;
    return;
  }
  const view = await response.json();
  if (!view.present) {
    // The same sentence the console pane uses for a board with no UART, and
    // for the same reason: an empty table reads as a program that has driven
    // nothing, which is a claim about the sketch rather than about the model.
    layout = null;
    renderTable([]);
    $(NOTE).textContent = "no header pins in this board description";
    $(CAPTION).textContent = view.note;
    $(CANVAS).hidden = true;
    (await renderer()) && scene.showBoard(null);
    return;
  }

  layout = view;
  renderTable(view.pads);
  renderCount();
  $(CANVAS).hidden = false;
  const drawn = await renderer();
  if (drawn) drawn.showBoard(view);
}

/** How many pads this repository can answer for, right now.
 *
 * **Counted from the pads and not read from `view.unknown`, because the count
 * moves.** It did not used to: before OH-70 a pad was `unknown` because the
 * board's table had no row for it, which is fixed for the life of a board, so
 * the number the layout fetch carried stayed true however long the sketch ran.
 * Then the Uno's USART started taking PD0 and PD1 while a `Serial` sketch runs
 * — and the note went on reading `22 of 32` beside two rows that had stopped
 * answering. Recomputing costs one pass over thirty-two rows.
 *
 * `/api/board/pins` still carries its own `unknown`, and it is not wrong: it
 * is that endpoint's answer at the moment it was asked. What it cannot be is
 * current, because the states arrive afterwards from a different endpoint —
 * `/api/board/state`, many times a second, carrying levels and no geometry.
 *
 * The count is the honest half of this panel: it is what tells a reader
 * whether they are looking at a thin model or a quiet program, and it is the
 * number a person would otherwise work out by reading every row.
 */
function renderCount() {
  const answerable = layout.pads.filter((p) => p.state !== "unknown").length;
  $(NOTE).textContent =
    `${answerable} of ${layout.pads.length} pads answerable · ${layout.board}`;
}

/** Repaint from a state poll. `pins` is `{pinName: state}`, or null. */
function levels(pins) {
  if (!layout) return;
  if (!pins) return;
  for (const pad of layout.pads) {
    pad.state = pins[pad.pin] ?? "unknown";
  }
  renderTable(layout.pads);
  renderCount();
  if (scene) scene.setLevels(pins);
}

/** Re-read the palette when the theme changes. */
function theme() {
  if (scene) scene.refreshTheme();
}

window.boardPins = { reload, levels, theme };
