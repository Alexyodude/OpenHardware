// OpenHardware — websocket client and render loop.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import {
  paint,
  paintBoardList,
  paintPalette,
  paintPins,
  paintWiring,
  paintWorkbench,
} from "/board.js";

const POLL_MS = 120;

const status = document.getElementById("status");
const log = document.getElementById("log");

let socket = null;
let nextId = 1;
const pending = new Map();
let catalogue = { parts: [] };

//: The 3D view and its ~2.1 MB of three.js are imported the first time it is
//: opened, not at page load. Someone who only wants the 2D board never pays
//: for the renderer.
let scene3d = null;
let view = "2d";

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
  } catch {
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
// a draw list covering the board and every placed peripheral, so this does not
// scale with the number of elements.
//
// A failed frame stops the loop and shows the failure. It never keeps painting
// the previous frame: a UI that shows a last-known-good board while the
// simulator is gone is claiming a simulator that is not there.

let looping = false;

const handlers = {
  onRegionClick: onPartRegionClick,
  onRemove: removePart,
  onWiring: showWiring,
};

async function frame() {
  if (!looping) return;
  try {
    const model = await call("render");
    if (view === "2d") {
      paint(model, onBoardRegionClick);
    } else if (scene3d) {
      scene3d.update(model);
    }
    paintWorkbench(model, handlers);

    document.getElementById("board-name").textContent = model.board;
    document.getElementById("board-mcu").textContent = model.processor;
    document.getElementById("board-clock").textContent = model.frequency;
    document.getElementById("board-note").textContent =
      model.unbound > 0
        ? `${model.regions.length} regions, ${model.unbound} not driven by this board`
        : `${model.regions.length} regions, all bound`;

    setStatus("live", "live");
    setTimeout(frame, POLL_MS);
  } catch (err) {
    looping = false;
    setStatus("down", "stopped");
    note(`render failed: ${err.message}`, true);
  }
}

// --- interactions -----------------------------------------------------------

async function onBoardRegionClick(region) {
  try {
    const current = await call("get_board_input", { index: region.index });
    await call("set_board_input", { index: region.index, value: current ? 0 : 1 });
    note(`${region.id}: wrote ${current ? 0 : 1}`);
  } catch (err) {
    note(`${region.id}: ${err.message}`, true);
  }
}

async function onPartRegionClick(part, region) {
  try {
    await call("set_part_input", {
      part: part.index,
      index: region.index,
      value: region.value ? 0 : 1,
    });
    note(`part[${part.index}] ${region.name}: wrote`);
  } catch (err) {
    note(`${region.id}: ${err.message}`, true);
  }
}

async function placePart(name) {
  try {
    await call("enable_spare_parts");
    const index = await call("place_part", { name, x: 120, y: 120 });
    note(`placed ${name} as part[${index}]`);
  } catch (err) {
    // 4a.1: placing a part whose assets are missing segfaults the simulator
    // rather than replying ERROR, so a dropped connection is a likely outcome.
    note(`could not place ${name}: ${err.message}`, true);
  }
}

async function removePart(part) {
  try {
    await call("remove_part", { index: part.index });
    note(`removed part[${part.index}]`);
  } catch (err) {
    note(`remove failed: ${err.message}`, true);
  }
}

async function showWiring(part) {
  try {
    const schema = await call("part_schema", { name: part.name });
    if (schema === null) {
      paintWiring(part.index, null, {}, () => {});
      note(`${part.name}: no schema`);
      return;
    }
    const wiring = await call("read_wiring", { index: part.index, name: part.name });
    paintWiring(part.index, schema, wiring, async (label, pin) => {
      try {
        await call("connect", {
          index: part.index,
          name: part.name,
          label,
          pin,
        });
        note(`${part.name}.${label} -> pin ${pin}`);
      } catch (err) {
        note(`${label}: ${err.message}`, true);
      }
    });
  } catch (err) {
    note(`wiring: ${err.message}`, true);
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

/**
 * Restart the simulator on another board.
 *
 * There is no rcontrol command that changes board -- the whole surface is in
 * `help` and none of it sets one -- so this restarts the process on that
 * board's workspace. The bridge refuses unless it was started with
 * --sim-command, and says so.
 */
async function switchBoard(board) {
  const name = board.art ?? board.name;
  try {
    note(`restarting the simulator on ${name}…`);
    looping = false;
    const result = await call("switch_board", { name });
    note(`now running ${result.board}`);
    if (scene3d) {
      scene3d.setPinMap(await call("pinmap"));
    }
    await loadCatalogue();
    looping = true;
    frame();
    refreshPins();
  } catch (err) {
    looping = true;
    frame();
    note(`could not switch to ${name}: ${err.message}`, true);
  }
}

async function loadCatalogue() {
  try {
    catalogue = await call("catalogue");
    paintPalette(catalogue, "", placePart);
    paintBoardList(await call("boards"), switchBoard);
  } catch (err) {
    note(`catalogue: ${err.message}`, true);
  }
}

// --- the 3D view ------------------------------------------------------------

/**
 * A wire dropped on a header pin.
 *
 * The scene never draws the connection itself — it calls this, and the wire
 * appears on the next frame only because `render` reported it. A picture of a
 * connection the simulator did not accept is exactly the
 * miswiring-reported-as-success failure this project has hit twice.
 */
async function onSceneConnect(anchor, pad) {
  try {
    await call("connect", {
      index: anchor.partIndex,
      name: anchor.partName,
      label: anchor.label,
      pin: pad.pin,
    });
    note(`${anchor.partName}.${anchor.label} → ${pad.label} (pin ${pad.pin})`);
  } catch (err) {
    note(`could not wire ${anchor.label} → ${pad.label}: ${err.message}`, true);
  }
}

/** Colour swatches for wires. Purely a viewing choice; never sent anywhere. */
function paintSwatches(palette) {
  const host = document.getElementById("swatches");
  if (!host || host.childElementCount) return;
  palette.forEach((hex, i) => {
    const swatch = document.createElement("button");
    swatch.type = "button";
    swatch.className = "swatch";
    swatch.style.background = `#${hex.toString(16).padStart(6, "0")}`;
    swatch.title = `wire colour ${i + 1}`;
    swatch.addEventListener("click", () => {
      for (const other of host.children) other.classList.remove("on");
      swatch.classList.add("on");
      scene3d?.setWireColour(hex);
    });
    host.append(swatch);
  });
}

/** Double-clicking a wired pin unwires it: `connect` with pin 0 disconnects. */
async function onSceneDisconnect(anchor) {
  try {
    await call("connect", {
      index: anchor.partIndex,
      name: anchor.partName,
      label: anchor.label,
      pin: 0,
    });
    note(`${anchor.partName}.${anchor.label} disconnected`);
  } catch (err) {
    note(`could not disconnect ${anchor.label}: ${err.message}`, true);
  }
}

async function showView(which) {
  view = which;
  document.getElementById("stage-2d").hidden = which !== "2d";
  document.getElementById("stage-3d").hidden = which !== "3d";
  document.getElementById("view-2d").classList.toggle("on", which === "2d");
  document.getElementById("view-3d").classList.toggle("on", which === "3d");

  if (which !== "3d" || scene3d) return;

  try {
    note("loading the 3D renderer…");
    const { Scene3D, JUMPER } = await import("/scene3d.js");
    scene3d = new Scene3D(document.getElementById("scene"), {
      onConnect: onSceneConnect,
      onDisconnect: onSceneDisconnect,
      onNote: (text) => note(text),
    });
    paintSwatches(JUMPER);
    const pinmap = await call("pinmap");
    scene3d.setPinMap(pinmap);
    if (!pinmap) {
      note("this board reports no pins, so there is nothing to wire", true);
    } else if (pinmap.derived) {
      note(
        `${pinmap.board}: ${pinmap.pads.length} pins laid out along the edge. ` +
          `Positions are schematic — no pad map is authored for this board — ` +
          `but wiring is by pin number, so a connection is exact.`,
      );
    } else {
      note(`${pinmap.board}: ${pinmap.pads.length} header pads, drag a pin onto one`);
    }
  } catch (err) {
    note(`3D view failed to start: ${err.message}`, true);
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
  document.getElementById("refresh-pins").addEventListener("click", refreshPins);
  document.getElementById("view-2d").addEventListener("click", () => showView("2d"));
  document.getElementById("view-3d").addEventListener("click", () => showView("3d"));
  document
    .getElementById("enable-spare")
    .addEventListener("click", send("enable_spare_parts"));
  document
    .getElementById("palette-filter")
    .addEventListener("input", (event) =>
      paintPalette(catalogue, event.target.value, placePart),
    );
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
    loadCatalogue();
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
