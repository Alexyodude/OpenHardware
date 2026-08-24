#!/usr/bin/env python3
# OpenHardware — find the firmware a project has already built.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Name the build artefacts in a project directory and say what is in them.

`webui/firmware.py` turns bytes into an address-tagged image. It never opens a
file and has no idea where a toolchain puts one. This is the other half: given
the directory a person points at, find the artefacts and hand each to
`load_image`.

## The layouts

**PlatformIO** — `.pio/build/<env>/`, one directory per environment in
`platformio.ini`. Measured on this machine from a three-environment blink
build, 2026-08-24:

    nucleo_g031k8       firmware.elf  firmware.bin
    pico                firmware.elf  firmware.bin  firmware.uf2
    seeed_xiao_esp32c3  firmware.elf  firmware.bin  bootloader.bin  partitions.bin

The names are an **allowlist, not a glob**. Those same directories hold
`firmware.map` — 618 KB of link map for the STM32, 7.8 MB for the ESP — and a
`firmware.*` glob hands that to a firmware parser as though it were an image.

`boot_app0.bin` is deliberately **not** searched for. The handoff that
specified this listed it, but it is not a build output: it is a constant
shipped with the framework, identical for every project, and it lives under
`~/.platformio/packages/framework-arduinoespressif32/tools/partitions/`.
Looking for it would make discovery depend on a global install path rather
than on the project it was handed. A caller assembling a whole flash layout
needs it at 0xE000 and now knows where it is.

**Arduino CLI** (`--export-binaries`) — `build/<fqbn>/<sketch>.ino.<tail>`,
with the `:` in an fqbn written as `.`. Rather than reproduce that encoding,
this takes every subdirectory of `build/` holding at least one `*.ino.*` file,
so a change in how the fqbn is spelled cannot break discovery.

**STM32CubeIDE** — one directory per build configuration, holding `*.elf` and
whatever the post-build step emitted. Gated on `.cproject`, Eclipse CDT's
marker, which is what makes "the subdirectories with ELFs in them" mean "the
build configurations" rather than "some directories that happen to hold an
ELF".

**Only the PlatformIO layout was measured here.** There is no arduino-cli and
no STM32CubeIDE on this machine; the other two are implemented from their
documented export shapes and tested against synthesised trees. That proves the
path logic, not the layout — the same distinction `docs/features/webui.md`
draws for the bridge's stub-server tests.

## Why a raw .bin is refused rather than guessed

`parse_bin` has no default base, for the reason in its docstring. This does not
add one. A directory scan reports a `.bin` and says what it would need; a
caller who knows the address points at that one file with `--base`.

One `--base` cannot serve a whole directory: in the ESP environment above,
`bootloader.bin` is flashed at 0x0, `partitions.bin` at 0x8000 and
`firmware.bin` at 0x10000. So `--base` with a directory is an error, not a
broadcast.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import struct
import sys

try:
    from webui import firmware
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from webui import firmware


# --- what a find returns ---------------------------------------------------

#: Roles, most-complete first. A merged image contains the others, so where
#: both are present the merged one is what a loader should be offered.
ROLE_ORDER = ("merged", "application", "bootloader", "partitions")


@dataclasses.dataclass(frozen=True)
class Artefact:
    """One file, and enough context to say what it is a part of.

    `role` is the field that stops a report from lying. An ESP environment
    emits three images flashed to three different addresses; listing them as
    three programs is wrong, and listing only the largest is silently
    incomplete.
    """

    path: pathlib.Path
    toolchain: str
    target: str
    role: str

    @property
    def sort_key(self) -> tuple[str, str, int, str]:
        rank = ROLE_ORDER.index(self.role)
        return (self.toolchain, self.target, rank, self.path.name)


# --- PlatformIO ------------------------------------------------------------

#: Exact names, not a glob. See the module docstring.
PIO_ARTEFACTS = {
    "firmware.uf2": "application",
    "firmware.elf": "application",
    "firmware.hex": "application",
    "firmware.bin": "application",
    "bootloader.bin": "bootloader",
    "partitions.bin": "partitions",
}


def find_platformio(project: pathlib.Path) -> list[Artefact]:
    """Artefacts under `.pio/build/<env>/`, one group per environment."""
    build = project / ".pio" / "build"
    if not build.is_dir():
        return []
    found: list[Artefact] = []
    for env in sorted(p for p in build.iterdir() if p.is_dir()):
        for name, role in PIO_ARTEFACTS.items():
            path = env / name
            if path.is_file():
                found.append(Artefact(path, "platformio", env.name, role))
    return found


# --- Arduino CLI -----------------------------------------------------------

#: Keyed on everything after `.ino.`, so `sketch.ino.merged.bin` is a merged
#: image and `sketch.ino.bin` is the application alone. A suffix test cannot
#: tell those apart — both end `.bin` — and getting it wrong means offering a
#: 4 MB flash image and a 200 KB fragment of it as the same kind of thing.
ARDUINO_TAILS = {
    "merged.bin": "merged",
    "with_bootloader.bin": "merged",
    "with_bootloader.hex": "merged",
    "bootloader.bin": "bootloader",
    "partitions.bin": "partitions",
    "bin": "application",
    "elf": "application",
    "hex": "application",
    "uf2": "application",
}


def _arduino_role(name: str) -> str | None:
    """The role of an Arduino export, or None when the name is not one."""
    _, separator, tail = name.partition(".ino.")
    if not separator:
        return None
    return ARDUINO_TAILS.get(tail)


def find_arduino_cli(project: pathlib.Path) -> list[Artefact]:
    """Artefacts under `build/<fqbn>/`, one group per fqbn directory."""
    build = project / "build"
    if not build.is_dir():
        return []
    found: list[Artefact] = []
    for fqbn in sorted(p for p in build.iterdir() if p.is_dir()):
        for path in sorted(fqbn.iterdir()):
            if not path.is_file():
                continue
            role = _arduino_role(path.name)
            if role is not None:
                found.append(Artefact(path, "arduino-cli", fqbn.name, role))
    return found


# --- STM32CubeIDE ----------------------------------------------------------

CUBE_SUFFIXES = frozenset({".elf", ".bin", ".hex"})


def find_stm32cubeide(project: pathlib.Path) -> list[Artefact]:
    """Artefacts in the build-configuration directories of an Eclipse project.

    Gated on `.cproject`. Without that gate this would claim any directory
    holding `Debug/x.elf` as a CubeIDE project, which is a label it has no
    evidence for — CMake, Make and a dozen other builds emit the same shape.
    """
    if not (project / ".cproject").is_file():
        return []
    found: list[Artefact] = []
    for config in sorted(p for p in project.iterdir() if p.is_dir()):
        files = sorted(p for p in config.iterdir() if p.is_file())
        if not any(p.suffix == ".elf" for p in files):
            continue
        for path in files:
            if path.suffix in CUBE_SUFFIXES:
                found.append(Artefact(path, "stm32cubeide", config.name, "application"))
    return found


# --- the whole scan --------------------------------------------------------

FINDERS = (find_platformio, find_arduino_cli, find_stm32cubeide)

#: Labelled with the same toolchain names the report prints, so a user who
#: searches the output for `arduino-cli` finds both the group heading and the
#: line saying where it was looked for.
WHERE_WE_LOOKED = (
    # Parenthesised, because an implicitly concatenated pair inside a tuple
    # and a tuple with a missing comma are the same three lines on the page.
    (
        "platformio    .pio/build/<env>/firmware.{uf2,elf,hex,bin}, "
        "bootloader.bin, partitions.bin"
    ),
    "arduino-cli   build/<fqbn>/*.ino.{bin,elf,hex,uf2}, including *.merged.bin",
    "stm32cubeide  <configuration>/*.{elf,bin,hex}, beside a .cproject",
)


def find_artefacts(project: pathlib.Path) -> list[Artefact]:
    """Every build artefact in `project`, in a fixed order.

    Ordered because `rules/determinism.md` applies to tools as much as to
    simulation: a scan whose output follows directory iteration order cannot
    be diffed between two runs.
    """
    if not project.is_dir():
        raise ValueError(f"{project}: not a directory")
    found: list[Artefact] = []
    for finder in FINDERS:
        found.extend(finder(project))
    return sorted(found, key=lambda a: a.sort_key)


# --- telling an esp-idf application image from a flat binary ---------------

ESP_IMAGE_MAGIC = 0xE9
ESP_HEADER_LEN = 24
ESP_HASH_LEN = 32

#: `esp_chip_id_t` from esp-idf, restricted to parts a board on this project's
#: list can be. Used as a validity test as much as a label.
ESP_CHIPS = {
    0x0000: "ESP32",
    0x0002: "ESP32-S2",
    0x0005: "ESP32-C3",
    0x0009: "ESP32-S3",
    0x000C: "ESP32-C2",
    0x000D: "ESP32-C6",
    0x0010: "ESP32-H2",
}


@dataclasses.dataclass(frozen=True)
class EspImage:
    """What an esp-idf application image says about itself."""

    chip: str
    entry: int
    segments: tuple[tuple[int, int], ...]


def identify_esp_image(data: bytes) -> EspImage | None:
    """Recognise an esp-idf application image by walking its own structure.

    **This identifies; it does not parse.** It returns where the segments say
    they load, not their bytes, because building an `Image` from them belongs
    in `webui/firmware.py` and needs its own tests.

    Identifying it matters anyway. `firmware.bin` in an ESP environment is a
    container whose five segments go to 0x3C030020, 0x3FC8A200, 0x40380000,
    0x42000020 and 0x403827FC, while the file itself is flashed flat at
    0x10000. Both views are true and they are not the same view, so a report
    showing the flat one has to say that is what it is showing.

    A magic-byte test would be far too weak to claim that. 0xE9 is `jmp rel32`,
    and an x86 image from this repository's own 8086 work could open with it.
    So the whole structure is walked — segment count, a known chip id, and a
    segment chain landing exactly on the 16-byte-aligned checksum, optionally
    followed by a 32-byte SHA-256. Anything that fails any of those is None,
    and the caller treats it as the flat binary it may well be.
    """
    if len(data) < ESP_HEADER_LEN or data[0] != ESP_IMAGE_MAGIC:
        return None
    count = data[1]
    if not 1 <= count <= 16:
        return None
    entry, = struct.unpack_from("<I", data, 4)
    chip_id, = struct.unpack_from("<H", data, 12)
    if chip_id not in ESP_CHIPS:
        return None

    offset = ESP_HEADER_LEN
    segments: list[tuple[int, int]] = []
    for _ in range(count):
        if offset + 8 > len(data):
            return None
        address, length = struct.unpack_from("<2I", data, offset)
        offset += 8 + length
        if offset > len(data):
            return None
        segments.append((address, length))

    # After the last segment: padding to a 16-byte boundary, one checksum
    # byte, then an optional SHA-256. Anything outside those two windows means
    # the walk did not really land, and the 0xE9 was a coincidence.
    trailing = len(data) - offset
    hashed = trailing > 16
    if not 1 <= trailing <= 16 + ESP_HASH_LEN:
        return None
    if (len(data) - (ESP_HASH_LEN if hashed else 0)) % 16 != 0:
        return None

    return EspImage(ESP_CHIPS[chip_id], entry, tuple(segments))


# --- reporting -------------------------------------------------------------


def _hex(value: int) -> str:
    return f"0x{value:08x}"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


#: What `describe` managed. `NEEDS_BASE` is a legitimate outcome and not a
#: failure — a `.bin` carries no address and the caller has not named one, so
#: every PlatformIO scan produces at least one. `ERROR` is an artefact that
#: should have parsed and did not. Collapsing the two into a boolean is how a
#: corrupt ELF exits 0 beside a healthy one.
OK, NEEDS_BASE, ERROR = "ok", "needs-base", "error"


def _self_identifying(data: bytes) -> bool:
    """Whether `load_image` can name this format without being told a base.

    Mirrors the sniff at the top of `load_image`. Duplicated rather than
    exported, because the alternative is branching on the text of an exception
    message — and a message is written for a person to read, not for a program
    to match.
    """
    return (
        data.startswith(firmware.ELF_MAGIC)
        or (
            len(data) >= 8
            and struct.unpack_from("<2I", data)
            == (firmware.UF2_MAGIC_START0, firmware.UF2_MAGIC_START1)
        )
        or data[:1] == b":"
    )


def describe(
    path: pathlib.Path,
    *,
    base: int | None = None,
    family: int | str | None = None,
    vectors: int | None = None,
) -> tuple[list[str], str]:
    """Lines describing one file, and one of `OK` / `NEEDS_BASE` / `ERROR`."""
    data = path.read_bytes()
    lines: list[str] = []

    esp = identify_esp_image(data)
    if esp is not None:
        lines.append(
            f"esp-idf application image for {esp.chip}, "
            f"{_count(len(esp.segments), 'segment')}, entry {_hex(esp.entry)}"
        )
        lines += [
            f"  segment {i} loads at {_hex(address)}, {_count(length, 'byte')}"
            for i, (address, length) in enumerate(esp.segments)
        ]
        # No offset is named here on purpose. An earlier draft said "normally
        # at 0x10000", which is the *application* partition -- and the same
        # line was printed over `bootloader.bin`, which goes to 0x0 on a C3
        # and 0x1000 on an ESP32. Where a container lands is a fact about the
        # partition table, not about the container.
        lines.append(
            "  those are run-time addresses; the file is flashed flat, "
            "wherever its partition entry puts it"
        )

    try:
        image = firmware.load_image(data, base=base, family=family)
    except firmware.FirmwareError as exc:
        if base is None and not _self_identifying(data):
            if esp is None:
                # Deliberately shorter than `exc`. `load_image`'s message
                # names all three known bases, which is right for someone who
                # hit it once and wrong in a scan that repeats it per file.
                lines.append(
                    "needs a base address: a raw .bin carries none. Re-run "
                    "pointing at this file, with --base"
                )
            else:
                # `load_image` would say "unrecognised format", contradicting
                # the four lines printed above it. It *is* recognised; it is
                # just not a flat binary, and turning a container into an
                # `Image` is not this tool's job.
                lines.append(
                    "no flat view: this is a container, not a raw binary. "
                    "--base <flash offset> shows it as the bytes written there"
                )
            return lines, NEEDS_BASE
        lines.append(f"no image: {exc}")
        return lines, ERROR

    span = image.span
    where = f"{_hex(span[0])}..{_hex(span[1])}" if span else "nothing"
    entry = _hex(image.entry) if image.entry is not None else "not stated"
    lines.append(
        f"{image.format}, {_count(len(image.segments), 'segment')}, "
        f"{_count(image.total_bytes, 'byte')}, {where}, entry {entry}"
    )
    if image.family:
        lines.append(f"  family {image.family}")
    lines += [f"  note: {note}" for note in image.notes]

    if vectors is not None:
        table = firmware.read_vector_table(image, vectors)
        if table is None:
            lines.append(
                f"  no vector table at {_hex(vectors)}: not covered by this image"
            )
        else:
            lines.append(
                f"  vector table at {_hex(vectors)}: "
                f"SP {_hex(table[0])}, reset {_hex(table[1])}"
            )
    return lines, OK


def _report_file(
    path: pathlib.Path,
    *,
    base: int | None,
    family: int | str | None,
    vectors: int | None,
) -> int:
    print(path)
    lines, status = describe(path, base=base, family=family, vectors=vectors)
    print("\n".join("  " + line for line in lines))
    # Stricter than a scan on purpose: someone who names one file wants that
    # file, so "it needs a base" is a failed request rather than a footnote.
    return 0 if status == OK else 1


def _report_project(
    project: pathlib.Path,
    *,
    family: int | str | None,
    vectors: int | None,
) -> int:
    """Scan a directory. **No `base` parameter, deliberately** — see `main`."""
    artefacts = find_artefacts(project)
    if not artefacts:
        print(f"{project}: no build artefacts. Looked for:", file=sys.stderr)
        for where in WHERE_WE_LOOKED:
            print(f"  {where}", file=sys.stderr)
        return 2

    statuses: list[str] = []
    group = None
    for artefact in artefacts:
        if (artefact.toolchain, artefact.target) != group:
            group = (artefact.toolchain, artefact.target)
            print(f"\n{artefact.toolchain}  {artefact.target}")
        lines, status = describe(artefact.path, family=family, vectors=vectors)
        statuses.append(status)
        print(f"  {artefact.path.name}  [{artefact.role}]")
        print("\n".join("    " + line for line in lines))

    for target in sorted({a.target for a in artefacts if a.role == "merged"}):
        print(f"\nnote: {target} has a merged image; the rest are parts of it.")

    # The report is stdout and the verdict is stderr, so the two are buffered
    # separately: without this flush the verdict lands *above* the report the
    # moment stdout is a pipe rather than a terminal.
    sys.stdout.flush()
    if ERROR in statuses:
        print("\nsome artefacts could not be read.", file=sys.stderr)
        return 1
    if OK not in statuses:
        print("\nnothing here could be read without a base address.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "path", nargs="?", default=".",
        help="a project directory to scan, or one artefact to read",
    )
    parser.add_argument(
        "--base", type=lambda s: int(s, 0),
        help="load address for a raw .bin. Only valid for a single file: the "
             "three images in an ESP build go to 0x0, 0x8000 and 0x10000",
    )
    parser.add_argument(
        "--family",
        help="which UF2 family to keep, by name or id, when a file holds two",
    )
    parser.add_argument(
        "--vectors", type=lambda s: int(s, 0),
        help="address of the Cortex-M vector table to report. Required and "
             "never guessed: 0x08000000 on STM32, 0x10000100 on RP2040, which "
             "is past boot2",
    )
    args = parser.parse_args(argv)

    path = pathlib.Path(args.path)

    if path.is_file():
        return _report_file(
            path, base=args.base, family=args.family, vectors=args.vectors
        )
    if not path.is_dir():
        print(f"import_firmware: {path}: no such file or directory", file=sys.stderr)
        return 2
    if args.base is not None:
        print(
            f"import_firmware: --base applies to one file, not the directory "
            f"{path}. A PlatformIO ESP environment holds three images flashed "
            f"to 0x0, 0x8000 and 0x10000, so one base would be wrong for two "
            f"of them. Point at the file you mean.",
            file=sys.stderr,
        )
        return 2
    return _report_project(path, family=args.family, vectors=args.vectors)


if __name__ == "__main__":
    raise SystemExit(main())
