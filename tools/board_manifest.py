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

    The part is the element a row's CAD places as `package` with `value`:
    an EAGLE element's package, or a KiCad footprint's name without its
    library, and the value either states.
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
    #: `(footprint pad, page number)` where the footprint names a pin other
    #: than by the number the page gives it; every other pad's name is its
    #: number.
    footprint_pads: tuple[tuple[str, str], ...] = ()


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
ESP32_C3_MINI_1 = PinTable(
    "ESP32-C3-MINI-1", "ESP32-C3_MINI-1",
    "ESP32-C3-MINI-1 & MINI-1U Datasheet v2.2, pp. 10-11, 3.2 Pin Description "
    "and Table 3-1 Pin Definitions: No. against the GPIO its Function names",
    _DOCS + "esp32-c3-mini-1_datasheet_en.pdf",
    "de7361381348d82a1abd337f10170be7a420675987568f71fe3c5b100deed270",
    53,
    (("5", 2), ("6", 3), ("12", 0), ("13", 1), ("16", 10), ("18", 4), ("19", 5),
     ("20", 6), ("21", 7), ("22", 8), ("30", 20), ("31", 21)),
    # Pins 23, 26 and 27 are GPIO9, GPIO18 and GPIO19, which no header
    # reaches, so they are in neither list.
    (("1", "GND"), ("2", "GND"), ("3", "3V3"), ("4", "NC"), ("7", "NC"), ("8", "EN"),
     ("9", "NC"), ("10", "NC"), ("11", "GND"), ("14", "GND"), ("15", "NC"),
     ("17", "NC"), ("24", "NC"), ("25", "NC"), ("28", "NC"), ("29", "NC"),
     *((str(pin), "NC") for pin in range(32, 36)),
     *((str(pin), "GND") for pin in range(36, 54))),
    # SparkFun's footprint splits the page's 49, the central ground pad, into
    # nine pads named 49.1 to 49.9.
    footprint_pads=tuple((f"49.{part}", "49") for part in range(1, 10)),
)
#: The same page, for the module as PCBCUPID's Glyph C3 places it: a KiCad
#: footprint its library names for the ESP32-H2-MINI-1, valued as the
#: ESP32-C3-MINI-1 it carries; the GPIO rows its headers reach -- pins 23, 26
#: and 27 are GPIO9, GPIO18 and GPIO19 on Table 3-1 -- and a footprint that
#: splits the page's 49 into nine pads named 49_1 to 49_9.
ESP32_C3_MINI_1_PCBCUPID = dataclasses.replace(
    ESP32_C3_MINI_1,
    package="ESP32-H2-MINI-1_EXP", value="ESP32-C3-MINI-1-N4",
    gpio=(("5", 2), ("6", 3), ("12", 0), ("13", 1), ("16", 10), ("18", 4), ("19", 5),
          ("20", 6), ("21", 7), ("22", 8), ("23", 9), ("26", 18), ("27", 19),
          ("30", 20), ("31", 21)),
    footprint_pads=tuple((f"49_{part}", "49") for part in range(1, 10)),
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
#: The same page, for the module as SparkFun's library places it, under a
#: package and value of its own: the GPIO rows a header of the Qwiic Pocket
#: reaches, and a footprint that splits the page's 49, the central ground
#: pad, into nine pads named 49.1 to 49.9.
ESP32_C6_MINI_1_SPARKFUN = dataclasses.replace(
    ESP32_C6_MINI_1,
    package="ESP32-C6-MINI-1", value="ESP32-C6-MINI-1",
    gpio=(("5", 2), ("6", 3), ("9", 4), ("10", 5), ("24", 18), ("25", 19),
          ("30", 17), ("31", 16)),
    footprint_pads=tuple((f"49.{part}", "49") for part in range(1, 10)),
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
RP2040_QFN56 = PinTable(
    "QFN56_7MM_REDUCEDEPAD", "RP2040_QFN56",
    "RP2040 Datasheet build-date 2025-02-20 build-version 3184e62-clean, PDF pp. "
    "613-615 (printed 612-614), 5.5.2.2 Pin List, Tables 615 and 617-621: Name "
    "against Number",
    "https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf",
    "be56fbb75ba0ae9e26558a73c93ac3e75c2ad4e6878d3b6703de2a76d886ea8c",
    57,
    (("2", 0), ("3", 1), ("4", 2), ("5", 3), ("6", 4), ("7", 5), ("8", 6), ("9", 7),
     ("11", 8), ("12", 9), ("13", 10), ("29", 18), ("30", 19), ("31", 20),
     ("38", 26), ("39", 27), ("40", 28), ("41", 29)),
    # Pins 51-56 are the QSPI pins of Table 616, a table apart from the GPIO
    # one, so they are in neither list.
    (("1", "IOVDD"), ("10", "IOVDD"), ("19", "TESTEN"), ("20", "XIN"), ("21", "XOUT"),
     ("22", "IOVDD"), ("23", "DVDD"), ("24", "SWCLK"), ("25", "SWD"), ("26", "RUN"),
     ("33", "IOVDD"), ("42", "IOVDD"), ("43", "ADC_AVDD"), ("44", "VREG_VIN"),
     ("45", "VREG_VOUT"), ("46", "USB_DM"), ("47", "USB_DP"), ("48", "USB_VDD"),
     ("49", "IOVDD"), ("50", "DVDD"), ("57", "GND")),
    # The page's 57 is "Common ground connection via central pad"; the KB2040's
    # footprint names its central pad `P$1`.
    footprint_pads=(("P$1", "57"),),
)
#: The same page, for the RP2040 as PCBCUPID's Glyph Mini places it: a
#: KiCad footprint and the value `RP2040`, the GPIO rows its headers reach
#: -- pins 14 to 18 are GPIO11 to GPIO15 on Table 615 -- and a footprint
#: that numbers the central pad 57 as the page does.
RP2040_QFN56_PCBCUPID = dataclasses.replace(
    RP2040_QFN56,
    package="QFN-56-1EP_7x7mm_P0.4mm_EP5.6x5.6mm", value="RP2040",
    gpio=(("2", 0), ("3", 1), ("4", 2), ("5", 3), ("6", 4), ("7", 5), ("8", 6),
          ("9", 7), ("11", 8), ("12", 9), ("13", 10), ("14", 11), ("15", 12),
          ("16", 13), ("17", 14), ("18", 15), ("38", 26), ("39", 27), ("40", 28),
          ("41", 29)),
    footprint_pads=(),
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
    #: Its devices say which pads are one pin: `import_board.Connects`. An
    #: EAGLE row needs it; a KiCad board's pads carry their own numbers and
    #: nets, which say the same, so a `.kicad_pcb` row names none.
    schematic: str | None
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
    #: reaches: `import_pindefs.read_eagle_traced` or `read_kicad_traced`.
    pin_table: PinTable | None = None


_THING_PLUS_SCH = "SparkFun's Thing_Plus_ESP32_C6.sch"
_POCKET_SCH = "SparkFun's Qwiic_Pocket_Dev_ESP32_C6.sch"

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
    # Its variant numbers no pin itself: `D<n>` and `A<n>` are declared in
    # arduino-pico's `variants/generic/common.h`, which it includes, and
    # `import_pindefs.read_pico_pins` reads them through the preprocessor
    # (OH-181).
    Row(
        board="Adafruit KB2040",
        source="adafruit-kb2040",
        cad="Adafruit KB2040.brd",
        schematic="Adafruit KB2040.sch",
        select=("JP1", "JP2"),
        chip="RP2040",
        package="arduino-pico",
        variant="adafruit_kb2040",
        labels=("A0", "A1", "A2", "A3", "MISO", "MOSI"),
        pin_table=RP2040_QFN56,
    ),
    Row(
        board="SparkFun Pro Micro ESP32-C3",
        source="sparkfun-pro-micro-esp32-c3",
        cad="Hardware/SparkFun_Dev_ESP32_C3_MINI.brd",
        schematic="Hardware/SparkFun_Dev_ESP32_C3_MINI.sch",
        select=("J6", "J7"),
        chip="ESP32-C3",
        package="arduino-esp32",
        variant="sparkfun_pro_micro_esp32c3",
        labels=("SDA", "SCL"),
        pin_table=ESP32_C3_MINI_1,
    ),
    Row(
        board="SparkFun Qwiic Pocket ESP32-C6",
        source="sparkfun-qwiic-pocket-esp32-c6",
        cad="Hardware/Qwiic_Pocket_Dev_ESP32_C6.brd",
        schematic="Hardware/Qwiic_Pocket_Dev_ESP32_C6.sch",
        select=("J2", "J3"),
        chip="ESP32-C6",
        package="arduino-esp32",
        variant="sparkfun_esp32c6_qwiic_pocket",
        labels=("TX", "RX"),
        licence_statement=(
            "FRAME1",
            "Released under the Creative Commons Attribution Share-Alike 4.0 License",
        ),
        reasons=(
            ("V_BATT",
             f"the battery, not a pin of the ESP32-C6: {_POCKET_SCH} puts V_BATT on "
             f"R13 (1M), whose other net, IO1/V_BATT_2, holds U1's `XTAL_32K_N/IO1` "
             f"(pad 13) and R14 (1M) to GND -- a divider onto IO1 that senses the "
             f"battery, which the trace does not cross because that net holds more "
             f"than R13 and the chip"),
        ),
        pin_table=ESP32_C6_MINI_1_SPARKFUN,
    ),
    # A KiCad board (OH-192). Its pads are labelled by net, `/GPIO-0` and so
    # on, which no label of its variant spells, so its pins are the traced
    # copper's; the variant is read all the same, for its chip.
    Row(
        board="PCBCUPID Glyph Mini RP2040",
        source="pcbcupid-glyph-mini-2040",
        cad="glyph-mini-rp2040.kicad_pcb",
        schematic=None,
        select=("J3", "J4", "J5"),
        chip="RP2040",
        package="arduino-pico",
        variant="pcbcupid_glyph_mini_2040",
        labels=(),
        pin_table=RP2040_QFN56_PCBCUPID,
    ),
    # KiCad, and licensed by its README alone (OH-194). Its pads are labelled
    # by net: `/SDA`, `/SCK` and so on, which its variant's labels name, and
    # `/GPIO_1` and so on, which the traced copper does.
    Row(
        board="PCBCUPID Glyph C3",
        source="pcbcupid-glyph-c3",
        cad="esp32c3.kicad_pcb",
        schematic=None,
        select=("J2", "J4"),
        chip="ESP32-C3",
        package="arduino-esp32",
        variant="Pcbcupid_GLYPH_C3",
        labels=("SDA", "SCL", "SCK", "MOSI", "MISO"),
        reasons=(
            ("unconnected-(J2-Pin_8-Pad8)",
             "no net: in the vendor's board file this pad is the only pad on its "
             "net, so it reaches no pin of the ESP32-C3 or of anything else"),
        ),
        pin_table=ESP32_C3_MINI_1_PCBCUPID,
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
        # A README asserting a licence is not the licence (OH-194), and the
        # board file says which it rests on.
        graded = (f"; graded {licence.evidence.label}: {licence.cite}"
                  if licence.evidence is board_sources.Evidence.STATED else "")
        return f"the repository's {licence.file} reads {licence.quote!r}{graded}"
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
    # Which pads are one pin: a KiCad board says so by its pads' numbers,
    # and an EAGLE board only through its schematic's device connects.
    is_kicad = pathlib.PurePosixPath(entry.cad).suffix.lower() == ".kicad_pcb"
    if is_kicad and entry.schematic is not None:
        raise ManifestError(
            f"{entry.board}: {entry.cad} is a KiCad board, whose pads carry "
            f"their own numbers and nets; a schematic's connects are read for "
            f"an EAGLE board only, so the row names no {entry.schematic}"
        )
    if not is_kicad and entry.schematic is None:
        raise ManifestError(
            f"{entry.board}: {entry.cad} is not a KiCad board, and which of "
            f"its pads are one pin is stated by its schematic's device "
            f"connects; the row names no schematic"
        )
    package = import_pindefs.PACKAGES[entry.package]
    checkout = import_pindefs.BSP_DIR / entry.package
    variant = checkout / "variants" / entry.variant / "pins_arduino.h"
    table = checkout / "boards.txt"
    wanted = [
        (cad_path(entry),
         f"python tools/get_board_sources.py {entry.source}"),
        *([(board_sources.source(entry.source).dest(REPO) / entry.schematic,
            f"python tools/get_board_sources.py {entry.source}")]
          if entry.schematic is not None else []),
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
    # What import_pindefs will read, read now and the same way: a label the
    # variant does not number is refused here rather than after a file is
    # half written.
    try:
        import_pindefs.variant_source(entry).pins(
            checkout, (variant.read_text(encoding="utf-8", errors="replace"),)
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
        read = import_board.read_geometry(
            path, entry.select,
            connects=connects(entry) if entry.schematic is not None else None)
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
