// OpenHardware - the i8086 emulator UI.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Talks to webui/emulator_server.py on its own origin. Every decision about
// what an instruction does lives in the C core; this file decides only what
// the screen shows.
//
// The one piece of state kept here rather than asked for is `previous`, the
// last register snapshot -- because "which registers just changed" is a fact
// about two instants and the server only ever describes one.

"use strict";

const $ = (id) => document.getElementById(id);

// --- sample programs ---------------------------------------------------------
//
// Fetched from the server, never held here. They used to be a hex string in
// this file, which made them the one part of the emulator no test could
// reach: a sample that stopped working would have shipped as a broken
// demonstration with nothing to say so. They now live in webui/emulator.py
// and the suite runs every one of them to the end.

let SAMPLES = [];

// --- talking to the server ---------------------------------------------------

async function api(path, body) {
  const options = body === undefined
    ? {}
    : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `${response.status}`);
  }
  return data;
}

// --- formatting ---------------------------------------------------------------

const hex = (value, width) => value.toString(16).toUpperCase().padStart(width, "0");

/** Address the user typed, in hex, or null. Accepts `0200`, `0x200`, `200`. */
function parseAddress(text) {
  const cleaned = text.trim().replace(/^0x/i, "");
  if (!/^[0-9a-f]{1,5}$/i.test(cleaned)) return null;
  return parseInt(cleaned, 16) & 0xfffff;
}

// --- rendering ----------------------------------------------------------------

const REGISTER_ORDER = [
  "ax", "bx", "cx", "dx",
  "si", "di", "bp", "sp",
  "cs", "ds", "es", "ss",
  "ip", "flags",
];

let previous = null;

function renderRegisters(registers) {
  const host = $("registers");
  host.replaceChildren(...REGISTER_ORDER.map((name) => {
    const cell = document.createElement("div");
    cell.className = "reg";
    if (previous && previous[name] !== registers[name]) cell.classList.add("moved");
    const label = document.createElement("span");
    label.className = "name";
    label.textContent = name;
    const value = document.createElement("span");
    value.className = "value";
    value.textContent = hex(registers[name], 4);
    cell.append(label, value);
    return cell;
  }));
}

function renderFlags(flags) {
  const host = $("flags");
  host.replaceChildren(...Object.entries(flags).map(([name, on]) => {
    const chip = document.createElement("span");
    chip.className = "flag";
    chip.dataset.on = String(on);
    chip.textContent = name;
    chip.title = `${name} is ${on ? "set" : "clear"}`;
    return chip;
  }));
}

function renderListing(lines) {
  const host = $("listing");
  host.replaceChildren(...lines.map((line) => {
    const row = document.createElement("div");
    row.className = "row" + (line.current ? " current" : "");
    const addr = document.createElement("span");
    addr.className = "addr";
    addr.textContent = `${hex(line.cs, 4)}:${hex(line.ip, 4)}`;
    const raw = document.createElement("span");
    raw.className = "raw";
    raw.textContent = line.bytes;
    const text = document.createElement("span");
    text.textContent = line.text;
    row.append(addr, raw, text);
    return row;
  }));
}

/** One `<span>` of a given class, as a node rather than as markup. */
function span(className, text) {
  const node = document.createElement("span");
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

/** Sixteen bytes per line, hex then printable text -- the shape every
 *  debugger has used since these machines were new, because it is the one
 *  that lets an eye find a string without reading the numbers.
 *
 *  **Built as DOM nodes, never as an HTML string.** This pane displays a
 *  megabyte of memory that a loaded program can write anything into, so it is
 *  the one place in this UI where the content is genuinely untrusted. An
 *  earlier version assembled markup and escaped `<` and `&` by hand, which is
 *  the approach that works until the day it misses a character. `textContent`
 *  cannot miss one. */
function renderMemory(memory) {
  const bytes = memory.bytes;
  const dump = $("hexdump");
  const lines = [];
  for (let offset = 0; offset < bytes.length; offset += 16) {
    const slice = bytes.slice(offset, offset + 16);
    const line = document.createDocumentFragment();
    line.append(span("addr", hex(memory.address + offset, 5)), "  ");

    slice.forEach((byte, column) => {
      if (column) line.append(" ");
      // Zero bytes are dimmed rather than hidden: a page of 00 is a fact
      // about the program, and blanking it would look like missing data.
      line.append(byte === 0 ? span("zero", "00") : span("", hex(byte, 2)));
    });

    const printable = slice
      .map((b) => (b >= 0x20 && b < 0x7f ? String.fromCharCode(b) : "."))
      .join("");
    line.append("  ", span("text", printable), "\n");
    lines.push(line);
  }
  dump.replaceChildren(...lines);
}

function renderStatus(state) {
  const status = $("status");
  status.dataset.state = state.status;
  status.textContent = state.status;
  $("counter").textContent = `${state.steps.toLocaleString()} steps`;
  $("detail").textContent = state.detail || "";
  $("where").textContent =
    `${hex(state.registers.cs, 4)}:${hex(state.registers.ip, 4)}`;

  const stopped = state.status !== "running";
  $("step").disabled = stopped;
  $("run").disabled = stopped || running;
  $("stop").disabled = !running;
}

// --- the loop -----------------------------------------------------------------

let running = false;
let watching = 0x0200;

async function refresh(rememberPrevious = true) {
  const state = await api(`/api/state?at=${watching}&len=256`);
  renderRegisters(state.registers);
  renderFlags(state.flags);
  renderListing(state.disassembly);
  renderMemory(state.memory);
  renderStatus(state);
  if (rememberPrevious) previous = state.registers;
  return state;
}

async function stepOnce() {
  previous = (await api("/api/state?at=0&len=1")).registers;
  await api("/api/step", {});
  await refresh(false);
}

/** Run in bounded bursts, redrawing between them.
 *
 *  Not one long request: a program with a loop that never exits would hold
 *  the connection open for as long as it ran, and there would be no moment
 *  at which the Stop button could be noticed. */
async function runContinuously() {
  running = true;
  previous = null;
  try {
    for (;;) {
      const result = await api("/api/run", { steps: 20000 });
      const state = await refresh(false);
      if (!running || state.status !== "running" || result.steps === 0) break;
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
  } finally {
    running = false;
    await refresh();
  }
}

// --- targets ------------------------------------------------------------------
//
// The selector and the "Runnable now" panel are both built from /api/targets,
// which reads `core/` and `build/lib/` on every request. Nothing about which
// targets exist is written down in this file, for the same reason the board
// list is generated rather than maintained: a hand-kept list of what works is
// wrong the moment someone adds a core or deletes a build, and wrong silently.

let TARGETS = [];

async function fillTargets() {
  // Fetched for the "Runnable now" table in the Targets view, and for nothing
  // else. It used to fill a core selector in the toolbar too; that selector
  // was removed on 2026-08-25 because with one drivable core it disabled
  // itself, and a disabled dropdown naming `core/` directories is not what
  // someone means when they go looking for their MCU. The table says the same
  // thing with room for the reason. `#board-pick` is the machine selector.
  const data = await api("/api/targets");
  TARGETS = data.targets;
  renderRunnable();
}

function renderRunnable() {
  const drivable = TARGETS.filter((t) => t.selectable).length;
  const built = TARGETS.filter((t) => t.library).length;
  $("runnable-strip").replaceChildren(
    stripCell(String(drivable), "drivable here", drivable > 0 ? "is-ok" : "is-stop"),
    stripCell(String(built), "cores built", "is-ok"),
    stripCell(String(TARGETS.length - built), "present but unbuilt",
              TARGETS.length - built > 0 ? "is-warn" : ""),
    stripCell(String(TARGETS.length), "cores in core/", ""),
  );

  $("runnable-rows").replaceChildren(...TARGETS.map((target) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.className = "chip";
    name.textContent = target.name;
    const status = document.createElement("td");
    // Three states, not two. A core that is built but not drivable is not
    // the same as one that was never compiled, and collapsing them would put
    // "UNBUILT" beside a library that is sitting on disk.
    const label = target.selectable
      ? "DRIVABLE"
      : (target.drivable === false && target.library ? "BUILT" : target.status.toUpperCase());
    const pill = span(target.selectable ? "pill p-ok" : "pill p-warn", label);
    status.append(pill);
    const detail = document.createElement("td");
    detail.className = "note-cell";
    detail.textContent = target.detail;
    row.append(name, status, detail);
    return row;
  }));
}

function stripCell(number, key, extra) {
  const cell = document.createElement("div");
  cell.className = extra ? `cell ${extra}` : "cell";
  cell.append(span("n", number), span("k", key));
  return cell;
}

// --- boards -------------------------------------------------------------------
//
// Rendered from /api/boards, which computes every field. Nothing about which
// board works is written in this file, for the same reason the board list and
// the target list are generated: a hand-kept claim about what works is wrong
// the moment someone builds or deletes a core, and wrong silently.

async function fillBoards() {
  const data = await api("/api/boards");
  const proven = data.boards.filter((b) => b.firmware_verified).length;
  const runnable = data.boards.filter((b) => b.runnable).length;

  // The evidence sentence, derived rather than written. The paragraph this
  // replaces was hand-kept prose reading "only one board has actually been
  // watched", and it went false the day a second one was. Naming the chips and
  // their tests from the data means it cannot say a number the table disagrees
  // with -- and phrasing it as a list rather than a count is what makes zero,
  // one and many all read correctly without a special case.
  const watched = data.boards.filter((b) => b.firmware_verified);
  const evidence = [...new Map(
    watched.map((b) => [b.chip, b.firmware_evidence]),
  ).entries()];
  $("boards-evidence").textContent = evidence.length
    ? "Watched running compiled code: " +
      evidence.map(([chip, test]) => `${chip} (${test})`).join(", ") + "."
    : "No board here has yet been watched running compiled code.";

  $("boards-strip").replaceChildren(
    stripCell(String(proven), "watched running firmware", proven ? "is-ok" : "is-stop"),
    stripCell(String(runnable), "core and board exist", runnable ? "is-ok" : ""),
    stripCell(String(data.boards.length - runnable), "not yet", "is-warn"),
    stripCell(String(data.boards.length), "boards imported", ""),
  );

  $("boards-rows").replaceChildren(...data.boards.map((board) => {
    const row = document.createElement("tr");
    if (!board.runnable) row.className = "dim";
    const name = document.createElement("td");
    name.className = "chip";
    name.textContent = board.name;
    const chip = document.createElement("td");
    chip.textContent = board.chip;
    const isa = document.createElement("td");
    isa.className = "isa";
    isa.textContent = board.isa;
    const core = document.createElement("td");
    core.className = "isa";
    core.textContent = board.core;
    const status = document.createElement("td");
    status.append(span(...boardStatus(board)));
    row.append(name, chip, isa, core, status);
    return row;
  }));

  $("boards-waiting").replaceChildren(...data.waiting.map((group) => {
    const row = document.createElement("tr");
    const core = document.createElement("td");
    core.className = "isa";
    core.textContent = group.core;
    const count = document.createElement("td");
    count.textContent = String(group.boards.length);
    const need = document.createElement("td");
    // A core that already exists is a different job from one that does not:
    // those boards need a description, not an instruction set.
    need.append(span(group.exists ? "pill p-warn" : "pill p-none",
                     group.exists ? "BOARD DESCRIPTION" : "A CORE"));
    const oracle = document.createElement("td");
    oracle.className = "note-cell";
    oracle.textContent = group.oracle;
    row.append(core, count, need, oracle);
    return row;
  }));

  // Filled from the same response rather than a second request. Two fetches
  // of /api/boards could disagree -- a core built between them is not
  // hypothetical, it happened twice in one afternoon -- and then the table
  // would explain options the selector did not offer.
  fillBoardPicker(data.boards);
}

/** The board selector, offering only what can be picked.
 *
 *  A board that is not runnable appears `disabled` carrying its reason, which
 *  is the same choice the target selector in the toolbar makes. Hiding them
 *  would leave someone hunting for a board that is right there in the table
 *  below; offering them would accept a click that cannot be honoured. */
function fillBoardPicker(boards) {
  const select = $("board-pick");
  const ordered = [...boards].sort((a, b) =>
    Number(b.runnable) - Number(a.runnable) || a.name.localeCompare(b.name));
  select.replaceChildren(...ordered.map((board) => {
    const option = document.createElement("option");
    option.value = board.name;
    option.disabled = !board.runnable;
    // The reason comes from boardStatus, so the word beside a board here is
    // the word beside it in the table below. Two spellings of one fact is how
    // a UI starts contradicting itself.
    option.textContent = board.runnable
      ? board.name
      : `${board.name} — ${boardStatus(board)[1].toLowerCase()}`;
    return option;
  }));
  const first = ordered.find((board) => board.runnable);
  if (first) select.value = first.name;
}

/** Which of the three facts is missing, said as the reason it is not runnable.
 *
 *  A single "not runnable" would hide the difference between a chip nobody has
 *  written a core for and one whose core exists but has no memory map -- and
 *  those are days apart in effort. */
function boardStatus(board) {
  // RUNS FIRMWARE is reserved for boards where a real image has actually been
  // watched executing. Everything else says what exists, which is a claim
  // about the repository rather than about the board -- the paragraph above
  // this table used to be honest about that while this badge was not.
  if (board.firmware_verified) return ["pill p-ok", "RUNS FIRMWARE"];
  if (board.runnable) return ["pill p-warn", "CORE + BOARD, UNPROVEN"];
  if (!board.core_exists) return ["pill p-none", "NO CORE"];
  if (!board.core_built) return ["pill p-warn", "CORE UNBUILT"];
  return ["pill p-warn", "NO BOARD DESCRIPTION"];
}

// --- running an image on a board ----------------------------------------------
//
// The three routes OH-32 built, driven from the page. Everything about whether
// an image belongs on a chip, where its vector table is and what the board
// refuses lives behind them; this decides only what is shown.
//
// Nothing here decides whether a board can run anything. `board.runnable` is
// computed by webui/boards/catalogue.py from what is on disk, and an option is
// offered or disabled on that alone -- the same rule the target selector in
// the toolbar follows, and for the same reason.

/** How far Run steps. Instant at this size, and enough for the UART sample to
 *  reach the end of its string. Shown in the report rather than hidden, since
 *  a program that has not finished has not finished for a reason.
 *
 *  Pressing Run again continues from where it stopped, and the console keeps
 *  growing, because /api/board/state reports everything transmitted since the
 *  image was loaded rather than what is new since the last poll. */
const BOARD_STEPS = 200000;

/** The last successful load, or null. Enables Run and names what is on. */
let boardImage = null;

/** Base64 of a File, without the `data:` prefix the reader puts in front. */
function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`could not read ${file.name}`));
    reader.onload = () => {
      const text = String(reader.result);
      const comma = text.indexOf(",");
      resolve(comma < 0 ? text : text.slice(comma + 1));
    };
    reader.readAsDataURL(file);
  });
}

/** Say what happened, or what went wrong. Never both at once.
 *
 *  `.detail` is the page's error styling, so it carries refusals only and is
 *  emptied on success -- a stale red line under a working load reads as a
 *  failure that already happened. */
function boardSays(report, error) {
  $("board-report").textContent = report;
  $("board-error").textContent = error || "";
}

async function loadBoardImage() {
  const board = $("board-pick").value;
  const file = $("board-file").files[0];
  if (!board) {
    boardSays("Nothing loaded yet.", "Pick a board first.");
    return;
  }
  if (!file) {
    boardSays("Nothing loaded yet.", "Choose a compiled image first.");
    return;
  }

  const request = { board, image: await fileAsBase64(file) };
  const base = $("board-base").value.trim();
  // Sent only when given. An empty string is not an address, and passing one
  // would turn "you did not say" into "you said nothing", which the server
  // would have to guess about -- the thing it exists not to do.
  if (base) request.base = base;

  boardImage = null;
  $("board-go").disabled = true;
  try {
    boardImage = await api("/api/board/load", request);
  } catch (error) {
    $("board-console").textContent = "";
    boardSays("Nothing loaded yet.", error.message);
    return;
  }

  $("board-go").disabled = false;
  $("board-console").textContent = "";
  $("board-console-note").textContent = "nothing transmitted yet";
  // Draw the machine at its reset vector straight away. Without this the
  // registers, listing and hexdump keep showing whatever was there before --
  // an i8086, or the previous board -- which reads as this board's state
  // rather than as a stale pane.
  previousBoard = null;
  renderBoardState(await api("/api/board/state"));
  const notes = boardImage.notes.length ? ` — ${boardImage.notes.join("; ")}` : "";
  boardSays(
    `${file.name}: ${boardImage.bytes} bytes of ${boardImage.format} on ` +
    `${boardImage.board}, a ${boardImage.chip} on the ${boardImage.core} core. ` +
    `Entered at 0x${boardImage.entry.toString(16).padStart(8, "0")}${notes}`,
    "",
  );
}

/** The sketch a person sees before they type anything.
 *
 *  A real Blink and not a stub, because the first thing anybody does is press
 *  the button -- and a page whose default sketch does nothing teaches nothing
 *  about whether the machine works. */
const DEFAULT_SKETCH = [
  "void setup() {",
  "  pinMode(13, OUTPUT);",
  "}",
  "",
  "void loop() {",
  "  digitalWrite(13, HIGH);",
  "  delay(500);",
  "  digitalWrite(13, LOW);",
  "  delay(500);",
  "}",
  "",
].join("\n");

/** `sketch.cpp:LINE:COL: message`, which is how gcc names a place.
 *
 *  Anchored at the start of a line so a path appearing mid-message cannot be
 *  mistaken for a location. */
const DIAGNOSTIC_AT = /^sketch\.cpp:(\d+):(\d+):/gm;

/** Render the compiler's output with the offending source line beside it.
 *
 *  **The page quotes the line, not the compiler.** `webui/compile.py` prepends
 *  `#line 1` so the numbers match what the person typed, and the cost of that
 *  is gcc dropping its own quoted source and caret -- it can no longer map the
 *  reported line back to a physical one to read. So the quote comes from the
 *  textarea, which is better than gcc's copy anyway: it is the text in front
 *  of the reader, and it stays right if they scroll.
 *
 *  A message with no `sketch.cpp:N:` in it is shown as-is. That is what a
 *  linker error looks like, and inventing a line for it would be a guess. */
function renderDiagnostics(text, source) {
  const lines = source.split("\n");
  const pane = $("sketch-errors");
  pane.textContent = "";
  pane.hidden = false;

  let last = 0;
  for (const match of text.matchAll(DIAGNOSTIC_AT)) {
    const [whole, lineText, columnText] = match;
    const line = Number(lineText);
    const column = Number(columnText);
    // Everything since the previous match, which is the message body of the
    // diagnostic before this one.
    pane.append(text.slice(last, match.index));
    last = match.index + whole.length;

    const anchor = document.createElement("span");
    anchor.className = "diagnostic-at";
    anchor.textContent = whole;
    // Clicking a location puts the cursor on it. This is the whole of
    // "renders against its line number" as a person experiences it.
    anchor.tabIndex = 0;
    const jump = () => focusSourceLine(line, column);
    anchor.addEventListener("click", jump);
    anchor.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); jump(); }
    });
    pane.append(anchor);

    const quoted = lines[line - 1];
    if (quoted !== undefined) {
      const shown = document.createElement("span");
      shown.className = "diagnostic-source";
      // The caret is built from the column, so a tab in the source would move
      // it. Tabs are rendered as-is above, so the two stay in step.
      shown.textContent = `\n    ${quoted}\n    ${" ".repeat(Math.max(0, column - 1))}^`;
      pane.append(shown);
    }
  }
  pane.append(text.slice(last));
}

/** Put the cursor on one line and column of the sketch, and show it. */
function focusSourceLine(line, column) {
  const box = $("sketch-source");
  const lines = box.value.split("\n");
  let offset = 0;
  for (let i = 0; i < line - 1 && i < lines.length; i += 1) offset += lines[i].length + 1;
  const at = offset + Math.max(0, column - 1);
  box.focus();
  box.setSelectionRange(at, at);
  // A textarea does not scroll to the selection on its own when it already
  // has focus, so nudge it: the line height times the line, less a third of
  // the box, puts the line about a third of the way down rather than at the
  // very top where it is easy to miss.
  const lineHeight = box.scrollHeight / Math.max(1, lines.length);
  box.scrollTop = Math.max(0, (line - 1) * lineHeight - box.clientHeight / 3);
}

/** Build the sketch on the server, load it, and leave it ready to run.
 *
 *  **Stop, load, enter -- in that order, and the order is the point.** A
 *  free-running machine whose flash is replaced underneath it executes a
 *  program that is half the old one, which is the hazard
 *  `webui/boards/atmega328p.py`'s `install` docstring records from the other
 *  side. `running = false` stops the loop; the server's compile route replaces
 *  the board only on a build that succeeded, so a syntax error costs nobody
 *  the program that was already there. */
async function buildSketch() {
  const board = $("board-pick").value;
  const source = $("sketch-source").value;
  const button = $("sketch-build");
  if (!board) {
    $("sketch-report").textContent = "Pick a board above first.";
    return;
  }

  running = false;
  // Disabled for the whole round trip. A build takes a second or two, and two
  // compilers racing for one temporary directory is the failure a second press
  // would buy.
  button.disabled = true;
  const wasLabel = button.textContent;
  button.textContent = "Building…";
  $("sketch-report").textContent = `Building for ${board}…`;
  $("sketch-errors").hidden = true;

  try {
    const built = await api("/api/board/compile", { board, source });
    if (!built.ok) {
      $("sketch-report").textContent = "Did not compile. The board is unchanged.";
      renderDiagnostics(built.diagnostics, source);
      return;
    }
    boardImage = built.board;
    $("board-go").disabled = false;
    $("board-console").textContent = "";
    $("board-console-note").textContent = "nothing transmitted yet";
    previousBoard = null;
    renderBoardState(await api("/api/board/state"));
    $("sketch-report").textContent =
      `${built.bytes} bytes on ${boardImage.board}, entered at ` +
      `0x${boardImage.entry.toString(16).padStart(8, "0")}. Press Run.`;
    boardSays(
      `Built from the sketch: ${built.bytes} bytes of ${boardImage.format} on ` +
      `${boardImage.board}, a ${boardImage.chip} on the ${boardImage.core} core.`,
      "",
    );
  } finally {
    // In `finally` so a thrown request -- an unknown board, a missing
    // toolchain -- does not leave the button dead for the rest of the session.
    button.disabled = false;
    button.textContent = wasLabel;
  }
}

async function runLoadedBoard() {
  if (!boardImage) {
    boardSays("Nothing loaded yet.", "Load an image before running it.");
    return;
  }
  let result;
  try {
    result = await api("/api/board/run", { steps: BOARD_STEPS });
  } catch (error) {
    boardSays($("board-report").textContent, error.message);
    return;
  }

  const state = await api("/api/board/state");
  renderBoardConsole(state.uart);
  renderBoardState(state);
  const stopped = result.status === "stopped"
    ? ` and stopped: ${result.detail}`
    : "";
  // `$("where")` was set by `renderBoardState` just above, from the machine's
  // own pc register and at that register's width. Read back rather than
  // recomputed: this line indexed the register array at position 15 and so
  // rendered `pc 0x[object Object]` the moment the wire carried named
  // registers -- a second place that had to know the register file's shape
  // and did not need to.
  boardSays(
    `${boardImage.board}: ${result.steps.toLocaleString()} instructions` +
    `${stopped}. pc 0x${$("where").textContent}`,
    result.status === "stopped" ? result.detail : "",
  );
}

/** The previous board register snapshot, keyed by name, for the "changed"
 *  highlight. Separate from `previous` so switching between the i8086 and a
 *  board does not mark every register as moved, and keyed by name rather than
 *  by index so switching between two *boards* does not either -- an Arm r13 and
 *  an AVR r13 are both at index 13 and are not the same register. */
let previousBoard = null;

/** Registers, as the machine that has them names them.
 *
 *  **This used to be an Arm table hard-coded here**, sixteen names and a fixed
 *  eight hex digits, with a comment arguing that a generic renderer would be
 *  the parameterise-instead-of-split move the house rules warn about. That
 *  argument was right about the i8086, which arrives keyed by name and carries
 *  segments, and it is still rendered separately below. It was wrong about
 *  *boards*, and the Arduino Uno is what showed it: an AVR has thirty-two
 *  eight-bit registers plus SP and PC, so the Arm table would have printed
 *  sixteen wrong names and shown r0 as `0x000000A5`.
 *
 *  So the wire carries `{name, value, width}` and this renders what it is
 *  given. There is no branch on machine here and no table -- adding a core does
 *  not touch this function. `core/<core>/machine.py`'s `view()` is what
 *  decides, which is the only place that knows. */
function renderBoardRegisters(registers) {
  $("registers").replaceChildren(...registers.map((register) => {
    const cell = document.createElement("div");
    cell.className = "reg";
    const was = previousBoard ? previousBoard[register.name] : undefined;
    if (was !== undefined && was !== register.value) {
      cell.classList.add("moved");
    }
    const label = document.createElement("span");
    label.className = "name";
    label.textContent = register.name;
    const value = document.createElement("span");
    value.className = "value";
    // Digits from the register's own width: 32 bits is eight, an AVR's eight
    // is two. Padding a byte to eight digits is not a cosmetic problem -- it
    // states a width the machine does not have.
    value.textContent = hex(register.value, register.width / 4);
    cell.append(label, value);
    return cell;
  }));
}

/** The flags this machine models, and only those.
 *
 *  Named on the wire rather than decoded from a status word here, because
 *  there is no status word two of these machines share: Armv6-M has four flags
 *  in the top of APSR and an AVR has eight in SREG, numbered from the bottom.
 *  `core/<core>/machine.py` reports `[{name, on}]` and this renders it. */
function renderBoardFlags(flags) {
  $("flags").replaceChildren(...flags.map(({ name, on }) => {
    const chip = document.createElement("span");
    chip.className = "flag";
    chip.dataset.on = String(on);
    chip.textContent = name;
    chip.title = `${name} is ${on ? "set" : "clear"}`;
    return chip;
  }));
}

/** The instructions around the program counter, or why there are none.
 *
 *  **An empty listing is not the same as a core that cannot disassemble**, and
 *  that is why `listing.present` is on the wire — the same distinction
 *  `uart.present` draws. `riscv32` is built and has no disassembler today, so
 *  this is a live case: the board still steps and its registers still read,
 *  and saying so beats an empty pane that reads as "no code here". */
function renderBoardListing(listing) {
  const host = $("listing");
  if (!listing.present) {
    const note = document.createElement("div");
    note.className = "row";
    note.style.color = "var(--muted)";
    note.style.whiteSpace = "pre-wrap";
    note.textContent = listing.note;
    host.replaceChildren(note);
    return;
  }
  host.replaceChildren(...listing.lines.map((line) => {
    const row = document.createElement("div");
    row.className = "row" + (line.current ? " current" : "");
    const addr = document.createElement("span");
    addr.className = "addr";
    addr.textContent = hex(line.address, 8);
    const raw = document.createElement("span");
    raw.className = "raw";
    raw.textContent = line.raw;
    const text = document.createElement("span");
    text.textContent = line.text;
    row.append(addr, raw, text);
    return row;
  }));
}

/** Registers, flags, listing and memory for a loaded board.
 *
 *  Memory goes through the i8086's `renderMemory` with one key renamed rather
 *  than a copy of it: a hexdump is a hexdump, and the two panes differ only in
 *  what the server calls the base address. Registers and flags do not get that
 *  treatment, because the i8086 session's own state arrives keyed by name and
 *  carries segments, while a board's arrives as an ordered list a machine
 *  module composed -- the same picture on screen, from two different shapes on
 *  the wire. */
function renderBoardState(state) {
  renderBoardRegisters(state.registers);
  renderBoardFlags(state.flags);
  renderBoardListing(state.listing);
  renderMemory({ address: state.memory.at, bytes: state.memory.bytes });
  // Found by name rather than at position 15, which is the program counter on
  // Armv6-M and an ordinary working register on an AVR. Every machine's view carries a register
  // called `pc` -- `test_every_machine_view_carries_a_register_called_pc` is
  // what makes that safe to rely on rather than a hope, and the width comes
  // from the same entry so an AVR's word-counting PC prints as four digits.
  const pc = state.registers.find((register) => register.name === "pc");
  $("where").textContent = hex(pc.value, pc.width / 4);
  previousBoard = Object.fromEntries(
    state.registers.map((register) => [register.name, register.value]),
  );
}

/** What the board printed, or why there is nothing to print.
 *
 *  **An empty console is not the same as a board that cannot print**, and this
 *  is the whole reason `uart.present` is on the wire. A board whose
 *  description models no UART says so in the console itself, because an empty
 *  black box is read as "it ran and printed nothing" -- a claim about the
 *  program, when the truth is a gap in the board description.
 *
 *  `textContent` throughout: the bytes came off an emulated wire and anything
 *  in them is data. Firmware that prints `<script>` prints those characters. */
function renderBoardConsole(uart) {
  const pane = $("board-console");
  const note = $("board-console-note");
  if (!uart.present) {
    pane.textContent = uart.note;
    // Muted inline rather than by class: emulator.css styles `.hexdump .text`
    // as a *descendant*, so putting that class on the <pre> itself matches
    // nothing. A class that looks like styling and does none is worse than no
    // class, because the next reader believes it.
    pane.style.color = "var(--muted)";
    pane.style.whiteSpace = "pre-wrap";
    note.textContent = "no UART in this board description";
    return;
  }

  pane.style.color = "";
  pane.style.whiteSpace = "";
  pane.textContent = uart.text;
  const parts = [`${uart.bytes} bytes`];
  // Both are counts the server computed, and both change what the text means.
  // Escapes shown without saying they are escapes read as output the program
  // produced; a truncated console with nothing said reads as a program that
  // stopped printing.
  if (uart.undecodable_bytes) {
    parts.push(`${uart.undecodable_bytes} not valid UTF-8, shown escaped`);
  }
  if (uart.dropped_bytes) {
    parts.push(`${uart.dropped_bytes} older bytes dropped`);
  }
  if (!uart.bytes) parts[0] = "nothing transmitted yet";
  note.textContent = parts.join(", ");
}

// --- wiring -------------------------------------------------------------------

async function fillSamples() {
  SAMPLES = (await api("/api/samples")).samples;
  const select = $("sample");
  select.replaceChildren(...SAMPLES.map((sample, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = sample.name;
    option.title = sample.listing.join("\n");
    return option;
  }));
}

async function loadSelected() {
  const sample = SAMPLES[Number($("sample").value)];
  // No origin: the server decides, and it puts programs clear of the
  // interrupt vector table. Naming one here overrode that -- and did it
  // with the very address the server had just been corrected away from.
  await api("/api/load", { hex: sample.hex });
  watching = sample.watch;
  $("at").value = hex(watching, 4);
  previous = null;
  await refresh();
}

function applyTheme(next) {
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("oh-theme", next); } catch { /* private mode */ }
}

function startingTheme() {
  try {
    const saved = localStorage.getItem("oh-theme");
    if (saved) return saved;
  } catch { /* private mode */ }
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark" : "light";
}

/** Switch between the emulator and the targets list.
 *
 *  The view is one attribute on `<body>`; the CSS does the rest, so there is
 *  no second place that can disagree about which is showing. Switching does
 *  NOT stop a run in progress — it is a change of what you are looking at,
 *  not of what the processor is doing, and stopping on a tab click would
 *  throw away a long run for no reason. */
function showView(name) {
  document.body.dataset.view = name;
  for (const view of ["emulator", "targets"]) {
    $(`tab-${view}`).setAttribute("aria-selected", String(view === name));
  }
}

function wire() {
  $("tab-emulator").addEventListener("click", () => showView("emulator"));
  $("tab-targets").addEventListener("click", () => showView("targets"));

  $("step").addEventListener("click", () => stepOnce().catch(report));
  $("run").addEventListener("click", () => runContinuously().catch(report));
  $("stop").addEventListener("click", () => { running = false; });
  $("reset").addEventListener("click", async () => {
    running = false;
    await api("/api/reset", {});
    previous = null;
    await refresh();
  });
  $("load").addEventListener("click", () => loadSelected().catch(report));
  // These report into their own panel, not through `report`, which writes to
  // the disassembly panel's detail line -- invisible from the view this
  // control lives in.
  $("board-load").addEventListener("click", () =>
    loadBoardImage().catch((error) => boardSays("Nothing loaded yet.", String(error.message || error))));
  $("board-go").addEventListener("click", () =>
    runLoadedBoard().catch((error) => boardSays($("board-report").textContent, String(error.message || error))));
  $("sketch-source").value = DEFAULT_SKETCH;
  $("sketch-build").addEventListener("click", () =>
    buildSketch().catch((error) => {
      // A refusal the server made before compiling -- an unknown board, or a
      // toolchain it does not have. It is not a diagnostic, so it goes in the
      // report line rather than the errors pane, which is for gcc's words.
      $("sketch-report").textContent = String(error.message || error);
    }));
  $("theme").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
  $("at").addEventListener("change", () => {
    const parsed = parseAddress($("at").value);
    if (parsed === null) {
      $("memnote").textContent = "not an address";
      return;
    }
    $("memnote").textContent = "";
    watching = parsed;
    refresh(false).catch(report);
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
    // The step and run keys are for the emulator. Firing them while the
    // targets list is showing would advance a processor the reader cannot see.
    if (document.body.dataset.view !== "emulator") return;
    if (event.key === "F10" || event.key === "s") { event.preventDefault(); stepOnce().catch(report); }
    if (event.key === "F5" || event.key === "r") { event.preventDefault(); runContinuously().catch(report); }
    if (event.key === "Escape") running = false;
  });
}

function report(error) {
  $("detail").textContent = String(error.message || error);
}

applyTheme(startingTheme());
wire();
// Targets first, and on its own chain: the samples are an i8086 thing, but
// which targets exist is true whether or not a sample ever loads. Chaining
// them would leave the selector empty whenever a sample failed.
fillTargets().catch(report);
fillBoards().catch(report);
fillSamples().then(loadSelected).catch(report);
