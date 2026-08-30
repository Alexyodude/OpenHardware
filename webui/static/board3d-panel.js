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
//: What the caption says when there is no board to caption.
//:
//: **The load address is named because that is the step people miss.** A raw
//: `.bin` carries no addresses, so it is refused without one, and "Load" then
//: does nothing visible while the reason sits in a field further up the page.
//: ELF, UF2 and Intel HEX say where they belong and the field is ignored.
//:
//: Written as a caption rather than as an error, because nothing has gone
//: wrong: this is the panel saying what it is waiting for, in the place the
//: explanation of the picture already lives.
const WAITING =
  "Nothing is loaded yet, so there is no board to draw. Pick one above, " +
  "choose a compiled image, and it appears here — a raw .bin also needs the " +
  "load address beside it, because a .bin cannot say where it belongs.";
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
//: **A third caption, because a composed model is neither of the other two.**
//: Saying "the vendor's own 3D model" of a board assembled here from two
//: libraries would be the same class of untruth as the footprint caption
//: claiming a KiCad footprint the Arduino Uno never had. The parts that are
//: missing are named by `composedCaption` from the model's own record of them,
//: rather than written down here where they would rot.
const COMPOSED_CAPTION =
  "Composed, not published: nobody ships a 3D model of this board. The " +
  "outline and every component's position are the vendor's own CAD, the " +
  "components are KiCad's published meshes, and the board colour is read from " +
  "PICSimLab's artwork. Drag to turn it.";

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

//: Which board was last brought into view, so it is brought once and not on
//: every poll. See `reload`, which is called on a timer while a board runs.
let shown = null;
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

/** Which of the three true sentences describes the board now on screen.
 *
 *  A composed model names what it could NOT draw, out of the record the
 *  composer put in the file. Writing that list here instead would be a second
 *  copy of a fact that changes whenever somebody finds a mesh -- and this
 *  repository has twice caught a hand-kept list describing code it no longer
 *  matched. `absent` is empty on a board that is complete, and then the
 *  sentence simply is not added. */
function caption(model) {
  if (!model || !model.file) return FOOTPRINT_CAPTION;
  if (!model.composed) return MODEL_CAPTION;
  const parts = [COMPOSED_CAPTION];
  // **Named, not counted.** "One part was modelled" tells a reader that
  // something in the picture is less trustworthy without telling them which,
  // which is the worst of both. `modelled` is empty on a board where every
  // mesh was published, and then the sentence is not there at all.
  const made = model.modelled ?? [];
  if (made.length) {
    parts.push(
      `Modelled here rather than published, from dimensions that each cite a ` +
      `source: ${made.join(", ")}. See tools/model_from_datasheet.py.`
    );
  }
  const missing = (model.absent ?? [])
    .map((gap) => `${gap.elements.join("/")} is ${gap.why}`)
    .join(" ");
  if (missing) parts.push(`Not drawn: ${missing}`);
  return parts.join(" ");
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

/** Fetch the layout for the board the picker names, and draw it.
 *
 * **"whatever board is loaded" is what this used to say, and it was the bug.**
 * The pin view existed only after a firmware load, so choosing a board drew
 * nothing at all -- and since this function is the ONLY thing that draws the
 * board, there was no other way for a picked board to appear. OH-89 made the
 * panel say what it was waiting for, which was the right fix to the symptom
 * and left this.
 *
 * The board is named in the request, so the answer is about the board the
 * reader is looking at rather than the one the server happens to be running.
 * `webui/emulator_server.py` merges live levels in when those are the same
 * board and reports every pad as `unknown` when they are not.
 */
async function reload() {
  // Read from the DOM rather than passed in, because all four callers would
  // otherwise have to agree on it -- and a caller that forgot would silently
  // ask about a different board than the one on screen.
  const picked = document.getElementById("board-pick")?.value ?? "";
  const response = await fetch(
    picked ? `/api/board/pins?board=${encodeURIComponent(picked)}`
           : "/api/board/pins");
  if (!response.ok) {
    // **It used to set `layout` and return, saying nothing at all.** The canvas
    // kept its 300 x 150 default, the caption kept whatever it last held, and
    // the page offered no hint that an image has to be loaded before there is
    // a board to draw -- reported twice as "no 3D model on 127.0.0.1:8088",
    // which is exactly what it looks like. The `!view.present` branch below
    // has always spoken; this is the exit that forgot to.
    layout = null;
    renderTable([]);
    $(NOTE).textContent = "no board loaded";
    $(CAPTION).textContent = WAITING;
    $(CANVAS).hidden = true;
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
  $(CAPTION).textContent = caption(model);

  const drawn = await renderer();
  if (drawn) drawn.showBoard(view, model);
  renderBench();

  // **Bring it into view the first time it is drawn, and only then.**
  // Moving the canvas above its caption got it on screen at every width
  // measured except 1366 x 768, where two columns put the whole load-and-run
  // panel above it in the same column and it starts 1,266 px down. Shortening
  // that panel's prose to win a screenful is the trade this repository has
  // refused before, so the board comes to the reader instead.
  //
  // `block: "nearest"` scrolls the least that will do, so a reader who can
  // already see it is not moved at all -- and `shown` means this happens when
  // the board CHANGES rather than on every poll, which would drag the page
  // out from under anyone reading the panel above while a blink runs.
  if (view.board !== shown) {
    shown = view.board;
    $(CANVAS).scrollIntoView({ block: "nearest" });
  }
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

/**
 * What is on the bench, what is wired to what, and what the circuit makes of it.
 *
 * **One row per PART rather than per wire, and that is this ticket's change.**
 * A wire is not a claim about anything on its own -- an LED needs two of them
 * and a return path before it can be said to be doing something -- so the row a
 * reader looks at is the part, carrying its wires, the sentence `circuit.js`
 * wrote about it, and any warning that came with it.
 */
function renderBench() {
  if (!scene) return;
  const joined = scene.connections();
  const onBench = scene.parts();
  const solved = scene.circuit();
  $(UNWIRE).disabled = joined.length === 0;

  const list = $(BENCH_LIST);
  list.textContent = "";
  for (const [index, part] of onBench.entries()) {
    const row = document.createElement("li");
    row.dataset.drive = part.drive;

    const head = document.createElement("div");
    head.className = "bench-head";
    const what = document.createElement("span");
    what.className = "bench-name";
    // **Named, not counted.** "5 mm LED — anode on D0" is a sentence a reader
    // can check against the table beside it; "1 connected" is one they have to
    // trust.
    what.textContent = part.label;
    head.append(what);

    // **The broken indicator, and it is a word rather than only a colour.**
    // `parts.js` paints a destroyed lens `--halt`, which is a cue and not a
    // claim: at the size a 5 mm LED is drawn, a broken red one and a lit red
    // one are both red. This is the half a reader can be sure of.
    if (part.destroyed) {
      const badge = document.createElement("span");
      badge.className = "bench-dead";
      badge.textContent = "destroyed";
      head.append(badge);
    }

    for (const wire of joined.filter((w) => w.part === index)) {
      const chip = document.createElement("span");
      chip.className = "bench-wire";
      chip.append(document.createTextNode(`${wire.terminal} on ${wire.pin}`));
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
      chip.append(off);
      head.append(chip);
    }
    // **The hatch `destroyed` depends on** (OH-131). The verdict latches for
    // the part's whole stay on the bench, and `circuit.js`'s justification
    // for that is "the only thing that undoes it is removePart, which is
    // what a person does with a burnt LED" -- but until this button,
    // `removePart` was exported with no caller anywhere in the page, so a
    // burnt part sat on the bench for the life of the tab. Not only for
    // burnt parts: taking a part off is ordinary bench housekeeping.
    const drop = document.createElement("button");
    drop.type = "button";
    drop.className = "bench-off bench-remove";
    drop.textContent = "remove";
    drop.title = `Take ${part.label} off the bench`;
    drop.setAttribute("aria-label", drop.title);
    drop.addEventListener("click", () => {
      scene.removePart(index);
      renderBench();
    });
    head.append(drop);
    row.append(head);

    if (part.reason) {
      const why = document.createElement("p");
      // A destroyed part's reason IS the warning -- it names the limit that
      // killed it -- so it is red rather than the quiet grey every other
      // verdict gets. `circuit.js` clears `warning` in that case for the same
      // reason: one sentence, not the same fact twice.
      why.className = part.destroyed ? "bench-warn" : "bench-why";
      // The current comes first when there is one, because it is the number a
      // reader is here for and the rest of the sentence is why it is that.
      why.textContent = part.reason;
      row.append(why);
    }
    if (part.warning) {
      const warn = document.createElement("p");
      warn.className = "bench-warn";
      warn.textContent = part.warning;
      row.append(warn);
    }
    list.append(row);
  }

  if (!onBench.length) {
    $(BENCH_NOTE).textContent =
      "Drag from a pad to a part's terminal to wire it. A part needs a " +
      "complete circuit — both legs, and a path back — before it does " +
      "anything; nothing flows back into the chip.";
    return;
  }
  // **The circuit's own sentence wins over the counting one**, because it is
  // the one that says why nothing can be computed — no supply for this board,
  // a part with no published model, a short. A count is what to say when there
  // is nothing more interesting to say.
  if (solved?.note) {
    $(BENCH_NOTE).textContent = solved.note;
    return;
  }
  const loose = onBench.length - new Set(joined.map((w) => w.part)).size;
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

// **Startup lives in `fillBoardPicker` now, and this is why it moved.**
//
// OH-89 put an unconditional `reload()` here, because nothing asked the server
// anything on a fresh page: the panel sat on the static caption and the canvas
// sat at its 300 x 150 default. That was right, and OH-94 makes it redundant
// -- `emulator.js` now draws whenever the picker is filled or changed, which
// covers page load as well.
//
// **Redundant is not free here.** This call runs before `/api/boards` has come
// back, so the picker is still empty and it can only ask about no board in
// particular. With nothing loaded that is a 400 -- the correct refusal, and a
// second console error on every fresh page load beside the one the picker's
// own probe already makes. Two requests to learn one thing, one of which
// cannot succeed.
//
// So the single startup path is: `/api/boards` fills the picker, the picker
// asks once whether the server already has a board, and then it draws.
