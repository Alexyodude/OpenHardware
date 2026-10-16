// OpenHardware - Build and run, compiled in this tab (OH-244).
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Loaded by the static build's index.html after inpage/transport.js and before
// emulator.js, and by nothing else: the local server's page compiles on the
// server, exactly as before.
//
// ## What it answers
//
// /api/board/compile. The server builds and loads in one route; this builds
// in compiler/worker.js and then loads through the route transport.js already
// answers, /api/board/load, with the image and the recipe's base -- so the
// board is replaced exactly as the server's compile route replaces it, and
// only by a build that succeeded: a failed one returns before the load and the
// board keeps what it had. The reply is the server's, field for field:
// {ok, bytes, diagnostics, command, board}, or its 400 {error} for a build
// that cannot be attempted.
//
// /api/boards. The in-page runtime has no compiler and answers buildable:
// false for every board; this sets it for the boards compiler/boards.json says
// the bundle builds -- none, on a page served over plain http from another
// machine (see `insecure`). Nothing else in the list changes.
//
// And the Build button's reason. emulator.js titles a board it cannot build
// "no compile recipe"; for a board the SERVER builds and this copy does not,
// that is not the reason, so this says what is: build it with the local server.
//
// Nothing is fetched for the compiler until Build is pressed but the board
// list, which is a few hundred bytes. compiler/worker.js says what then.

"use strict";

(() => {
  const site = new URL("./", document.baseURI);
  const here = new URL("compiler/", site);
  // transport.js's fetch, which this wraps as it wraps the browser's.
  const upstream = window.fetch.bind(window);

  let compiler = null;
  // Each build asked and not yet answered, by id: {settle, tool, timer}.
  const waiting = new Map();
  let nextId = 1;
  // compiler/boards.json, once asked for; and once answered.
  let listing = null;
  let listed = null;
  // A browser gives a page served over plain http from anywhere but this
  // machine neither crypto.subtle, which checks each compiler file against
  // manifest.json, nor Cache Storage, which keeps them. Such a page builds
  // nothing, and every board says why, rather than failing in the compiler.
  const insecure = window.isSecureContext ? null :
    "building in this tab needs the page served over https or from localhost, " +
    `and this one is ${location.origin}`;

  function reply(status, body) {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }

  /** The line beside the Build button. */
  function say(text) {
    const line = document.getElementById("sketch-report");
    if (line) line.textContent = text;
  }

  // Asked once, failure and all: emulator.js asks for the board list once a
  // page, so a second try would have nobody to answer; a reload asks again.
  function boardsHere() {
    listing ??= upstream(new URL("boards.json", here)).then(async (response) => {
      if (!response.ok) throw new Error(`compiler/boards.json answered HTTP ${response.status}`);
      const bundle = await response.json();
      listed = insecure === null ? bundle : {
        buildable: [],
        refused: { ...bundle.refused,
                   ...Object.fromEntries(bundle.buildable.map((board) => [board, insecure])) },
      };
      return listed;
    });
    return listing;
  }

  /** The Worker gone, and every build it held answered with `answer(id)`. */
  function stopCompiler(answer) {
    compiler.terminate();
    compiler = null;
    for (const [id, build] of waiting) {
      clearTimeout(build.timer);
      build.settle(answer(id));
    }
    waiting.clear();
  }

  /**
   * compile.build's budget (`BUILD_BUDGET_SECONDS`), kept from the moment the
   * first tool starts -- fetching the compiler is not building -- and kept by
   * stopping the Worker, since a tool running in it cannot be interrupted from
   * inside. Answered as the server answers it: a failed build, in its words.
   */
  function startBudget(id, seconds) {
    waiting.get(id).timer = setTimeout(() => {
      const late = waiting.get(id);
      stopCompiler((other) => (other === id
        ? { type: "built", ok: false, image: new Uint8Array(), command: [late.tool],
            diagnostics: `the build ran out of its ${seconds} s budget while running ${late.tool}` }
        : { type: "failed", error: "the compiler was stopped when the build before this one " +
            "ran out of its time budget; press Build again" }));
    }, seconds * 1000);
  }

  function compilerWorker() {
    if (compiler === null) {
      const worker = new Worker(new URL("worker.js", here), { type: "module" });
      compiler = worker;
      worker.addEventListener("message", ({ data }) => {
        // From a Worker already stopped, or about a build already answered:
        // nothing left to tell.
        if (worker !== compiler) return;
        if (data.type === "progress") {
          say(data.text);
          return;
        }
        const build = waiting.get(data.id);
        if (build === undefined) return;
        if (data.type === "running") {
          if (build.tool === null) startBudget(data.id, data.budget_seconds);
          build.tool = data.tool;
          return;
        }
        clearTimeout(build.timer);
        waiting.delete(data.id);
        build.settle(data);
        // A compiler that failed keeps nothing worth keeping -- the manifest
        // it holds may be the one a redeploy replaced -- so the next press
        // starts a new one. Stopping it also stops the fetches still running
        // after one failed, whose progress would replace the error shown.
        if (data.type === "failed") {
          stopCompiler(() => ({ type: "failed", error: "the compiler was restarted after the " +
                                "build before this one failed; press Build again" }));
        }
      });
      // A worker that fails to LOAD, or throws outside a build, posts nothing
      // and raises this instead; without it the build would wait forever. The
      // next press starts a new one.
      worker.addEventListener("error", (event) => {
        if (worker !== compiler) return;
        const error = event.message || "compiler/worker.js could not be loaded";
        stopCompiler(() => ({ type: "failed", error }));
      });
    }
    return compiler;
  }

  function ask(board, source) {
    return new Promise((settle) => {
      const id = nextId++;
      waiting.set(id, { settle, tool: null, timer: undefined });
      compilerWorker().postMessage({ type: "build", id, board, source });
    });
  }

  function base64(bytes) {
    let text = "";
    for (let at = 0; at < bytes.length; at += 0x8000) {
      text += String.fromCharCode(...bytes.subarray(at, at + 0x8000));
    }
    return btoa(text);
  }

  /** /api/board/compile: emulator_server's route, built here. */
  async function compileHere(body) {
    let payload;
    try {
      payload = JSON.parse(body || "{}");
    } catch (error) {
      return reply(400, { error: `body is not JSON: ${error.message}` });
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return reply(400, { error: "body must be a JSON object" });
    }
    // emulator_server.prepare_compile's two refusals, in its words.
    const { board, source } = payload;
    if (typeof board !== "string") {
      return reply(400, { error: "board must be a string naming a board from /api/boards" });
    }
    if (typeof source !== "string") {
      return reply(400, { error: "source must be a string holding the sketch" });
    }
    const answer = await ask(board, source);
    if (answer.type === "refused") return reply(400, { error: answer.error });
    if (answer.type === "failed") {
      return reply(503, { error: `the compiler in this tab failed: ${answer.error}` });
    }
    const built = {
      ok: answer.ok, bytes: answer.image.length,
      diagnostics: answer.diagnostics, command: answer.command,
    };
    if (!answer.ok) return reply(200, built);
    const loaded = await upstream("/api/board/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board, image: base64(answer.image), base: answer.base }),
    });
    // The load's own refusal, as the server's compile route would raise it.
    if (!loaded.ok) return loaded;
    return reply(200, { ...built, board: await loaded.json() });
  }

  /** /api/boards, with `buildable` saying what THIS copy can build. */
  async function boardsWithCompiler(input, init) {
    const response = await upstream(input, init);
    if (!response.ok) return response;
    let bundle;
    try {
      bundle = await boardsHere();
    } catch (error) {
      // No compiler in this copy: the list is right as the runtime answered
      // it, every Build off, and the reason goes where a developer looks.
      console.error(`OpenHardware: no compiler in this copy, so no board builds: ${error.message}`);
      return response;
    }
    const data = await response.json();
    const buildable = new Set(bundle.buildable);
    return reply(response.status, {
      ...data,
      boards: data.boards.map((board) => ({ ...board, buildable: buildable.has(board.name) })),
    });
  }

  window.fetch = async (input, init = {}) => {
    const request = input instanceof Request ? input : null;
    const url = new URL(request ? request.url : String(input), location.href);
    if (url.origin === location.origin) {
      const verb = (init.method || request?.method || "GET").toUpperCase();
      // Any other verb goes on, to be refused as the server refuses it.
      if (url.pathname === "/api/board/compile" && verb === "POST") {
        const body = init.body !== undefined ? String(init.body)
          : request ? await request.text() : "";
        return compileHere(body);
      }
      if (url.pathname === "/api/boards" && verb === "GET") {
        return boardsWithCompiler(input, init);
      }
    }
    return upstream(input, init);
  };

  // --- the Build button -------------------------------------------------------

  /** What the line beside the button says for a board, before anything is built. */
  function sayFor(board) {
    if (listed === null) return;
    if (refusal(board) !== null) say(refusal(board));
    else if (listed.buildable.includes(board)) {
      say("Builds in this tab. The first build fetches the compiler, once.");
    } else {
      // Neither: no compiler here or on the server, which the button's own
      // title says; what the line said for the last board is not true of this.
      say("");
    }
  }

  /** compiler/boards.json's reason this copy does not build `board`, or null. */
  function refusal(board) {
    return Object.hasOwn(listed.refused, board) ? listed.refused[board] : null;
  }

  function watch(picker, button) {
    // emulator.js reflects a board's buildability when the picker CHANGES and
    // not when it is first filled, which is why the page ships the button
    // disabled. This does the first one, from the same list.
    new MutationObserver(() => {
      if (listed === null || !picker.value) return;
      const can = listed.buildable.includes(picker.value);
      button.disabled = !can;
      button.title = can ? "" : refusal(picker.value) ??
        `no compile recipe for ${picker.value}'s chip, here or on the server`;
      sayFor(picker.value);
    }).observe(picker, { childList: true });
    // And after emulator.js's own reflection, the reason that is true here.
    new MutationObserver(() => {
      const reason = listed === null ? null : refusal(picker.value);
      if (reason !== null && button.title !== reason) button.title = reason;
    }).observe(button, { attributes: true, attributeFilter: ["title"] });
    picker.addEventListener("change", () => sayFor(picker.value));
  }

  function start() {
    const picker = document.getElementById("board-pick");
    const button = document.getElementById("sketch-build");
    if (picker === null || button === null) {
      throw new Error("inpage/compile.js found no #board-pick or #sketch-build on this page");
    }
    watch(picker, button);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
