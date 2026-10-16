#!/usr/bin/env python3
# OpenHardware - the compiler the static page builds sketches with (OH-244).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""One command -> `build/compiler/`, the compiler a static copy of the page
fetches when Build is pressed.

    python tools/build_compiler.py          # build/compiler/

`tools/build_site.py` runs this and copies the result into the site's
`compiler/`; running it alone is for working on the compiler.

## What it is for

`webui/compile.py` builds a sketch with PlatformIO's GCCs, in a subprocess,
on the machine the server runs on. A copy of the page served as files has no
such machine. This builds the same compilers for WebAssembly, from the same
sources, and lays out everything one build reads -- headers, libraries, the
Arduino core already compiled, and the exact command lines -- so
`webui/static/compiler/build.js` can do in a tab what `compile.build` does on
the server, and get the same bytes. `tests/webui/test_compile_wasm.py` holds
it to that, chip by chip.

## The sources, and why these

Each chip's are whoever built what the server runs, pinned by sha256, so a
build here is one of the same sources and not of a lookalike (measured
2026-10-16):

- **ATmega328P.** PlatformIO's toolchain-atmelavr 3.70300.220127 has the
  same cc1plus, cc1, as, ld and objcopy, byte for byte, as Arduino's
  7.3.0-atmel3.6.1-arduino7 release; the same avr-libc archives member for
  member; and a libgcc.a that differs only in debug relocations. Its
  framework-arduino-avr 5.4.0 is Arduino's avr-1.8.8 file for file in every
  file the recipe reads. So: `AVR_SOURCES`, what Arduino's toolchain-avr
  scripts build that release from; `AVR_RELEASE`, Arduino's own build of it,
  for the headers and libraries a link reads; `AVR_CORE`, the core.
- **SAMD21.** PlatformIO's toolchain-gccarmnoneeabi 1.120301.0 is xPack's
  GNU Arm Embedded GCC 12.3.1-1.2, whose every header and Cortex-M0+ library
  is byte for byte the ones in xPack's win32-x64 release, and NOT Arm's own
  12.3.Rel1 binaries, whose libraries differ. xPack builds it from Arm's
  12.3.Rel1 component archives. So: `ARM_SOURCES`, those archives;
  `XPACK_RELEASE`, xPack's build, for the headers and libraries; Arduino's
  SAMD core 1.8.14 and Arm's CMSIS 6.3.0, which are PlatformIO's
  framework-arduino-samd and framework-cmsis file for file; Seeed's own 1.8.6
  release for the XIAO's variant; and PlatformIO's framework-cmsis-atmel
  1.2.2 itself, which no upstream release matches.

## What it costs, and what is never fetched

The page fetches what `manifest.json` lists for a chip, once, on the first
Build press, and keeps it in Cache Storage. `source/` -- every source tarball,
patch and script above, about 306 MB -- is laid down beside it for the GPL's
sake and is never fetched by the page; `--no-sources` leaves it out of a
build meant only for testing, and `tools/build_site.py` never asks for that.

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
import zipfile
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
PLAN_FORMAT = 2


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

#: What `build-arm.sh` compiles: Arm's own archives for its 12.3.Rel1, which
#: xPack's scripts/versioning.sh at 2fcd97d (tag v12.3.1-1.2) names for GCC,
#: and GMP, MPFR and MPC at the versions xPack's distro-info/licenses lists.
#: xPack takes binutils from a fork tag, binutils-2.40-arm-none-eabi-12.3.rel1,
#: whose every file in bfd, gas, ld, binutils, opcodes, libiberty, include,
#: libctf, libsframe, zlib and config is this archive's (25865 of 25865).
ARM_SOURCES: tuple[Pinned, ...] = (
    Pinned("arm-12.3.rel1-gcc.tar.xz",
           "https://developer.arm.com/-/media/Files/downloads/gnu/12.3.rel1/src/gcc.tar.xz",
           "eb7e241fdd672fa008194580bb030c6de894c25a3c9d27d657c1470f83d06648", 81440272),
    Pinned("arm-12.3.rel1-binutils-gdb.tar.xz",
           "https://developer.arm.com/-/media/Files/downloads/gnu/12.3.rel1/src/binutils-gdb.tar.xz",
           "7dfbc766ae491c6762025086ccbff006c6a8ef4081a790c9a92f815d6ca8c7c7", 35918700),
    Pinned("gmp-6.2.1.tar.xz", "https://ftp.gnu.org/gnu/gmp/gmp-6.2.1.tar.xz",
           "fd4829912cddd12f84181c3451cc752be224643e87fac497b69edddadc49b4f2", 2027316),
    Pinned("mpfr-3.1.6.tar.xz", "https://ftp.gnu.org/gnu/mpfr/mpfr-3.1.6.tar.xz",
           "7a62ac1a04408614fccdc506e4844b10cf0ad2c2b1677097f8f35d3a1344a950", 1133672),
    Pinned("mpc-1.0.3.tar.gz", "https://ftp.gnu.org/gnu/mpc/mpc-1.0.3.tar.gz",
           "617decc6ea09889fb08ede330917a00b16809b8db88c29c31bfbb49cbf88ecc3", 669925),
    # GCC's own fix for PR 111632, from its 12 branch (a995fded, in 12.4):
    # 12.3's system.h includes safe-ctype.h before the C++ headers, whose
    # ctype macros then break libc++'s <locale>, which is Emscripten's. This
    # is the whole file at that commit; it differs from the archive's by that
    # fix alone, which build-arm.sh checks before putting it in place.
    Pinned("gcc-12-a995fded34fe-system.h",
           "https://raw.githubusercontent.com/gcc-mirror/gcc/"
           "a995fded34fe488153b06bb41e026277f01efded/gcc/system.h",
           "63ead0bed549944c03e0bef727b1bcbbf1f4b51c691902aa55691767d6bb16d1", 41833),
)

#: xPack's own build, for the headers, start files and libraries a link
#: reads. Its executables are unused. The win32-x64 one, because its archives
#: are PlatformIO's byte for byte and the linux-x64 one's are not (stripped).
XPACK_RELEASE = Pinned(
    "xpack-arm-none-eabi-gcc-12.3.1-1.2-win32-x64.zip",
    "https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v12.3.1-1.2/"
    "xpack-arm-none-eabi-gcc-12.3.1-1.2-win32-x64.zip",
    "cb5e2be31fcfc7c78390041efc5602f22266f21ed968443827898fa4c47c6f20", 261121947)

#: The scripts XPACK_RELEASE's libraries were built by (MIT), and newlib's
#: source, which those libraries are (newlib's licences ask nothing of a
#: binary's distributor but notice; offered, as avr-libc's is).
XPACK_SCRIPTS = Pinned(
    "arm-none-eabi-gcc-xpack-2fcd97d20c3f459fd4d7068d7d69954f7352ea44.tar.gz",
    "https://codeload.github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/tar.gz/"
    "2fcd97d20c3f459fd4d7068d7d69954f7352ea44",
    "9071e8f172f99d227bf703285ec7068fccedeeefe6f09f1ecb387ab72975ac86", 2139594)
#: What those scripts call to configure and build each component, and the GCC
#: patch they apply (patches/gcc-12.3.1-cross.git.patch): xPack's xbb-helper
#: (MIT). Their package.json asks for ^2.0.1 of it; 2.0.1 was published on
#: 2023-09-20 and 2.0.2 on 2023-11-08, and the release's archives were made on
#: 2023-09-21, so 2.0.1 is the only version the build could have installed.
#: npm's own integrity for it is this file's sha512.
XBB_HELPER = Pinned(
    "xbb-helper-2.0.1.tgz",
    "https://registry.npmjs.org/@xpack-dev-tools/xbb-helper/-/xbb-helper-2.0.1.tgz",
    "fb7065a4a70be783a3e0f54469a2f4296e1a8ddaec2b04391a83e9c6ecfaf0dc", 249042)
NEWLIB = Pinned(
    "arm-12.3.rel1-newlib-cygwin.tar.xz",
    "https://developer.arm.com/-/media/Files/downloads/gnu/12.3.rel1/src/newlib-cygwin.tar.xz",
    "d387442c0e42db33669922d0e7ebdf72511bbf5ac801a8865e49488cc9f5c4e7", 7231256)

#: Arduino's SAMD core, from its package index: framework-arduino-samd 1.8.14,
#: file for file in cores/arduino, libraries/SPI and libraries/Wire.
SAMD_CORE = Pinned(
    "core-ArduinoCore-samd-1.8.14.tar.bz2",
    "https://downloads.arduino.cc/cores/staging/core-ArduinoCore-samd-1.8.14.tar.bz2",
    "bbb35d6edd6e57e13d29e7dcc9975fb605e180fc36b451b890d36820300a023b", 3061758)
#: Arm's CMSIS 6.3.0: framework-cmsis 2.60300.0's CMSIS/Core/Include, file
#: for file. A .pack is a zip.
CMSIS = Pinned(
    "ARM.CMSIS.6.3.0.pack",
    "https://github.com/ARM-software/CMSIS_6/releases/download/v6.3.0/ARM.CMSIS.6.3.0.pack",
    "63dcb5808bf172c53fd1eee014156985dac989e931a2dbd091f83d862d17c8bc", 8496225)
#: PlatformIO's framework-cmsis-atmel 1.2.2, from its registry: no upstream
#: release is these bytes. Arduino's CMSIS-Atmel 1.2.0, the nearest, differs
#: in samd21g18a.h, which every build reads: it defines LITTLE_ENDIAN without
#: the `#ifndef` around it that 1.2.2 adds.
CMSIS_ATMEL = Pinned(
    "framework-cmsis-atmel-1.2.2.tar.gz",
    "https://dl.registry.platformio.org/download/platformio/tool/framework-cmsis-atmel/1.2.2/"
    "framework-cmsis-atmel-1.2.2.tar.gz",
    "de7778f049e2558e1c8dbb50478f47c5680d4b393bc49e702203ffdd7a6ca60c", 4146988)
#: Seeed's SAMD core 1.8.6, from Seeed's own package index, for the XIAO's
#: variant: its variants/XIAO_m0 is third_party/bsp/seeed-samd's at 2e6b174
#: (tag v1.8.6), file for file once that Windows checkout's CRLFs are LFs.
SEEED_SAMD = Pinned(
    "ArduinoCore-samd-1.8.6.tar.bz2",
    "https://files.seeedstudio.com/arduino/core/samd/ArduinoCore-samd-1.8.6.tar.bz2",
    "8daf5aec9d3e424775cd79cfee2834f81ea14211190e4ceac1652e078a69a13a", 3516211)


#: What the bundle reads, or carries in its source/, besides each toolchain's
#: sources, which wasm_tools fetches. Every one but XPACK_RELEASE goes into
#: source/: that one is 261 MB of executables this bundle does not run, and
#: what it is built from is ARM_SOURCES, NEWLIB and XPACK_SCRIPTS.
BUNDLE_PINS = (AVR_RELEASE, AVR_CORE, AVR_LIBC, TOOLCHAIN_AVR, XPACK_RELEASE, XPACK_SCRIPTS,
               XBB_HELPER, NEWLIB, SAMD_CORE, CMSIS, CMSIS_ATMEL, SEEED_SAMD)


class Toolchain(NamedTuple):
    """A GCC built for WebAssembly by one script in tools/wasm_toolchain."""

    #: Its folder in WASM_OUT and in the bundle, and its Docker volume's name.
    name: str
    script: str
    #: What the script compiles, laid out in /src under each pin's name.
    sources: tuple[Pinned, ...]
    #: What its tools were configured with: cc1plus finds its own headers under
    #: it, so the files a build reads are laid out there.
    prefix: str
    #: What its tools' names start with: avr-as, arm-none-eabi-as.
    target: str
    gcc_version: str


AVR = Toolchain("avr", "build-avr.sh", AVR_SOURCES, "/opt/avr", "avr", "7.3.0")
ARM = Toolchain("arm", "build-arm.sh", ARM_SOURCES, "/opt/arm", "arm-none-eabi", "12.3.1")
TOOLCHAINS = (AVR, ARM)

#: Where the compiled core and libraries sit in a tool's filesystem, and
#: where the Uno's Arduino core does.
OBJECTS = "/objects"
ARDUINO = "/arduino-avr"


def runtime_tools(toolchain: Toolchain) -> tuple[tuple[str, str, str, str], ...]:
    """What the page runs, by the key build.js knows each by:
    (key, built file, name shown back to the page, argv[0]).

    ld's argv[0] puts it BESIDE its ldscripts/ directory, because that is the
    one place it will find its default script from. binutils 2.26's
    find_scripts_dir (ld/ldfile.c) tries three directories, each made by
    libiberty's make_relative_prefix from argv[0] alone: a bare name, under
    Emscripten's PATH of "/", makes none; the installed /opt/avr/bin/avr-ld
    makes nothing on the first try ("still installed in the standard
    location") and /opt/avr/bin/../lib on the second, which MEMFS walks
    component by component through a /opt/avr/bin no file is in. From
    /opt/avr/avr/lib the second try is <that>/../lib and the third is
    <that> -- both the directory holding ldscripts/. (Measured each way:
    "cannot open linker script file ldscripts/avr5.xn".) The SAMD21's link
    names its own script, but its ld is given the same argv[0], since 2.40's
    find_scripts_dir is the same function.
    """
    target = toolchain.target
    return (
        ("cc1plus", "cc1plus", "cc1plus", "cc1plus"),
        ("as", f"{target}-as", f"{target}-as", "as"),
        ("ld", f"{target}-ld", f"{target}-ld", f"{toolchain.prefix}/{target}/lib/{target}-ld"),
        ("objcopy", f"{target}-objcopy", f"{target}-objcopy", "objcopy"),
    )


def bundle_tools(toolchain: Toolchain) -> tuple[str, ...]:
    """What drive.mjs runs at bundle time as well: the two drivers and cc1.
    Each is given its installed path as argv[0], for the reason ld is: a
    driver finds its specs relative to it."""
    return (f"{toolchain.target}-gcc", f"{toolchain.target}-g++", "cc1")


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


def _text_of(name: str) -> bytes:
    """A file of TOOLCHAIN_DIR as a checkout on any OS gives it to Docker."""
    return (TOOLCHAIN_DIR / name).read_bytes().replace(b"\r\n", b"\n")


def _toolchain_key(toolchain: Toolchain) -> str:
    """What a toolchain's tools are a function of: the image, its script, and
    every source's hash. Not the other toolchain's script, which the image
    carries and this build never runs."""
    digest = hashlib.sha256()
    for name in ("Dockerfile", toolchain.script):
        digest.update(_text_of(name))
    for pin in toolchain.sources:
        digest.update(pin.sha256.encode())
    return digest.hexdigest()


def _image_key() -> str:
    """What the image is a function of: the Dockerfile and every script it copies."""
    digest = hashlib.sha256()
    for name in ("Dockerfile", *(toolchain.script for toolchain in TOOLCHAINS)):
        digest.update(_text_of(name))
    return digest.hexdigest()


#: The licence texts each script in tools/wasm_toolchain copies out of the
#: Emscripten tree that linked the tools, into their licenses/: its runtime,
#: musl, and LLVM's libc++, libc++abi and compiler-rt.
EMSCRIPTEN_LICENCES = ("Emscripten-LICENSE.txt", "musl-COPYRIGHT.txt", "libcxx-LICENSE.txt",
                       "libcxxabi-LICENSE.txt", "compiler-rt-LICENSE.txt")


def _built_files(toolchain: Toolchain) -> list[str]:
    """What the Docker build leaves in its output: each tool, and the licence
    texts of what Emscripten linked into them."""
    names = [built for _, built, _, _ in runtime_tools(toolchain)] + list(bundle_tools(toolchain))
    return ([f"{name}{suffix}" for name in names for suffix in (".mjs", ".wasm")]
            + [f"licenses/{name}" for name in EMSCRIPTEN_LICENCES])


def wasm_tools(toolchain: Toolchain) -> pathlib.Path:
    """`toolchain`'s tools as WebAssembly: built by Docker unless already
    built from exactly this recipe and these sources.

    The build tree is a Docker volume named for the same key, so a second
    run of an unchanged recipe resumes where the first stopped, and a changed
    recipe starts from nothing rather than from another recipe's stamps.
    """
    out = WASM_OUT / toolchain.name
    key = _toolchain_key(toolchain)
    stamp = out / "BUILT"
    if (stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == key
            and all((out / name).is_file() for name in _built_files(toolchain))):
        return out
    for pin in toolchain.sources:
        fetch_pinned(pin)
    docker = shutil.which("docker")
    if docker is None:
        raise CompilerError(
            f"the WebAssembly {toolchain.target}-gcc is built in Docker "
            f"(tools/wasm_toolchain/Dockerfile), and there is no docker on PATH; or put "
            f"tools built elsewhere from this same recipe in {out} with a BUILT file "
            f"reading {key}")
    out.mkdir(parents=True, exist_ok=True)
    stamp.unlink(missing_ok=True)
    image = f"openhardware/wasm-toolchain:{_image_key()[:12]}"
    subprocess.run([docker, "build", "-t", image, str(TOOLCHAIN_DIR)], check=True)
    subprocess.run([
        docker, "run", "--rm",
        "--mount", f"type=volume,source=openhardware-wasm-{toolchain.name}-{key[:12]},target=/build",
        "--mount", f"type=bind,source={CACHE},target=/src,readonly",
        "--mount", f"type=bind,source={out},target=/out",
        image, f"/usr/local/bin/{toolchain.script}",
    ], check=True)
    missing = [name for name in _built_files(toolchain) if not (out / name).is_file()]
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


def avr_sysroot(root: pathlib.Path) -> tuple[list[str], list[str]]:
    """AVR_RELEASE's headers and link inputs under `root` at AVR's prefix,
    and the device specs file the bundle-time driver reads.

    Returns the header paths and the link inputs.
    """
    prefix, version = AVR.prefix, AVR.gcc_version
    gcc = f"avr/lib/gcc/avr/{version}"
    libc = "avr/avr/include/"
    specs = f"{gcc}/device-specs/specs-atmega328p"
    link = {f"avr/avr/lib/avr5/{n}": f"{prefix}/avr/lib/avr5/{n}"
            for n in ("crtatmega328p.o", "libc.a", "libm.a", "libatmega328p.a")}
    link[f"{gcc}/avr5/libgcc.a"] = f"{prefix}/lib/gcc/avr/{version}/avr5/libgcc.a"
    # This ld reads its linker script from disk rather than having it
    # compiled in, from ldscripts/ under a -L directory the driver passes. The
    # recipe's link opens avr5.xn (measured: "cannot open linker script file
    # ldscripts/avr5.xn" without it), the same file as PlatformIO's.
    link["avr/avr/lib/ldscripts/avr5.xn"] = f"{prefix}/avr/lib/ldscripts/avr5.xn"
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
            headers[f"{prefix}/avr/include/{relative}"] = data
        elif name.startswith(gcc) and name not in link and name != specs:
            headers[f"{prefix}/{name[len('avr/'):]}"] = data
    _write(root, {**headers, **{target: found[name] for name, target in link.items()},
                  f"{prefix}/{specs[len('avr/'):]}": found[specs]})
    return sorted(headers), sorted(link.values())


#: The SAMD21's multilib: what -mcpu=cortex-m0plus -mthumb selects, by
#: `arm-none-eabi-gcc -print-multi-directory` with the recipe's flags.
ARM_MULTILIB = "thumb/v6-m/nofp"


def arm_sysroot(root: pathlib.Path) -> tuple[list[str], list[str]]:
    """XPACK_RELEASE's headers and link inputs for ARM_MULTILIB under `root`
    at ARM's prefix, and the two specs files the bundle-time driver reads.

    Its newlib headers and GCC's own, whole, as the Uno has avr-libc's; and
    libstdc++'s, without the bits/ directories of every other multilib. The
    link inputs are the ten files the server's link opens: what ld's --trace
    names when the recipe's link is run with it (measured 2026-10-16).

    Returns the header paths and the link inputs.
    """
    top = "xpack-arm-none-eabi-gcc-12.3.1-1.2/"
    target, version = ARM.target, ARM.gcc_version
    newlib = f"{top}{target}/include/"
    others = f"{newlib}c++/{version}/{target}/"
    gcc = f"{top}lib/gcc/{target}/{version}/"
    link = {f"{top}{target}/lib/{ARM_MULTILIB}/{name}":
            f"{ARM.prefix}/{target}/lib/{ARM_MULTILIB}/{name}"
            for name in ("crt0.o", "libc_nano.a", "libm.a", "libstdc++_nano.a", "libnosys.a")}
    link |= {f"{gcc}{ARM_MULTILIB}/{name}": f"{ARM.prefix}/lib/gcc/{target}/{version}/"
                                            f"{ARM_MULTILIB}/{name}"
             for name in ("crti.o", "crtn.o", "crtbegin.o", "crtend.o", "libgcc.a")}
    specs = {f"{top}{target}/lib/{name}": f"{ARM.prefix}/{target}/lib/{name}"
             for name in ("nano.specs", "nosys.specs")}

    def wanted(name: str) -> bool:
        if name in link or name in specs:
            return True
        if name.startswith(others):
            return name.startswith(f"{others}{ARM_MULTILIB}/")
        return name.startswith((newlib, f"{gcc}include/", f"{gcc}include-fixed/"))

    found: dict[str, bytes] = {}
    with zipfile.ZipFile(fetch_pinned(XPACK_RELEASE)) as archive:
        for member in archive.infolist():
            if not member.is_dir() and wanted(member.filename):
                found[member.filename] = archive.read(member)
    absent = [name for name in (*link, *specs) if name not in found]
    if absent:
        raise CompilerError(f"{XPACK_RELEASE.name} has none of {absent}")
    headers = {f"{ARM.prefix}/{name[len(top):]}": data for name, data in found.items()
               if name not in link and name not in specs}
    _write(root, {**headers, **{target_path: found[name] for name, target_path in link.items()},
                  **{target_path: found[name] for name, target_path in specs.items()}})
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


#: Where the SAMD21's trees sit in a tool's filesystem: each PlatformIO
#: package at its own name, as the server finds it under PACKAGES, and
#: Seeed's core at its name under third_party/bsp.
SAMD_FRAMEWORK = "/framework-arduino-samd"
CMSIS_CORE = "/framework-cmsis"
CMSIS_DEVICE = "/framework-cmsis-atmel"
SEEED = "/seeed-samd"
#: The recipe's -D naming the part, which picks its device header.
_SAMD_PART = re.compile(r"-D__(SAMD21\w+)__$")


def _atmel_headers(recipe: compiler.Recipe) -> set[str]:
    """The CMSIS-Atmel headers a build for `recipe`'s part reads, relative
    to CMSIS/Device/ATMEL: samd.h, the family's dispatch and system headers,
    the part's own header and port table, and every peripheral's register
    layout -- which the part's header includes whole. The 60 files a server
    build of Blink reads (measured 2026-10-16); every other part's header,
    of over a thousand, is left out."""
    parts = [m.group(1).lower() for flag in recipe.flags if (m := _SAMD_PART.match(flag))]
    if len(parts) != 1:
        raise CompilerError(f"expected one -D__SAMD21...__ in the recipe's flags, found {parts}: "
                            f"{recipe.flags}")
    (part,) = parts
    return {"samd.h", "samd21/include/samd21.h", "samd21/include/system_samd21.h",
            f"samd21/include/{part}.h", f"samd21/include/pio/{part}.h"}


def samd(root: pathlib.Path, recipe: compiler.Recipe) -> tuple[list[str], dict[str, str], str]:
    """SAMD_CORE's core and libraries, CMSIS's core headers, the CMSIS-Atmel
    headers the part reads, and SEEED_SAMD's variant for the board, under
    `root`.

    Returns the header paths, every source the recipe compiles by its path
    relative to the framework root (and the variant's own variant.cpp, as
    `variant.cpp`), and the linker script's path.
    """
    files: dict[str, bytes] = {}
    top = "ArduinoCore-samd/"
    trees = tuple(f"{top}{tree}/" for tree in
                  (recipe.core, *(lib.include for lib in recipe.libraries)))
    files |= {f"{SAMD_FRAMEWORK}/{name[len(top):]}": data for name, data in
              _read(fetch_pinned(SAMD_CORE), lambda name: name.startswith(trees)).items()}
    seeed = f"ArduinoCore-samd-1.8.6/{recipe.variant}/"
    files |= {f"{SEEED}/{recipe.variant}/{name[len(seeed):]}": data for name, data in
              _read(fetch_pinned(SEEED_SAMD), lambda name: name.startswith(seeed)).items()}
    with zipfile.ZipFile(fetch_pinned(CMSIS)) as pack:
        files |= {f"{CMSIS_CORE}/{member.filename}": pack.read(member)
                  for member in pack.infolist()
                  if not member.is_dir() and member.filename.startswith("CMSIS/Core/Include/")}
    atmel = "CMSIS/Device/ATMEL/"
    named = _atmel_headers(recipe)
    registers = (f"{atmel}samd21/include/component/", f"{atmel}samd21/include/instance/")
    found = _read(fetch_pinned(CMSIS_ATMEL), lambda name: name[len(atmel):] in named
                  or name.startswith(registers))
    absent = sorted(name for name in named if f"{atmel}{name}" not in found)
    if absent:
        raise CompilerError(f"{CMSIS_ATMEL.name} has none of {absent}")
    files |= {f"{CMSIS_DEVICE}/{name}": data for name, data in found.items()}
    _write(root, files)

    script = f"{SEEED}/{recipe.variant}/{recipe.linker_script}"
    sources = {s: f"{SAMD_FRAMEWORK}/{recipe.core}/{s}" for s in recipe.core_sources}
    sources |= {s: f"{SAMD_FRAMEWORK}/{s}" for lib in recipe.libraries for s in lib.sources}
    sources["variant.cpp"] = f"{SEEED}/{recipe.variant}/variant.cpp"
    absent = [path for path in (*sources.values(), script) if path.lstrip("/") not in
              {name.lstrip("/") for name in files}]
    if absent:
        raise CompilerError(f"none of {absent} is in the SAMD21's sources, which the recipe reads")
    # Headers only: this core keeps each library at its root, beside its
    # examples/ and library.properties, and the variant's folder holds the
    # bootloader's linker script and OpenOCD's.
    headers = [path for path in files if posixpath.splitext(path)[1] in ("", ".h")]
    return sorted(headers), sources, script


# --- one chip, laid out -------------------------------------------------------------


class Laid(NamedTuple):
    """One chip's files in a tool's filesystem, and the names compile.build
    gives them."""

    #: Every file cc1plus may read, and every file ld reads but the objects.
    headers: list[str]
    link_files: list[str]
    #: What the recipe compiles, by its name in the recipe -> its path.
    sources: dict[str, str]
    #: compile.build's -I directories, in its order: the core, the variant,
    #: each wanted library's, then `extras`.
    core: str
    variant: str
    #: What a Library's `include` and `sources` are relative to.
    library_root: str
    extras: list[str]
    #: Names in `sources` that link after the libraries' objects.
    trailing: list[str]
    #: The -T linker script, or None where the driver knows its own.
    script: str | None
    #: compile._diagnostics' labels for the same files: (path, label).
    labels: list[list[str]]


def lay_avr(root: pathlib.Path, recipe: compiler.Recipe) -> Laid:
    """The Uno's: everything in two of Arduino's own releases."""
    if recipe.extra_includes or recipe.bsp_includes or recipe.variant_package:
        raise CompilerError(f"lay_avr lays out a recipe whose headers are all in its framework, "
                            f"and this one names more: {recipe}")
    headers, link_files = avr_sysroot(root)
    arduino_headers, sources = arduino(root, recipe)
    return Laid(
        headers=[*headers, *arduino_headers], link_files=link_files, sources=sources,
        core=f"{ARDUINO}/{recipe.core}", variant=f"{ARDUINO}/{recipe.variant}",
        library_root=ARDUINO, extras=[], trailing=[], script=None,
        # The server finds these under PACKAGES and its temporary directory,
        # the tools here under ARDUINO, the prefix and /build.
        labels=[[f"{ARDUINO}/", f"<toolchain>/{recipe.framework}/"],
                [f"{AVR.prefix}/", f"<toolchain>/{recipe.toolchain}/"],
                ["/build/", "<build>/"]])


def lay_samd(root: pathlib.Path, recipe: compiler.Recipe) -> Laid:
    """The XIAO SAMD21's: xPack's libraries, Arduino's core, Arm's and
    Atmel's CMSIS, and Seeed's variant -- which compile.build compiles as a
    source after the libraries, and whose linker script it names."""
    if recipe.bsp_includes or recipe.variant_package != "seeed-samd":
        raise CompilerError(f"lay_samd lays out Seeed's variant over Arduino's SAMD core, and "
                            f"this recipe asks for more: {recipe}")
    headers, link_files = arm_sysroot(root)
    framework_headers, sources, script = samd(root, recipe)
    # Each package at its own name: so the recipe's extra_includes, which are
    # <package>/<path> under PACKAGES, are the same paths here.
    extras = [f"/{relative}" for relative in recipe.extra_includes]
    if any(not extra.startswith((f"{CMSIS_CORE}/", f"{CMSIS_DEVICE}/")) for extra in extras):
        raise CompilerError(f"lay_samd lays out CMSIS and CMSIS-Atmel, and the recipe includes "
                            f"{recipe.extra_includes}")
    return Laid(
        headers=[*headers, *framework_headers], link_files=[*link_files, script],
        sources=sources,
        core=f"{SAMD_FRAMEWORK}/{recipe.core}", variant=f"{SEEED}/{recipe.variant}",
        library_root=SAMD_FRAMEWORK, extras=extras, trailing=["variant.cpp"], script=script,
        # The server names Seeed's tree by its whole path in a checkout, which
        # says nothing in a tab; here it is named from the checkout's root.
        labels=[[f"{SAMD_FRAMEWORK}/", f"<toolchain>/{recipe.framework}/"],
                [f"{CMSIS_CORE}/", "<toolchain>/framework-cmsis/"],
                [f"{CMSIS_DEVICE}/", "<toolchain>/framework-cmsis-atmel/"],
                [f"{ARM.prefix}/", f"<toolchain>/{recipe.toolchain}/"],
                [f"{SEEED}/", "third_party/bsp/seeed-samd/"],
                ["/build/", "<build>/"]])


class Chip(NamedTuple):
    """A compile.RECIPES row this bundle builds, and how."""

    name: str
    toolchain: Toolchain
    lay: Callable[[pathlib.Path, compiler.Recipe], Laid]


CHIPS = (Chip("ATmega328P", AVR, lay_avr), Chip("SAMD21", ARM, lay_samd))


# --- the driver's commands --------------------------------------------------------


def _includes(laid: Laid, libraries: list[str]) -> list[str]:
    """`compile.build`'s `includes`: core, variant, each wanted library's,
    then the recipe's own."""
    return [f"-I{laid.core}", f"-I{laid.variant}", *(f"-I{include}" for include in libraries),
            *(f"-I{extra}" for extra in laid.extras)]


def _compile_argv(chip: Chip, recipe: compiler.Recipe, includes: list[str], source: str,
                  obj: str) -> tuple[str, list[str]]:
    """`compile.build`'s compile command for one source, as driver and argv."""
    cxx = source.endswith(".cpp")
    argv = ["-c", *recipe.flags, *includes, *(recipe.cxx_flags if cxx else ()),
            source, "-o", obj]
    return f"{chip.toolchain.target}-{'g++' if cxx else 'gcc'}", argv


def _object_path(source: str) -> str:
    """Where a source's object goes: by its whole name, because the core has
    both wiring_pulse.c and wiring_pulse.S."""
    return f"{OBJECTS}/{source.replace('/', '_')}.o"


def _compile_job(chip: Chip, recipe: compiler.Recipe, includes: list[str], source: str,
                 obj: str, root: pathlib.Path) -> dict[str, object]:
    """One compile job for drive.mjs: `source` compiled in the tool's working
    directory, /build, which every instance has (drive.mjs mirrors the tree's
    files, so an empty directory of it does not exist in a tool), and kept at
    `obj` in the bundle. Where an object is written is not in its bytes."""
    built = posixpath.basename(obj)
    driver, argv = _compile_argv(chip, recipe, includes, source, built)
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


def chip_plan(chip: Chip, tools: pathlib.Path, root: pathlib.Path, work: pathlib.Path,
              recipe: compiler.Recipe) -> tuple[dict[str, object], dict[str, pathlib.Path]]:
    """Compile the core and libraries into `root`, and expand the sketch's and
    the link's commands: the plan's entry for `chip`, and the objects made."""
    laid = chip.lay(root, recipe)
    toolchain = chip.toolchain
    plain = _includes(laid, [])
    compile_jobs: dict[str, object] = {}
    objects: dict[str, str] = {}
    for name in (*recipe.core_sources, *laid.trailing):
        objects[name] = _object_path(laid.sources[name])
        compile_jobs[name] = _compile_job(chip, recipe, plain, laid.sources[name],
                                          objects[name], root)
    libraries = []
    for library in recipe.libraries:
        include = f"{laid.library_root}/{library.include}"
        own = []
        for name in library.sources:
            objects[name] = _object_path(laid.sources[name])
            compile_jobs[name] = _compile_job(chip, recipe, _includes(laid, [include]),
                                              laid.sources[name], objects[name], root)
            own.append(objects[name])
        libraries.append({"header": library.header, "include": include, "objects": own})
    (root / OBJECTS.lstrip("/")).mkdir(parents=True, exist_ok=True)

    sketch_driver, sketch_argv = _compile_argv(
        chip, recipe, _includes(laid, [INCLUDE_SENTINEL]), SKETCH, "00.o")
    # compile.build's link, and -fno-use-linker-plugin. A GCC configured
    # against a plugin-capable ld (build-avr.sh says why it is) hands ld the
    # LTO plugin by default, and the server's ld loads it; one in a tab
    # cannot, being a dlopen. In GCC's LINK_COMMAND_SPEC the flag removes the
    # -plugin and -plugin-opt arguments and nothing else, and a link with no
    # LTO object never calls the plugin, so the image is the same.
    link_driver = f"{toolchain.target}-g++"
    link_argv = [*recipe.link_flags, "-fno-use-linker-plugin",
                 *(("-T", laid.script) if laid.script is not None else ()),
                 OBJECT_SENTINEL, "-o", "sketch.elf", "-lm"]
    job = {
        "tools": {key: {"glue": str(tools / f"{built}.mjs"), "wasm": str(tools / f"{built}.wasm"),
                        "program": program}
                  for key, built, _, program in runtime_tools(toolchain)}
                 | {name: {"glue": str(tools / f"{name}.mjs"), "wasm": str(tools / f"{name}.wasm"),
                           "program": f"{toolchain.prefix}/bin/{name}"}
                    for name in bundle_tools(toolchain)},
        "fs": str(root),
        "programs": PROGRAMS,
        "expand": {
            "sketch": {"driver": sketch_driver, "argv": sketch_argv,
                       "placeholders": [SKETCH]},
            "link": {"driver": link_driver, "argv": link_argv,
                     "placeholders": [OBJECT_SENTINEL]},
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
    # GCC 12's driver hands as the compile's -I directories too, and GCC 7's
    # for AVR does not; where it does, the libraries' go where it put them,
    # as in cc1plus's.
    if INCLUDE_SENTINEL in assemble:
        assemble = _collapse(assemble, ("-I", INCLUDE_SENTINEL), LIBRARY_INCLUDES)
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
        "fs": f"{toolchain.name}/fs",
        "sketch": SKETCH,
        "tools": {key: {"name": shown, "glue": f"{toolchain.name}/tools/{built}.mjs",
                        "wasm": f"{toolchain.name}/tools/{built}.wasm", "program": program}
                  for key, built, shown, program in runtime_tools(toolchain)},
        "headers": laid.headers,
        "link_files": laid.link_files,
        "objects": [objects[name] for name in recipe.core_sources],
        "libraries": libraries,
        "trailing": [objects[name] for name in laid.trailing],
        "cc1plus": cc1plus,
        "as": assemble,
        "ld": ld,
        "objcopy": ["-O", "binary", "-R", ".eeprom", "sketch.elf", "sketch.bin"],
        "hints": [list(hint) for hint in recipe.hints],
        # So that a note in a core header or a link error names the file as
        # the server's build would.
        "labels": laid.labels,
        "driver": {"sketch": [sketch_driver, *sketch_argv], "link": [link_driver, *link_argv]},
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
    ("arm-12.3.rel1-newlib-cygwin.tar.xz", "newlib-cygwin/COPYING.NEWLIB", "newlib-COPYING.NEWLIB.txt"),
    ("arm-12.3.rel1-newlib-cygwin.tar.xz", "newlib-cygwin/COPYING.LIBGLOSS",
     "newlib-COPYING.LIBGLOSS.txt"),
    ("ARM.CMSIS.6.3.0.pack", "LICENSE", "Apache-2.0.txt"),
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

arm/tools/cc1plus.*
    GCC 12.3.1's C++ compiler for Arm, from Arm's 12.3.Rel1 source, compiled
    to WebAssembly, with GMP 6.2.1, MPFR 3.1.6 and MPC 1.0.3 linked into it,
    and GCC's own libbacktrace and copy of zlib.
    Licence: GPL-3.0-or-later (GCC); LGPL-3.0-or-later (MPFR, MPC, and GMP,
    whose own terms offer it or GPL-2.0); BSD-3-Clause (libbacktrace, whose
    notice is licenses/libbacktrace-12-LICENSE.txt); the zlib licence (zlib).
    Source: source/arm-12.3.rel1-gcc.tar.xz, with
    source/gcc-12-a995fded34fe-system.h in place of its gcc/system.h -- GCC's
    own fix for PR 111632, from its 12 branch, which lets it compile against
    Emscripten's C++ library; source/gmp-6.2.1.tar.xz,
    source/mpfr-3.1.6.tar.xz, source/mpc-1.0.3.tar.gz.

arm/tools/arm-none-eabi-as.*, arm/tools/arm-none-eabi-ld.*,
arm/tools/arm-none-eabi-objcopy.*
    GNU binutils 2.40, from Arm's 12.3.Rel1 source, compiled to WebAssembly,
    with binutils' own copy of zlib.
    Licence: GPL-3.0-or-later; the zlib licence (zlib).
    Source: source/arm-12.3.rel1-binutils-gdb.tar.xz.

arm/fs/opt/arm/lib/gcc/, arm/fs/opt/arm/arm-none-eabi/include/c++/,
arm/fs/opt/arm/arm-none-eabi/lib/thumb/v6-m/nofp/libstdc++_nano.a
    GCC 12.3.1's own headers, start files and runtime library (libgcc.a), and
    libstdc++'s headers and newlib-nano build, for the Cortex-M0+, from
    xPack's GNU Arm Embedded GCC 12.3.1-1.2 release.
    Licence: GPL-3.0-or-later with the GCC Runtime Library Exception 3.1.
    Source: source/arm-12.3.rel1-gcc.tar.xz, built by the scripts in
    source/arm-none-eabi-gcc-xpack-2fcd97d20c3f459fd4d7068d7d69954f7352ea44.tar.gz
    and the xbb-helper 2.0.1 they call, source/xbb-helper-2.0.1.tgz, which
    holds the configure and make calls and the patch applied to GCC
    (patches/gcc-12.3.1-cross.git.patch). The release itself is not copied here -- it is 261 MB, nearly all of it
    executables this does not use -- and is at
    https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/tag/v12.3.1-1.2

arm/fs/opt/arm/arm-none-eabi/, the rest
    newlib and newlib-nano from Arm's 12.3.Rel1 source: their headers,
    crt0.o, libc_nano.a, libm.a and libnosys.a, from the same release.
    Licence: newlib's, a set of BSD-style and similar permissive notices,
    file by file: licenses/newlib-COPYING.NEWLIB.txt and
    licenses/newlib-COPYING.LIBGLOSS.txt.
    Source: source/arm-12.3.rel1-newlib-cygwin.tar.xz, built by the same
    scripts.

arm/fs/framework-arduino-samd/, arm/fs/seeed-samd/, arm/fs/objects/
    The Arduino SAMD core 1.8.14's headers and its SPI and Wire libraries,
    Seeed's XIAO variant from its SAMD core 1.8.6, and their sources
    compiled by the compiler above.
    Licence: LGPL-2.1-or-later, except where a file says otherwise, and these
    do: cores/arduino/Udp.h, cores/arduino/api/Udp.h and
    cores/arduino/api/deprecated-avr-comp/avr/pgmspace.h carry MIT-style
    permissions, each in the file. api/Common.cpp, api/Common.h,
    api/Compat.h, api/Interrupts.h, compact/dtostrf.c, sync.h and USB/CDC.h
    state none.
    Source: source/core-ArduinoCore-samd-1.8.14.tar.bz2,
    source/ArduinoCore-samd-1.8.6.tar.bz2.

arm/fs/framework-cmsis/
    Arm's CMSIS 6.3.0 core headers.
    Licence: Apache-2.0; see licenses/Apache-2.0.txt.
    Source: source/ARM.CMSIS.6.3.0.pack.

arm/fs/framework-cmsis-atmel/
    Microchip's (formerly Atmel's) ATSAMD21G18A device headers, as
    PlatformIO's framework-cmsis-atmel 1.2.2 carries them.
    Licence: Atmel's, in each file's opening comment, in two versions. Every
    header under samd21/ carries the one in licenses/atmel-cmsis-LICENSE.txt,
    whose fourth condition is that the software "may only be redistributed
    and used in connection with an Atmel microcontroller product"; these
    headers are here only to build programs for the ATSAMD21G18A a XIAO
    SAMD21 carries. samd.h carries the SAM Software Package License, in
    licenses/atmel-samd-LICENSE.txt, which has one condition and no such
    clause.
    Source: source/framework-cmsis-atmel-1.2.2.tar.gz.

How the WebAssembly was made: source/openhardware/ holds the scripts.
Dockerfile, build-avr.sh and build-arm.sh compile the sources above with
Emscripten 5.0.3; build_compiler.py and drive.mjs lay this directory out and
compile the cores; build.js and worker.js run it in the page. They are
OpenHardware's own, MIT-licensed, and `python tools/build_compiler.py` in a
checkout runs them.

Each tool also carries what Emscripten 5.0.3 linked into it: Emscripten's
runtime, which is the .mjs file (MIT or NCSA), musl (MIT), and LLVM's
libc++, libc++abi and compiler-rt (Apache-2.0 WITH LLVM-exception).

licenses/ holds the licence texts: GPL-3.0, the GCC Runtime Library
Exception 3.1, LGPL-2.1, LGPL-3.0, Apache-2.0, avr-libc's, newlib's two,
Atmel's two, libbacktrace's (one per GCC), and Emscripten's, musl's, libc++'s,
libc++abi's and compiler-rt's.

An Uno image built here links the Arduino core (LGPL-2.1-or-later, and SPI's
GPL-2.0 or LGPL-2.1 if the sketch includes it), avr-libc
(modified BSD) and libgcc (whose exception puts no condition on the image).
A XIAO SAMD21 image links the SAMD core and Seeed's variant
(LGPL-2.1-or-later), newlib-nano (its permissive notices), and libgcc and
libstdc++ (whose exception puts no condition on the image).
The image stays in your tab; if you distribute one, the core's part of it
comes with the LGPL's conditions.
"""


#: Licences stated only in a source file's opening comment, which is what is
#: written out: GCC's libbacktrace, which cc1plus links, has no licence file of
#: its own, and its BSD terms ask that a binary carry the notice.
LEADING_COMMENTS = (
    ("gcc-7.3.0.tar.xz", "gcc-7.3.0/libbacktrace/backtrace.h", "libbacktrace-LICENSE.txt"),
    ("arm-12.3.rel1-gcc.tar.xz", "gcc/libbacktrace/backtrace.h", "libbacktrace-12-LICENSE.txt"),
    # Atmel's terms are in every device header and in no file of their own,
    # and samd.h's are another licence than the rest's.
    ("framework-cmsis-atmel-1.2.2.tar.gz", "CMSIS/Device/ATMEL/samd21/include/samd21.h",
     "atmel-cmsis-LICENSE.txt"),
    ("framework-cmsis-atmel-1.2.2.tar.gz", "CMSIS/Device/ATMEL/samd.h", "atmel-samd-LICENSE.txt"),
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


def _members(archive: pathlib.Path, keep: Callable[[str], bool]) -> dict[str, bytes]:
    """`_read` for a tar, and the same for a zip (a CMSIS .pack is one)."""
    if not zipfile.is_zipfile(archive):
        return _read(archive, keep)
    with zipfile.ZipFile(archive) as opened:
        return {member.filename: opened.read(member) for member in opened.infolist()
                if not member.is_dir() and keep(member.filename)}


def _pinned(name: str) -> Pinned:
    """The pin of the archive called `name`, among every toolchain's sources
    and BUNDLE_PINS."""
    pins = [pin for pin in (*(pin for toolchain in TOOLCHAINS for pin in toolchain.sources),
                            *BUNDLE_PINS) if pin.name == name]
    if not pins:
        raise CompilerError(f"no pinned archive is called {name}")
    return pins[0]


def notices(out: pathlib.Path, tools: dict[str, pathlib.Path], sources: bool) -> None:
    """NOTICE.txt, licenses/, and with `sources`, source/."""
    (out / "NOTICE.txt").write_text(NOTICE if sources else NOT_FOR_DISTRIBUTION + NOTICE,
                                    encoding="utf-8")
    licences = out / "licenses"
    licences.mkdir()
    # One Emscripten linked every toolchain, so one copy of its texts.
    for name in EMSCRIPTEN_LICENCES:
        texts = {(tools[toolchain.name] / "licenses" / name).read_bytes()
                 for toolchain in TOOLCHAINS}
        if len(texts) != 1:
            raise CompilerError(f"the toolchains' licenses/{name} differ: each was linked by "
                                f"another Emscripten, and the Dockerfile pins one")
        (licences / name).write_bytes(texts.pop())
    for archive_name in dict.fromkeys(name for name, _, _ in (*LICENCES, *LEADING_COMMENTS)):
        whole = {member: target for name, member, target in LICENCES if name == archive_name}
        comments = {member: target for name, member, target in LEADING_COMMENTS
                    if name == archive_name}
        found = _members(fetch_pinned(_pinned(archive_name)),
                         lambda member: member in whole or member in comments)
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
    for pin in (*(pin for toolchain in TOOLCHAINS for pin in toolchain.sources),
                *(pin for pin in BUNDLE_PINS if pin != XPACK_RELEASE)):
        shutil.copyfile(fetch_pinned(pin), source / pin.name)
    ours = source / "openhardware"
    ours.mkdir()
    for path in (TOOLCHAIN_DIR / "Dockerfile",
                 *(TOOLCHAIN_DIR / toolchain.script for toolchain in TOOLCHAINS),
                 TOOLCHAIN_DIR / "drive.mjs", pathlib.Path(__file__),
                 STATIC / "compiler" / "build.js", STATIC / "compiler" / "worker.js"):
        shutil.copyfile(path, ours / path.name)


# --- the whole thing ------------------------------------------------------------------


def _chip_files(entry: dict[str, object]) -> list[str]:
    """Every file of a chip's fs that its build reads."""
    return [*entry["headers"], *entry["link_files"], *entry["objects"],  # type: ignore[misc]
            *(o for library in entry["libraries"] for o in library["objects"]),  # type: ignore[union-attr]
            *entry["trailing"]]  # type: ignore[misc]


def _manifest(out: pathlib.Path, plan: dict[str, object]) -> dict[str, object]:
    """Every file the page may fetch, with its size and hash, and which ones
    each chip's build reads."""
    files: dict[str, list[object]] = {}
    chips: dict[str, list[str]] = {}
    for chip, entry in plan["chips"].items():  # type: ignore[union-attr]
        wanted = [path for tool in entry["tools"].values() for path in (tool["glue"], tool["wasm"])]
        wanted += [f"{entry['fs']}{path}" for path in _chip_files(entry)]
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
        tools = {toolchain.name: wasm_tools(toolchain) for toolchain in TOOLCHAINS}
        for pin in BUNDLE_PINS:
            fetch_pinned(pin)
        partial = out.with_name(out.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        entries: dict[str, object] = {}
        with tempfile.TemporaryDirectory(prefix="openhardware-compiler-") as scratch:
            for chip in CHIPS:
                work = pathlib.Path(scratch) / chip.toolchain.name
                work.mkdir()
                root = work / "fs"
                entry, _ = chip_plan(chip, tools[chip.toolchain.name], root, work,
                                     compiler.RECIPES[chip.name])
                fs = partial / entry["fs"]  # type: ignore[operator]
                for path in _chip_files(entry):
                    target = fs / path.lstrip("/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(root / path.lstrip("/"), target)
                entries[chip.name] = entry
        for toolchain in TOOLCHAINS:
            shipped = partial / toolchain.name / "tools"
            shipped.mkdir(parents=True)
            for _, built, _, _ in runtime_tools(toolchain):
                for suffix in (".mjs", ".wasm"):
                    shutil.copyfile(tools[toolchain.name] / f"{built}{suffix}",
                                    shipped / f"{built}{suffix}")
        buildable, refused = boards(tuple(chip.name for chip in CHIPS))
        plan = {
            "format": PLAN_FORMAT,
            "budget_seconds": compiler.BUILD_BUDGET_SECONDS,
            "preamble": compiler.ARDUINO_PREAMBLE,
            "max_source_bytes": compiler.MAX_SOURCE_BYTES,
            "boards": buildable,
            "refused": refused,
            "chips": entries,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-sources", action="store_true",
                        help="leave out source/: for a build only tests read, which may "
                             "not be published")
    args = parser.parse_args(argv)
    try:
        manifest = build(sources=not args.no_sources)
    except CompilerError as exc:
        print(f"build_compiler: {exc}", file=sys.stderr)
        return 1
    print(f"{COMPILER}: {len(manifest['files'])} files the page may fetch, "  # type: ignore[arg-type]
          f"{manifest['total'] / 1e6:.1f} MB, version {manifest['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
