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
  const data = await api("/api/targets");
  TARGETS = data.targets;

  const select = $("target");
  select.replaceChildren(...TARGETS.map((target) => {
    const option = document.createElement("option");
    option.value = target.name;
    // The reason rides in the label rather than only in a colour, so it
    // survives being read aloud, printed, or looked at by someone who cannot
    // distinguish the two greens.
    //
    // It must be the reason it is *disabled*, not its status: `cortexm0 —
    // ready` beside a greyed-out option reads as a broken UI, because "ready"
    // is exactly what it is not.
    option.textContent = target.selectable
      ? target.name
      : `${target.name} — ${target.drivable === false && target.library
            ? "not drivable here" : target.status}`;
    option.disabled = !target.selectable;
    option.title = target.detail;
    return option;
  }));

  if (TARGETS.length === 0) {
    const option = document.createElement("option");
    option.textContent = "no cores built";
    option.disabled = true;
    select.replaceChildren(option);
  }
  if (data.selected) select.value = data.selected;
  select.disabled = TARGETS.filter((t) => t.selectable).length < 2;
  // Disabled, not hidden. With one core there is nothing to switch to, and a
  // control that disappears reads as a missing feature rather than as an
  // accurate report of a repository with one core in it.
  select.title = select.disabled
    ? "one runnable target; the selector opens when a second core is built"
    : "choose which core to drive";

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

async function selectTarget(name) {
  await api("/api/target", { name });
  await fillTargets();
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
  $("target").addEventListener("change", (event) =>
    selectTarget(event.target.value).catch(report));
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
