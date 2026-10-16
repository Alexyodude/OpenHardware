# The emulator page as a static site, and release 0.1.0

The owner, 2026-10-16: "openhardware is also not accesable in webatm?",
"openhardware could run client side right?", "make some release along with
it". Today the page runs only from `webui/emulator_server.py` on
`127.0.0.1:8088`, unhosted and unversioned.

## Scope

```text
IN   the emulator page (webui/static/emulator.html) as files a static host serves:
       - the i8086 session and its six sample programs
       - every runnable board, from an image the visitor uploads
       - the pin view and the 3D bench, drawing a vendor model only where its licence allows
     served at https://alexyodude.com/OpenHardware/ by a GitHub Pages workflow, relative paths
     version 0.1.0, release notes
OUT  compiling a sketch (needs a toolchain; the page says so and sends people to the server)
     artefact search (reads the server's disk; same)
     PICSimLab and the bridge page (index.html): shipping PICSimLab would distribute GPL code
     the webui.wasm.* ledger cells: they are PICSimLab's own Emscripten build, which is that GPL code
     pushing, tagging, enabling Pages, publishing a release: the operator, after a secret scan and the owner's yes
UNCHANGED  emulator_server.py's loopback bind and Origin check; every file another ticket holds
```

## Path, confirmed by spike before this was written

```text
core/<core>/*.cc --em++ 5.0.3, -sSIDE_MODULE=1 -fwasm-exceptions--> lib<core>.so  (a wasm side module)
Pyodide 314.0.7 (CPython 3.14.2, emscripten_5_0_3, links libffi and libc++ into its main module)
  ctypes.CDLL("/…/build/lib/libi8086.so")  <- core/i8086/abi.py, UNCHANGED
  webui.emulator_server.handle_api(...)    <- UNCHANGED, imported as-is

Measured 2026-10-16 under node 24: all six i8086 samples give the server's answers
(Sum 1..10 -> ax=55, 5! -> 120, Fibonacci -> 144); XIAO-RP2040 + tests/cortexm0/uart/hello.bin
prints "hello, world\n" on its UART; Arduino Uno + tests/avr/blink/blink.bin runs 200,000
steps in 0.13 s. Cores: avr 10 KB, i8086 16 KB, cortexm0 19 KB, riscv32 43 KB.
```

The emulator page is not the bridge page and has no PICSimLab in it: every
route it calls is `webui/emulator_server.py`'s, which drives this repository's
own cores. So "only the transport changes" holds literally: the Python that
answers `/api/*` is the same module, and what changes is that a `fetch` is
answered by a Worker instead of a socket.

## Architecture

```text
browser tab (https://alexyodude.com/OpenHardware/)
 ├─ index.html          = emulator.html, adapted by the build (relative paths) + notice + transport
 ├─ emulator.js, board3d-panel.js, board3d.js, …   UNCHANGED, still fetch("/api/…")
 ├─ inpage/transport.js  window.fetch: "/api/*" -> Worker; any other "/x" -> "<site>/x"; else native
 └─ Worker: inpage/worker.js (module worker)
      ├─ pyodide/            vendored Pyodide 314.0.7 runtime (pinned tarball, sha256-checked)
      ├─ openhardware.zip    the Python the page runs + build/lib/lib<core>.so
      └─ webui.inpage.InPage().answer(verb, target, body) -> (status, json)
```

## File layout

```text
webui/inpage.py                     NEW  MIT  the page's /api answered with no socket (OH-238)
webui/static/inpage/transport.js    NEW  MIT  fetch -> Worker, absolute path -> site path (OH-238, OH-240)
webui/static/inpage/worker.js       NEW  MIT  boots Pyodide, unpacks the bundle, answers (OH-238)
webui/static/inpage/inpage.css      NEW  MIT  the notice's look (OH-239)
tools/build_site.py                 NEW  MIT  one command -> build/site/ (OH-238 .. OH-241)
tools/site_licences.py              NEW  MIT  what may ship, under what licence, and the notices (OH-241)
tools/build_core.py                 EDIT      LIB_NAME_PATTERNS gains "Emscripten": "lib{}.so" (OH-238)
tests/webui/test_inpage.py          NEW       InPage vs. the real loopback server, request for request (OH-238/239)
tests/webui/test_site_build.py      NEW       page(), core_sources(), the bundle list, the lock (OH-238/240)
tests/webui/test_site_pyodide.py    NEW       node + Pyodide boot the built bundle alone and run it (OH-238/239)
tests/webui/test_site_browser.py    NEW       Chromium against build/site under a subpath: network log (OH-240)
tests/rules/test_site_licences.py   NEW       every model has a row; every shipped row is opened CC BY-SA/MIT (OH-241)
.github/workflows/pages.yml         NEW       tag v* -> build -> test -> deploy-pages (OH-242)
pyproject.toml                      EDIT      [project] name, version = "0.1.0" (OH-243)
docs/releases/0.1.0.md              NEW       release notes (OH-243)
PROVENANCE.md, rules/licence-hygiene.md  EDIT  Pyodide, the wasm cores, the shipped models (OH-241)

build/site/          (gitignored, under the existing /build/)  the output, replaced whole each build
build/site.lock      O_EXCL: one build at a time
third_party/emsdk/   (gitignored)  emsdk 5.0.3, or $EMSDK
third_party/site-cache/ (gitignored)  pinned downloads, sha256-checked
```

## Signatures

```python
# webui/inpage.py
NO_COMPILER: str          # the refusal /api/board/compile answers, naming the server
NO_SEARCH: str            # the note /api/board/artefacts answers

class InPage:
    """The one i8086 session and board slot a page talks to, as Handler holds them."""
    session: emulator.Session
    boards: emulator_server.BoardSlot
    def __init__(self) -> None: ...
    def answer(self, verb: str, target: str, body: str) -> tuple[int, str]:
        """One request -> (status, JSON text), as Handler._api + do_POST would answer it.
        405 via ROUTE_METHODS, 413 past MAX_BODY_BYTES, 400 for a body that is not a
        JSON object, BOARD_ERROR_STATUS for a BoardRunError, 400 unreadable-artefact,
        400 for ApiError/EmulatorError/ValueError. Two routes differ, on purpose:
        /api/boards answers buildable=false for every board, /api/board/compile 400 NO_COMPILER."""
```

```python
# tools/build_site.py
SITE: pathlib.Path            # build/site
LOCK: pathlib.Path            # build/site.lock
EMSCRIPTEN_VERSION = "5.0.3"  # == Pyodide's platform, checked against pyodide-lock.json
SIDE_MODULE_FLAGS: tuple[str, ...]
PAGE_FILES: tuple[str, ...]   # what the emulator page loads, relative to webui/static/
BUNDLE: tuple[str, ...]       # globs: the Python the page runs, measured by an audit-hook trace

class Pinned(NamedTuple): url: str; sha256: str; size: int
PYODIDE: Pinned               # pyodide-core-314.0.7.tar.bz2
LICENCE_TEXTS: dict[str, Pinned]  # Pyodide MPL-2.0, CPython LICENSE, CPython Doc/license.rst, Emscripten LICENSE

class SiteError(Exception): ...

def main(argv: list[str] | None = None) -> int
def build(site: pathlib.Path = SITE) -> dict[str, object]      # under LOCK; returns the manifest
def core_sources(core: str) -> list[pathlib.Path]              # read from core/<core>/CMakeLists.txt
def wasm_cores(out: pathlib.Path) -> list[pathlib.Path]        # one em++ per core
def em_cxx() -> list[str]                                      # [python, …/em++.py], version checked
def fetch_pinned(pin: Pinned) -> pathlib.Path                  # third_party/site-cache/, sha256 checked
def pyodide_runtime(dest: pathlib.Path) -> list[pathlib.Path]  # the five files the runtime loads
def bundle(cores: list[pathlib.Path], dest: pathlib.Path) -> pathlib.Path   # openhardware.zip
def page(html: str, version: str, commit: str) -> str          # emulator.html -> index.html
def module_specifiers(js: str) -> list[str]                    # absolute "/x.js" imports needing a map entry
def models(dest: pathlib.Path) -> dict[str, list[str]]         # via site_licences; filtered index.json + NOTICE
```

```python
# tools/site_licences.py
class Ships(NamedTuple): licence: str; registry: str | None; why: str
class Withheld(NamedTuple): why: str
class UnlistedModel(Exception): ...
BOARD_MODELS: dict[str, Ships | Withheld]     # one row per .glb in webui/static/models/
PART_LIBRARY: str                             # parts/*.glb from here ship as CC BY-SA 4.0
def decide(file: str, sources: list[str]) -> Ships | Withheld
def model_notice(shipped: dict[str, Ships], index: dict) -> str
def runtime_notice(texts: dict[str, str]) -> str
```

```js
// webui/static/inpage/transport.js  (classic script, before emulator.js)
//   window.fetch(input, init): /api/* -> worker.postMessage({id, verb, target, body}) -> Response
//                               "/x" not under the site's own path -> "<site>/x"; otherwise native
// webui/static/inpage/worker.js     (module worker)
//   loadPyodide({indexURL: "../pyodide/"}); unpackArchive(openhardware.zip, "/home/pyodide/openhardware")
//   InPage() once; onmessage -> answer(verb, target, body) -> postMessage({id, status, body})
//   boot failure -> {type: "failed"}; every later /api answer is 503 naming it
```

## Call stack: pressing Run on a sample

```text
emulator.js  api("/api/run", {steps})
  window.fetch                              inpage/transport.js
    worker.postMessage({id, "POST", "/api/run", body})
      worker.js onmessage
        InPage.answer("POST", "/api/run", body)            webui/inpage.py
          emulator_server.handle_api(session, "/api/run", …)   UNCHANGED
            emulator.Session.run -> core/i8086/abi.py -> ctypes -> libi8086.so (wasm)
        <- (200, '{"steps": …}')
    <- new Response(body, {status: 200})
```

## Tests

```text
test_inpage.py         every route and every refusal: InPage.answer == the loopback server's
                       (status, JSON) for the same request, both sides fresh (the oracle for
                       "only the transport changed"); /api/boards all buildable=false;
                       /api/board/compile 400 naming the server; 405 for a GET that mutates
test_site_build.py     page(): no src/href/import/import-map value left starting with "/";
                       transport loads before emulator.js; each anchor matched once or SiteError;
                       core_sources() == the .cc files each CMakeLists names; the lock refuses a
                       second build
test_site_pyodide.py   node + the BUILT site: boots openhardware.zip alone, six samples give the
                       server's answers, hello.bin prints "hello, world\n" (skips without node or build)
test_site_browser.py   Chromium, build/ served by http.server so the site sits at /site/: the
                       sample runs, the Uno takes blink.bin, every request is to 127.0.0.1
test_site_licences.py  every .glb in models/index.json has a row; every Ships row cites an
                       opened CC BY-SA/MIT source in tools/board_sources.py; nothing Seeed ships
```

## Uncertain choices

```text
1. Pyodide is FETCHED at build time (pinned + sha256) into the site, not committed. The page
   loads it from its own origin, which is what the offline guarantee needs; the repository
   stays as lean as "fetched, never tracked" keeps it. Committing it is 15 MB of binary.
2. The fetch shim, not an edit to emulator.js: emulator.js, board3d.js and api.py are OH-161's,
   and board3d-panel.js and board3d.js fetch /api themselves, so fetch is the one place every
   caller passes through.
3. InPage restates Handler._api's error mapping (25 lines) instead of sharing it: Handler is
   OH-161's file. test_inpage.py holds the two together; when OH-161 releases
   emulator_server.py, Handler._api can call InPage's mapping instead.
4. The hosted build has NO vendor models: they are generated from fetched vendor files CI does
   not have. A local build ships the licence-cleared ones. Putting them on Pages is a follow-up.
5. Deploy on a v* tag (and by hand), not on every push: the hosted page is a release.
6. A Worker, not the main thread: Chrome refuses synchronous WebAssembly compiles on the main
   thread, ctypes.CDLL compiles synchronously, and a run of 20,000 steps would freeze the page.
```

## Slices

```text
OH-238  The i8086 samples run in a tab with no server
        Verify: python tools/build_site.py && python -m http.server -d build/site 8123
                -> open, pick a sample, Run: registers match the server's; test_inpage, test_site_pyodide
OH-239  A board runs from an uploaded image; the page says compiling needs the server
        Verify: upload tests/avr/blink/blink.bin on Arduino Uno, Run: pins toggle; hello.bin prints
OH-240  Served from a subfolder, and no request leaves the page
        Verify: python -m http.server -d build 8123 -> /site/ ; test_site_browser network log
OH-241  Only files whose licence allows it ship, and each says whose it is
        Verify: python tools/build_site.py prints shipped/withheld per model; test_site_licences
OH-242  A v* tag deploys build/site to GitHub Pages
        Verify: the workflow's steps run locally in order; versions pinned once
OH-243  0.1.0
        Verify: the page's footer says 0.1.0 and the commit; docs/releases/0.1.0.md
```
