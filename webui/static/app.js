// OpenHardware — websocket client and render loop.
//
// This program is free software; you can redistribute it and/or modify it under
// the terms of the GNU General Public License as published by the Free Software
// Foundation; either version 2, or (at your option) any later version.

import { paint, paintParts, paintPins, paintRegionTable } from "/board.js";

const POLL_MS = 120;

const status = document.getElementById("status");
const log = document.getElementById("log");

let socket = null;
let nextId = 1;
const pending = new Map();

function setStatus(state, text) {
  status.dataset.state = state;
  status.textContent = text;
}

function note(text, isError = false) {
  log.textContent = text;
  log.className = isError ? "err" : "";
}

/**
 * Send one operation and resolve with its result.
 *
 * The bridge replies with the request id it was given, so replies are matched
 * rather than assumed to arrive in order. The bridge already serialises
 * commands to the simulator, but that is its guarantee to keep, not ours to
 * depend on.
 */
function call(op, args = {}) {
  return new Promise((resolve, reject) => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      reject(new Error("not connected"));
      return;
    }
    const id = nextId++;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, op, args }));
  });
}

function onMessage(event) {
  let payload;
  try {
    payload = JSON.parse(event.data);
  } catch (err) {
    note(`unparseable reply: ${event.data}`, true);
    return;
  }
  const waiter = pending.get(payload.id);
  if (!waiter) return;
  pending.delete(payload.id);
  if (payload.ok) waiter.resolve(payload.result);
  else waiter.reject(new Error(payload.error));
}

// --- the render loop --------------------------------------------------------
//
// One `render` call per frame. The server turns a single `info` round trip into
// a draw list, so this does not scale with the number of elements on the board.
//
// A failed frame stops the loop and shows the failure. It never keeps painting
// the previous frame: a UI that shows a last-known-good board while the
// simulator is gone is claiming a simulator that is not there.

let looping = false;

async function frame() {
  if (!looping) return;
  try {
    const model = await call("render");
    paint(model, onRegionClick);
    paintRegionTable(model);
    paintParts(model, onPartInput);

    document.getElementById("board-name").textContent = model.board;
    document.getElementById("board-mcu").textContent = model.processor;
    document.getElementById("board-clock").textContent = model.frequency;

    const note_ = document.getElementById("board-note");
    note_.textContent =
      model.unbound > 0
        ? `${model.regions.length} regions from board.map; ` +
          `${model.unbound} not reported by this board and drawn dashed.`
        : `${model.regions.length} regions, all bound.`;

    setStatus("live", "live");
    setTimeout(frame, POLL_MS);
  } catch (err) {
    looping = false;
    setStatus("down", "stopped");
    note(`render failed: ${err.message}`, true);
  }
}

// --- interactions -----------------------------------------------------------

async function onRegionClick(region) {
  try {
    const current = await call("get_board_input", { index: region.index });
    await call("set_board_input", {
      index: region.index,
      value: current ? 0 : 1,
    });
    note(`${region.id}: wrote ${current ? 0 : 1}`);
  } catch (err) {
    note(`${region.id}: ${err.message}`, true);
  }
}

async function onPartInput(part, input) {
  try {
    await call("set_part_input", {
      part: part.index,
      index: input.index,
      value: input.value ? 0 : 1,
    });
    note(`part[${part.index}].in[${input.index}] ${input.name}: wrote`);
  } catch (err) {
    note(`${input.name}: ${err.message}`, true);
  }
}

async function refreshPins() {
  try {
    paintPins(await call("pins"));
    note("pins refreshed");
  } catch (err) {
    note(`pins: ${err.message}`, true);
  }
}

function wireControls() {
  const send = (op) => async () => {
    try {
      await call(op);
      note(`${op} ok`);
    } catch (err) {
      note(`${op}: ${err.message}`, true);
    }
  };
  document.getElementById("run").addEventListener("click", send("run"));
  document.getElementById("pause").addEventListener("click", send("pause"));
  document.getElementById("reset").addEventListener("click", send("reset"));
  document
    .getElementById("refresh-pins")
    .addEventListener("click", refreshPins);
}

// --- connection -------------------------------------------------------------

function connect() {
  setStatus("connecting", "connecting…");
  socket = new WebSocket(`ws://${location.host}/`);

  socket.addEventListener("open", () => {
    setStatus("live", "live");
    note(`connected to ${location.host}`);
    looping = true;
    frame();
    refreshPins();
  });

  socket.addEventListener("message", onMessage);

  socket.addEventListener("close", () => {
    looping = false;
    setStatus("down", "disconnected");
    note("bridge closed the connection", true);
    for (const { reject } of pending.values()) {
      reject(new Error("connection closed"));
    }
    pending.clear();
  });

  socket.addEventListener("error", () => {
    setStatus("down", "error");
    note("websocket error — is the bridge running?", true);
  });
}

wireControls();
connect();
