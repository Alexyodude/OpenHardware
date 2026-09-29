#!/usr/bin/env python3
# OpenHardware - a board that is not a XIAO footprint, as one row.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Write a board file from one row naming its CAD, its chip and its pins.

A XIAO is found by its name. Any other board was a hand-written exception in
`webui/boards/catalogue.py` and in `tools/import_pindefs.py` (OH-176). Here it
is a row, and the tools that already read each input do the rest:

    tools/import_board.py      the pads, from the CAD file and the elements named
    tools/import_pindefs.py    each pad's `chip_pin`, from the variant named,
                               and from the chip pad its net reaches in the CAD
    webui/boards/catalogue.py  the chip, from the row

A row is checked before anything is written, and the refusal names what it
looked for: every input file not on disk, a chip the package's own
`boards.txt` does not build the variant for, a label the variant does not
number, a licence the vendor's own files do not state. The whole file is built before
it is written, so a row that fails leaves `webui/boards/` as it was.

    python tools/board_manifest.py --check    # every row's inputs; writes nothing
    python tools/board_manifest.py            # write every row's board file
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import tempfile
import xml.etree.ElementTree as ET

try:
    from tools import board_sources, import_board
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import board_sources, import_board

REPO = pathlib.Path(__file__).resolve().parents[1]
BOARDS_DIR = REPO / "webui" / "boards"

#: Packages whose Arduino pin number is the GPIO, which is what
#: `import_pindefs.arduino_flat` reads. Any other would be read as `D6 -> 6`
#: -- the first trap in that module's docstring -- and look successful.
#:
#: Each maps to the `boards.txt` key that names the part a board is built
#: for. arduino-esp32 writes `build.mcu=esp32c6`; arduino-pico's `build.mcu`
#: is the CPU (`cortex-m0plus`), and its part is `build.chip=rp2040`.
FLAT_PACKAGES = {"arduino-esp32": "build.mcu", "arduino-pico": "build.chip"}


class ManifestError(Exception):
    """A row cannot become a board file, and here is why."""


@dataclasses.dataclass(frozen=True)
class PinTable:
    """One part's pins, as its datasheet's pin table numbers them.

    The part is the element a row's CAD places as `package` with `value`.
    `gpio` holds only the pads some row's header reaches (OH-178);
    `not_gpio` every pad the page gives no GPIO, by the name it gives; and
    `pins` how many pins the page numbers. A pad within `pins` in neither
    list is refused where a header reaches it, never read as no GPIO.
    """

    package: str
    value: str
    #: The document, its version, and where in it.
    cite: str
    url: str
    #: Of the PDF at `url` when it was read: the URL names no version.
    pdf_sha256: str
    pins: int
    gpio: tuple[tuple[str, int], ...]
    not_gpio: tuple[tuple[str, str], ...]


_DOCS = "https://www.espressif.com/sites/default/files/documentation/"

ESP32_C3FH4 = PinTable(
    "QFN32_5MM", "ESP32-C3FH4",
    "ESP32-C3 Series Datasheet v2.4, p. 67, ESP32-C3 Consolidated Pin Overview: "
    "Pin No. against IO MUX Function 1",
    _DOCS + "esp32-c3_datasheet_en.pdf",
    "833fc000b4b3c3d39c496fcbd597fed5806956503ce7390b19cc8ae82f19f968",
    33,
    (("4", 0), ("5", 1), ("8", 3), ("9", 4), ("10", 5), ("12", 6), ("13", 7),
     ("14", 8), ("16", 10), ("27", 20), ("28", 21)),
    # Pin 18, VDD_SPI, is a Power pin whose IO MUX Function 1 is GPIO11, so
    # it is in neither list.
    (("1", "LNA_IN"), ("2", "VDD3P3"), ("3", "VDD3P3"), ("7", "CHIP_EN"),
     ("11", "VDD3P3_RTC"), ("17", "VDD3P3_CPU"), ("29", "XTAL_N"), ("30", "XTAL_P"),
     ("31", "VDDA"), ("32", "VDDA"), ("33", "GND")),
)
ESP32_C6_MINI_1 = PinTable(
    "ESP32-PICO-MINI", "ESP32-C6-MINI_MINI",
    "ESP32-C6-MINI-1 & MINI-1U Datasheet v1.5, pp. 10-11, 3.2 Pin Description "
    "and Table 3-1 Pin Definitions: No. against the GPIO its Function names",
    _DOCS + "esp32-c6-mini-1_mini-1u_datasheet_en.pdf",
    "26691033f31cbebf623842c16624e61151b152533c13a850c091c8e858c510a2",
    53,
    (("5", 2), ("6", 3), ("9", 4), ("10", 5), ("12", 0), ("13", 1), ("15", 6),
     ("16", 7), ("19", 14), ("20", 15), ("22", 8), ("23", 9), ("24", 18),
     ("25", 19), ("27", 21), ("28", 22), ("29", 23), ("30", 17), ("31", 16)),
    (("1", "GND"), ("2", "GND"), ("3", "3V3"), ("4", "NC"), ("7", "NC"), ("8", "EN"),
     ("11", "GND"), ("14", "GND"), ("21", "NC"), ("32", "NC"), ("33", "NC"),
     ("34", "NC"), ("35", "NC"), *((str(pin), "GND") for pin in range(36, 54))),
)
ESP32_C6_WROOM_1 = PinTable(
    "ESP32-C6-WROOM-1-NARROW", "ESP32-C6-WROOM-1-NARROW",
    "ESP32-C6-WROOM-1 & WROOM-1U Datasheet v1.4, pp. 10-11, 3.2 Pin Description "
    "and Table 3-1 Pin Definitions: No. against the GPIO its Function names",
    _DOCS + "esp32-c6-wroom-1_wroom-1u_datasheet_en.pdf",
    "163020762fa6d499e0c611c5a13e78ad9d4720b421c6bc5e14e16fc748862b73",
    29,
    (("4", 4), ("5", 5), ("6", 6), ("7", 7), ("8", 0), ("9", 1), ("10", 8),
     ("11", 10), ("12", 11), ("15", 9), ("16", 18), ("17", 19), ("18", 20),
     ("19", 21), ("20", 22), ("21", 23), ("23", 15), ("24", 17), ("25", 16),
     ("26", 3), ("27", 2)),
    (("1", "GND"), ("2", "3V3"), ("3", "EN"), ("22", "NC"), ("28", "GND"),
     ("29", "EPAD")),
)


@dataclasses.dataclass(frozen=True)
class Row:
    """One board, as the inputs its file is generated from."""

    #: The name of the board file and of the board on the page.
    board: str
    #: The key in `tools/board_sources.py`, which says where it is fetched to.
    source: str
    #: The CAD file, relative to that source's checkout.
    cad: str
    #: The vendor's schematic of the same board, relative to the same checkout.
    #: Its devices say which pads are one pin: `import_board.Connects`.
    schematic: str
    #: The placed elements carrying the header: `tools/import_board.py --select`.
    select: tuple[str, ...]
    #: A key of `webui/boards/catalogue.py`'s `CHIPS`.
    chip: str
    #: A key of `FLAT_PACKAGES`, and the directory under its `variants/` whose
    #: `pins_arduino.h` defines this board's pins.
    package: str
    variant: str
    #: Labels the variant defines other than `D<n>`, opted in by name as
    #: `import_pindefs.select_labels` requires of every such label.
    labels: tuple[str, ...]
    #: Where the CAD file states its licence: a placed element, and the text
    #: its package carries. Checked against the file, and quoted in the board
    #: file's `source`. None where the registry read the licence from a file
    #: its source fetches, `Licence.file`, which is checked the same way.
    licence_statement: tuple[str, str] | None = None
    #: `(label, why)` for a pad whose null has a better reason than "no
    #: package defines this label"; `import_pindefs.Board.reasons`.
    reasons: tuple[tuple[str, str], ...] = ()
    #: The chip's pads in the CAD, read so that a pad names the GPIO its net
    #: reaches: `import_pindefs.read_eagle_traced`.
    pin_table: PinTable | None = None


_THING_PLUS_SCH = "SparkFun's Thing_Plus_ESP32_C6.sch"

ROWS = (
    Row(
        board="SparkFun Thing Plus ESP32-C6",
        source="sparkfun-thing-plus-esp32-c6",
        cad="Hardware/Thing_Plus_ESP32_C6.brd",
        schematic="Hardware/Thing_Plus_ESP32_C6.sch",
        select=("J1",),
        chip="ESP32-C6",
        package="arduino-esp32",
        variant="sparkfun_esp32c6_thing_plus",
        labels=("TX", "RX", "SDA", "SCL", "SCK"),
        licence_statement=(
            "FRAME1",
            "Released under the Creative Commons Attribution Share-Alike 4.0 License",
        ),
        reasons=(
            ("ESP_EN",
             f"the enable pin of the ESP32-C6-WROOM-1 module, not a GPIO: "
             f"{_THING_PLUS_SCH} puts the net ESP_EN on U1's `EN`, the RESET "
             f"switch, R11 and C5, and U1's GPIOs are its `IOn` pins"),
            ("VREG_EN",
             f"the enable of the board's regulator, not a pin of the ESP32-C6: "
             f"{_THING_PLUS_SCH} puts the net VREG_EN on U2's `EN` (an "
             f"RT9080-33GJ5, whose `OUT` is the 3.3V net) and R8, and on no "
             f"pin of U1"),
            ("LED_DO",
             f"no ESP32-C6 pin is on this net: {_THING_PLUS_SCH} puts LED_DO on "
             f"this pad and pin 1 of the jumper RGB (JUMPER-SMT_2_NO), whose "
             f"pin 2 is the `DO` of the WS2812 D5"),
        ),
        pin_table=ESP32_C6_WROOM_1,
    ),
    Row(
        board="Adafruit QT Py ESP32-C3",
        source="adafruit-qt-py-esp32-c3",
        cad="Adafruit QT Py ESP32-C3.brd",
        schematic="Adafruit QT Py ESP32-C3.sch",
        select=("JP1", "JP3"),
        chip="ESP32-C3",
        package="arduino-esp32",
        variant="adafruit_qtpy_esp32c3",
        labels=("A0", "A1", "A2", "A3", "SDA", "SCL", "TX", "RX", "SCK", "MISO", "MOSI"),
        pin_table=ESP32_C3FH4,
    ),
    Row(
        board="Adafruit Feather ESP32-C6",
        source="adafruit-feather-esp32-c6",
        cad="Adafruit Feather ESP32-C6.brd",
        schematic="Adafruit Feather ESP32-C6.sch",
        select=("JP1", "JP3"),
        chip="ESP32-C6",
        package="arduino-esp32",
        variant="adafruit_feather_esp32c6",
        labels=("A0", "A1", "A2", "A3", "A4", "A5", "SDA", "SCL", "TX", "RX", "SCK",
                "MISO", "MOSI"),
        pin_table=ESP32_C6_MINI_1,
    ),
)


def find(name: str) -> Row | None:
    """The row called `name`, or None where `name` is not a row: the one
    answer to "is this a manifest board", which `webui/api.py`,
    `webui/compile.py` and `webui/boards/catalogue.py` ask."""
    return next((candidate for candidate in ROWS if candidate.board == name), None)


def row(name: str) -> Row:
    """The row called `name`, or an error naming every row there is."""
    found = find(name)
    if found is None:
        raise ManifestError(
            f"no row called {name!r}. Rows: {', '.join(r.board for r in ROWS)}"
        )
    return found


def cad_path(entry: Row) -> pathlib.Path:
    """Where the row's CAD file is, under the checkout its source names."""
    try:
        source = board_sources.source(entry.source)
    except board_sources.SourceError as exc:
        raise ManifestError(f"{entry.board}: {exc}") from exc
    return source.dest(REPO) / entry.cad


def connects(entry: Row) -> import_board.Connects:
    """Each selected element's device, as the row's schematic states it."""
    path = board_sources.source(entry.source).dest(REPO) / entry.schematic
    root = ET.parse(path).getroot().find("drawing/schematic")
    stated = {}
    for name in entry.select:
        part = root.find(f"parts/part[@name='{name}']")
        if part is None:
            raise ManifestError(f"{entry.board}: {entry.schematic} places no part {name!r}")
        devices = root.findall(
            f"libraries/library[@name='{part.get('library')}']/devicesets/"
            f"deviceset[@name='{part.get('deviceset')}']/devices/"
            f"device[@name='{part.get('device')}']"
        )
        if len(devices) != 1:
            raise ManifestError(
                f"{entry.board}: {entry.schematic} defines {len(devices)} devices "
                f"for part {name!r} ({part.get('library')}/{part.get('deviceset')}"
                f"/{part.get('device')!r}), not one"
            )
        stated[name] = (
            devices[0].get("package"),
            tuple(tuple(connect.get("pad").split())
                  for connect in devices[0].findall("connects/connect")),
        )
    return stated


def chips_building(table: pathlib.Path, variant: str, key: str) -> set[str]:
    """Every value `key` takes on a board `table` builds `variant` for.

    A board's key may sit under a menu -- `rpipico2.menu.arch.arm.build.chip`
    -- and then each option is one answer, so all of them are returned.
    """
    boards: set[str] = set()
    values: dict[str, set[str]] = {}
    for line in table.read_text(encoding="utf-8", errors="replace").splitlines():
        name, _, value = line.strip().partition("=")
        board, _, rest = name.partition(".")
        if rest == "build.variant" and value.strip() == variant:
            boards.add(board)
        elif rest == key or (rest.startswith("menu.") and rest.endswith("." + key)):
            values.setdefault(board, set()).add(value.strip())
    return {value for board in boards for value in values.get(board, ())}


def licence_evidence(entry: Row) -> str:
    """The words the vendor's own files state its licence in, checked there."""
    if entry.licence_statement is None:
        licence = board_sources.source(entry.source).licence
        if not licence.file:
            raise ManifestError(
                f"{entry.board}: the row names no licence statement in "
                f"{entry.cad}, and tools/board_sources.py read {entry.source}'s "
                f"licence from no file it fetches"
            )
        path = board_sources.source(entry.source).dest(REPO) / licence.file
        text = " ".join(path.read_text(encoding="utf-8", errors="replace").split())
        if " ".join(licence.quote.split()) not in text:
            raise ManifestError(
                f"{entry.board}: {path.relative_to(REPO).as_posix()} does not "
                f"read {licence.quote!r}"
            )
        return f"the repository's {licence.file} reads {licence.quote!r}"
    element_name, text = entry.licence_statement
    board = ET.parse(cad_path(entry)).getroot().find("drawing/board")
    element = board.find(f"elements/element[@name='{element_name}']")
    if element is None:
        raise ManifestError(f"{entry.board}: {entry.cad} places no element {element_name!r}")
    library, package = element.get("library"), element.get("package")
    texts = [node.text for node in board.findall(
        f"libraries/library[@name='{library}']/packages/package[@name='{package}']/text")]
    if text not in texts:
        raise ManifestError(
            f"{entry.board}: {element_name}'s package {library}/{package} in "
            f"{entry.cad} does not read {text!r}; it reads {texts}"
        )
    return f"{entry.cad} places {element_name}, whose package {library}/{package} reads {text!r}"


def check(entry: Row) -> None:
    """Refuse a row unless its inputs are on disk and agree with it."""
    # Here and not at the top: `import_pindefs` reads `ROWS` as it loads.
    from tools import import_pindefs

    if entry.package not in FLAT_PACKAGES:
        raise ManifestError(
            f"{entry.board}: {entry.package!r} is not one of "
            f"{sorted(FLAT_PACKAGES)}, whose Arduino pin number is the GPIO; "
            f"read flat, its numbers would be indices into the core's own table"
        )
    package = import_pindefs.PACKAGES[entry.package]
    checkout = import_pindefs.BSP_DIR / entry.package
    variant = checkout / "variants" / entry.variant / "pins_arduino.h"
    table = checkout / "boards.txt"
    wanted = [
        (cad_path(entry),
         f"python tools/get_board_sources.py {entry.source}"),
        (board_sources.source(entry.source).dest(REPO) / entry.schematic,
         f"python tools/get_board_sources.py {entry.source}"),
        (variant, package.how_to_fetch()),
        (table, package.how_to_fetch()),
    ]
    licence = board_sources.source(entry.source).licence
    if entry.licence_statement is None and licence.file:
        wanted.append((
            board_sources.source(entry.source).dest(REPO) / licence.file,
            f"python tools/get_board_sources.py {entry.source}",
        ))
    missing = [(path, how) for path, how in wanted if not path.is_file()]
    if missing:
        raise ManifestError(
            f"{entry.board}: {len(missing)} input(s) not on disk, so no board "
            f"file is written: "
            + "; ".join(f"{path.relative_to(REPO).as_posix()} ({how})"
                        for path, how in missing)
        )
    # The chip is the row's claim; `boards.txt` is the package's, spelled its
    # own way, so the two are compared without case or hyphens.
    key = FLAT_PACKAGES[entry.package]
    built_for = chips_building(table, entry.variant, key)
    if entry.chip.lower().replace("-", "") not in {
        chip.lower().replace("-", "") for chip in built_for
    }:
        raise ManifestError(
            f"{entry.board}: the row says {entry.chip}, and "
            f"{table.relative_to(REPO).as_posix()} builds {entry.variant} for "
            f"{key}={sorted(built_for) or 'nothing'}"
        )
    # What import_pindefs will read, read now: a label the variant does not
    # number is refused here rather than after a file is half written.
    try:
        import_pindefs.read_flat_pins(
            (variant.read_text(encoding="utf-8", errors="replace"),),
            extras=entry.labels,
        )
    except import_pindefs.PindefError as exc:
        raise ManifestError(
            f"{entry.board}: {variant.relative_to(REPO).as_posix()}: {exc}"
        ) from exc
    licence_evidence(entry)


def geometry(entry: Row) -> dict:
    """The board file as `tools/import_board.py` builds it: pads, no pins."""
    path = cad_path(entry)
    try:
        read = import_board.read_geometry(path, entry.select, connects=connects(entry))
    except import_board.BoardImportError as exc:
        raise ManifestError(f"{entry.board}: {exc}") from exc
    source = board_sources.source(entry.source)
    document = import_board.build_board(
        read._replace(name=entry.board),
        path.relative_to(REPO),
        {
            "vendor": source.vendor,
            "repository": source.fetch.url,
            "licence": source.licence.name,
            "licence_evidence": licence_evidence(entry),
            "registry": source.name,
        },
    )
    # No `image.file` (OH-179): nothing reads it -- webui/pinmap.py reads the
    # width and height -- and nothing here writes the SVG it would name.
    del document["image"]["file"]
    # `tools/import_board.py` alone does not reproduce this file: the name,
    # the source and the pins come from the row.
    document["derivation"] = document["derivation"].replace(
        "Generated by tools/import_board.py ",
        "Generated by `python tools/board_manifest.py` (this board's row, read "
        "through tools/import_board.py) ",
        1,
    )
    return document


def write(entry: Row) -> pathlib.Path:
    """Build the whole file, pads and pins, and only then write it."""
    from tools import import_pindefs

    check(entry)
    if entry not in ROWS:
        raise ManifestError(
            f"{entry.board}: only a row in ROWS is written, because "
            f"tools/import_pindefs.py registers ROWS as it loads"
        )
    document = geometry(entry)
    with tempfile.TemporaryDirectory() as scratch:
        staged = pathlib.Path(scratch)
        (staged / f"{entry.board}.json").write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        filled = import_pindefs.filled_board(
            entry.board, import_pindefs.BSP_DIR, staged,
            modules_dir=import_pindefs.BOARDS_DIR,
        )
    path = BOARDS_DIR / f"{entry.board}.json"
    path.write_text(json.dumps(filled, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    # Here and not at the top: `import_pindefs` reads `ROWS` as it loads.
    from tools import import_pindefs

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("boards", nargs="*", help="rows to act on; every row without")
    parser.add_argument("--check", action="store_true",
                        help="check each row's inputs and write nothing")
    args = parser.parse_args(argv)

    try:
        entries = [row(name) for name in args.boards] if args.boards else list(ROWS)
        for entry in entries:
            if args.check:
                check(entry)
                print(f"ok     {entry.board}")
                continue
            path = write(entry)
            print(f"wrote  {path}")
    except (ManifestError, import_pindefs.PindefError) as exc:
        print(f"board_manifest: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
