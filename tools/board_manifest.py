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
    tools/import_pindefs.py    each pad's `chip_pin`, from the variant named
    webui/boards/catalogue.py  the chip, from the row

A row is checked before anything is written, and the refusal names what it
looked for: every input file not on disk, a chip the package's own
`boards.txt` does not build the variant for, a label the variant does not
number, a licence the CAD file does not state. The whole file is built before
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
class Row:
    """One board, as the inputs its file is generated from."""

    #: The name of the board file and of the board on the page.
    board: str
    #: The key in `tools/board_sources.py`, which says where it is fetched to.
    source: str
    #: The CAD file, relative to that source's checkout.
    cad: str
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
    #: file's `source`.
    licence_statement: tuple[str, str]
    #: `(label, why)` for a pad whose null has a better reason than "no
    #: package defines this label"; `import_pindefs.Board.reasons`.
    reasons: tuple[tuple[str, str], ...] = ()


_THING_PLUS_SCH = "SparkFun's Thing_Plus_ESP32_C6.sch"

ROWS = (
    Row(
        board="SparkFun Thing Plus ESP32-C6",
        source="sparkfun-thing-plus-esp32-c6",
        cad="Hardware/Thing_Plus_ESP32_C6.brd",
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
    ),
)


def row(name: str) -> Row:
    """The row called `name`, or an error naming every row there is."""
    for candidate in ROWS:
        if candidate.board == name:
            return candidate
    raise ManifestError(
        f"no row called {name!r}. Rows: {', '.join(r.board for r in ROWS)}"
    )


def cad_path(entry: Row) -> pathlib.Path:
    """Where the row's CAD file is, under the checkout its source names."""
    try:
        source = board_sources.source(entry.source)
    except board_sources.SourceError as exc:
        raise ManifestError(f"{entry.board}: {exc}") from exc
    return source.dest(REPO) / entry.cad


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
    """The sentence the CAD file carries about its licence, where the row says."""
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
        (variant, package.how_to_fetch()),
        (table, package.how_to_fetch()),
    ]
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
        read = import_board.read_geometry(path, entry.select)
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
            entry.board, import_pindefs.BSP_DIR, staged, modules_dir=BOARDS_DIR
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
            print(
                f"note: webui/boards/{entry.board}.svg was NOT generated; "
                f"tools/import_board.py writes no artwork.",
                file=sys.stderr,
            )
    except (ManifestError, import_pindefs.PindefError) as exc:
        print(f"board_manifest: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
