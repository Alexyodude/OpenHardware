// OpenHardware - the page's /api, answered inside the tab (OH-238).
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Loaded by the static build's index.html before emulator.js, and by nothing
// else: the page webui/emulator_server.py serves never loads it, and talks to
// that server exactly as before.
//
// ## Why fetch, and not emulator.js's api()
//
// emulator.js is not the only caller. board3d-panel.js and board3d.js fetch
// /api/board/state, /api/board/pins and /api/board/drive themselves, so the
// one place every request to the server passes through is window.fetch. This
// wraps it: a same-origin request whose path starts /api/ is posted to the
// Worker in inpage/worker.js, which answers it with the server's own Python
// (webui/inpage.py), and comes back as a real Response with the status and
// JSON the server would have sent. The callers cannot tell, which is the
// point -- only the transport changed.
//
// A same-origin path outside the folder the site is served from goes to that
// folder (OH-240, below); everything else goes to the network exactly as asked.

"use strict";

(() => {
  // The folder this page was served from, which is where the site's files are.
  const site = new URL("./", document.baseURI);
  const worker = new Worker(new URL("inpage/worker.js", site), { type: "module" });

  const waiting = new Map();
  let nextId = 1;
  // Why the runtime could not start, once it is known it could not.
  let failed = null;
  let settleReady;
  const ready = new Promise((resolve) => { settleReady = resolve; });

  /** One line of progress, where the page has room for it (OH-239). */
  function say(text) {
    const status = document.getElementById("inpage-status");
    if (status) status.textContent = text;
  }

  worker.addEventListener("message", ({ data }) => {
    if (data.type === "progress") {
      say(data.text);
    } else if (data.type === "ready") {
      say(data.text);
      settleReady();
    } else if (data.type === "failed") {
      failed = data.error;
      say(`The in-browser runtime did not start: ${data.error}`);
      settleReady();
    } else if (data.type === "answer") {
      const settle = waiting.get(data.id);
      waiting.delete(data.id);
      settle(data);
    }
  });
  // A worker that fails to LOAD -- its file missing, a syntax error -- posts
  // nothing and raises this instead; without it every request would wait on
  // `ready` forever.
  worker.addEventListener("error", (event) => {
    failed = event.message || "inpage/worker.js could not be loaded";
    say(`The in-browser runtime did not start: ${failed}`);
    settleReady();
  });

  function reply(status, body) {
    return new Response(body, {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }

  async function answerHere(url, verb, body) {
    await ready;
    if (failed !== null) {
      return reply(503, JSON.stringify({
        error: `the in-browser runtime did not start: ${failed}`,
      }));
    }
    const id = nextId++;
    const answered = await new Promise((settle) => {
      waiting.set(id, settle);
      worker.postMessage({
        type: "request", id, verb, target: url.pathname + url.search, body,
      });
    });
    return reply(answered.status, answered.body);
  }

  const nativeFetch = window.fetch.bind(window);

  window.fetch = async (input, init = {}) => {
    const request = input instanceof Request ? input : null;
    const url = new URL(request ? request.url : String(input), location.href);
    if (url.origin === location.origin && url.pathname.startsWith("/api/")) {
      const verb = (init.method || request?.method || "GET").toUpperCase();
      const body = init.body !== undefined ? String(init.body)
        : request ? await request.text() : "";
      return answerHere(url, verb, body);
    }
    // The page's scripts fetch their own files from the server's root --
    // board3d.js asks for /models/index.json -- which is where the local
    // server keeps them. This site may be served from a folder instead, as
    // GitHub Pages serves it at /OpenHardware/, whose root is another site's
    // (OH-240). So a same-origin path outside the folder is the folder's file.
    // Served from a root, every path is inside it and nothing moves.
    if (url.origin === location.origin && !url.pathname.startsWith(site.pathname)) {
      const moved = new URL(`.${url.pathname}${url.search}`, site);
      return nativeFetch(request ? new Request(moved, request) : moved, init);
    }
    return nativeFetch(input, init);
  };
})();
