# OpenHardware - the Arduino Uno's traced pads, held to Arduino's own CAD.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The Arduino Uno's pad map against Arduino's own board file (OH-201).

`webui/boards/Arduino Uno.json` is the one board file whose pads are in
ARTWORK space: pixels on PICSimLab's `share/boards/Arduino Uno/board.svg`,
which they are painted over. Its `source.file` names Arduino's EAGLE board,
`UNO-TH_Rev3e.brd`, and `tools/inventory.py` scores the board's geometry on
that name. These tests are what make the name a claim rather than a citation:
they read Arduino's file through `tools/import_board.py`'s own reader and hold
the artwork to it -- its rows, the fit between the two, the artwork's two
scales, and every label against the net its pad is on.

Labels on one net -- SDA and A4, SCL and A5, IOREF and 5V, and the GNDs --
cannot be told apart by any test here: swapping two of them passes every one.

Both files come from Arduino's A000066 CAD zip, an https-archive that is
downloaded by hand, so every test here skips by name where it is absent.
"""

import collections
import functools
import json
import pathlib
import re
import statistics

import pytest

from tools import eagle
from tools.import_board import PadSpec, read_geometry
from webui import api
from webui.boards import atmega328p

REPO = pathlib.Path(__file__).resolve().parents[2]
BOARD_FILE = REPO / "webui" / "boards" / "Arduino Uno.json"
BRD = REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd"
SCH = BRD.with_suffix(".sch")
#: The four placed headers that carry the Uno's pads, as Arduino's board file
#: names them: IOH (1X10) and IOL (1X08) along one edge, POWER (1X08) and AD
#: (1X06) along the other. See `tools/import_board.py`'s `_from_eagle`.
HEADERS = ("IOH", "IOL", "POWER", "AD")
#: The ATmega328P, as both of Arduino's files name it: deviceset ATMEGA328P-,
#: device PU, in a DIL28 socket.
ATMEGA = "ZU4"
#: The board file stores every pad coordinate to one decimal place.
STORED_STEP_PX = 0.1


def _vendor_file(path: pathlib.Path) -> pathlib.Path:
    if not path.is_file():
        pytest.skip(
            f"SKIPPED: {path.relative_to(REPO).as_posix()} is not fetched. Run: "
            f"python tools/get_board_sources.py arduino-uno, which prints the URL "
            f"to download by hand"
        )
    return path


def _artwork() -> list[dict]:
    """The pads as the board file states them, in artwork pixels."""
    return json.loads(BOARD_FILE.read_text(encoding="utf-8"))["pads"]


@functools.cache
def _vendor_pads() -> tuple[PadSpec, ...]:
    """Arduino's header pads, in millimetres with y down, named by their nets."""
    return read_geometry(_vendor_file(BRD), select=HEADERS).pads


@functools.cache
def _nets() -> frozenset[str]:
    """Every net Arduino's board file puts a pad on."""
    board = eagle.read_board(_vendor_file(BRD))
    return frozenset(pad.net for element in board.elements for pad in element.pads
                     if pad.net)


@functools.cache
def _atmega_pins() -> dict[str, str]:
    """The ATmega's pins, as Arduino's schematic names them, to their nets."""
    schematic = eagle.read_schematic(_vendor_file(SCH))
    return {ref.pin: net.name for net in schematic.nets for ref in net.on(ATMEGA)}


def _port_nets() -> dict[str, str]:
    """Port pin to net: the schematic names PB5 `(SCK)PB5` and PC0 `(ADC0)PC0)`."""
    return {
        found.group(): net
        for pin, net in _atmega_pins().items()
        if (found := re.search(r"P[A-Z][0-7]", pin))
    }


def _pairs() -> list[tuple[dict, PadSpec]]:
    """Each artwork pad beside the vendor pad it is: top row first, then left to right.

    By position and not by name, because the names repeat -- GND is on three
    pads, +5V on two, AD4/SDA and AD5/SCL on two each -- so a join on names
    would need the very correspondence these tests check. Sound only while
    the rows agree, which the first test holds.
    """
    artwork = sorted(_artwork(), key=lambda pad: (pad["y"], pad["x"]))
    vendor = sorted(_vendor_pads(), key=lambda pad: (pad.y_mm, pad.x_mm))
    return list(zip(artwork, vendor, strict=True))


def _fit(mm: list[float], px: list[float]) -> tuple[float, float]:
    """Least-squares scale and offset taking millimetres onto pixels."""
    mean_mm = statistics.fmean(mm)
    mean_px = statistics.fmean(px)
    across = sum((m - mean_mm) * (p - mean_px) for m, p in zip(mm, px, strict=True))
    along = sum((m - mean_mm) ** 2 for m in mm)
    return across / along, mean_px - across / along * mean_mm


def _most_rounding_leaves(mm: list[float]) -> float:
    """The largest residual a least-squares line over `mm` can leave on any
    one pad when each pixel it is fitted to is out by up to half a stored step
    and by nothing else: half a step times max_i sum_j |delta_ij - h_ij|, h
    being the fit's hat matrix, h_ij = 1/n + d_i d_j / sum d^2, d each
    position's distance from their mean. Where the pixels are otherwise an
    exact scale and offset of `mm`, the residuals are (I - h) times the pixel
    errors, which is where that comes from."""
    mean = statistics.fmean(mm)
    d = [m - mean for m in mm]
    along = sum(x * x for x in d)
    return STORED_STEP_PX / 2 * max(
        sum(abs((i == j) - (1 / len(d) + d[i] * d[j] / along)) for j in range(len(d)))
        for i in range(len(d))
    )


def _most_rounding_tilts(mm: list[float]) -> float:
    """The most a least-squares scale over `mm` moves when each pixel it is
    fitted to is out by up to half a stored step: half a step times
    sum|d| / sum d^2, d being each position's distance from their mean."""
    mean = statistics.fmean(mm)
    return (STORED_STEP_PX / 2 * sum(abs(m - mean) for m in mm)
            / sum((m - mean) ** 2 for m in mm))


def test_the_artwork_has_arduinos_header_rows_with_as_many_pads_in_each():
    """Pairing by row and by order needs the rows to agree first.

    A row is the pads sharing one y: the artwork stores each of its rows at
    one exact pixel and Arduino's file each of its rows at one exact
    millimetre, so a pad moved off its row, or onto the other, changes these
    counts.
    """
    artwork = collections.Counter(pad["y"] for pad in _artwork())
    vendor = collections.Counter(pad.y_mm for pad in _vendor_pads())
    artwork_rows = [artwork[y] for y in sorted(artwork)]
    vendor_rows = [vendor[y] for y in sorted(vendor)]
    assert artwork_rows == vendor_rows, (
        f"top to bottom, the artwork's rows hold {artwork_rows} pads and "
        f"Arduino's hold {vendor_rows}"
    )


def test_every_artwork_coordinate_is_stored_as_a_whole_number_of_steps():
    """Both rounding arguments below start here: a coordinate stored to one
    decimal place is out by at most half a step, 0.05 px.

    `_most_rounding_leaves` and `_most_rounding_tilts` take that half step as
    the whole of the error rounding can contribute. A coordinate stored to
    more places, or moved by hand by less than a step, is outside what they
    allow for, and the bounds they give would no longer be about rounding.

    One behaviour across every coordinate: the assertion names each one that
    is not a whole number of steps.
    """
    off = [
        (pad["label"], axis, pad[axis])
        for pad in _artwork()
        for axis in ("x", "y")
        if abs(pad[axis] / STORED_STEP_PX - round(pad[axis] / STORED_STEP_PX)) > 1e-6
    ]
    assert off == [], (
        f"(label, axis, px) of every coordinate that is not a whole multiple of "
        f"{STORED_STEP_PX} px: {off}"
    )


def test_one_scale_and_offset_across_leaves_no_pad_further_off_than_rounding_could():
    """The artwork pads are Arduino's pads across the board, to the precision
    the board file stores them at.

    A fit across only, with its own scale, because board.svg is not uniformly
    scaled; see the next test. Were the artwork exactly a scale and offset of
    Arduino's pads, the only error left would be rounding to the stored
    0.1 px, at most 0.05 px on each coordinate, and the most a least-squares
    line can turn that into on any one pad is computed from Arduino's own pad
    positions by `_most_rounding_leaves`. A residual beyond that is a pad that
    is not where Arduino put it, not rounding. A pad moved on its own can go a
    little further than the bound before this fails, because the fit moves
    with it. The message gives the bound in millimetres too, against a header
    pitch of 2.54 mm.

    Down, nothing is fitted here: two rows fix a line exactly, so the residual
    down is zero whenever the first test passes. What holds down is that test's
    rows, and the spacing between them is bounded only by
    tests/rules/test_import_board.py's
    test_the_unos_traced_pads_agree_under_one_scale_too_which_is_what_the_page_uses.

    One behaviour across every pad: the residuals are left by one fit through
    all of them, so the assertion is on the worst of them.
    """
    pairs = _pairs()
    mm = [v.x_mm for _, v in pairs]
    scale, offset = _fit(mm, [a["x"] for a, _ in pairs])
    across = [abs(scale * v.x_mm + offset - a["x"]) for a, v in pairs]
    bound = _most_rounding_leaves(mm)
    assert max(across) <= bound, (
        f"worst residual {max(across):.4f} px ({max(across) / scale:.4f} mm), "
        f"median {statistics.median(across):.4f} px, against {bound:.4f} px "
        f"({bound / scale:.4f} mm), the most rounding to {STORED_STEP_PX} px "
        f"could leave on these pad positions. Measured when this test was "
        f"written: worst 0.0475 px (0.0084 mm), median 0.0257 px (0.0045 mm), "
        f"against 0.1245 px (0.0220 mm)"
    )


def test_the_artwork_is_scaled_more_across_than_down_by_more_than_rounding_could_make():
    """board.svg is not uniformly scaled: a property of the artwork, not of the pads.

    Each scale is fitted over Arduino's own pad positions, and the most that
    rounding to the stored 0.1 px could move the two apart is computed from
    those positions by `_most_rounding_tilts`. A difference beyond that is the
    artwork's, and it is why the board file states no `px_per_mm` and why a
    single scale for both axes would misplace pads.
    """
    pairs = _pairs()
    across = [v.x_mm for _, v in pairs]
    down = [v.y_mm for _, v in pairs]
    scale_x, _ = _fit(across, [a["x"] for a, _ in pairs])
    scale_y, _ = _fit(down, [a["y"] for a, _ in pairs])
    slack = _most_rounding_tilts(across) + _most_rounding_tilts(down)
    assert scale_x - scale_y > slack, (
        f"{scale_x:.4f} px/mm across and {scale_y:.4f} px/mm down differ by "
        f"{scale_x - scale_y:.4f} ({scale_x / scale_y - 1:.2%}), and rounding could "
        f"account for {slack:.4f}. Measured when this test was written: 5.6616 "
        f"and 5.6382 px/mm, 0.0234 apart (0.41%), against 0.0054"
    )


def test_every_label_the_avr_module_names_is_on_the_net_arduino_gives_its_port_pin():
    """13 is on SCK: a label the AVR module names is compared with a net
    through the chip.

    `atmega328p.PIN_NAMES` gives the port pin behind a label, 13 to PB5, from
    Arduino's variant file `pins_arduino.h`; `api.header_key` drops the PWM
    tilde, so ~11 is 11. Arduino's schematic names that pin of the ATmega
    `(SCK)PB5` and puts it on net SCK, and the label's pad must be on the same
    net in Arduino's board file. SDA and A4 are both PC4, which is why the R3
    header repeats them beside AREF and why both are on AD4/SDA -- and so why
    swapping those two labels, or SCL and A5, passes here.
    `test_the_uno_states_in_its_file_the_chip_pins_its_module_states` holds the
    board file's own `chip_pin` to the same table.

    One behaviour across every such pad: the rule is the claim, and the
    assertion names each pad that breaks it. A port pin the schematic puts on
    no net is named first, as the label that leads to it.
    """
    names = atmega328p.PIN_NAMES
    ports = _port_nets()
    behind = {pad["label"]: names.get(api.header_key(pad["label"], names))
              for pad in _artwork()}
    unknown = sorted(f"{label} is {port}" for label, port in behind.items()
                     if port is not None and port not in ports)
    assert unknown == [], (
        f"atmega328p.PIN_NAMES puts these labels on port pins Arduino's schematic "
        f"names on no net: {unknown}. The port pins it does put on a net are "
        f"{sorted(ports)}"
    )
    wrong = [
        f"{a['label']} is {behind[a['label']]}, which Arduino's schematic puts on "
        f"{ports[behind[a['label']]]}, and its pad is on {v.label}"
        for a, v in _pairs()
        if behind[a["label"]] is not None and ports[behind[a["label"]]] != v.label
    ]
    assert wrong == [], wrong


def test_every_label_that_names_one_of_arduinos_nets_is_on_that_net():
    """GND is on GND and 3V3 on +3V3: a label that is a net's name is compared
    with it directly.

    Which labels name a net is read from the net list in Arduino's board file,
    not from a list here. Arduino names its two regulated rails +5V and +3V3
    and prints 5V and 3V3 beside their pads -- the nets are in the board
    file's signals and the words on its silkscreen -- so the '+' it writes
    before a rail is allowed for. IOREF and NC name no net, and the two tests
    below compare them. The GNDs are all on GND, so swapping any two passes.

    One behaviour across every such pad, as above.
    """
    nets = _nets()
    wrong = [
        (a["label"], v.label)
        for a, v in _pairs()
        if {a["label"], "+" + a["label"]} & nets
        and v.label not in {a["label"], "+" + a["label"]}
    ]
    assert wrong == [], f"(label, the net its pad is on in Arduino's file): {wrong}"


def test_the_pad_labelled_nc_is_the_one_arduinos_board_file_puts_on_no_net():
    """NC is "not connected", and so is the pad it is on.

    `tools/import_board.py` names a pad on no net by its pad number, so a
    vendor pad whose name is none of the board's nets has nothing on it.
    """
    nets = _nets()
    unconnected = [a["label"] for a, v in _pairs() if v.label not in nets]
    assert unconnected == ["NC"], (
        f"the labels on the pads Arduino's file connects to nothing: {unconnected}"
    )


def test_ioref_is_on_the_rail_arduinos_schematic_powers_the_atmega_from():
    """IOREF is on +5V: it tells a shield the voltage the board's logic runs at.

    Arduino's datasheet for this board describes IOREF as "Reference for
    digital logic V - connected to 5V": in `arduino/docs-content`,
    `content/hardware/uno/boards/uno-rev3/datasheet/datasheet.md`, section
    "Connector Pinouts", table JANALOG, pin 2, read 2026-10-08 at commit
    dab66ec. The logic is the ATmega's, and Arduino's schematic powers its VCC
    pin from a net; IOREF's pad must be on that net.

    IOREF and 5V share that net, so no comparison with nets can tell those two
    labels apart.
    """
    vcc = _atmega_pins()["VCC"]
    ioref = [v.label for a, v in _pairs() if a["label"] == "IOREF"]
    assert ioref == [vcc], (
        f"IOREF's pad is on {ioref}; Arduino's schematic powers the ATmega's VCC "
        f"from {vcc}"
    )


def test_every_label_is_one_the_tests_above_compare_with_a_net():
    """No label goes unchecked by being a kind none of the tests above takes.

    Each of them compares one kind of label and passes over the rest: a label
    `atmega328p.PIN_NAMES` names, a label that is one of the board file's net
    names with or without Arduino's '+', NC, and IOREF. A label of none of
    those kinds -- `Vin` for VIN, `RST` for RESET -- would pass all of them
    while being compared with nothing, and the board file's `assumption`
    says every label is compared.

    One behaviour across every pad: the assertion names each label of no
    compared kind.
    """
    names = atmega328p.PIN_NAMES
    nets = _nets()
    uncompared = [
        pad["label"]
        for pad in _artwork()
        if names.get(api.header_key(pad["label"], names)) is None
        and not {pad["label"], "+" + pad["label"]} & nets
        and pad["label"] not in {"NC", "IOREF"}
    ]
    assert uncompared == [], (
        f"labels that are no port pin atmega328p.PIN_NAMES names, no net of "
        f"Arduino's board file with or without '+', and neither NC nor IOREF, so "
        f"no test here compares them with anything: {uncompared}"
    )
