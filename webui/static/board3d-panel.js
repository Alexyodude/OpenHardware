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
const MENU = "bench-menu";
const TREE = "bench-tree";
const BENCH_LIST = "bench-list";
const UNWIRE = "bench-clear";
const BENCH_NOTE = "bench-note";

//: Where `tools/import_3d_model.py` writes which board it has a model for.
const MODEL_INDEX = "/models/index.json";

//: What the caption says, and it is the honest-degradation rule in two
//: sentences rather than one.
//:
//: **The static text in `emulator.html` said "a footprint, extruded -- not a
//: model of the board" and was true of every board when OH-30 wrote it.** It
//: stopped being true of nine of them, and a page that goes on disclaiming a
//: model it is now showing is wrong in the same direction as one that claims a
//: model it has not got: both leave a reader unable to tell which they are
//: looking at, which is the only thing the sentence was ever for.
const FOOTPRINT_CAPTION =
  "A footprint, extruded — not a model of the board. Every pad position and " +
  "the outline are the vendor's own KiCad footprint, exact to three decimals. " +
  "The thickness is a stated 1.6 mm and there are no components on it, " +
  "because this board publishes no 3D model. Drag to turn it.";
const MODEL_CAPTION =
  "The vendor's own 3D model. The board, its components and its connector are " +
  "Seeed's published mechanical model, tessellated by " +
  "tools/import_3d_model.py; the pad markers on it are this repository's " +
  "reading of the chip's registers. Drag to turn it.";

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
let models = null;     // the model index, fetched once and remembered

/** Which board has a vendor model, from `models/index.json`.
 *
 * Fetched once and remembered **including the failure**: a checkout that has
 * not run `tools/import_3d_model.py` has no such file, and asking for it again
 * on every board change would put a 404 in the console for each.
 */
function modelIndex() {
  if (models === null) {
    models = fetch(MODEL_INDEX)
      .then((response) => (response.ok ? response.json() : { boards: {} }))
      .catch(() => ({ boards: {} }));
  }
  return models;
}

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

  const model = (await modelIndex()).boards?.[view.board] ?? null;
  $(CAPTION).textContent =
    model && model.file ? MODEL_CAPTION : FOOTPRINT_CAPTION;

  const drawn = await renderer();
  if (drawn) drawn.showBoard(view, model);
  renderBench();
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
  if (scene) {
    scene.setLevels(pins);
    renderBench();
  }
}

/** Re-read the palette when the theme changes. */
function theme() {
  if (scene) scene.refreshTheme();
}

/**
 * The catalogue, as nested folders.
 *
 * **KiCad's own library tree and not a taxonomy invented here.** The index
 * `tools/import_3d_model.py` writes has one entry per library folder --
 * `LED_THT`, `Buzzer_Beeper` -- and this renders exactly that, so somebody who
 * knows the library finds the same names and this page has no second
 * classification to keep true.
 *
 * `<details>` rather than a `<select>` with `<optgroup>`: a select gives one
 * level of grouping and this needs two, and a native disclosure is keyboard
 * reachable and closes on Escape without a line of script.
 */
async function renderTree() {
  const tree = $(TREE);
  if (tree.dataset.built === "yes") return;
  const index = await modelIndex();
  const catalogue = index.parts;
  tree.textContent = "";
  if (!catalogue || !Object.keys(catalogue.libraries ?? {}).length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent =
      "No part models here. Run tools/import_3d_model.py --parts to fetch them.";
    tree.append(empty);
    tree.dataset.built = "yes";
    return;
  }

  const root = document.createElement("details");
  root.open = true;
  const rootName = document.createElement("summary");
  rootName.textContent = "KiCad packages3D";
  root.append(rootName);

  for (const [library, entries] of Object.entries(catalogue.libraries)) {
    const folder = document.createElement("details");
    const name = document.createElement("summary");
    name.textContent = library;
    folder.append(name);
    for (const part of entries) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "bench-part";
      item.textContent = part.label;
      // A part whose mesh was never fetched is shown and refused, rather than
      // hidden: "run the importer" is a fixable answer and an absence is not.
      item.disabled = !part.file;
      item.title = part.file ? part.name : `${part.name} — not imported`;
      item.addEventListener("click", () => addPart(part.slug));
      folder.append(item);
    }
    root.append(folder);
  }
  const note = document.createElement("p");
  note.className = "hint";
  note.textContent = catalogue.source;
  root.append(note);
  tree.append(root);
  tree.dataset.built = "yes";
}

/** Put one part on the bench. */
async function addPart(slug) {
  // The renderer is loaded lazily, so the first part is also what pays for
  // three.js. A browser with no WebGL gets the table and a message rather than
  // a button that silently does nothing.
  const drawn = await renderer();
  if (!drawn) {
    $(BENCH_NOTE).textContent =
      "The 3D view could not start, so there is nowhere to put a part.";
    return;
  }
  await drawn.addPart(slug);
  $(MENU).open = false;
  renderBench();
}

/** What is on the bench, and what is wired to what. */
function renderBench() {
  if (!scene) return;
  const joined = scene.connections();
  const onBench = scene.parts();
  $(UNWIRE).disabled = joined.length === 0;

  const list = $(BENCH_LIST);
  list.textContent = "";
  for (const wire of joined) {
    const row = document.createElement("li");
    const what = document.createElement("span");
    // **Named, not counted.** "5 mm LED — anode on D0" is a sentence a reader
    // can check against the table beside it; "1 connected" is one they have to
    // trust.
    what.textContent = `${wire.label} — ${wire.terminal} on ${wire.pin}`;
    const off = document.createElement("button");
    off.type = "button";
    off.className = "bench-off";
    off.textContent = "×";
    off.title = `Unwire ${wire.label} from ${wire.pin}`;
    off.setAttribute("aria-label", off.title);
    off.addEventListener("click", () => {
      scene.disconnect(wire.id);
      renderBench();
    });
    row.append(what, off);
    list.append(row);
  }

  if (!onBench.length) {
    $(BENCH_NOTE).textContent =
      "Drag from a pad to a part's terminal to wire it. The part shows what " +
      "that pin is doing; nothing flows back into the chip.";
    return;
  }
  const loose = onBench.length - joined.length;
  $(BENCH_NOTE).textContent = loose
    ? `${loose} part${loose === 1 ? "" : "s"} not wired yet. Drag from a pad ` +
      `to a terminal.`
    : "Every part is wired. Drag from another pad to wire another.";
}

/** Wire up the bench controls. Called once, when this module loads. */
function mountBench() {
  // A wire made by dragging happens inside the canvas and nothing else sees
  // it; `board3d.js` says so with an event rather than calling in here.
  $(CANVAS).addEventListener("wires-changed", renderBench);
  $(MENU).addEventListener("toggle", () => {
    if ($(MENU).open) renderTree();
  });
  $(UNWIRE).addEventListener("click", () => {
    if (scene) scene.clearBench();
    renderBench();
  });
}

mountBench();

window.boardPins = { reload, levels, theme };
