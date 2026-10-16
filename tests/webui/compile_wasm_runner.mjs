// OpenHardware - the page's compiler, under node, for a test (OH-244).
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
//   node tests/webui/compile_wasm_runner.mjs JOB.json
//
// JOB is {bundle, builds: [{board, source}], result}. Each build runs
// webui/static/compiler/build.js -- the module the page's Worker runs --
// over a bundle tools/build_compiler.py made, and the results land in
// `result` as [{ok, image (base64), diagnostics, command, ms} | {refused}],
// in order. tests/webui/test_compile_wasm.py compares them with what
// webui/compile.py builds from the same sources.
//
// Each tool's WebAssembly is compiled once and instantiated per run, as the
// Worker does.

import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { build, Refused } from "../../webui/static/compiler/build.js";

async function main() {
  const job = JSON.parse(await readFile(process.argv[2], "utf8"));
  const plan = JSON.parse(await readFile(join(job.bundle, "plan.json"), "utf8"));
  const files = async (path) => new Uint8Array(await readFile(join(job.bundle, path)));
  const compiled = new Map();
  async function toolsFor(chip) {
    if (!compiled.has(chip)) {
      const tools = {};
      for (const [key, spec] of Object.entries(plan.chips[chip].tools)) {
        tools[key] = {
          create: (await import(pathToFileURL(join(job.bundle, spec.glue)).href)).default,
          module: await WebAssembly.compile(await files(spec.wasm)),
          program: spec.program,
        };
      }
      compiled.set(chip, tools);
    }
    return compiled.get(chip);
  }

  const results = [];
  for (const { board, source } of job.builds) {
    const chip = plan.boards[board];
    const started = Date.now();
    try {
      const tools = chip === undefined ? {} : await toolsFor(chip);
      const done = await build({ plan, board, source, files, tools });
      results.push({ ok: done.ok, image: Buffer.from(done.image).toString("base64"),
                     diagnostics: done.diagnostics, command: done.command,
                     ms: Date.now() - started });
    } catch (error) {
      if (!(error instanceof Refused)) throw error;
      results.push({ refused: error.message });
    }
  }
  await writeFile(job.result, JSON.stringify(results, null, 1));
}

// Emscripten's node exit handler sets process.exitCode to each tool's status,
// so the runner's own outcome is stated explicitly, last.
main().then(() => process.exit(0), (error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
