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

function wire() {
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
fillSamples().then(loadSelected).catch(report);
