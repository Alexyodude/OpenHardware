#!/usr/bin/env python3
# OpenHardware - the emulator page as files a static host can serve.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Build `build/site/`: the emulator page, its Python and its cores, no server.

    python tools/build_site.py          # -> build/site/, replacing what was there
    python -m http.server -d build/site 8123

Per OH-238 and `docs/superpowers/plans/2026-10-16-static-site.md`. The page is
`webui/static/emulator.html` with `inpage/transport.js` loaded first, which
answers its `/api/*` requests from a Worker running this repository's own
Python under Pyodide. Nothing the page loads comes from anywhere but the
folder this writes.

## What goes in, and from where

| in `build/site/`      | from                                                   |
|---|---|
| `index.html`, page JS | `webui/static/`; `page()` adds the transport and notice |
| `inpage/`             | `webui/static/inpage/`                                 |
| `pyodide/`            | the pinned Pyodide release, fetched and sha256-checked |
| `openhardware.zip`    | `BUNDLE`, plus every core compiled by `wasm_cores()`   |

## Why the cores are compiled here and not by CMake

They are wasm **side modules**, which `ctypes.CDLL` inside Pyodide loads the
way it loads a `.so` on Linux -- so `core/*/abi.py` binds them unchanged. A
side module has to be built by the Emscripten that built Pyodide, with its
exception model, and CMake's Emscripten toolchain turns a SHARED library into
a static one. So this calls `em++` once per core on the sources the core's own
`CMakeLists.txt` names (`core_sources`), with Pyodide's flags.

## One build at a time

The output folder is replaced whole, and two builds into it at once would
interleave. `LOCK` is taken with `O_EXCL` before anything is written and
removed after; a second build refuses and names the holder. Like a ticket
lock, it never expires on its own: a lock left by a killed build is deleted
by hand, after checking nothing is building.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import typing
import urllib.request
import zipfile

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools import build_core, site_licences  # noqa: E402

STATIC = REPO / "webui" / "static"
SITE = REPO / "build" / "site"
LOCK = REPO / "build" / "site.lock"
CACHE = REPO / "third_party" / "site-cache"


class Pinned(typing.NamedTuple):
    """A file fetched at build time, and the only bytes it may be."""

    url: str
    sha256: str
    size: int


#: Pyodide's runtime, which the page loads from `pyodide/`. Its platform is
#: `emscripten_5_0_3` (`pyodide-lock.json`), which is why `EMSCRIPTEN_VERSION`
#: is what it is: a side module must come from the Emscripten that built the
#: main module it is loaded into.
PYODIDE = Pinned(
    "https://github.com/pyodide/pyodide/releases/download/314.0.7/"
    "pyodide-core-314.0.7.tar.bz2",
    "2abdcc2e35208af406e07724cffa85bc582ced97e9028383ecf5462541393f95",
    6_757_104,
)

#: The files of that release the page loads, and the name each is shipped
#: under. The rest of the tarball -- node's CLI launcher, `python.exe`,
#: TypeScript declarations -- is not shipped.
#:
#: **The two ES modules are renamed to end `.js`, byte for byte as released.**
#: A browser refuses a module served as anything but JavaScript, and on
#: Windows `python -m http.server` types `.mjs` from the registry, which on
#: the machine this was built on says `text/plain` (`HKCR\.mjs`): the page
#: stopped at `pyodide.mjs` with nothing in its console. Every server types
#: `.js`. `inpage/worker.js` imports the asm module itself and hands it to
#: `loadPyodide` as `createPyodideModule`, the option Pyodide documents for a
#: worker that cannot use its own `import()` of `pyodide.asm.mjs`.
PYODIDE_RUNTIME = {
    "pyodide.mjs": "pyodide.mjs.js",
    "pyodide.asm.mjs": "pyodide.asm.mjs.js",
    "pyodide.asm.wasm": "pyodide.asm.wasm",
    "python_stdlib.zip": "python_stdlib.zip",
    "pyodide-lock.json": "pyodide-lock.json",
}

EMSCRIPTEN_VERSION = "5.0.3"

#: Pyodide's own `CFLAGS_BASE` (its Makefile.envs at 314.0.7: `-O2 -fPIC
#: -fwasm-exceptions -sSUPPORT_LONGJMP=wasm`) plus what makes a side module,
#: and the hidden visibility CMakeLists.txt gives the native build, so the
#: module exports what `abi.h` marks and nothing else.
SIDE_MODULE_FLAGS = (
    "-std=c++17",
    "-O2",
    "-fPIC",
    "-fwasm-exceptions",
    "-sSUPPORT_LONGJMP=wasm",
    "-sSIDE_MODULE=1",
    "-fvisibility=hidden",
    "-fvisibility-inlines-hidden",
)

#: What the emulator page loads, relative to `webui/static/`. Not the whole
#: directory: `index.html`, `app.js`, `board.js` and `scene3d.js` are the
#: bridge page's, which drives PICSimLab and has no place here.
PAGE_FILES = (
    "emulator.css",
    "emulator.js",
    "board3d-panel.js",
    "board3d.js",
    "wires.js",
    "circuit.js",
    "parts.js",
    "clock.js",
    "vendor/three.module.js",
    "vendor/three.core.js",
    "vendor/OrbitControls.js",
    "vendor/LICENSE",
    "inpage/transport.js",
    "inpage/worker.js",
    "inpage/inpage.css",
)

#: The Python the page runs, as globs from the repository root.
#:
#: **Measured, not guessed** (2026-10-16): Pyodide under node, an audit hook
#: recording every file opened, every route called, all six samples run and
#: two boards loaded. `tools/` is eight modules because `emulator_server`
#: imports `import_firmware`, `compile` reads `board_manifest`, and the
#: catalogue reads the board files through `import_board`, `eagle` and
#: `kicad`. Each core's `CMakeLists.txt` is in because `build_core.cores()`
#: is how a core is known to exist. `tests/webui/test_site_pyodide.py` boots
#: the bundle alone, so a module missing from here fails there by name.
BUNDLE = (
    "webui/*.py",
    "webui/boards/*.py",
    "webui/boards/*.json",
    "webui/devices/*.py",
    "webui/parts/*.py",
    "webui/arduino/variants/*/soc/soc_caps.h",
    "core/__init__.py",
    "core/*/*.py",
    "core/*/CMakeLists.txt",
    "tools/__init__.py",
    "tools/board_manifest.py",
    "tools/board_sources.py",
    "tools/build_core.py",
    "tools/eagle.py",
    "tools/import_board.py",
    "tools/import_firmware.py",
    "tools/kicad.py",
)

#: Every zip entry carries this date, so one tree always zips to one sha256.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class SiteError(Exception):
    """The site could not be built, and why."""


# --- the lock -----------------------------------------------------------------


def take_lock(lock: pathlib.Path) -> None:
    """Create `lock`, or refuse naming whoever holds it."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = lock.read_text(encoding="utf-8", errors="replace").strip()
        raise SiteError(
            f"another build holds {lock} ({holder or 'no holder written'}): "
            f"one build at a time. If none is running, delete that file."
        ) from None
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        out.write(f"pid {os.getpid()} since "
                  f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")


# --- the cores ----------------------------------------------------------------


def core_sources(core: str) -> list[pathlib.Path]:
    """The `.cc` files `core/<core>/CMakeLists.txt` builds its library from.

    Read out of `add_library(<core> SHARED ...)` rather than globbed, so the
    browser's core is the native one, file for file.
    """
    cmake = build_core.CORE_DIR / core / "CMakeLists.txt"
    text = cmake.read_text(encoding="utf-8")
    found = re.search(rf"add_library\(\s*{re.escape(core)}\s+SHARED\s+([^)]*)\)",
                      text)
    if found is None:
        raise SiteError(f"{cmake}: expected add_library({core} SHARED ...), "
                        f"found none")
    words = [word for line in found.group(1).splitlines()
             for word in line.split("#", 1)[0].split()]
    sources = [cmake.parent / word for word in words]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing or not sources:
        raise SiteError(f"{cmake} names sources that are not there: "
                        f"{missing or 'none at all'}")
    return sources


def emscripten() -> pathlib.Path:
    """Emscripten's own directory: under `$EMSDK` where it is set (emsdk's
    environment script sets it), else under `third_party/emsdk`."""
    root = (pathlib.Path(os.environ["EMSDK"]) if os.environ.get("EMSDK")
            else REPO / "third_party" / "emsdk")
    return root / "upstream" / "emscripten"


def em_cxx() -> list[str]:
    """The command that runs Emscripten's `em++`, checked to be 5.0.3.

    Run through this interpreter rather than as `em++`, which is a `.bat` on
    Windows and a shell script elsewhere.
    """
    script = emscripten() / "em++.py"
    if not script.is_file():
        raise SiteError(
            f"no Emscripten at {script}. Install the one Pyodide was built "
            f"with:\n  git clone https://github.com/emscripten-core/emsdk "
            f"third_party/emsdk\n  python third_party/emsdk/emsdk.py install "
            f"{EMSCRIPTEN_VERSION}\n  python third_party/emsdk/emsdk.py "
            f"activate {EMSCRIPTEN_VERSION}")
    command = [sys.executable, str(script)]
    done = subprocess.run([*command, "--version"], capture_output=True,
                          text=True, check=False)
    first = (done.stdout.splitlines() or [""])[0]
    if done.returncode != 0 or f") {EMSCRIPTEN_VERSION} (" not in first:
        raise SiteError(
            f"{script} must be Emscripten {EMSCRIPTEN_VERSION}, the one "
            f"Pyodide's main module was linked by; it reported "
            f"{first or done.stderr.strip()!r}")
    return command


def wasm_cores(out: pathlib.Path) -> list[pathlib.Path]:
    """Every core in `core/`, compiled to `out/lib<core>.so`."""
    out.mkdir(parents=True, exist_ok=True)
    command = em_cxx()
    built = []
    for core in build_core.cores():
        target = out / f"lib{core}.so"
        done = subprocess.run(
            [*command, *SIDE_MODULE_FLAGS, f"-I{build_core.CORE_DIR / core}",
             *map(str, core_sources(core)), "-o", str(target)],
            capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise SiteError(f"em++ failed on core/{core} "
                            f"(exit {done.returncode}):\n{done.stderr}")
        built.append(target)
    return built


# --- Pyodide ------------------------------------------------------------------


def fetch_pinned(pin: Pinned) -> pathlib.Path:
    """`pin`'s file in `third_party/site-cache/`, fetched once and checked.

    Cached under its hash as well as its name: four of the licence texts the
    site carries are each called LICENSE.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{pin.sha256[:12]}-{pin.url.rsplit('/', 1)[1]}"
    if not path.is_file():
        partial = path.with_name(path.name + ".part")
        with urllib.request.urlopen(pin.url, timeout=120) as response:
            partial.write_bytes(response.read())
        partial.replace(path)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != pin.size or digest != pin.sha256:
        raise SiteError(
            f"{path} is {len(data)} bytes with sha256 {digest}; {pin.url} is "
            f"pinned at {pin.size} bytes, {pin.sha256}. Delete it to refetch, "
            f"or re-pin after reading why it changed.")
    return path


def pyodide_runtime(dest: pathlib.Path) -> list[pathlib.Path]:
    """Unpack `PYODIDE_RUNTIME` from the pinned release into `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    with tarfile.open(fetch_pinned(PYODIDE), "r:bz2") as archive:
        for name, shipped in PYODIDE_RUNTIME.items():
            member = archive.extractfile(f"pyodide/{name}")
            if member is None:
                raise SiteError(f"pyodide/{name} is not a file in {PYODIDE.url}")
            (dest / shipped).write_bytes(member.read())
            written.append(dest / shipped)
    platform = json.loads((dest / "pyodide-lock.json").read_bytes())["info"]["platform"]
    wanted = "emscripten_" + EMSCRIPTEN_VERSION.replace(".", "_")
    if platform != wanted:
        raise SiteError(f"this Pyodide was built for {platform}; the cores are "
                        f"built for {wanted}, and a side module from one will "
                        f"not link into the other")
    return written


# --- the bundle ---------------------------------------------------------------


def bundle_files() -> list[pathlib.Path]:
    """Every file `BUNDLE` names, sorted, each once."""
    found = {path for pattern in BUNDLE for path in REPO.glob(pattern)
             if path.is_file()}
    empty = [pattern for pattern in BUNDLE if not any(REPO.glob(pattern))]
    if empty:
        raise SiteError(f"BUNDLE patterns that match nothing: {empty}")
    return sorted(found)


def bundle(cores: list[pathlib.Path], dest: pathlib.Path) -> pathlib.Path:
    """`dest/openhardware.zip`: the Python, and the cores under build/lib/."""
    entries = [(path.relative_to(REPO).as_posix(), path.read_bytes())
               for path in bundle_files()]
    lib = build_core.LIB_DIR.relative_to(REPO).as_posix()
    entries += [(f"{lib}/{core.name}", core.read_bytes()) for core in cores]
    target = dest / "openhardware.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return target


# --- the page -----------------------------------------------------------------

#: The tag `page()` puts the transport in front of. It must be there exactly
#: once: twice and the transport would run before only one of them.
EMULATOR_SCRIPT = '<script src="/emulator.js"></script>'
TRANSPORT_SCRIPT = '<script src="inpage/transport.js"></script>'

#: The page's stylesheet, and the notice's, which follows it (OH-239).
EMULATOR_STYLE = '<link rel="stylesheet" href="/emulator.css" />'
INPAGE_STYLE = '<link rel="stylesheet" href="inpage/inpage.css" />'

# emulator.html loads its own files from the server's root, which is where the
# local server puts them. GitHub Pages serves this site from a folder --
# alexyodude.com/OpenHardware/, whose root is another site -- so each of
# those references becomes relative to the page (OH-240). A fetch the page's
# scripts make from the root, as board3d.js makes for /models/, is moved into
# the folder by inpage/transport.js instead, since those files are not adapted.
EMULATOR_SCRIPT_HERE = '<script src="emulator.js"></script>'
EMULATOR_STYLE_HERE = '<link rel="stylesheet" href="emulator.css" />'
PANEL_SCRIPT = '<script type="module" src="/board3d-panel.js"></script>'
PANEL_SCRIPT_HERE = '<script type="module" src="board3d-panel.js"></script>'
CLOCK_IMPORT = 'import { Clock, TICK_STEPS } from "/clock.js";'
CLOCK_IMPORT_HERE = 'import { Clock, TICK_STEPS } from "./clock.js";'

#: The import map's entries. Its last line is new: board3d-panel.js imports
#: "/board3d.js", and an import map remaps a specifier written as a path,
#: so the one script that names a module from the root needs no edit.
IMPORT_MAP = ('"three": "/vendor/three.module.js",\n'
              '    "three/addons/controls/OrbitControls.js": "/vendor/OrbitControls.js"')
IMPORT_MAP_HERE = ('"three": "./vendor/three.module.js",\n'
                   '    "three/addons/controls/OrbitControls.js": "./vendor/OrbitControls.js",\n'
                   '    "/board3d.js": "./board3d.js"')

#: The toolbar. The notice goes above it, so it is the first thing read.
TOOLBAR = '<div class="bar">'

#: Where this copy runs and what it cannot do there, before anything else on
#: the page. `#inpage-status` is where `inpage/transport.js` reports the
#: runtime starting, and why, if it did not.
NOTICE = """<aside class="inpage" aria-label="About this copy">
  <p><strong>This copy of OpenHardware runs in your browser, with no
    server.</strong> <span id="inpage-status" role="status">Starting…</span></p>
  <p>It runs the sample programs, and any firmware image you built yourself:
    pick a board and load the image in the board panel. It cannot compile a
    sketch, which needs a toolchain; for that, run
    <code>python webui/emulator_server.py</code> from a checkout. Whose
    work is in it, and under what licence: <a href="NOTICE.txt">NOTICE.txt</a>.</p>
</aside>"""

#: The Build button, disabled in the page itself rather than by a script.
#: `emulator.js` greys it only once `/api/board/pins` answers, which at first
#: load it refuses -- no board is loaded -- so a script-free page would offer
#: a button whose every press is refused.
BUILD_BUTTON = '<button id="sketch-build" class="primary">'
BUILD_BUTTON_HERE = ('<button id="sketch-build" class="primary" disabled '
                     'title="Compiling needs the local server">')

#: The line beside it, which said "Uses the board picked above."
SKETCH_REPORT = '<span class="note" id="sketch-report">Uses the board picked above.</span>'
SKETCH_REPORT_HERE = ('<span class="note" id="sketch-report">Compiling needs the '
                      'local server, and this copy has none: load an image you '
                      'built in the board panel above.</span>')

#: Each `(anchor, replacement)` `page()` makes in `emulator.html`. Every
#: anchor must be there exactly once: an anchor that moved would otherwise
#: leave the page silently without the notice, or with a live Build button.
ADAPTATIONS = (
    (EMULATOR_STYLE, f"{EMULATOR_STYLE_HERE}\n{INPAGE_STYLE}"),
    (IMPORT_MAP, IMPORT_MAP_HERE),
    (TOOLBAR, f"{NOTICE}\n\n{TOOLBAR}"),
    (BUILD_BUTTON, BUILD_BUTTON_HERE),
    (SKETCH_REPORT, SKETCH_REPORT_HERE),
    (EMULATOR_SCRIPT, f"{TRANSPORT_SCRIPT}\n{EMULATOR_SCRIPT_HERE}"),
    (PANEL_SCRIPT, PANEL_SCRIPT_HERE),
    (CLOCK_IMPORT, CLOCK_IMPORT_HERE),
)


def _once(html: str, anchor: str) -> None:
    count = html.count(anchor)
    if count != 1:
        raise SiteError(f"emulator.html carries {anchor!r} {count} times; "
                        f"page() expects it exactly once")


def page(html: str) -> str:
    """`emulator.html` -> the static site's `index.html`: `ADAPTATIONS`.

    The transport goes first, so that every `fetch` the page's own scripts
    make -- `emulator.js` is a classic script and runs as soon as it is
    parsed -- already finds it in place.
    """
    for anchor, _ in ADAPTATIONS:
        _once(html, anchor)
    for anchor, replacement in ADAPTATIONS:
        html = html.replace(anchor, replacement)
    return html


# --- what may ship, and the notices -------------------------------------------

#: What the page is given when this machine has built no models, as CI has
#: not: the page draws every board as its footprint, and asks for no file.
NO_MODELS = {"units": "mm", "boards": {}, "parts": {"libraries": {}}}


def _text(pin: site_licences.Pinned) -> str:
    return fetch_pinned(Pinned(*pin)).read_text(encoding="utf-8")


def models(dest: pathlib.Path,
           source: pathlib.Path = site_licences.MODELS) -> site_licences.Selection:
    """The models `tools/site_licences.py` lets ship, from `source` into
    `dest`, with an `index.json` naming only them and `NOTICE.txt`.

    `index.json` is written even when nothing ships, so the page's request
    for it is answered rather than refused.
    """
    index_file = source / "index.json"
    index = (json.loads(index_file.read_text(encoding="utf-8"))
             if index_file.is_file() else NO_MODELS)
    selection = site_licences.select(index, site_licences.on_disk(source))
    for name in selection.files:
        (dest / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, dest / name)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.json").write_text(json.dumps(selection.index, indent=1),
                                     encoding="utf-8")
    named = {key for row in selection.shipped.values() for key in row.notices}
    texts = {key: _text(site_licences.NOTICE_TEXTS[key]) for key in named}
    (dest / "NOTICE.txt").write_text(site_licences.model_notice(selection, texts),
                                     encoding="utf-8")
    return selection


def runtime_notice(dest: pathlib.Path) -> pathlib.Path:
    """`NOTICE.txt`: every licence the vendored runtime is under, whole."""
    texts = {title: _text(pin) for title, pin in site_licences.RUNTIME_TEXTS.items()}
    for title, relative in site_licences.EMSCRIPTEN_TEXTS.items():
        path = emscripten() / relative
        if not path.is_file():
            raise SiteError(f"{title}'s licence is not at {path}")
        texts[title] = path.read_text(encoding="utf-8")
    notice = dest / "NOTICE.txt"
    notice.write_text(site_licences.runtime_notice(texts), encoding="utf-8")
    return notice


# --- the whole thing ----------------------------------------------------------


def _write_site(site: pathlib.Path) -> dict[str, int]:
    """Everything into `site`, which is empty. Returns bytes per part."""
    for name in PAGE_FILES:
        source = STATIC / name
        if not source.is_file():
            raise SiteError(f"PAGE_FILES names {source}, which is not there")
        (site / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, site / name)
    html = (STATIC / "emulator.html").read_text(encoding="utf-8")
    (site / "index.html").write_text(page(html), encoding="utf-8")

    runtime = pyodide_runtime(site / "pyodide")
    notice = runtime_notice(site)
    selection = models(site / "models")
    for name, row in sorted(selection.shipped.items()):
        print(f"  ships     models/{name}")
    for name, row in sorted(selection.withheld.items()):
        print(f"  withheld  models/{name}: {row.why}")
    with tempfile.TemporaryDirectory() as scratch:
        cores = wasm_cores(pathlib.Path(scratch))
        zipped = bundle(cores, site)
        cores_size = sum(core.stat().st_size for core in cores)
    return {
        "page": sum((site / name).stat().st_size for name in PAGE_FILES)
        + (site / "index.html").stat().st_size,
        "pyodide": sum(path.stat().st_size for path in runtime),
        "openhardware.zip": zipped.stat().st_size,
        "cores (inside the zip)": cores_size,
        "models": sum(path.stat().st_size for path in (site / "models").rglob("*")
                      if path.is_file()),
        "notices": notice.stat().st_size,
    }


def build(site: pathlib.Path = SITE, lock: pathlib.Path = LOCK) -> dict[str, int]:
    """Build the site into `site`, replacing it whole, under `lock`.

    Written into a sibling folder first and swapped in at the end, so a
    build that fails leaves the last good site where it was.
    """
    take_lock(lock)
    try:
        staging = site.with_name(site.name + ".partial")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        sizes = _write_site(staging)
        if site.exists():
            shutil.rmtree(site)
        staging.rename(site)
        return sizes
    finally:
        lock.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    try:
        sizes = build()
    except SiteError as exc:
        print(f"build_site: {exc}", file=sys.stderr)
        return 1
    total = sum(path.stat().st_size for path in SITE.rglob("*") if path.is_file())
    print(f"build_site: {SITE}")
    for part, size in sizes.items():
        print(f"  {part:<24} {size:>12,} bytes")
    print(f"  {'total on disk':<24} {total:>12,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
