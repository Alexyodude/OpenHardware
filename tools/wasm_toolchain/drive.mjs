// OpenHardware - the driver's work, done by hand, at bundle time (OH-244).
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
//   node tools/wasm_toolchain/drive.mjs JOB.json      -> result JSON on stdout
//
// tools/build_compiler.py writes the job and reads the result. Two kinds of
// work, both through the WebAssembly avr-g++ / avr-gcc:
//
//   expand   run the driver with -### over an argv and return the commands it
//            would have run, each in full. plan.json's cc1plus, as and ld
//            lines are these, verbatim but for two stand-ins.
//   compile  the same, then RUN those commands with the WebAssembly cc1, cc1plus
//            and as, carrying each file one writes to the next, and keep the
//            object. The core and library objects the page links are these.
//
// ## Why the driver cannot simply be run
//
// It runs its sub-programs with vfork and exec, and a WebAssembly instance
// has neither. -### is the driver saying what it would exec, one command per
// line; this executes them, which is all the driver does with them. Each
// program is matched by its basename: cc1, cc1plus, as. (A link is only ever
// expanded here, never run: the page runs it.)
//
// Every tool sees the job's whole filesystem tree at /, the way a native tool
// sees the disk: headers, libraries, the sources being compiled.

import { readFile, writeFile, readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { run } from "../../webui/static/compiler/build.js";

async function loadTool(spec) {
  const create = (await import(pathToFileURL(spec.glue).href)).default;
  const module = await WebAssembly.compile(await readFile(spec.wasm));
  return { create, module, program: spec.program };
}

/** Every file under `root`, as [path under /, bytes]. */
async function tree(root, under = "") {
  const out = [];
  for (const entry of await readdir(join(root, under), { withFileTypes: true })) {
    const relative = `${under}/${entry.name}`;
    if (entry.isDirectory()) out.push(...await tree(root, relative));
    else out.push([relative, await readFile(join(root, relative))]);
  }
  return out;
}

/**
 * The commands in a `-###` listing: each line that starts with a space, one
 * word per space. gcc.c quotes a word only when it holds something other than
 * [A-Za-z0-9_/.-] -- `"-mn-flash=1"` beside a bare `-quiet` -- and escapes a
 * quote, backslash or dollar inside one with a backslash. Every other line
 * (COLLECT_GCC_OPTIONS=, Target:, the version) starts with a letter.
 */
export function commands(listing) {
  const out = [];
  for (const line of listing.split("\n")) {
    if (!line.startsWith(" ")) continue;
    const words = [...line.matchAll(/ (?:"((?:[^"\\]|\\.)*)"|([^ "]+))/g)]
      .map((m) => (m[1] === undefined ? m[2] : m[1].replace(/\\(.)/g, "$1")));
    out.push(words);
  }
  return out;
}

const basename = (path) => path.slice(path.lastIndexOf("/") + 1);

async function expand(tools, files, driver, argv, extra) {
  const done = await run(tools[driver], ["-###", ...argv], [...files, ...extra]);
  if (done.status !== 0) {
    throw new Error(`${driver} -### ${argv.join(" ")} exited ${done.status}:\n${done.stderr}`);
  }
  return commands(done.stderr);
}

/** The tool key for each program the driver names, and the argv it is given. */
function step(programs, command) {
  const name = basename(command[0]);
  const key = programs[name];
  if (key === undefined) throw new Error(`the driver ran ${name}, which this runner has no tool for: ${command.join(" ")}`);
  return { key, argv: command.slice(1) };
}

async function compile(tools, files, programs, job) {
  const listed = await expand(tools, files, job.driver, job.argv, []);
  const carried = new Map();
  const ran = [];
  for (const command of listed) {
    const { key, argv } = step(programs, command);
    const done = await run(tools[key], argv, [...files, ...carried]);
    ran.push([key, ...argv]);
    if (done.status !== 0) {
      throw new Error(`${key} ${argv.join(" ")} exited ${done.status}:\n${done.stderr}`);
    }
    const output = argv[argv.indexOf("-o") + 1];
    const path = output.startsWith("/") ? output : `/build/${output}`;
    carried.set(path, done.fs.readFile(path));
  }
  const object = carried.get(job.object);
  if (object === undefined) throw new Error(`nothing wrote ${job.object}: ${JSON.stringify(ran)}`);
  await writeFile(job.host, object);
  return ran;
}

async function main() {
  const job = JSON.parse(await readFile(process.argv[2], "utf8"));
  const tools = {};
  for (const [key, spec] of Object.entries(job.tools)) tools[key] = await loadTool(spec);
  const files = await tree(job.fs);
  const result = { expanded: {}, compiled: {} };
  for (const [name, want] of Object.entries(job.expand)) {
    const extra = want.placeholders.map((path) => [path, new Uint8Array()]);
    result.expanded[name] = await expand(tools, files, want.driver, want.argv, extra);
  }
  for (const [name, want] of Object.entries(job.compile)) {
    result.compiled[name] = await compile(tools, files, job.programs, want);
  }
  await writeFile(job.result, JSON.stringify(result, null, 1));
}

// Emscripten's node exit handler sets process.exitCode to each tool's status,
// so the runner's own outcome is stated explicitly, last.
main().then(() => process.exit(0), (error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
