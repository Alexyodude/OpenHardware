// OpenHardware - the server's Python, running in a Worker (OH-238).
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// inpage/transport.js posts every /api request here; this answers it with
// webui/inpage.py, which calls webui/emulator_server.py's routes unchanged.
//
// ## What it loads, all from this site
//
//   pyodide/            CPython 3.14 compiled to WebAssembly (Pyodide), the
//                       runtime files tools/build_site.py vendors
//   openhardware.zip    the Python the page runs, and build/lib/lib<core>.so:
//                       each core in core/ compiled to a wasm side module,
//                       which core/<core>/abi.py loads through ctypes exactly
//                       as it loads the .dll or .so on a desktop
//
// Nothing is fetched from anywhere else. Pyodide is told where its files are
// (indexURL) and asked for no packages, so it has no reason to reach a CDN.
//
// ## Why a Worker
//
// ctypes.CDLL compiles a side module synchronously, which Chrome refuses on
// the main thread for anything but a tiny module, and a run of twenty thousand
// steps would freeze the page if it shared the page's thread.

// `.mjs.js`, not `.mjs`: tools/build_site.py's PYODIDE_RUNTIME says why.
import { loadPyodide } from "../pyodide/pyodide.mjs.js";
import createPyodideModule from "../pyodide/pyodide.asm.mjs.js";

const SITE = new URL("../", import.meta.url);
// Where the bundle is unpacked. `tools/build_core.py` finds the cores under
// <this>/build/lib because REPO is this file's grandparent there too.
const HOME = "/home/pyodide/openhardware";

let page = null;

async function boot() {
  postMessage({ type: "progress", text: "Starting Python in your browser…" });
  const pyodide = await loadPyodide({
    indexURL: new URL("pyodide/", SITE).href,
    createPyodideModule,
  });
  postMessage({ type: "progress", text: "Unpacking OpenHardware…" });
  const response = await fetch(new URL("openhardware.zip", SITE));
  if (!response.ok) {
    throw new Error(`openhardware.zip answered HTTP ${response.status}`);
  }
  pyodide.unpackArchive(await response.arrayBuffer(), "zip", { extractDir: HOME });
  pyodide.runPython(`import sys; sys.path.insert(0, ${JSON.stringify(HOME)})`);
  postMessage({ type: "progress", text: "Loading the cores…" });
  page = pyodide.pyimport("webui.inpage").InPage();
}

boot().then(
  () => postMessage({
    type: "ready",
    text: "Ready: nothing you load leaves this tab.",
  }),
  (error) => postMessage({ type: "failed", error: String(error) }),
);

/** The last line of a Python traceback, which is the one that names it. */
function lastLine(error) {
  const lines = String(error).trim().split("\n");
  return lines[lines.length - 1];
}

onmessage = ({ data }) => {
  if (data.type !== "request") return;
  if (page === null) {
    // transport.js waits for `ready` before posting, so this is a bug there.
    postMessage({
      type: "answer", id: data.id, status: 503,
      body: JSON.stringify({ error: "a request arrived before the runtime started" }),
    });
    return;
  }
  try {
    const answered = page.answer(data.verb, data.target, data.body);
    const [status, body] = answered.toJs();
    answered.destroy();
    postMessage({ type: "answer", id: data.id, status, body });
  } catch (error) {
    // A Python exception InPage does not map is a defect, as an uncaught one
    // in the server's handler is. The whole traceback goes to the console;
    // the page gets a 500 naming its last line, rather than a request that
    // never settles.
    console.error(error);
    postMessage({
      type: "answer", id: data.id, status: 500,
      body: JSON.stringify({ error: `the in-browser server failed: ${lastLine(error)}` }),
    });
  }
};
