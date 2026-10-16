#!/usr/bin/env python3
# OpenHardware - the compiler the static page builds sketches with (OH-244).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""One command -> `build/compiler/`, the compiler a static copy of the page
fetches when Build is pressed.

    python tools/build_compiler.py          # build/compiler/
    python tools/build_compiler.py --site   # and build/site-with-compiler/: build/site with it in

## What it is for

`webui/compile.py` builds a sketch with PlatformIO's avr-gcc, in a
subprocess, on the machine the server runs on. A copy of the page served as
files has no such machine. This builds the same compiler for WebAssembly,
from the same sources, and lays out everything one build reads -- headers,
libraries, the Arduino core already compiled, and the exact command lines --
so `webui/static/compiler/build.js` can do in a tab what `compile.build`
does on the server, and get the same bytes. `tests/webui/test_compile_wasm.py`
holds it to that.

## The sources, and why these

PlatformIO's toolchain-atmelavr 3.70300.220127 -- what `compile.py` runs --
has the same cc1plus, cc1, as, ld and objcopy, byte for byte, as Arduino's
7.3.0-atmel3.6.1-arduino7 release; the same avr-libc archives member for
member; and a libgcc.a that differs only in debug relocations. Its
framework-arduino-avr 5.4.0 is Arduino's avr-1.8.8 file for file in every
file the recipe reads (measured 2026-10-16). So everything here comes from
Arduino and GNU, pinned by sha256, and nothing from PlatformIO:

- `AVR_SOURCES`: what Arduino's toolchain-avr scripts build that release
  from, which `tools/wasm_toolchain/build-avr.sh` compiles with Emscripten.
- `AVR_RELEASE`: Arduino's own x86_64-linux build of it, for the headers,
  the start file and the libraries a link reads. Its executables are unused.
- `AVR_CORE`: Arduino's AVR core 1.8.8.

## What it costs, and what is never fetched

The page fetches what `manifest.json` lists for a chip, once, on the first
Build press, and keeps it in Cache Storage. `source/` -- every source tarball,
patch and script above, about 150 MB -- is laid down beside it for the GPL's
sake and is never fetched by the page; `--no-sources` leaves it out of a
build meant only for testing, which `--site` then refuses to publish.

## Not here

The board list. Which boards build here is `compile.recipe_for` asked of
every catalogue board, restricted to the chips this bundle carries, so a
board the server cannot build is never offered here either.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pathlib
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable, Iterator
from typing import NamedTuple

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from webui import compile as compiler  # noqa: E402
from webui.boards import catalogue as board_catalogue  # noqa: E402

#: Where pinned downloads are kept, each checked against its sha256 on use.
CACHE = REPO / "third_party" / "compiler-cache"
#: Where the WebAssembly tools land, one directory per toolchain.
WASM_OUT = REPO / "third_party" / "wasm-toolchain" / "out"
#: The Docker recipe that makes them.
TOOLCHAIN_DIR = REPO / "tools" / "wasm_toolchain"
#: The bundle.
COMPILER = REPO / "build" / "compiler"
#: O_EXCL: one bundle build at a time.
LOCK = REPO / "build" / "compiler.lock"
#: `tests/webui/compile_wasm_runner.mjs`'s and the page's entry points.
STATIC = REPO / "webui" / "static"


class CompilerError(Exception):
    """The bundle could not be built, and why."""


#: plan.json's and manifest.json's shape; build.js's PLAN_FORMAT, which
#: refuses any other.
PLAN_FORMAT = 1


class Pinned(NamedTuple):
    """A download, by what it must hash to."""

    name: str
    url: str
    sha256: str
    size: int


#: What `build-avr.sh` compiles, under the names it expects in /src. From
#: github.com/arduino/toolchain-avr at 368b87a (tag 7.3.0-atmel3.6.1-arduino7):
#: build.conf names the GMP, MPFR and MPC versions and the Atmel source
#: directory; gcc.build.bash the gcc tarball and patch; binutils.build.bash
#: the binutils tarball and patch. MPC 0.9's own URL there is dead; this one
#: is its author's and hashes the same as GCC's infrastructure copy.
AVR_SOURCES: tuple[Pinned, ...] = (
    Pinned("gcc-7.3.0.tar.xz",
           "https://ftp.gnu.org/gnu/gcc/gcc-7.3.0/gcc-7.3.0.tar.xz",
           "832ca6ae04636adbb430e865a1451adf6979ab44ca1c8374f61fba65645ce15c", 62462388),
    Pinned("atmel-patches-gcc.7.3.0-arduino2.patch",
           "https://raw.githubusercontent.com/arduino/toolchain-avr/"
           "368b87a73e3677071fa44f2182c1ea4cc6a90557/avr-gcc-patches/"
           "atmel-patches-gcc.7.3.0-arduino2.patch",
           "96782c75dd11e994e1ab9250c41fc5cd81ba65bbcf44383cd9d660d01cc85f97", 107177),
    Pinned("avr-binutils.tar.bz2",
           "http://downloads.arduino.cc/tools/opensource/Atmel-AVR-GNU-Toolchain/"
           "3.6.1/avr-binutils.tar.bz2",
           "7f2ee50c3867ca13be47aee7925c4c9182b15cb5fe6ace23849ee9005081a340", 40602308),
    Pinned("00-binutils-data_region_length.patch",
           "https://raw.githubusercontent.com/arduino/toolchain-avr/"
           "368b87a73e3677071fa44f2182c1ea4cc6a90557/binutils-patches/"
           "00-binutils-data_region_length.patch",
           "d9e9f183bad9e1cfe27f3569163ccd3c39b1784b12978b47a2206eb31e2547e8", 1221),
    Pinned("gmp-5.0.2.tar.bz2", "https://ftp.gnu.org/gnu/gmp/gmp-5.0.2.tar.bz2",
           "dbc2db76fdd4e99f85d5e35aa378ed62c283e0d586b91bd8703aff75a7804c28", 2024576),
    Pinned("mpfr-3.1.0.tar.bz2", "https://ftp.gnu.org/gnu/mpfr/mpfr-3.1.0.tar.bz2",
           "74a7bbbad168dd1cc414f1c9210b8fc16ccfc8e422d34b3371a8978e31eab680", 1203891),
    Pinned("mpc-0.9.tar.gz", "https://www.multiprecision.org/downloads/mpc-0.9.tar.gz",
           "fd3efe422f0d454592059e80f2c00d1a2e381bf2beda424c5094abd4deb049ac", 565953),
)

#: Arduino's x86_64-linux build of the same release, from its package index.
AVR_RELEASE = Pinned(
    "avr-gcc-7.3.0-atmel3.6.1-arduino7-x86_64-pc-linux-gnu.tar.bz2",
    "https://downloads.arduino.cc/tools/"
    "avr-gcc-7.3.0-atmel3.6.1-arduino7-x86_64-pc-linux-gnu.tar.bz2",
    "bd8c37f6952a2130ac9ee32c53f6a660feb79bee8353c8e289eb60fdcefed91e", 37630618)

#: Arduino's AVR core, from its package index: framework-arduino-avr 5.4.0.
AVR_CORE = Pinned(
    "avr-1.8.8.tar.bz2", "https://downloads.arduino.cc/cores/staging/avr-1.8.8.tar.bz2",
    "a234c2a43dcd01ce54be665806f183b8e6ec4e966d2e3e0c3358b63023d6390c", 7162150)

#: avr-libc's source, for its licence text and as the source of the archives
#: AVR_RELEASE carries (avr-libc is BSD-licensed: offered, not owed).
AVR_LIBC = Pinned(
    "avr-libc.tar.bz2",
    "http://downloads.arduino.cc/tools/opensource/Atmel-AVR-GNU-Toolchain/3.6.1/avr-libc.tar.bz2",
    "8dd2a70c6fac96f151eaa1110c109b5579f4f75da76be08e8434475dab8ae575", 3142203)

#: The scripts AVR_RELEASE's libgcc was built by, which the GPL counts as part
#: of its corresponding source.
TOOLCHAIN_AVR = Pinned(
    "toolchain-avr-368b87a73e3677071fa44f2182c1ea4cc6a90557.tar.gz",
    "https://codeload.github.com/arduino/toolchain-avr/tar.gz/"
    "368b87a73e3677071fa44f2182c1ea4cc6a90557",
    "38a1b196d2774198c6b16f99e88c7c6af1103f52e7f621f4d620b6f681029b29", 881161)

#: The chip this bundle builds for, as `compile.RECIPES` keys it.
CHIP = "ATmega328P"
#: Where each tree sits in a tool's in-memory filesystem. PREFIX is what
#: build-avr.sh configured the tools with, so cc1plus finds its own headers
#: there with no -iprefix.
PREFIX = "/opt/avr"
ARDUINO = "/arduino-avr"
OBJECTS = "/objects"
GCC_VERSION = "7.3.0"
#: What the bundle's tools are called, by the key build.js knows them by.
#: (key, built file, name shown back to the page, argv[0])
#:
#: ld's argv[0] puts it BESIDE its ldscripts/ directory, because that is the
#: one place it will find its default script from. binutils 2.26's
#: find_scripts_dir (ld/ldfile.c) tries three directories, each made by
#: libiberty's make_relative_prefix from argv[0] alone: a bare name, under
#: Emscripten's PATH of "/", makes none; the installed /opt/avr/bin/avr-ld
#: makes nothing on the first try ("still installed in the standard
#: location") and /opt/avr/bin/../lib on the second, which MEMFS walks
#: component by component through a /opt/avr/bin no file is in. From
#: /opt/avr/avr/lib the second try is <that>/../lib and the third is
#: <that> -- both the directory holding ldscripts/. (Measured each way:
#: "cannot open linker script file ldscripts/avr5.xn".)
RUNTIME_TOOLS = (
    ("cc1plus", "cc1plus", "cc1plus", "cc1plus"),
    ("as", "avr-as", "avr-as", "as"),
    ("ld", "avr-ld", "avr-ld", f"{PREFIX}/avr/lib/avr-ld"),
    ("objcopy", "avr-objcopy", "avr-objcopy", "objcopy"),
)
#: What drive.mjs runs at bundle time as well: the two drivers and cc1. Each
#: is given its installed path as argv[0], for the reason ld is above: a
#: driver finds its device specs relative to it.
BUNDLE_TOOLS = ("avr-gcc", "avr-g++", "cc1")
#: The program a compile's driver names -> drive.mjs's tool key.
PROGRAMS = {"cc1": "cc1", "cc1plus": "cc1plus", "as": "as"}
#: The stand-ins build.js replaces: see its header.
LIBRARY_INCLUDES = "@LIBRARY_INCLUDES@"
OBJECTS_HERE = "@OBJECTS@"
#: How a stand-in reaches the driver: as an include directory, and as an
#: object file that has to exist for it to be accepted as one.
INCLUDE_SENTINEL = "/@LIBRARY_INCLUDES@"
OBJECT_SENTINEL = "/build/@OBJECTS@.o"
#: Where the sketch is, in a tool's filesystem: an absolute path OUTSIDE the
#: working directory (/build), as the server's is -- its temporary directory,
#: with the server's own directory as cwd. GCC quotes the offending source
#: line by reopening the name `#line` gave the file, "sketch.cpp", relative to
#: cwd; the server finds nothing there and quotes nothing. A sketch in the cwd
#: was found, and under an error on line 2 GCC quoted the preambled file's
#: line 2, which is the `#line` directive itself (measured).
SKETCH = "/sketch/sketch.cpp"


def sha256_of(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_pinned(pin: Pinned) -> pathlib.Path:
    """`pin`, in CACHE, checked; downloaded first when absent."""
    path = CACHE / pin.name
    if not path.is_file():
        CACHE.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".partial")
        print(f"fetching {pin.url}", file=sys.stderr)
        with urllib.request.urlopen(pin.url) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.replace(path)
    size, digest = path.stat().st_size, sha256_of(path)
    if (size, digest) != (pin.size, pin.sha256):
        raise CompilerError(
            f"{path}: expected {pin.size} bytes with sha256 {pin.sha256}, got {size} "
            f"bytes with {digest}. Delete it to fetch it again from {pin.url}")
    return path


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise CompilerError(f"{LOCK} exists: another bundle build is running, or one "
                            f"died; remove it if none is") from exc
    try:
        os.close(fd)
        yield
    finally:
        LOCK.unlink(missing_ok=True)


# --- the WebAssembly tools ------------------------------------------------------


def _toolchain_key() -> str:
    """What the tools are a function of: the recipe and every source's hash."""
    digest = hashlib.sha256()
    for name in ("Dockerfile", "build-avr.sh"):
        digest.update((TOOLCHAIN_DIR / name).read_bytes().replace(b"\r\n", b"\n"))
    for pin in AVR_SOURCES:
        digest.update(pin.sha256.encode())
    return digest.hexdigest()


#: The licence texts tools/wasm_toolchain/build-avr.sh copies out of the
#: Emscripten tree that linked the tools, into their licenses/: its runtime,
#: musl, and LLVM's libc++, libc++abi and compiler-rt.
EMSCRIPTEN_LICENCES = ("Emscripten-LICENSE.txt", "musl-COPYRIGHT.txt", "libcxx-LICENSE.txt",
                       "libcxxabi-LICENSE.txt", "compiler-rt-LICENSE.txt")


def _built_files() -> list[str]:
    """What the Docker build leaves in its output: each tool, and the licence
    texts of what Emscripten linked into them."""
    names = [built for _, built, _, _ in RUNTIME_TOOLS] + list(BUNDLE_TOOLS)
    return ([f"{name}{suffix}" for name in names for suffix in (".mjs", ".wasm")]
            + [f"licenses/{name}" for name in EMSCRIPTEN_LICENCES])


def wasm_tools() -> pathlib.Path:
    """The AVR tools as WebAssembly: built by Docker unless already built
    from exactly this recipe and these sources.

    The build tree is a Docker volume named for the same key, so a second
    run of an unchanged recipe resumes where the first stopped, and a changed
    recipe starts from nothing rather than from another recipe's stamps.
    """
    out = WASM_OUT / "avr"
    key = _toolchain_key()
    stamp = out / "BUILT"
    if (stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == key
            and all((out / name).is_file() for name in _built_files())):
        return out
    for pin in AVR_SOURCES:
        fetch_pinned(pin)
    docker = shutil.which("docker")
    if docker is None:
        raise CompilerError(
            "the WebAssembly avr-gcc is built in Docker (tools/wasm_toolchain/Dockerfile), "
            f"and there is no docker on PATH; or put tools built elsewhere from this same "
            f"recipe in {out} with a BUILT file reading {key}")
    out.mkdir(parents=True, exist_ok=True)
    stamp.unlink(missing_ok=True)
    image = f"openhardware/wasm-avr:{key[:12]}"
    subprocess.run([docker, "build", "-t", image, str(TOOLCHAIN_DIR)], check=True)
    subprocess.run([
        docker, "run", "--rm",
        "--mount", f"type=volume,source=openhardware-wasm-avr-{key[:12]},target=/build",
        "--mount", f"type=bind,source={CACHE},target=/src,readonly",
        "--mount", f"type=bind,source={out},target=/out",
        image,
    ], check=True)
    missing = [name for name in _built_files() if not (out / name).is_file()]
    if missing:
        raise CompilerError(f"the Docker build finished without {missing} in {out}")
    stamp.write_text(key + "\n", encoding="utf-8")
    return out


# --- the filesystem a tool sees -------------------------------------------------


def _read(archive: pathlib.Path, keep: Callable[[str], bool]) -> dict[str, bytes]:
    """Every regular member whose name `keep` accepts, in ONE pass.

    Opened as a stream on purpose: a .bz2 or .xz tar has no index, so a member
    fetched by name decompresses the archive again from its start, and this
    module's first draft spent minutes doing that once per header."""
    out: dict[str, bytes] = {}
    with tarfile.open(archive, "r|*") as tar:
        for member in tar:
            if member.isfile() and keep(member.name):
                handle = tar.extractfile(member)
                if handle is None:
                    raise CompilerError(f"{archive.name}: {member.name} cannot be read")
                out[member.name] = handle.read()
    return out


def _write(root: pathlib.Path, files: dict[str, bytes]) -> None:
    """Each in-memory path -> its bytes, under `root`."""
    for path, data in files.items():
        target = root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


#: The device macro, and not `-D__AVR_DEVICE_NAME__=atmega328p` beside it.
_DEVICE_MACRO = re.compile(r"-D(__AVR_\w+__)(?![=\w])")
_DEVICE_INCLUDE = re.compile(r"#\s*include\s*<(avr/io\w*\.h)>")


def _device_headers(include: dict[str, str], specs: str) -> set[str]:
    """The `avr/io*.h` an ATmega328P build can reach: the one `avr/io.h`
    picks by the device macro the specs file defines, and what that one
    includes. Every other device's header is left out -- there are hundreds,
    and no Uno sketch reads one. `include` is avr-libc's include tree by
    relative path."""
    macros = set(_DEVICE_MACRO.findall(specs))
    if len(macros) != 1:
        raise CompilerError(f"expected one device macro in the specs file, found {macros}")
    (macro,) = macros
    found = re.search(rf"defined\s*\({macro}\)\s*\n#\s*include\s*<(avr/io\w+\.h)>",
                      include["avr/io.h"])
    if found is None:
        raise CompilerError(f"avr/io.h names no header for {macro}")
    headers: set[str] = set()
    pending = [found.group(1)]
    while pending:
        name = pending.pop()
        if name not in headers:
            headers.add(name)
            pending += _DEVICE_INCLUDE.findall(include[name])
    return headers


def sysroot(root: pathlib.Path) -> tuple[list[str], list[str]]:
    """AVR_RELEASE's headers and link inputs under `root` at PREFIX, and the
    device specs file the bundle-time driver reads.

    Returns the header paths and the link inputs.
    """
    gcc = f"avr/lib/gcc/avr/{GCC_VERSION}"
    libc = "avr/avr/include/"
    specs = f"{gcc}/device-specs/specs-atmega328p"
    link = {f"avr/avr/lib/avr5/{n}": f"{PREFIX}/avr/lib/avr5/{n}"
            for n in ("crtatmega328p.o", "libc.a", "libm.a", "libatmega328p.a")}
    link[f"{gcc}/avr5/libgcc.a"] = f"{PREFIX}/lib/gcc/avr/{GCC_VERSION}/avr5/libgcc.a"
    # This ld reads its linker script from disk rather than having it
    # compiled in, from ldscripts/ under a -L directory the driver passes. The
    # recipe's link opens avr5.xn (measured: "cannot open linker script file
    # ldscripts/avr5.xn" without it), the same file as PlatformIO's.
    link["avr/avr/lib/ldscripts/avr5.xn"] = f"{PREFIX}/avr/lib/ldscripts/avr5.xn"
    found = _read(fetch_pinned(AVR_RELEASE), lambda name: name in link or name == specs
                  or name.startswith((libc, f"{gcc}/include/", f"{gcc}/include-fixed/")))
    absent = [name for name in (*link, specs) if name not in found]
    if absent:
        raise CompilerError(f"{AVR_RELEASE.name} has none of {absent}")
    devices = _device_headers(
        {name[len(libc):]: data.decode("latin-1") for name, data in found.items()
         if name.startswith(libc)},
        found[specs].decode("latin-1"))
    headers: dict[str, bytes] = {}
    for name, data in found.items():
        if name.startswith(libc):
            relative = name[len(libc):]
            if relative.startswith("avr/io") and relative != "avr/io.h" and relative not in devices:
                continue
            headers[f"{PREFIX}/avr/include/{relative}"] = data
        elif name.startswith(gcc) and name not in link and name != specs:
            headers[f"{PREFIX}/{name[len('avr/'):]}"] = data
    _write(root, {**headers, **{target: found[name] for name, target in link.items()},
                  f"{PREFIX}/{specs[len('avr/'):]}": found[specs]})
    return sorted(headers), sorted(link.values())


#: What the recipe compiles, and so what a sketch's compile never reads. Every
#: other file in the core, variant and libraries is a header: the core's `new`
#: has no suffix at all, and the server's compile finds it with the rest.
_SOURCE_SUFFIXES = (".c", ".cpp", ".S")


def arduino(root: pathlib.Path, recipe: compiler.Recipe) -> tuple[list[str], dict[str, str]]:
    """AVR_CORE's core, variant and libraries under `root` at ARDUINO.

    Returns the header paths (what cc1plus may read) and every source the
    recipe compiles, by its path relative to the framework root.
    """
    top = "ArduinoCore-avr-1.8.8/"
    trees = tuple(f"{top}{tree}/" for tree in
                  (recipe.core, recipe.variant, *(lib.include for lib in recipe.libraries)))
    found = _read(fetch_pinned(AVR_CORE), lambda name: name.startswith(trees))
    files = {f"{ARDUINO}/{name[len(top):]}": data for name, data in found.items()}
    _write(root, files)
    headers = [path for path in files if not path.endswith(_SOURCE_SUFFIXES)]
    sources = {s: f"{ARDUINO}/{recipe.core}/{s}" for s in recipe.core_sources}
    sources |= {s: f"{ARDUINO}/{s}" for lib in recipe.libraries for s in lib.sources}
    absent = [path for path in sources.values() if not (root / path.lstrip("/")).is_file()]
    if absent:
        raise CompilerError(f"{AVR_CORE.name} has none of {absent}, which the recipe compiles")
    return sorted(headers), sources


# --- the driver's commands --------------------------------------------------------


def _includes(recipe: compiler.Recipe, libraries: list[str]) -> list[str]:
    """`compile.build`'s `includes`: core, variant, then each wanted library's."""
    if recipe.extra_includes or recipe.bsp_includes or recipe.variant_package:
        raise CompilerError("this bundle builds recipes whose headers are all in their "
                            f"framework, and {CHIP}'s names more: {recipe}")
    return [f"-I{ARDUINO}/{recipe.core}", f"-I{ARDUINO}/{recipe.variant}",
            *(f"-I{include}" for include in libraries)]


def _compile_argv(recipe: compiler.Recipe, includes: list[str], source: str,
                  obj: str) -> tuple[str, list[str]]:
    """`compile.build`'s compile command for one source, as driver and argv."""
    cxx = source.endswith(".cpp")
    argv = ["-c", *recipe.flags, *includes, *(recipe.cxx_flags if cxx else ()),
            source, "-o", obj]
    return ("avr-g++" if cxx else "avr-gcc"), argv


def _object_path(source: str) -> str:
    """Where a source's object goes: by its whole name, because the core has
    both wiring_pulse.c and wiring_pulse.S."""
    return f"{OBJECTS}/{source.replace('/', '_')}.o"


def _compile_job(recipe: compiler.Recipe, includes: list[str], source: str, obj: str,
                 root: pathlib.Path) -> dict[str, object]:
    """One compile job for drive.mjs: `source` compiled in the tool's working
    directory, /build, which every instance has (drive.mjs mirrors the tree's
    files, so an empty directory of it does not exist in a tool), and kept at
    `obj` in the bundle. Where an object is written is not in its bytes."""
    built = posixpath.basename(obj)
    driver, argv = _compile_argv(recipe, includes, source, built)
    return {"driver": driver, "argv": argv, "object": f"/build/{built}",
            "host": str(root / obj.lstrip("/"))}


def _steady(ran: list[list[str]], built: str) -> list[list[str]]:
    """drive.mjs's record of one compile, with the driver's temporary assembly
    file -- a random /tmp/cc*.s -- named after the object instead, so the plan
    (and the bundle version hashed from it) is the same from run to run."""
    first = ran[0]
    temp = first[first.index("-o") + 1]
    steady = f"{posixpath.splitext(posixpath.basename(built))[0]}.s"
    return [[steady if arg == temp else arg for arg in command] for command in ran]


def _drive(job: dict[str, object], work: pathlib.Path) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        raise CompilerError("the core is compiled by the WebAssembly compiler under "
                            "node, and there is no node on PATH")
    job_path, result_path = work / "drive-job.json", work / "drive-result.json"
    job["result"] = str(result_path)
    job_path.write_text(json.dumps(job, indent=1), encoding="utf-8")
    done = subprocess.run([node, str(TOOLCHAIN_DIR / "drive.mjs"), str(job_path)],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise CompilerError(f"drive.mjs exited {done.returncode}:\n{done.stderr}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _collapse(argv: list[str], pair: tuple[str, str], token: str) -> list[str]:
    """`argv` with the one adjacent `pair` replaced by `token`."""
    hits = [i for i in range(len(argv) - 1) if (argv[i], argv[i + 1]) == pair]
    if len(hits) != 1:
        raise CompilerError(f"expected {pair} once in the driver's command, found it "
                            f"{len(hits)} times: {argv}")
    (at,) = hits
    return [*argv[:at], token, *argv[at + 2:]]


def chip_plan(tools: pathlib.Path, root: pathlib.Path, work: pathlib.Path,
              recipe: compiler.Recipe) -> tuple[dict[str, object], dict[str, pathlib.Path]]:
    """Compile the core and libraries into `root`, and expand the sketch's and
    the link's commands: the plan's entry for CHIP, and the objects made."""
    headers, link_files = sysroot(root)
    arduino_headers, sources = arduino(root, recipe)
    plain = _includes(recipe, [])
    compile_jobs: dict[str, object] = {}
    objects: dict[str, str] = {}
    for name in recipe.core_sources:
        objects[name] = _object_path(sources[name])
        compile_jobs[name] = _compile_job(recipe, plain, sources[name], objects[name], root)
    libraries = []
    for library in recipe.libraries:
        include = f"{ARDUINO}/{library.include}"
        own = []
        for name in library.sources:
            objects[name] = _object_path(sources[name])
            compile_jobs[name] = _compile_job(recipe, _includes(recipe, [include]),
                                              sources[name], objects[name], root)
            own.append(objects[name])
        libraries.append({"header": library.header, "include": include, "objects": own})
    (root / OBJECTS.lstrip("/")).mkdir(parents=True, exist_ok=True)

    sketch_driver, sketch_argv = _compile_argv(
        recipe, [*plain, f"-I{INCLUDE_SENTINEL}"], SKETCH, "00.o")
    # compile.build's link, and -fno-use-linker-plugin. A GCC configured
    # against a plugin-capable ld (build-avr.sh says why it is) hands ld the
    # LTO plugin by default, and the server's ld loads it; one in a tab
    # cannot, being a dlopen. In GCC 7's LINK_COMMAND_SPEC the flag removes
    # the -plugin and -plugin-opt arguments and nothing else, and a link with
    # no LTO object never calls the plugin, so the image is the same.
    link_argv = [*recipe.link_flags, "-fno-use-linker-plugin", OBJECT_SENTINEL,
                 "-o", "sketch.elf", "-lm"]
    job = {
        "tools": {key: {"glue": str(tools / f"{built}.mjs"), "wasm": str(tools / f"{built}.wasm"),
                        "program": program}
                  for key, built, _, program in RUNTIME_TOOLS}
                 | {name: {"glue": str(tools / f"{name}.mjs"), "wasm": str(tools / f"{name}.wasm"),
                           "program": f"{PREFIX}/bin/{name}"}
                    for name in BUNDLE_TOOLS},
        "fs": str(root),
        "programs": PROGRAMS,
        "expand": {
            "sketch": {"driver": sketch_driver, "argv": sketch_argv,
                       "placeholders": [SKETCH]},
            "link": {"driver": "avr-g++", "argv": link_argv, "placeholders": [OBJECT_SENTINEL]},
        },
        "compile": compile_jobs,
    }
    result = _drive(job, work)

    expanded_sketch = result["expanded"]["sketch"]
    names = [posixpath.basename(command[0]) for command in expanded_sketch]
    if names != ["cc1plus", "as"]:
        raise CompilerError(f"expected the sketch's compile to run cc1plus then as, got "
                            f"{names}: {expanded_sketch}")
    cc1plus_cmd, as_cmd = expanded_sketch
    assembly = cc1plus_cmd[cc1plus_cmd.index("-o") + 1]
    cc1plus = _collapse([("sketch.s" if a == assembly else a) for a in cc1plus_cmd[1:]],
                        ("-I", INCLUDE_SENTINEL), LIBRARY_INCLUDES)
    assemble = [("sketch.s" if a == assembly else a) for a in as_cmd[1:]]
    # The driver names collect2 only when it finds one, and LINKER_NAME's
    # fallback is ld itself, given what collect2 would have been -- which,
    # with no LTO, is what collect2 hands ld.
    (link_cmd,) = result["expanded"]["link"]
    if link_cmd[0] != "ld":
        raise CompilerError(f"expected the link to run ld, got {link_cmd}")
    ld = [OBJECTS_HERE if a == OBJECT_SENTINEL else a for a in link_cmd[1:]]
    if ld.count(OBJECTS_HERE) != 1:
        raise CompilerError(f"expected the objects once in the link, got {ld}")

    plan = {
        "base": recipe.base,
        "fs": "avr/fs",
        "sketch": SKETCH,
        "tools": {key: {"name": shown, "glue": f"avr/tools/{built}.mjs",
                        "wasm": f"avr/tools/{built}.wasm", "program": program}
                  for key, built, shown, program in RUNTIME_TOOLS},
        "headers": [*headers, *arduino_headers],
        "link_files": link_files,
        "objects": [objects[name] for name in recipe.core_sources],
        "libraries": libraries,
        "cc1plus": cc1plus,
        "as": assemble,
        "ld": ld,
        "objcopy": ["-O", "binary", "-R", ".eeprom", "sketch.elf", "sketch.bin"],
        "hints": [list(hint) for hint in recipe.hints],
        # compile._diagnostics' labels for the same files, so that a note in a
        # core header or a link error names it as the server's build would:
        # the server finds them under PACKAGES and its temporary directory,
        # the tools here under ARDUINO, PREFIX and /build.
        "labels": [[f"{ARDUINO}/", f"<toolchain>/{recipe.framework}/"],
                   [f"{PREFIX}/", f"<toolchain>/{recipe.toolchain}/"],
                   ["/build/", "<build>/"]],
        "driver": {"sketch": [sketch_driver, *sketch_argv], "link": ["avr-g++", *link_argv]},
        "precompiled": {name: _steady(ran, compile_jobs[name]["object"])  # type: ignore[index]
                        for name, ran in result["compiled"].items()},
    }
    return plan, {name: root / path.lstrip("/") for name, path in objects.items()}


# --- which boards -----------------------------------------------------------------


#: What a board whose chip's compiler is not in this bundle says, in the
#: Build button's place. The server can build it; this copy cannot.
BUILD_LOCALLY = (
    "{board}'s compiler is not in this browser copy of OpenHardware, which "
    "builds for {chips} only. Build it with the local server: "
    "python webui/emulator_server.py from a checkout."
)


def boards(chips: tuple[str, ...]) -> tuple[dict[str, str], dict[str, str]]:
    """Board -> chip for every catalogue board this bundle builds, and board ->
    reason for every one the server builds and this does not.

    Asked of `compile.recipe_for`, the predicate `/api/boards` uses for
    `buildable`, so this never offers a board the server would refuse. A
    board that is a row in tools/board_manifest.py gets a recipe of its own,
    which this bundle does not carry, so it is in the second list -- and a
    board whose recipe `recipe_for` refuses is in neither, since the server
    does not build it either.
    """
    buildable: dict[str, str] = {}
    refused: dict[str, str] = {}
    shown = ", ".join(chips)
    for board in board_catalogue.catalogue():
        if board.chip not in compiler.RECIPES:
            continue
        try:
            recipe = compiler.recipe_for(board.name)
        except compiler.UnknownBoard:
            continue
        if board.chip in chips and recipe == compiler.RECIPES[board.chip]:
            buildable[board.name] = board.chip
        else:
            refused[board.name] = BUILD_LOCALLY.format(board=board.name, chips=shown)
    return buildable, refused


# --- notices and source -------------------------------------------------------------


#: Licence texts, each from the source tarball it governs.
LICENCES = (
    ("gcc-7.3.0.tar.xz", "gcc-7.3.0/COPYING3", "GPL-3.0.txt"),
    ("gcc-7.3.0.tar.xz", "gcc-7.3.0/COPYING.RUNTIME", "GCC-runtime-library-exception-3.1.txt"),
    ("gcc-7.3.0.tar.xz", "gcc-7.3.0/COPYING.LIB", "LGPL-2.1.txt"),
    ("gcc-7.3.0.tar.xz", "gcc-7.3.0/COPYING3.LIB", "LGPL-3.0.txt"),
    ("avr-libc.tar.bz2", "libc/avr-libc/LICENSE", "avr-libc-LICENSE.txt"),
)

NOTICE = """The compiler in this copy of OpenHardware
=======================================

The page fetches what is listed below the first time Build is pressed, and
compiles sketches with it in your browser tab. It is free software; these are
its terms, and source/ beside this file is its source. The page never fetches
anything in source/.

avr/tools/cc1plus.*
    GCC 7.3.0's C++ compiler for AVR, compiled to WebAssembly, with GMP 5.0.2,
    MPFR 3.1.0 and MPC 0.9 linked into it, and GCC's own libbacktrace and copy
    of zlib.
    Licence: GPL-3.0-or-later (GCC); LGPL-3.0-or-later (GMP, MPFR);
    LGPL-2.1-or-later (MPC); BSD-3-Clause (libbacktrace, whose notice is
    licenses/libbacktrace-LICENSE.txt); the zlib licence (zlib).
    Source: source/gcc-7.3.0.tar.xz with
    source/atmel-patches-gcc.7.3.0-arduino2.patch; source/gmp-5.0.2.tar.bz2,
    source/mpfr-3.1.0.tar.bz2, source/mpc-0.9.tar.gz.

avr/tools/avr-as.*, avr/tools/avr-ld.*, avr/tools/avr-objcopy.*
    GNU binutils 2.26.20160125, Atmel's AVR toolchain 3.6.1 snapshot,
    compiled to WebAssembly, with binutils' own copy of zlib.
    Licence: GPL-3.0-or-later; the zlib licence (zlib).
    Source: source/avr-binutils.tar.bz2 with
    source/00-binutils-data_region_length.patch.

avr/fs/opt/avr/lib/gcc/
    GCC 7.3.0's own headers and runtime library (libgcc.a) for AVR, from
    Arduino's 7.3.0-atmel3.6.1-arduino7 release.
    Licence: GPL-3.0-or-later with the GCC Runtime Library Exception 3.1.
    Source: source/gcc-7.3.0.tar.xz with the patch above, built by the
    scripts in source/toolchain-avr-368b87a73e3677071fa44f2182c1ea4cc6a90557.tar.gz;
    the release itself is source/avr-gcc-7.3.0-atmel3.6.1-arduino7-x86_64-pc-linux-gnu.tar.bz2.

avr/fs/opt/avr/avr/
    avr-libc 2.0.0's headers, start file and libraries, from the same release.
    Licence: modified BSD; see licenses/avr-libc-LICENSE.txt.
    Source: source/avr-libc.tar.bz2.

avr/fs/opt/avr/avr/lib/ldscripts/avr5.xn
    binutils' linker script for the ATmega328P's family, from the same
    release.
    Licence: the FSF's all-permissive notice, in the file.
    Source: source/avr-binutils.tar.bz2, which generates it.

avr/fs/arduino-avr/, avr/fs/objects/
    The Arduino AVR core 1.8.8's headers, and its sources compiled by the
    compiler above.
    Licence: LGPL-2.1-or-later, except where a file says otherwise, and these
    do: the SPI library is offered under GPL-2.0 or LGPL-2.1, at your choice;
    cores/arduino/USBCore.h and USBDesc.h carry Peter Barrett's ISC-style
    permission, and Udp.h the MIT licence, each in the file. new.h states
    none.
    Source: source/avr-1.8.8.tar.bz2.

How the WebAssembly was made: source/openhardware/ holds the scripts.
Dockerfile and build-avr.sh compile the sources above with Emscripten 5.0.3;
build_compiler.py and drive.mjs lay this directory out and compile the core;
build.js and worker.js run it in the page. They are OpenHardware's own,
MIT-licensed, and `python tools/build_compiler.py` in a checkout runs them.

Each tool also carries what Emscripten 5.0.3 linked into it: Emscripten's
runtime, which is the .mjs file (MIT or NCSA), musl (MIT), and LLVM's
libc++, libc++abi and compiler-rt (Apache-2.0 WITH LLVM-exception).

licenses/ holds the licence texts: GPL-3.0, the GCC Runtime Library
Exception 3.1, LGPL-2.1, LGPL-3.0, avr-libc's, libbacktrace's, and
Emscripten's, musl's, libc++'s, libc++abi's and compiler-rt's.

An image built here links the Arduino core (LGPL-2.1-or-later, and SPI's
GPL-2.0 or LGPL-2.1 if the sketch includes it), avr-libc
(modified BSD) and libgcc (whose exception puts no condition on the image).
The image stays in your tab; if you distribute one, the core's part of it
comes with the LGPL's conditions.
"""


#: Licences stated only in a source file's opening comment, which is what is
#: written out: GCC's libbacktrace, which cc1plus links, has no licence file of
#: its own, and its BSD terms ask that a binary carry the notice.
LEADING_COMMENTS = (
    ("gcc-7.3.0.tar.xz", "gcc-7.3.0/libbacktrace/backtrace.h", "libbacktrace-LICENSE.txt"),
)

#: What NOTICE.txt opens with in a bundle built without source/.
NOT_FOR_DISTRIBUTION = """THIS COPY HAS NO source/ AND MAY NOT BE PUBLISHED. It was built with
--no-sources, for tests; python tools/build_compiler.py without it builds
one that carries the source the licences below ask for.

"""


def _leading_comment(data: bytes, member: str) -> bytes:
    """The text of the comment `data` opens with."""
    text = data.decode("utf-8")
    if not text.startswith("/*") or "*/" not in text:
        raise CompilerError(f"{member} does not open with a comment to take its licence from: "
                            f"it starts {text[:40]!r}")
    return (text[2:text.index("*/")].strip() + "\n").encode("utf-8")


def notices(out: pathlib.Path, tools: pathlib.Path, sources: bool) -> None:
    """NOTICE.txt, licenses/, and with `sources`, source/."""
    (out / "NOTICE.txt").write_text(NOTICE if sources else NOT_FOR_DISTRIBUTION + NOTICE,
                                    encoding="utf-8")
    licences = out / "licenses"
    licences.mkdir()
    for name in EMSCRIPTEN_LICENCES:
        shutil.copyfile(tools / "licenses" / name, licences / name)
    for archive_name in dict.fromkeys(name for name, _, _ in (*LICENCES, *LEADING_COMMENTS)):
        whole = {member: target for name, member, target in LICENCES if name == archive_name}
        comments = {member: target for name, member, target in LEADING_COMMENTS
                    if name == archive_name}
        found = _read(CACHE / archive_name, lambda member: member in whole or member in comments)
        absent = sorted((set(whole) | set(comments)) - set(found))
        if absent:
            raise CompilerError(f"{archive_name} has none of {absent}")
        for member, target in whole.items():
            (licences / target).write_bytes(found[member])
        for member, target in comments.items():
            (licences / target).write_bytes(_leading_comment(found[member], member))
    if not sources:
        return
    source = out / "source"
    source.mkdir()
    for pin in (*AVR_SOURCES, AVR_RELEASE, AVR_CORE, AVR_LIBC, TOOLCHAIN_AVR):
        shutil.copyfile(fetch_pinned(pin), source / pin.name)
    ours = source / "openhardware"
    ours.mkdir()
    for path in (TOOLCHAIN_DIR / "Dockerfile", TOOLCHAIN_DIR / "build-avr.sh",
                 TOOLCHAIN_DIR / "drive.mjs", pathlib.Path(__file__),
                 STATIC / "compiler" / "build.js", STATIC / "compiler" / "worker.js"):
        shutil.copyfile(path, ours / path.name)


# --- the whole thing ------------------------------------------------------------------


def _manifest(out: pathlib.Path, plan: dict[str, object]) -> dict[str, object]:
    """Every file the page may fetch, with its size and hash, and which ones
    each chip's build reads."""
    files: dict[str, list[object]] = {}
    chips: dict[str, list[str]] = {}
    for chip, entry in plan["chips"].items():  # type: ignore[union-attr]
        wanted = [path for tool in entry["tools"].values() for path in (tool["glue"], tool["wasm"])]
        wanted += [f"{entry['fs']}{path}" for path in
                   (*entry["headers"], *entry["link_files"], *entry["objects"],
                    *(o for library in entry["libraries"] for o in library["objects"]))]
        chips[chip] = wanted
        for path in wanted:
            target = out / path
            files[path] = [target.stat().st_size, sha256_of(target)]
    files["plan.json"] = [(out / "plan.json").stat().st_size, sha256_of(out / "plan.json")]
    version = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16]
    total = sum(size for size, _ in files.values())
    return {"format": PLAN_FORMAT, "version": version, "total": total, "files": files,
            "chips": chips}


def build(*, sources: bool = True) -> dict[str, object]:
    """The bundle, into COMPILER, replacing it whole. Returns its manifest."""
    out = COMPILER
    with _locked():
        tools = wasm_tools()
        for pin in (*AVR_SOURCES, AVR_RELEASE, AVR_CORE, AVR_LIBC, TOOLCHAIN_AVR):
            fetch_pinned(pin)
        partial = out.with_name(out.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        with tempfile.TemporaryDirectory(prefix="openhardware-compiler-") as scratch:
            work = pathlib.Path(scratch)
            root = work / "fs"
            entry, _ = chip_plan(tools, root, work, compiler.RECIPES[CHIP])
            fs = partial / entry["fs"]  # type: ignore[operator]
            for path in (*entry["headers"], *entry["link_files"], *entry["objects"],  # type: ignore[misc]
                         *(o for library in entry["libraries"] for o in library["objects"])):  # type: ignore[union-attr]
                target = fs / path.lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / path.lstrip("/"), target)
        (partial / "avr" / "tools").mkdir(parents=True)
        for _, built, _, _ in RUNTIME_TOOLS:
            for suffix in (".mjs", ".wasm"):
                shutil.copyfile(tools / f"{built}{suffix}", partial / "avr" / "tools" / f"{built}{suffix}")
        buildable, refused = boards((CHIP,))
        plan = {
            "format": PLAN_FORMAT,
            "budget_seconds": compiler.BUILD_BUDGET_SECONDS,
            "preamble": compiler.ARDUINO_PREAMBLE,
            "max_source_bytes": compiler.MAX_SOURCE_BYTES,
            "boards": buildable,
            "refused": refused,
            "chips": {CHIP: entry},
        }
        (partial / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
        (partial / "boards.json").write_text(
            json.dumps({"buildable": sorted(buildable), "refused": refused}, indent=1),
            encoding="utf-8")
        manifest = _manifest(partial, plan)
        (partial / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        notices(partial, tools, sources)
        shutil.rmtree(out, ignore_errors=True)
        partial.replace(out)
        return manifest


# --- the post-step, until tools/build_site.py does this itself -----------------------

#: How the page loads the compiler: after the transport, which it wraps.
COMPILE_SCRIPT = '<script src="inpage/compile.js"></script>'


#: Where the post-step writes its copy of build/site.
SITE_WITH_COMPILER = REPO / "build" / "site-with-compiler"


def install_into_site() -> pathlib.Path:
    """A copy of the site tools/build_site.py built, with the bundle and
    `inpage/compile.js` in it and its index.html adapted to match.

    **A stand-in, and temporary.** tools/build_site.py is OH-238's chain's
    until OH-243 is done; its owner asked that nothing be added to it until
    then, and agreed to this over its output in the meantime. When it is
    handed over, these lines become one PAGE_FILES entry, one ADAPTATION and
    a call to `build`, and this function goes.

    A COPY, and not build/site itself: tests/webui/test_site_browser.py holds
    build/site to the page OH-239 shipped, whose Build button says it needs
    the local server, and both pages are right until build_site.py has these
    lines.
    """
    from tools import build_site  # read for its anchors, never written

    if not (build_site.SITE / "index.html").is_file():
        raise CompilerError(f"no site at {build_site.SITE}: python tools/build_site.py first")
    # A site is published, and publishing the compiler is distributing GPL
    # object code, which must carry its source.
    if not (COMPILER / "source").is_dir():
        raise CompilerError(f"{COMPILER} has no source/: it was built with --no-sources, for "
                            "tests, and may not go into a site. Build it again without.")
    buildable = json.loads((COMPILER / "boards.json").read_text(encoding="utf-8"))["buildable"]
    if not buildable:
        raise CompilerError(f"{COMPILER / 'boards.json'} names no board this bundle builds")
    site = SITE_WITH_COMPILER.with_name(SITE_WITH_COMPILER.name + ".partial")
    shutil.rmtree(site, ignore_errors=True)
    shutil.copytree(build_site.SITE, site)
    index = site / "index.html"
    html = index.read_text(encoding="utf-8")
    adaptations = (
        (build_site.TRANSPORT_SCRIPT, f"{build_site.TRANSPORT_SCRIPT}\n{COMPILE_SCRIPT}"),
        # Still disabled in the page: inpage/compile.js enables it for a board
        # it builds once the picker is filled, which emulator.js does not
        # reflect (BUILD_BUTTON_HERE's comment). Without the script, it stays off.
        (build_site.BUILD_BUTTON_HERE,
         '<button id="sketch-build" class="primary" disabled title="Waiting for the board list">'),
        (build_site.SKETCH_REPORT_HERE,
         '<span class="note" id="sketch-report">Builds in this tab. The first '
         'build fetches the compiler, once.</span>'),
        ("It cannot compile a\n    sketch, which needs a toolchain; for that, run\n"
         "    <code>python webui/emulator_server.py</code> from a checkout.",
         f"It compiles a sketch\n    for the {', '.join(buildable)} in this tab, fetching "
         "its compiler the first\n    time Build is pressed (<a href=\"compiler/NOTICE.txt\">its "
         "licences and source</a>);\n    for any other board, run "
         "<code>python webui/emulator_server.py</code> from a checkout."),
    )
    for anchor, _ in adaptations:
        count = html.count(anchor)
        if count != 1:
            raise CompilerError(f"{index} carries {anchor!r} {count} times; the post-step "
                                f"expects it exactly once")
    for anchor, replacement in adaptations:
        html = html.replace(anchor, replacement)
    shutil.copytree(COMPILER, site / "compiler")
    for name in ("build.js", "worker.js"):
        shutil.copyfile(STATIC / "compiler" / name, site / "compiler" / name)
    shutil.copyfile(STATIC / "inpage" / "compile.js", site / "inpage" / "compile.js")
    index.write_text(html, encoding="utf-8")
    shutil.rmtree(SITE_WITH_COMPILER, ignore_errors=True)
    site.replace(SITE_WITH_COMPILER)
    return SITE_WITH_COMPILER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--site", action="store_true",
                        help=f"and write {SITE_WITH_COMPILER.relative_to(REPO)}: build/site "
                             "with the compiler in it (the post-step)")
    parser.add_argument("--no-sources", action="store_true",
                        help="leave out source/: for a build only tests read")
    args = parser.parse_args(argv)
    # Refused before building: the build would replace a publishable bundle
    # with one install_into_site then refuses.
    if args.site and args.no_sources:
        parser.error("--site publishes the bundle, which then must carry source/: "
                     "drop --no-sources")
    try:
        manifest = build(sources=not args.no_sources)
        site = install_into_site() if args.site else None
    except CompilerError as exc:
        print(f"build_compiler: {exc}", file=sys.stderr)
        return 1
    print(f"{COMPILER}: {len(manifest['files'])} files the page may fetch, "  # type: ignore[arg-type]
          f"{manifest['total'] / 1e6:.1f} MB, version {manifest['version']}")
    if site is not None:
        print(f"{site}: python -m http.server -d {site.parent} 8123, then "
              f"http://127.0.0.1:8123/{site.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
