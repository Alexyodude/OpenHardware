#!/usr/bin/env python3
# OpenHardware - source in, a loadable image out.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Compile a sketch for a board, using a toolchain this machine already has.

## What this is for

`webui/api.py` takes BYTES and a board name; somebody has to have built them.
`tools/import_firmware.py` finds artefacts somebody else built. This is the
third door: source, and a board name, and the bytes come back.

    from webui import compile as compiler

    built = compiler.build("Arduino Uno", "void setup(){} void loop(){}")
    if built.ok:
        api.load_firmware("Arduino Uno", built.image, base=0)
    else:
        print(built.diagnostics)      # avr-gcc's own words, line numbers and all

## The safety boundary, and it is the whole design

**The request carries source and a board name. Nothing else.** The compiler,
its flags, the framework, the linker arguments and the output format are read
out of `RECIPES` here, keyed by the chip the catalogue says that board carries.

A request that could name its own compiler, or add its own flags, is a request
that can run any program on this machine -- `-specs=`, `-B`, `@file` and plain
`-o` over something important are all ordinary compiler arguments. So the
untrusted half of the input reaches `subprocess` in exactly one place: as the
CONTENTS of a file, written into a fresh temporary directory that is removed
afterwards.

That is the same posture `webui/bridge.py` argues for at length and the one
the user chose on 2026-08-25 when this was proposed: loopback bind plus an
Origin check, and the server decides what runs.

## A compile error is a RESULT, not a fault

It is the most common thing that will happen here. `Build.ok` is false, the
compiler's own stderr is in `Build.diagnostics` with its line numbers intact,
and no exception is raised. A service that answered "build failed" would be
useless, and one that raised would make the ordinary case the exceptional
path.

What DOES raise is a request that cannot be attempted at all: an unknown
board, or a toolchain this machine does not have. `ToolchainMissing` names the
package it wanted, because "install PlatformIO's toolchain-atmelavr" is
actionable and "compile failed" is not.

## Why the recipes live here and not in the board module

`webui/boards/atmega328p.py` describes the part to a *core*: address spaces and
peripheral registers. Which compiler builds for it is a fact about this
machine's PlatformIO install, and it changes when a package is upgraded rather
than when the silicon does. Keeping them apart means a board description stays
readable to somebody who never compiles anything.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import subprocess
import tempfile

from webui.boards import catalogue as board_catalogue

#: Where PlatformIO puts the toolchains and frameworks.
#:
#: `$USERPROFILE` and not `~`: Git Bash on this machine sets `HOME` to a
#: profile redirect, so `~/.platformio` resolves to a directory that does not
#: exist. Measured, twice, and it is the reason every path in this repository
#: spells it out.
PACKAGES = pathlib.Path(
    os.environ.get("PLATFORMIO_CORE_DIR")
    or pathlib.Path(os.environ.get("USERPROFILE", pathlib.Path.home()), ".platformio")
) / "packages"

#: How long a build may take before it is killed. A compiler that hangs would
#: otherwise hold the server's lock forever, and this runs under one.
TIMEOUT_SECONDS = 120

#: A sketch larger than this is refused before a compiler is started. Not a
#: security boundary -- the body limit in `emulator_server.py` is that -- but a
#: sketch of a megabyte is a mistake and saying so beats a two-minute timeout.
MAX_SOURCE_BYTES = 256 << 10


class CompileError(Exception):
    """The build could not be attempted. Not "the code did not compile"."""


class UnknownBoard(CompileError):
    """No recipe for this board's chip."""


class ToolchainMissing(CompileError):
    """The recipe names a package this machine does not have."""


@dataclasses.dataclass(frozen=True)
class Recipe:
    """Everything needed to build for one chip, and none of it from a request.

    `core_sources` are files of the vendor framework compiled alongside the
    sketch. Compiling the whole framework would work and take twenty times as
    long, so the list is what a sketch actually calls -- and it is a list here
    rather than a glob so that adding a file is a decision somebody made.
    """

    toolchain: str                    #: PlatformIO package holding the compiler
    prefix: str                       #: e.g. "avr-", how its binaries are named
    framework: str                    #: PlatformIO package holding the core
    core: str                         #: subdirectory of it holding the sources
    variant: str                      #: subdirectory holding pins_arduino.h
    flags: tuple[str, ...]            #: compile flags, identical for C and C++
    cxx_flags: tuple[str, ...]        #: added for C++ only; errors on C
    link_flags: tuple[str, ...]
    core_sources: tuple[str, ...]
    #: The base address `webui/api.load_firmware` should be given. Zero on a
    #: Harvard part whose program space starts there; an Arm board would carry
    #: its flash origin here instead.
    base: int


#: One recipe per chip, keyed as `webui/boards/catalogue.py` spells the chip.
#:
#: **Only the Uno today, and that is the vertical slice on purpose.** OH-61
#: says one board end to end before any second one, and the flags below are not
#: guessed: they are what `tests/avr/test_arduino_sketch.py`'s fixture has been
#: building real sketches with since OH-58, including the two things that
#: fixture got wrong first -- `avr-gcc` for `.c` and `avr-g++` for `.cpp` are
#: not interchangeable, and `-fno-threadsafe-statics` is a hard error on a C
#: file.
RECIPES: dict[str, Recipe] = {
    "ATmega328P": Recipe(
        toolchain="toolchain-atmelavr",
        prefix="avr-",
        framework="framework-arduino-avr",
        core="cores/arduino",
        variant="variants/standard",
        flags=(
            "-mmcu=atmega328p", "-DF_CPU=16000000L", "-DARDUINO=10808",
            "-DARDUINO_AVR_UNO", "-DARDUINO_ARCH_AVR",
            "-Os", "-ffunction-sections", "-fdata-sections",
        ),
        cxx_flags=("-fno-exceptions", "-fno-threadsafe-statics"),
        link_flags=("-mmcu=atmega328p", "-Os", "-Wl,--gc-sections"),
        # main.cpp is what calls setup() then loop() forever; the rest are what
        # pinMode, digitalWrite, delay and Serial live in. HardwareSerial pulls
        # in Print, Stream and WString, and virtual dispatch pulls in abi/new.
        core_sources=(
            "main.cpp", "hooks.c", "wiring.c", "wiring_digital.c",
            "HardwareSerial.cpp", "HardwareSerial0.cpp", "Print.cpp",
            "Stream.cpp", "WString.cpp", "abi.cpp", "new.cpp",
        ),
        base=0,
    ),
}


@dataclasses.dataclass(frozen=True)
class Build:
    """What a build produced.

    Exactly one of `image` and a non-empty `diagnostics` is meaningful, and
    `ok` is the only thing a caller should branch on -- a zero-length image
    from a sketch that defines nothing is still a successful build.
    """

    ok: bool
    image: bytes
    diagnostics: str
    #: What was run, so a failure that is not the sketch's fault can be
    #: reproduced by hand. Rule 9: an error carries the values that caused it.
    command: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """What the wire carries. The image is left out on purpose.

        Bytes do not survive JSON, and the caller that wants them is in this
        process. `/api/compile` builds and loads in one step for that reason,
        so an image never crosses the wire in either direction.
        """
        return {
            "ok": self.ok,
            "bytes": len(self.image),
            "diagnostics": self.diagnostics,
            "command": list(self.command),
        }


def recipe_for(board: str) -> Recipe:
    """The recipe for a board, by the chip the catalogue says it carries.

    Keyed on the chip rather than the board name because four XIAO variants of
    one part build identically -- and because the catalogue is already the one
    place that maps a board to its silicon.
    """
    try:
        chip = board_catalogue.chip_for(board)
    except board_catalogue.CatalogueError as exc:
        # Re-raised as this module's own type, with the catalogue's reason
        # kept: "does not start with XIAO-" is the actionable half and losing
        # it would leave "unknown board" and nothing else.
        raise UnknownBoard(f"{board!r}: {exc}") from exc
    recipe = RECIPES.get(chip)
    if recipe is None:
        buildable = ", ".join(sorted(RECIPES)) or "none"
        raise UnknownBoard(
            f"{board} carries a {chip} and nothing here knows how to build for "
            f"one. Chips with a recipe: {buildable}."
        )
    return recipe


def toolchain_root(recipe: Recipe) -> pathlib.Path:
    """Where the compiler is, or a refusal naming the package it wanted."""
    root = PACKAGES / recipe.toolchain
    compiler = root / "bin" / f"{recipe.prefix}gcc"
    if not compiler.is_file() and not compiler.with_suffix(".exe").is_file():
        raise ToolchainMissing(
            f"no {recipe.prefix}gcc under {root}. Install it with:\n"
            f"  pio pkg install --global --tool {recipe.toolchain}"
        )
    return root


def framework_root(recipe: Recipe) -> pathlib.Path:
    """Where the vendor core is, or a refusal naming the package."""
    root = PACKAGES / recipe.framework
    if not (root / recipe.core).is_dir():
        raise ToolchainMissing(
            f"no {recipe.core} under {root}. Install it with:\n"
            f"  pio pkg install --global --tool {recipe.framework}"
        )
    return root


def _tool(root: pathlib.Path, recipe: Recipe, name: str) -> str:
    """One binary of the toolchain, with the platform's suffix if it needs one."""
    path = root / "bin" / f"{recipe.prefix}{name}"
    return str(path if path.is_file() else path.with_suffix(".exe"))


def build(board: str, source: str) -> Build:
    """Compile `source` for `board`, and return the image or the diagnostics.

    Raises `UnknownBoard` or `ToolchainMissing` when the build cannot be
    ATTEMPTED. A build that is attempted and fails returns `ok=False` -- see
    the module docstring for why that difference is load-bearing.
    """
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise CompileError(
            f"sketch is {len(source.encode('utf-8'))} bytes, over the "
            f"{MAX_SOURCE_BYTES} this accepts"
        )
    recipe = recipe_for(board)
    tools = toolchain_root(recipe)
    framework = framework_root(recipe)
    core = framework / recipe.core
    variant = framework / recipe.variant

    gcc = _tool(tools, recipe, "gcc")
    gxx = _tool(tools, recipe, "g++")
    objcopy = _tool(tools, recipe, "objcopy")

    includes = (f"-I{core}", f"-I{variant}")
    with tempfile.TemporaryDirectory(prefix="openhardware-build-") as tmp:
        out = pathlib.Path(tmp)
        # **The one place untrusted input reaches the filesystem**, and it is
        # as file contents in a directory that exists for this build alone.
        # The name is ours; nothing from the request chooses a path.
        sketch = out / "sketch.cpp"
        sketch.write_text(preamble(source), encoding="utf-8")

        objects: list[str] = []
        for index, path in enumerate([sketch, *(core / n for n in recipe.core_sources)]):
            cxx = path.suffix == ".cpp"
            # Numbered rather than named after the source: two framework files
            # could share a stem, and one silently overwriting the other's
            # object is a link error nobody could read.
            obj = out / f"{index:02d}.o"
            command = (
                _tool(tools, recipe, "g++") if cxx else gcc,
                "-c", *recipe.flags, *includes,
                *(recipe.cxx_flags if cxx else ()),
                str(path), "-o", str(obj),
            )
            done = _run(command)
            if done.returncode != 0:
                # The sketch is compiled first, so a failure here is almost
                # always the caller's -- but the command is returned either way
                # so a framework file that stopped compiling is not mistaken
                # for a syntax error in three lines of sketch.
                return Build(False, b"", _diagnostics(done, sketch), command)
            objects.append(str(obj))

        elf = out / "sketch.elf"
        link = (gxx, *recipe.link_flags, *objects, "-o", str(elf), "-lm")
        done = _run(link)
        if done.returncode != 0:
            return Build(False, b"", _diagnostics(done, sketch), link)

        image = out / "sketch.bin"
        extract = (objcopy, "-O", "binary", "-R", ".eeprom", str(elf), str(image))
        done = _run(extract)
        if done.returncode != 0:
            return Build(False, b"", _diagnostics(done, sketch), extract)

        return Build(True, image.read_bytes(), "", extract)


#: What the Arduino IDE silently puts at the top of every `.ino`, and what
#: PlatformIO does NOT put at the top of a `.cpp` -- a difference recorded in
#: OH-10's own notes after it cost somebody a build.
#:
#: **The `#line` is the load-bearing half.** Without it every diagnostic is
#: reported one line further down than the person typed, which is worse than no
#: line number at all: a number that is confidently wrong sends a reader to the
#: wrong line and they believe it.
ARDUINO_PREAMBLE = '#include <Arduino.h>\n#line 1 "sketch.cpp"\n'


def preamble(source: str) -> str:
    """`source` with the Arduino header prepended, unless it has its own.

    Left alone when the sketch already includes it, so a person who writes the
    include -- which is what a PlatformIO project does -- gets exactly the file
    they wrote and no shifted line numbers from a duplicate.

    **`#line` costs gcc's quoted source line, and that is the right trade.**
    Measured: without it a diagnostic reads

        sketch.cpp:3:22: error: expected primary-expression before ';' token
         void loop(){ int x = ; }
                              ^

    -- the caret is helpful and the number is wrong by two. With it the number
    is right and gcc drops the quote, because it can no longer map the reported
    line back to a physical one to read. The editor quotes the line instead,
    from the source the person actually typed, which is better than gcc's copy
    of a file it was handed.
    """
    if "<Arduino.h>" in source or '"Arduino.h"' in source:
        return source
    return ARDUINO_PREAMBLE + source


def _run(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
    )


def _diagnostics(done: subprocess.CompletedProcess[str],
                 sketch: pathlib.Path) -> str:
    """The compiler's own words, with the temporary path taken back out.

    A person reading `C:\\Users\\...\\Temp\\openhardware-build-3f2a\\sketch.cpp:2:1`
    learns nothing from the first sixty characters, and the line number is the
    only part that matters. Replacing the path rather than stripping it keeps
    the `file:line:column:` shape an editor can parse.
    """
    text = (done.stderr or done.stdout or "").strip()
    return text.replace(str(sketch), "sketch.cpp").replace(
        str(sketch).replace("\\", "/"), "sketch.cpp"
    )
