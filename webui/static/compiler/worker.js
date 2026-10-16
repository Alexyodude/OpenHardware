// OpenHardware - the compiler, in a Worker, in this tab (OH-244).
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// inpage/compile.js starts this the first time Build is pressed, and posts it
// {type: "build", id, board, source}. It answers each with one of
//
//   {type: "built", id, ok, image, diagnostics, command, base}
//   {type: "refused", id, error}      what compile.build raises CompileError for
//   {type: "failed", id, error}       the compiler itself failed, or could not be had
//
// and, along the way, {type: "progress", text} while it fetches and
// {type: "running", id, tool, budget_seconds} as each tool starts, which is
// what compile.js keeps the server's time budget by: a tool running here
// cannot be interrupted from inside, so it is the page that stops the Worker.
//
// ## What it fetches, and when
//
// Nothing until the first build. Then manifest.json, which names every file a
// chip's build reads with its size and sha256, plan.json, which must be the
// plan.json manifest.json names, and those files -- the tools' WebAssembly,
// the headers, the libraries, the core already compiled -- from this site's
// compiler/ folder and nowhere else. Each is checked against its sha256 and
// kept in Cache Storage under the manifest's version, and checked again each
// time it is read back, so a second visit fetches nothing, a rebuilt bundle (a
// new version) replaces the old one rather than mixing with it, and nothing
// another page of the same origin put there is run.
//
// ## Why a Worker
//
// cc1plus is an 11 MB module that runs for a good fraction of a second on a
// one-line sketch; on the page's thread that is a frozen page, and Chrome
// refuses to compile a module that size there synchronously anyway.

import { build, checkFormat, refusal, Refused } from "./build.js";

const HERE = new URL("./", import.meta.url);
// One origin can carry more than one copy of the site -- a GitHub Pages
// account serves every project from one -- so the folder is in the name, and
// one copy's rebuild does not delete another's compiler.
const CACHE_PREFIX = `openhardware-compiler:${HERE.pathname}@`;

/** One sentence of progress, for the line beside the Build button. */
function say(text) {
  postMessage({ type: "progress", text });
}

function megabytes(bytes) {
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

async function sha256(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function fetchBytes(path) {
  const response = await fetch(new URL(path, HERE), { cache: "no-cache" });
  if (!response.ok) throw new Error(`compiler/${path} answered HTTP ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
}

/** Whether `bytes` are the file manifest.json says `path` is; and if not, why not. */
async function mismatch(manifest, path, bytes) {
  const [size, digest] = manifest.files[path];
  const actual = await sha256(bytes);
  if (bytes.length === size && actual === digest) return null;
  return `expected ${size} bytes with sha256 ${digest}, got ${bytes.length} with ${actual}`;
}

/**
 * Cache Storage, or null where the browser refuses it: storage blocked for
 * the site, or a private window that has the API and rejects every call. A
 * page with none at all -- one not served over https or from localhost -- has
 * no crypto.subtle either, and inpage/compile.js builds nothing there.
 */
async function openCache(manifest) {
  try {
    const cache = await caches.open(`${CACHE_PREFIX}${manifest.version}`);
    // A bundle that has been rebuilt leaves its predecessor's files behind;
    // they are no use to this one and are tens of megabytes.
    for (const name of await caches.keys()) {
      if (name.startsWith(CACHE_PREFIX) && name !== `${CACHE_PREFIX}${manifest.version}`) {
        await caches.delete(name);
      }
    }
    return cache;
  } catch (error) {
    // The build goes on from memory; keeping the compiler is an economy.
    console.warn(`OpenHardware compiler: Cache Storage refused (${error.name}: ${error.message}), ` +
                 "so the compiler is fetched again on every visit");
    return null;
  }
}

/** The bytes Cache Storage holds for `url`, or null: none, or a lookup that failed. */
async function lookup(cache, url) {
  if (cache === null) return null;
  try {
    const found = await cache.match(url);
    return found === undefined ? null : new Uint8Array(await found.arrayBuffer());
  } catch (error) {
    // A miss: the file is fetched as though it had never been kept.
    console.warn(`OpenHardware compiler: Cache Storage did not answer for ${url.pathname} ` +
                 `(${error.name}: ${error.message}); fetching it`);
    return null;
  }
}

/** What Cache Storage holds for `paths` that is still what the manifest says. */
async function kept(cache, manifest, paths, out) {
  const wanted = [];
  for (const path of paths) {
    const bytes = await lookup(cache, new URL(path, HERE));
    if (bytes === null) {
      wanted.push(path);
      continue;
    }
    const wrong = await mismatch(manifest, path, bytes);
    if (wrong === null) {
      out.set(path, bytes);
      continue;
    }
    // Fetched again; keep() puts the fetched copy in its place, if Cache
    // Storage takes it, and if not this one is checked and refused again.
    console.warn(`OpenHardware compiler: the cached compiler/${path} is not the file ` +
                 `manifest.json names (${wrong}); fetching it again`);
    wanted.push(path);
  }
  return wanted;
}

async function keep(cache, url, bytes) {
  if (cache === null) return;
  try {
    await cache.put(url, new Response(bytes));
  } catch (error) {
    // Full, or refusing: the build goes on from memory, and the next visit
    // fetches the file again.
    console.warn(`OpenHardware compiler: Cache Storage did not keep ${url.pathname} ` +
                 `(${error.name}: ${error.message})`);
  }
}

/**
 * Every file `paths` names, as bytes by path: from Cache Storage where an
 * earlier visit kept it, else fetched, checked, and kept.
 */
async function files(manifest, paths) {
  const cache = await openCache(manifest);
  const out = new Map();
  const wanted = await kept(cache, manifest, paths, out);
  const total = wanted.reduce((sum, path) => sum + manifest.files[path][0], 0);
  let fetched = 0;
  const started = performance.now();
  // Six at a time: what a browser opens to one origin anyway.
  // The first failure answers the build "failed", and the page then stops
  // this Worker, the other five fetches with it.
  const queue = [...wanted];
  async function worker() {
    for (let path = queue.shift(); path !== undefined; path = queue.shift()) {
      const bytes = await fetchBytes(path);
      const wrong = await mismatch(manifest, path, bytes);
      if (wrong !== null) throw new Error(`compiler/${path}: ${wrong}`);
      await keep(cache, new URL(path, HERE), bytes);
      out.set(path, bytes);
      fetched += bytes.length;
      say(`Fetching the compiler, once: ${megabytes(fetched)} of ${megabytes(total)}…`);
    }
  }
  await Promise.all(Array.from({ length: 6 }, worker));
  return { out, fetched, ms: performance.now() - started };
}

/** A tool's glue, imported from its bytes, and its module compiled once. */
async function tool(spec, bytes) {
  const glue = URL.createObjectURL(new Blob([bytes.get(spec.glue)], { type: "text/javascript" }));
  try {
    const create = (await import(glue)).default;
    const module = await WebAssembly.compile(bytes.get(spec.wasm));
    return { create, module, program: spec.program };
  } finally {
    URL.revokeObjectURL(glue);
  }
}

/**
 * manifest.json and plan.json, once -- and plan.json only if it is the one
 * manifest.json names: a host that serves one build's manifest beside
 * another's plan would otherwise check every file against the first and run
 * the second's commands.
 *
 * Kept for the Worker's life, failures with the rest: the page stops a
 * Worker that answers "failed" and starts a new one on the next press, so
 * what a failed fetch leaves here is never asked again.
 */
let bundleOnce = null;

function bundle() {
  if (bundleOnce === null) {
    bundleOnce = (async () => {
      const manifest = JSON.parse(new TextDecoder().decode(await fetchBytes("manifest.json")));
      checkFormat("manifest.json", manifest.format);
      const bytes = await fetchBytes("plan.json");
      const wrong = await mismatch(manifest, "plan.json", bytes);
      if (wrong !== null) {
        throw new Error(`compiler/plan.json is not the one manifest.json (version ` +
                        `${manifest.version}) names: ${wrong}. They are from different builds.`);
      }
      const plan = JSON.parse(new TextDecoder().decode(bytes));
      checkFormat("plan.json", plan.format);
      return { manifest, plan };
    })();
  }
  return bundleOnce;
}

/** Per chip, once: {tools, read}. Kept for the Worker's life, as bundle() is. */
const loaded = new Map();

function forChip(manifest, plan, chip) {
  if (!loaded.has(chip)) {
    loaded.set(chip, (async () => {
      const paths = manifest.chips[chip];
      if (paths === undefined) throw new Error(`manifest.json lists no files for ${chip}`);
      say("Fetching the compiler, once…");
      const { out, fetched, ms } = await files(manifest, paths);
      say("Starting the compiler…");
      const tools = {};
      for (const [key, spec] of Object.entries(plan.chips[chip].tools)) {
        tools[key] = await tool(spec, out);
      }
      const total = paths.reduce((sum, path) => sum + manifest.files[path][0], 0);
      // The first build's cost, which the owner asked to be told.
      console.info(fetched > 0
        ? `OpenHardware compiler for ${chip}: fetched ${megabytes(fetched)} in ` +
          `${(ms / 1000).toFixed(1)} s and kept it`
        : `OpenHardware compiler for ${chip}: ${megabytes(total)}, all from Cache Storage`);
      const read = async (path) => {
        const bytes = out.get(path);
        if (bytes === undefined) throw new Error(`the ${chip} build read ${path}, which manifest.json does not list`);
        return bytes;
      };
      return { tools, read };
    })());
  }
  return loaded.get(chip);
}

async function answer({ id, board, source }) {
  const { manifest, plan } = await bundle();
  // Before the chip's files: a build that cannot be attempted fetches nothing.
  const refused = refusal(plan, board, source);
  if (refused !== null) {
    postMessage({ type: "refused", id, error: refused });
    return;
  }
  const chip = plan.boards[board];
  const here = await forChip(manifest, plan, chip);
  const started = performance.now();
  try {
    const done = await build({
      plan, board, source,
      files: here.read,
      tools: here.tools,
      step: (name) => postMessage({ type: "running", id, tool: name,
                                    budget_seconds: plan.budget_seconds }),
    });
    console.info(`OpenHardware compiler: ${board} built in ` +
                 `${((performance.now() - started) / 1000).toFixed(2)} s`);
    postMessage({ type: "built", id, ok: done.ok, image: done.image, diagnostics: done.diagnostics,
                  command: done.command, base: plan.chips[chip].base }, [done.image.buffer]);
  } catch (error) {
    if (!(error instanceof Refused)) throw error;
    postMessage({ type: "refused", id, error: error.message });
  }
}

// One build at a time, in the order asked: each runs several tools in turn,
// and two interleaved would share nothing but would double the memory.
let queue = Promise.resolve();
onmessage = ({ data }) => {
  if (data.type !== "build") return;
  queue = queue.then(() => answer(data)).catch((error) => {
    console.error(error);
    postMessage({ type: "failed", id: data.id, error: String(error.message || error) });
  });
};
