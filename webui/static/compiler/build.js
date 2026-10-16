// OpenHardware - a sketch in, an image out, in this tab (OH-244).
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// What webui/compile.py's build() does on the server, done with avr-gcc
// compiled to WebAssembly: the same recipe, the same commands, the same
// compiler, so the same bytes. tests/webui/test_compile_wasm.py holds that,
// sample for sample.
//
// Nothing here knows where it runs. The page's Worker (worker.js) and the
// test's node runner (tests/webui/compile_wasm_runner.mjs) each hand build()
// a way to read the bundle's files and the tools, already compiled.
//
// ## Where the commands come from
//
// Not from here. tools/build_compiler.py takes compile.py's recipe, runs the
// WebAssembly driver with -### over it, and writes what the driver would have
// run -- cc1plus, as, ld, objcopy, each argv in full -- into plan.json. Two
// arguments in it are stand-ins, because they are the two things a sketch
// changes: @LIBRARY_INCLUDES@, the -I of each library the sketch includes,
// and @OBJECTS@, the objects linked. The driver does not reorder -I
// directories among themselves or objects among themselves, so putting the
// real ones where the stand-ins are is exactly what it would have printed.
//
// ## What is the same as the server, and what cannot be
//
// The preamble, which libraries a sketch gets, the order objects link in,
// the image, and a compiler error's text, with the paths in it given the
// labels compile.py's _diagnostics gives them (`<toolchain>/...`,
// `<build>/...`). NOT the server's separators, which are its host's. NOT the
// trailing "collect2: error: ld returned 1 exit status" of a link error,
// which is the server's driver speaking: no driver runs here. And not where
// the server's own labelling misses: on Windows its gcc names avr-libc's
// headers in lower case (`c:\users\...\toolchain-atmelavr\avr\include\...`),
// which compile._diagnostics' replacement, matching case, leaves as it is;
// here they read `<toolchain>/toolchain-atmelavr/avr/include/...`.

/** The build could not be attempted. The server's 400, not a failed build. */
export class Refused extends Error {}

/** The plan.json and manifest.json this reads; tools/build_compiler.py's PLAN_FORMAT. */
export const PLAN_FORMAT = 2;

/**
 * Throws unless `format` is PLAN_FORMAT. Asked of manifest.json and plan.json
 * as soon as each is parsed, before anything reads their shape: a new format
 * is a new shape, and an old reader would fail on it with a TypeError that
 * names neither file.
 */
export function checkFormat(name, format) {
  if (format !== PLAN_FORMAT) {
    throw new Error(`${name} is format ${format} and this build.js reads format ` +
                    `${PLAN_FORMAT}: the page and its compiler/ folder are from different builds`);
  }
}

/**
 * Why compile.build would refuse to attempt this build -- a board with no
 * compiler here, or a sketch too large -- or null. Asked before a file is
 * fetched, so a refusal costs nothing.
 */
export function refusal(plan, board, source) {
  // Own properties only: a board named "constructor" is a board nobody has.
  if (!Object.hasOwn(plan.boards, board)) {
    return (Object.hasOwn(plan.refused, board) ? plan.refused[board] : null) ??
      `${board}: no compiler for it in this copy. Boards it builds for: ` +
      `${Object.keys(plan.boards).sort().join(", ")}.`;
  }
  const size = new TextEncoder().encode(source).length;
  if (size > plan.max_source_bytes) {
    return `sketch is ${size} bytes, over the ${plan.max_source_bytes} this accepts`;
  }
  return null;
}

/** Every tool runs here, and every file a build makes is named relative to it. */
const BUILD_DIR = "/build";

/** `compile.preamble`: the Arduino header and a #line, unless the sketch has its own. */
export function preamble(source, text) {
  if (source.includes("<Arduino.h>") || source.includes('"Arduino.h"')) return source;
  return text + source;
}

/** `compile.build`'s `wanted`: a library is compiled only for a sketch naming its header. */
export function wantedLibraries(recipe, source) {
  return recipe.libraries.filter((library) =>
    source.includes(`<${library.header}>`) || source.includes(`"${library.header}"`));
}

/** `compile._hinted`: the recipe's note under any error its table caused. */
function hinted(diagnostics, recipe) {
  const said = [diagnostics];
  for (const [needle, note] of recipe.hints) {
    if (diagnostics.includes(needle)) said.push(note);
  }
  return said.join("\n");
}

function mkdirs(fs, path) {
  let at = "";
  for (const part of path.split("/").slice(1, -1)) {
    at += `/${part}`;
    if (!fs.analyzePath(at).exists) fs.mkdir(at);
  }
}

/**
 * Run one tool once, in a fresh instance: GCC's state does not survive
 * exit(), so an instance is never reused.
 *
 * `inputs` is [path, bytes] pairs written before it starts. Returns its exit
 * status, what it printed, and its filesystem, to read what it wrote.
 */
export async function run(tool, argv, inputs) {
  const stdout = [];
  const stderr = [];
  // Emscripten's glue waits on `receive` and on nothing else, so an
  // instantiation that fails -- no memory left for a fourth instance, say --
  // would leave the build waiting forever. The race carries the failure out.
  let failed;
  const failure = new Promise((_, reject) => { failed = reject; });
  const instance = await Promise.race([tool.create({
    thisProgram: tool.program,
    print: (line) => stdout.push(line),
    printErr: (line) => stderr.push(line),
    instantiateWasm: (imports, receive) => {
      WebAssembly.instantiate(tool.module, imports).then(
        (made) => receive(made, tool.module),
        (error) => failed(new Error(`${tool.program} could not be started: ${error.message}`)));
      return {};
    },
  }), failure]);
  const fs = instance.FS;
  for (const [path, bytes] of inputs) {
    mkdirs(fs, path);
    fs.writeFile(path, bytes);
  }
  mkdirs(fs, `${BUILD_DIR}/.`);
  fs.chdir(BUILD_DIR);
  const status = instance.callMain([...argv]);
  return { status, stdout: stdout.join("\n"), stderr: stderr.join("\n"), fs };
}

/**
 * What a failed step said, as compile._diagnostics keeps it: stderr, else
 * stdout, trimmed, the sketch's own path said as "sketch.cpp" -- which is
 * how a sketch that includes Arduino.h itself, and so has no #line, is
 * named -- and every other path by the label the server's build gives it
 * (plan.json's `labels`).
 */
function said(done, recipe) {
  let text = (done.stderr || done.stdout || "").trim().replaceAll(recipe.sketch, "sketch.cpp");
  for (const [path, label] of recipe.labels) {
    // Only where a path starts -- a line's start, or after a space, quote or
    // bracket -- so a "/build/" inside some longer path is left as it is.
    // Unlike the server's, these paths are short enough to be typed: a line
    // gcc quotes from a sketch -- one including Arduino.h itself, so with no
    // #line -- that holds the string " /build/x" is quoted as " <build>/x".
    // Accepted; the line and column it is reported at are untouched.
    const at = new RegExp(`(^|[\\s'"\`(])${path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "gm");
    text = text.replace(at, `$1${label}`);
  }
  return text;
}

/** The argv shown back to the page, as `Build.command` is: tool name first. */
function shown(name, argv) {
  return [name, ...argv];
}

/**
 * Compile `source` for `board`: {ok, image, diagnostics, command}.
 *
 * Throws Refused where compile.build raises CompileError -- a board with no
 * compiler here, or a sketch too large -- and returns ok:false, with the
 * compiler's own words, where it returns ok=False.
 *
 *   plan    compiler/plan.json
 *   files   async (bundle path) => Uint8Array
 *   tools   {cc1plus, as, ld, objcopy}: each {create, module, program}, the
 *           chip's own, as its plan.chips[chip].tools names them
 *   step    called with each tool's name as it starts, for a caller keeping
 *           the server's time budget
 */
export async function build({ plan, board, source, files, tools, step = () => {} }) {
  checkFormat("plan.json", plan.format);
  const refused = refusal(plan, board, source);
  if (refused !== null) throw new Refused(refused);
  const recipe = plan.chips[plan.boards[board]];
  const read = (path) => files(`${recipe.fs}${path}`);
  const loaded = (paths) => Promise.all(paths.map(async (path) => [path, await read(path)]));
  const wanted = wantedLibraries(recipe, source);

  // The sketch, as compile.build writes it: `sketch.cpp`, its preamble
  // added, outside the working directory (build_compiler.SKETCH says why).
  const sketch = new TextEncoder().encode(preamble(source, plan.preamble));
  // cc1plus's, and as's where the driver hands as the -I directories too.
  const withLibraries = (argv) => argv.flatMap((arg) =>
    arg === "@LIBRARY_INCLUDES@" ? wanted.flatMap((library) => ["-I", library.include]) : [arg]);
  const cc1plusArgv = withLibraries(recipe.cc1plus);
  step(recipe.tools.cc1plus.name);
  const compiled = await run(tools.cc1plus, cc1plusArgv, [
    ...await loaded(recipe.headers),
    [recipe.sketch, sketch],
  ]);
  if (compiled.status !== 0) {
    return { ok: false, image: new Uint8Array(), diagnostics: hinted(said(compiled, recipe), recipe),
             command: shown(recipe.tools.cc1plus.name, cc1plusArgv) };
  }

  const asArgv = withLibraries(recipe.as);
  step(recipe.tools.as.name);
  const assembled = await run(tools.as, asArgv, [
    [`${BUILD_DIR}/sketch.s`, compiled.fs.readFile(`${BUILD_DIR}/sketch.s`)],
  ]);
  if (assembled.status !== 0) {
    return { ok: false, image: new Uint8Array(), diagnostics: hinted(said(assembled, recipe), recipe),
             command: shown(recipe.tools.as.name, asArgv) };
  }

  // compile.build's link order: the sketch, the core, each wanted library's
  // sources in the recipe's order, then a variant from outside the framework
  // (the SAMD21's variant.cpp; none on the Uno).
  const objects = [...recipe.objects, ...wanted.flatMap((library) => library.objects),
                   ...recipe.trailing];
  const ldArgv = recipe.ld.flatMap((arg) =>
    arg === "@OBJECTS@" ? [`${BUILD_DIR}/00.o`, ...objects] : [arg]);
  step(recipe.tools.ld.name);
  const linked = await run(tools.ld, ldArgv, [
    ...await loaded([...recipe.link_files, ...objects]),
    [`${BUILD_DIR}/00.o`, assembled.fs.readFile(`${BUILD_DIR}/00.o`)],
  ]);
  if (linked.status !== 0) {
    return { ok: false, image: new Uint8Array(), diagnostics: said(linked, recipe),
             command: shown(recipe.tools.ld.name, ldArgv) };
  }

  step(recipe.tools.objcopy.name);
  const extracted = await run(tools.objcopy, recipe.objcopy, [
    [`${BUILD_DIR}/sketch.elf`, linked.fs.readFile(`${BUILD_DIR}/sketch.elf`)],
  ]);
  const command = shown(recipe.tools.objcopy.name, recipe.objcopy);
  if (extracted.status !== 0) {
    return { ok: false, image: new Uint8Array(), diagnostics: said(extracted, recipe), command };
  }
  return { ok: true, image: extracted.fs.readFile(`${BUILD_DIR}/sketch.bin`), diagnostics: "",
           command };
}
