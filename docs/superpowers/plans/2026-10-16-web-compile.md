# Build and run in the static build: the sketch compiles in the tab

The owner, 2026-10-16: "CAN YOU MAKE IT SO WEB COMPILE IS POSSIBLE AND
RUNNING?", then chose "In the browser", with no server. OH-244. Builds on the
static build (`2026-10-16-static-site.md`, OH-238..OH-243), whose plan put
compiling OUT; this puts it back in, for the boards whose compiler fits.

## Scope

```text
IN   the page's Build button in the static build, with no server and no PlatformIO:
       the Arduino Uno first, its image byte-identical to webui/compile.py's
     avr-gcc 7.3.0 + binutils 2.26 compiled to WebAssembly from the sources the server's
       toolchain was built from, by a tools/ script, reproducibly
     fetched only when Build is pressed, from the site itself, and cached (Cache Storage)
     the GPL/LGPL obligations of shipping it: notices and the corresponding source, beside it
     then the SAMD21 the same way; RP2040 and ESP32 measured and reported
OUT  webui/compile.py and the server's /api/board/compile: unchanged
     tools/build_site.py until OH-238's chain hands it over after OH-243; until then a post-step
       over build/site stands in for the few lines it will gain
     pushing, tagging, publishing: the operator, after a scan and the owner's yes
UNCHANGED  every file another open ticket claims
```

## What the server's toolchain is, measured 2026-10-16

```text
PlatformIO toolchain-atmelavr 3.70300.220127 (what compile.py runs)
  bin/, libexec/ (cc1plus, cc1, as, ld, objcopy, the driver)  == Arduino 7.3.0-atmel3.6.1-arduino7, byte for byte
  avr/lib/avr5/{libc,libm,libatmega328p}.a                     == the same, member for member
  lib/gcc/avr/7.3.0/avr5/libgcc.a                              differs in .rela.debug_info only
PlatformIO framework-arduino-avr 5.4.0
  cores/, variants/standard, libraries/{Wire,SPI,EEPROM}       == Arduino's avr-1.8.8.tar.bz2, file for file
Arduino 7.3.0-atmel3.6.1-arduino7 is github.com/arduino/toolchain-avr at 368b87a:
  gcc-7.3.0.tar.xz + atmel-patches-gcc.7.3.0-arduino2.patch, GMP 5.0.2, MPFR 3.1.0, MPC 0.9
  Atmel 3.6.1 avr-binutils.tar.bz2 (2.26.20160125) + 00-binutils-data_region_length.patch
Host independence: Arduino's x86_64-linux build and this PC's i686-mingw build give the same
  image for all five samples (blink 500/250, OH-135's idioms, Serial, float).
@horang-corp/avr-gcc-wasm 0.2.0: not used. No licence on its own code, no build scripts for
  its wasm (its notices ask a distributor to supply them), binutils 2.42 against the server's 2.26.
```

## Architecture

```text
tools/build_compiler.py                       (Python, the build machine)
  fetch pinned sources ──> third_party/compiler-cache/      sha256-checked
  docker: tools/wasm_toolchain/ ──> third_party/wasm-toolchain/out/avr/<tool>.{mjs,wasm}
  node:   precompile the core and library objects with those tools, through the wasm
          driver's -### so each sub-command is the driver's own
  ──> build/compiler/          the bundle a site serves at compiler/
        manifest.json          every runtime file, size, sha256
        boards.json            which boards build here, and why the others do not
        avr/plan.json          expanded cc1plus/as/ld/objcopy argv, objects, libraries, base
        avr/tools/, avr/sysroot/, avr/objects/
        NOTICE.md, licenses/, source/   (source/ is never fetched by the page)

browser tab
  emulator.js  api("/api/board/compile", {board, source})            UNCHANGED
    window.fetch                         inpage/compile.js   (wraps OH-238's transport.js)
      compiler Worker: compiler/worker.js
        load the bundle (Cache Storage, sha256-checked) ── first press only
        compiler/build.js  build(plan, board, source)
          cc1plus.wasm -> avr-as.wasm -> avr-ld.wasm -> avr-objcopy.wasm, one instance each
      ok:   fetch("/api/board/load", {board, image, base})  -> transport.js -> Pyodide  UNCHANGED
            -> {ok, bytes, diagnostics, command, board}      the server's reply, field for field
      fail: {ok:false, bytes:0, diagnostics, command}         no load: the board is unchanged
```

## File layout

```text
tools/wasm_toolchain/Dockerfile        NEW  MIT  emsdk 5.0.3 by digest, + m4 bison flex texinfo
tools/wasm_toolchain/build-avr.sh      NEW  MIT  Arduino's configure lines, emcc as the host
tools/build_compiler.py                NEW  MIT  one command -> build/compiler/
webui/static/compiler/build.js        NEW  MIT  source -> image, environment-free (tab or node)
webui/static/compiler/worker.js        NEW  MIT  the tab's compiler Worker: fetch, cache, build
webui/static/inpage/compile.js         NEW  MIT  fetch wrapper: /api/board/compile, /api/boards
tests/webui/compile_wasm_runner.mjs    NEW  MIT  node: build.js over build/compiler/, for the test
tests/webui/test_compile_wasm.py       NEW       the samples both ways, byte for byte
tests/webui/test_compiler_page.py      NEW       Chromium: edit Blink, Build and run, PB5, network log
docs/research/web-compile/             NEW       measurements: sizes, times, the ESP32 answer
PROVENANCE.md                          EDIT      borrowed from OH-163 after OH-241 returns it
tools/build_site.py                    EDIT      after OH-243: PAGE_FILES, one ADAPTATION, bundle call
```

## Signatures

```python
# tools/build_compiler.py
class Pinned(NamedTuple): url: str; sha256: str; size: int
AVR_SOURCES: dict[str, Pinned]     # what build-avr.sh compiles: gcc, binutils, gmp, mpfr, mpc, 2 patches
AVR_RELEASE: Pinned                # Arduino's x86_64-linux avr-gcc: headers, crt, libgcc, avr-libc
AVR_CORE: Pinned                   # Arduino's avr-1.8.8.tar.bz2 == framework-arduino-avr 5.4.0
TOOLCHAIN_AVR: Pinned              # arduino/toolchain-avr at 368b87a: the scripts libgcc was built by
COMPILER: pathlib.Path             # build/compiler
class CompilerError(Exception): ...
def main(argv: list[str] | None = None) -> int
def build(out: pathlib.Path = COMPILER, *, sources: bool = True) -> dict[str, object]
def fetch_pinned(pin: Pinned) -> pathlib.Path
def wasm_tools(chip: str) -> pathlib.Path                 # docker, or the cached out/ dir
def plan(chip: str, recipe: compile.Recipe) -> dict[str, object]   # from webui.compile.RECIPES
def install_into_site(site: pathlib.Path) -> None         # the post-step; gone in slice 6 (As built)
```

```js
// webui/static/compiler/build.js
export class Refused extends Error {}   // cannot be attempted: the server's 400
/** -> {ok, image: Uint8Array, diagnostics: string, command: string[]} */
export async function build({ plan, board, source, files, tools })
//   files: async (path) => Uint8Array   tools: {name: {create, module: WebAssembly.Module}}
// webui/static/compiler/worker.js   onmessage {id, board, source} -> {id, ok, image, diagnostics,
//   command} | {id, refused} ; {type: "progress", text, bytes, total} while it downloads
// webui/static/inpage/compile.js    classic script after transport.js; wraps window.fetch
```

## Call stack: Build and run on Blink

```text
emulator.js buildSketch -> api("/api/board/compile", {board: "Arduino Uno", source})
  compile.js fetch wrapper
    worker.postMessage({id, board, source})
      worker.js: bundle() once -> Cache Storage / fetch, sha256 -> WebAssembly.compile x4
      build.js build(): preamble(source) == compile.preamble; wanted libraries == compile.build's
        cc1plus  plan.cc1plus with @INCLUDES@ -> the wanted libraries' -I     -> sketch.s
        avr-as   plan.as                                                       -> 00.o
        avr-ld   plan.ld with @OBJECTS@ -> 00.o + core objects + wanted lib objects, server order
        avr-objcopy -O binary -R .eeprom                                       -> image
    <- {ok, image}
    transport.js fetch("/api/board/load", {board, image: base64, base: plan.base})   UNCHANGED
  <- Response {ok, bytes, diagnostics: "", command, board}     emulator.js renders as today
```

## Tests

```text
test_compile_wasm.py   each sample built by webui.compile.build (skips without PlatformIO) and by
                       build.js under node over build/compiler (skips without node or the bundle):
                       the same bytes; a syntax error's diagnostics name sketch.cpp:2 both ways
test_compiler_page.py  Chromium against build/site with the compiler installed: Blink's delay
                       edited 500 -> 250, Build and run, PB5's half-period follows; a syntax error
                       renders on its line; every request is to the page's own origin
```

## Uncertain choices

```text
1. Core and library objects are PRECOMPILED at bundle time, by the shipped wasm compiler, rather
   than compiled per build as the server does. Same commands, same compiler, so the same bytes,
   and the test holds it; per build it would be ~20 cc1plus runs and tens of seconds.
2. A library object is compiled with only its own include root added, where the server adds every
   wanted library's. The three AVR libraries share no header name; the idioms sample, which wants
   all three, is the test that would catch a difference.
3. The corresponding source ships IN the bundle (source/, ~110 MB, never fetched by the page),
   because GPLv3 §6(d) leaves the distributor responsible for a third-party server staying up --
   and one of this toolchain's own source URLs (MPC 0.9's) is already dead.
4. Arduino's prebuilt libgcc and avr-libc, not ones built here: they are the server's objects,
   and their source is the same gcc tarball and patch the compiler is built from.
5. The driver's -### expansion is taken once, at bundle time, with sentinel arguments, rather
   than shipping the driver: the driver does not reorder -I directories or objects among
   themselves, so substituting the sentinels is exact.
```

## Slices

```text
1  avr-gcc as WebAssembly, from the server's sources, by one script
   Verify: tools/wasm_toolchain builds cc1plus/as/ld/objcopy; node compiles Blink with them
2  The bundle, and the same bytes as the server
   Verify: python tools/build_compiler.py; pytest tests/webui/test_compile_wasm.py
3  Build and run in the tab, through the post-step
   Verify: serve build/site, edit Blink, Build and run, PB5's period follows; network log
4  Notices and source; PROVENANCE.md (borrowed)
5  SAMD21; RP2040 and ESP32 measured and reported
6  build_site.py takes the post-step's lines (after OH-243 hands it over)
```

## As built, 2026-10-16: where it departed from the above

```text
Layout     build/compiler/ holds plan.json, manifest.json, boards.json at its root, avr/tools/
           and avr/fs/ (one in-memory filesystem per tool, laid out as the tools were
           configured: /opt/avr, /arduino-avr, /objects); NOTICE.txt, not NOTICE.md, as the
           site's own NOTICE.txt and models/NOTICE.txt are
           build.js, not build.mjs: Windows' python -m http.server serves .mjs as text/plain,
           and a module script must be served as JavaScript (build_site.py's PYODIDE_RUNTIME
           says the same of Pyodide)
           the tool glue is imported through same-origin blob: URLs, after its sha256 is checked,
           on every read and not only the first fetch: Cache Storage is the whole origin's
Post-step  install_into_site() wrote a COPY, build/site-with-compiler/, and not build/site,
           while test_site_browser.py held build/site to OH-239's page, whose Build said it
           needed the local server. Gone with slice 6: build_site.py's compiler() builds the
           bundle into build/site/compiler/, one ADAPTATION adds compile.js after the
           transport, the notice names the compiler's NOTICE.txt, and SKETCH_REPORT_HERE is
           dropped, since compile.js writes the line once the board list is in
Signatures build(*, sources=True) writes COMPILER; wasm_tools() takes no chip; chip_plan()
           replaces plan()
Sentinels  @LIBRARY_INCLUDES@ and @OBJECTS@, collapsed from -I/@LIBRARY_INCLUDES@ and
           /build/@OBJECTS@.o, which is how the driver spells what it was handed
Found      GCC's configure probes the target assembler and linker and changes codegen by the
           answer (COMDAT groups, mergeable strings): a native avr-binutils is built first for
           it to ask, and build-avr.sh checks auto-host.h before compiling GCC
           a plugin-capable ld makes the driver add -fuse-linker-plugin: the link expansion
           carries -fno-use-linker-plugin
           with no collect2, the driver runs ld directly; ld finds its ldscripts/ relative to
           argv[0], so ld runs as /opt/avr/avr/lib/avr-ld and avr5.xn ships
           the sketch is /sketch/sketch.cpp, compiled from /build, so GCC quotes no line of its
           own when it reopens "sketch.cpp", as the server's build does not
           the core's <new> has no suffix: every file in the include trees but a source ships
           the server labels paths in its messages <toolchain>/... and <build>/...: plan.json's
           labels does the same; a link error lacks collect2's last line, which the test says
           Emscripten's runtime, musl and LLVM's C++ runtime are linked into each tool: their
           texts are copied out of the image by build-avr.sh into licenses/
           MPC 0.9 is LGPL-2.1-or-later, and SPI is GPL-2.0 or LGPL-2.1: NOTICE.txt and
           PROVENANCE.md say so file by file; cc1plus links libbacktrace (BSD-3), whose
           notice is backtrace.h's opening comment
Review     the first review's findings, fixed: a failed instantiation could hang a build;
           manifest.json and plan.json fetches were never retried, and plan.json was never
           checked against the manifest; cached files were not re-hashed; --no-sources could
           be published; no time budget. The tab now keeps compile.py's BUILD_BUDGET_SECONDS
           from the first tool's start, by stopping the Worker
           the second review's: a fetch that failed left the others running, whose progress
           replaced the error; the format check ran after the files were fetched, and after a
           new shape had already thrown; a sketch too large fetched 21 MB before its refusal;
           a Cache Storage that exists and refuses failed every build. Now the page stops any
           Worker that answers "failed" and the next press starts a new one (which is also
           what retries a failed manifest), both files' formats are checked as each is
           parsed, compile.build's refusals are asked before the chip's files, and a refusing
           cache is no cache
           the verification's: a cache that opened and then failed a lookup still failed the
           build, and none of the cache's refusals had a test. A failed lookup is now a miss,
           and three tests give the Worker a cache that refuses to open, to look up and to
           keep. Found beside it: a page served over plain http from another machine has no
           crypto.subtle, so every build failed on a TypeError; Build is now off there and
           says why
SAMD21     PLAN_FORMAT 2: a chip's plan gains `trailing`, objects linked after the wanted
           libraries (variant.cpp, from outside the framework, as compile.build orders it),
           and its link a -T script. One image builds every toolchain, each by its own
           script (build-avr.sh, build-arm.sh). A toolchain's key is the Dockerfile, its own
           script and its sources, so the Dockerfile change rebuilt both, and the AVR
           tools came out the same bytes; a change to one script rebuilds that toolchain. GCC 12.3 needed GCC's own fix for PR 111632 to
           compile against libc++: its 12 branch's system.h, pinned, put in place by
           build-arm.sh over the 12.3 file it was measured to differ from by that alone
Source     source/ is 149 MB for the Uno, not ~110; 306 MB with the SAMD21
Measured   docs/research/web-compile/README.md: sizes, first-build times, the SAMD21, RP2040
           and ESP32 answers
Slices     1-4 done for the Uno. 5: the SAMD21 built the same way and the same bytes;
           RP2040 has no server recipe to match; the ESP32s' framework is the repository's own 128 KB core, so they need only
           a riscv32 GCC and fit. 6 done once OH-243 handed build_site.py over (3ea2e1f); the
           Pages workflow's timeout is 90 minutes for the compiler's Docker build, which no
           run of the workflow has measured yet
```
