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

A row whose inputs are not on disk is refused before anything is written, and
the refusal names every file it looked for and did not find.

    python tools/board_manifest.py --check    # every row's inputs; writes nothing
    python tools/board_manifest.py            # write every row's board file
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

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
FLAT_PACKAGES = ("arduino-esp32", "arduino-pico")


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
    #: A key of `tools/import_pindefs.py`'s `PACKAGES`, and the directory under
    #: its `variants/` whose `pins_arduino.h` defines this board's pins.
    package: str
    variant: str
    #: Labels the variant defines other than `D<n>`, opted in by name as
    #: `import_pindefs.select_labels` requires of every such label.
    labels: tuple[str, ...]


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


def check(entry: Row) -> None:
    """Refuse a row unless every input is on disk and the BSP agrees on its chip."""
    # Here and not at the top: `import_pindefs` reads `ROWS` as it loads.
    from tools import import_pindefs

    if entry.package not in FLAT_PACKAGES:
        raise ManifestError(
            f"{entry.board}: {entry.package!r} is not one of {FLAT_PACKAGES}, "
            f"whose Arduino pin number is the GPIO; read flat, its numbers "
            f"would be indices into the core's own table"
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
    # The chip is the row's claim; `boards.txt` is the package's. A variant
    # belongs to a chip when a board row there builds it for that `build.mcu`.
    mcu = entry.chip.lower().replace("-", "")
    relative = f"variants/{entry.variant}/pins_arduino.h"
    if relative not in import_pindefs.variants_of_chip(checkout, mcu):
        raise ManifestError(
            f"{entry.board}: the row says {entry.chip}, and no board in "
            f"{table.relative_to(REPO).as_posix()} builds {entry.variant} with "
            f"build.mcu={mcu}"
        )


def geometry(entry: Row) -> dict:
    """The board file as `tools/import_board.py` builds it: pads, no pins."""
    path = cad_path(entry)
    try:
        read = import_board.read_geometry(path, entry.select)
    except import_board.BoardImportError as exc:
        raise ManifestError(f"{entry.board}: {exc}") from exc
    source = board_sources.source(entry.source)
    return import_board.build_board(
        read._replace(name=entry.board),
        path.relative_to(REPO),
        {
            "vendor": source.vendor,
            "repository": source.fetch.url,
            "licence": source.licence.name,
            "registry": source.name,
        },
    )


def write(entry: Row) -> pathlib.Path:
    """Check the row, write its pads, then have import_pindefs write its pins."""
    from tools import import_pindefs

    check(entry)
    document = geometry(entry)
    path = BOARDS_DIR / f"{entry.board}.json"
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    import_pindefs.write_board(entry.board)
    return path


def main(argv: list[str] | None = None) -> int:
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
    except ManifestError as exc:
        print(f"board_manifest: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
