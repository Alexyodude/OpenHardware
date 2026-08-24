# OpenHardware - tests for the multi-format board importer.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import json
import math
import pathlib

import pytest

from tools import eagle
from tools.import_board import (
    READERS,
    REFUSED,
    BoardImportError,
    build_board,
    read_geometry,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
#: The first non-KiCad, non-Seeed CAD in this project. Fetched by
#: `tools/get_board_sources.py`, so it is absent from a fresh clone and every
#: test that needs it skips by name rather than failing.
VENDOR_BRD = (
    REPO
    / "third_party"
    / "sparkfun-thing-plus-esp32-c6"
    / "Hardware"
    / "Thing_Plus_ESP32_C6.brd"
)
KICAD_LIB = REPO / "third_party" / "seeed-xiao" / "Seeed Studio XIAO Series Library"


def _brd() -> pathlib.Path:
    if not VENDOR_BRD.is_file():
        pytest.skip(
            f"SKIPPED: {VENDOR_BRD.name} is not fetched. Run: "
            f"python tools/get_board_sources.py sparkfun-thing-plus-esp32-c6"
        )
    return VENDOR_BRD


def _kicad(name: str) -> pathlib.Path:
    path = KICAD_LIB / f"{name}.kicad_mod"
    if not path.is_file():
        pytest.skip(
            f"SKIPPED: {name} is not fetched. Run: "
            f"python tools/get_board_sources.py seeed-xiao"
        )
    return path


def _coincident(path, place):
    """(pads whose net is routed to their centre, worst residual) under `place`.

    Takes the placement function so the caller can feed it a deliberately
    broken one and see the score fall. `import` is local because this is the
    only thing in the file that needs the raw tree rather than the parser.
    """
    import xml.etree.ElementTree as ET

    board = ET.parse(path).getroot().find("drawing/board")
    libraries = {
        library.get("name"): library for library in board.findall("libraries/library")
    }
    centres = {}
    for element in board.findall("elements/element"):
        library = libraries.get(element.get("library"))
        package = (
            None
            if library is None
            else library.find("packages/package[@name='%s']" % element.get("package"))
        )
        if package is None:
            continue
        origin = (float(element.get("x")), float(element.get("y")))
        rot = element.get("rot")
        for tag in ("pad", "smd"):
            for pad in package.findall(tag):
                centres[(element.get("name"), pad.get("name"))] = place(
                    float(pad.get("x")), float(pad.get("y")), origin, rot
                )

    coincident, residuals = 0, [0.0]
    for signal in board.findall("signals/signal"):
        if signal.find("polygon") is not None:
            continue
        points = [
            (float(wire.get(x)), float(wire.get(y)))
            for wire in signal.findall("wire")
            for x, y in (("x1", "y1"), ("x2", "y2"))
        ] + [(float(v.get("x")), float(v.get("y"))) for v in signal.findall("via")]
        if not points:
            continue
        for ref in signal.findall("contactref"):
            centre = centres.get((ref.get("element"), ref.get("pad")))
            if centre is None:
                continue
            gap = min(math.hypot(centre[0] - x, centre[1] - y) for x, y in points)
            if gap < 0.01:
                coincident += 1
            else:
                residuals.append(round(gap, 4))
    return coincident, max(residuals)


def _synthetic(tmp_path, pads, outline=((0, 0, 10, 0), (0, 10, 10, 10)), rot=None):
    """A minimal EAGLE board placing one package, for tests with no vendor tree.

    Written as text rather than built with ElementTree so the fixture reads as
    the format it is imitating: a reviewer can see it is an EAGLE file.
    """
    pad_xml = "".join(
        f'<pad name="{n}" x="{x}" y="{y}" drill="1.016" diameter="1.8796"/>'
        for n, x, y in pads
    )
    nets = "".join(
        f'<signal name="NET{n}"><contactref element="J1" pad="{n}"/></signal>'
        for n, _, _ in pads
    )
    wires = "".join(
        f'<wire x1="{a}" y1="{b}" x2="{c}" y2="{d}" width="0.2" layer="20"/>'
        for a, b, c, d in outline
    )
    placed = '<element name="J1" library="L" package="P" x="0" y="0"'
    if rot is not None:
        placed += f' rot="{rot}"'
    placed += "/>"

    path = tmp_path / "probe.brd"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eagle version="9.6.2"><drawing><board>'
        f"<plain>{wires}</plain>"
        '<libraries><library name="L"><packages>'
        f'<package name="P">{pad_xml}</package>'
        "</packages></library></libraries>"
        f"<elements>{placed}</elements>"
        f"<signals>{nets}</signals>"
        "</board></drawing></eagle>",
        encoding="utf-8",
    )
    return path


# --- the vendor's own coordinates ------------------------------------------


def test_an_eagle_pad_is_the_coordinate_the_file_states():
    """Traceability, checked against the bytes rather than against a number.

    The parser must not be trusted to say what it read, so the literal text
    the vendor wrote is searched for in the file and matched to what came out.
    """
    path = _brd()
    board = eagle.read_board(path)
    pad = next(p for p in board.element("J1").pads_of("thru_hole") if p.number == "1")

    assert (pad.x_mm, pad.y_mm) == (1.27, 52.07)
    assert pad.net == "IO6/SDA"
    text = path.read_text(encoding="utf-8", errors="replace")
    assert '<pad name="1" x="1.27" y="52.07"' in text, (
        "the vendor's own line is not in the file, so this test is checking "
        "the parser against itself"
    )


def test_the_header_pitch_is_exactly_one_tenth_of_an_inch():
    """An independent fact about the object, not about the parse.

    A 0.1 inch header pitch is a physical property of every through-hole
    development board, and `webui/pinmap.py` treats that pitch as what
    identifies a header run. Coming out at exactly 2.54 mm is evidence the
    units are millimetres and the placement did not scale anything.
    """
    pads = eagle.read_board(_brd()).element("J1").pads_of("thru_hole")
    rows = sorted({round(pad.y_mm, 4) for pad in pads})
    pitches = {round(b - a, 6) for a, b in zip(rows, rows[1:])}
    assert pitches == {2.54}, f"header rows are not on a 0.1 inch pitch: {pitches}"


def test_the_outline_is_a_round_number_of_inches():
    """The second independent check, on the other axis and a different node.

    The outline comes from `<plain>` wires and the pads from `<elements>`, so
    agreeing that both are millimetres is two separate readings landing on the
    same convention. 22.86 mm is 0.900 inch and 58.42 mm is 2.300 inch, to the
    micrometre; a misread scale would not produce round imperial numbers.
    """
    min_x, min_y, max_x, max_y = eagle.read_board(_brd()).extent_mm()
    assert (min_x, min_y) == (0.0, 0.0)
    assert round((max_x - min_x) / 25.4, 4) == 0.9
    assert round((max_y - min_y) / 25.4, 4) == 2.3


def test_routed_copper_lands_on_the_computed_pad_centres():
    """The placement transform, checked against data it does not use.

    Mirror-then-rotate-then-translate is a convention the file never states.
    But a routed signal's copper has to end on the pads it connects, and the
    wire coordinates are independent of the element placement arithmetic. So
    the two are compared.

    Nets with a copper pour are excluded: there is no wire to land on, only a
    polygon.

    The two negative controls are the point. A threshold on its own proves
    nothing — so the same score is recomputed with the mirror dropped and
    with the rotation dropped, and both have to be worse. A check that cannot
    fail is not evidence.

    It does *not* pin the direction of rotation: see the note at the end of
    `tools/eagle.py`'s docstring.
    """
    path = _brd()
    assert _coincident(path, eagle.place) == (120, 2.0828), (
        "the transform, or the vendor's file, is not what this was measured on"
    )

    def unmirrored(x, y, origin, rot):
        return eagle.place(x, y, origin, (rot or "").replace("M", ""))

    def unrotated(x, y, origin, rot):
        return (origin[0] + x, origin[1] + y)

    worse_mirror, gap_mirror = _coincident(path, unmirrored)
    worse_rot, _ = _coincident(path, unrotated)
    assert worse_mirror < 120 and gap_mirror > 10.0, (
        f"dropping the mirror changed nothing ({worse_mirror} coincident), so this "
        f"check is not sensitive to the mirror and proves nothing about it"
    )
    assert worse_rot < worse_mirror, (
        f"dropping the rotation ({worse_rot}) should be worse than dropping only "
        f"the mirror ({worse_mirror})"
    )


# --- placement, on fixtures that need no vendor tree ------------------------


def test_placement_rotates_counter_clockwise():
    """R90 takes (1, 0) to (0, 1). Stated so the convention is testable."""
    x, y = eagle.place(1.0, 0.0, (0.0, 0.0), "R90")
    assert (round(x, 9), round(y, 9)) == (0.0, 1.0)


def test_placement_mirrors_in_x_before_it_rotates():
    """MR90 is not R90 mirrored afterwards, and the order is visible here."""
    assert tuple(round(v, 9) for v in eagle.place(1.0, 0.0, (0.0, 0.0), "MR0")) == (
        -1.0,
        0.0,
    )
    assert tuple(round(v, 9) for v in eagle.place(1.0, 0.0, (0.0, 0.0), "MR90")) == (
        0.0,
        -1.0,
    )


def test_a_spin_does_not_move_a_pad():
    """EAGLE's S prefix spins the text, not the geometry."""
    assert eagle.place(2.0, 3.0, (0.0, 0.0), "SR0") == (2.0, 3.0)


def test_an_unreadable_rotation_names_the_value_it_could_not_read():
    with pytest.raises(eagle.EagleError, match="RUBBISH"):
        eagle.place(0.0, 0.0, (0.0, 0.0), "RUBBISH")


def test_placement_carries_the_element_origin(tmp_path):
    board = eagle.read_board(_synthetic(tmp_path, [("1", 2.0, 3.0)]))
    pad = board.element("J1").pads[0]
    assert (pad.x_mm, pad.y_mm) == (2.0, 3.0)
    assert pad.net == "NET1"


# --- refusing what cannot be read ------------------------------------------


def test_a_pdf_is_refused_naming_what_is_missing(tmp_path):
    """OH-25's done-criterion: a vendor with only a PDF is refused, with why."""
    paper = tmp_path / "RPI-PICO-R3-PUBLIC-SCHEMATIC.pdf"
    paper.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(BoardImportError) as caught:
        read_geometry(paper)
    message = str(caught.value)
    assert "no pad coordinates" in message
    assert ".brd" in message and ".kicad_mod" in message, (
        "refusing has to say what would have worked"
    )
    assert "board_sources" in message, "and where to find out who publishes one"


def test_an_image_is_refused_citing_the_precedent_for_not_measuring_one(tmp_path):
    """The sentence 26 board files carry, defended.

    `webui/pinmap.py` records that the Arduino Uno's pad centres were taken
    off `board.svg` by hand. Doing that silently for a vendor would make
    'Nothing here was measured off an image' false everywhere at once.
    """
    picture = tmp_path / "pinout.png"
    picture.write_bytes(b"\x89PNG\r\n")

    with pytest.raises(BoardImportError, match="measured off an image"):
        read_geometry(picture)


def test_a_binary_brd_is_refused_as_not_being_eagle(tmp_path):
    """The extension is not the format. Cadence Allegro writes .brd too.

    The Raspberry Pi Pico design files ship `RPI-PICO-R3a-PUBLIC.brd`, which
    is Allegro. Dispatching on the suffix alone and handing it to an XML
    parser would fail with a message about a byte offset.
    """
    allegro = tmp_path / "RPI-PICO-R3a-PUBLIC.brd"
    allegro.write_bytes(b"\x00\x01\x02\x03cadence allegro\x00\xff")

    with pytest.raises(BoardImportError) as caught:
        read_geometry(allegro)
    assert "Allegro" in str(caught.value)


def test_an_eagle_schematic_is_refused_because_pads_have_no_position(tmp_path):
    schematic = tmp_path / "board.sch"
    schematic.write_text("<eagle/>", encoding="utf-8")
    with pytest.raises(BoardImportError, match="no board geometry"):
        read_geometry(schematic)


def test_an_unknown_suffix_lists_what_can_be_read(tmp_path):
    odd = tmp_path / "board.qqq"
    odd.write_text("?", encoding="utf-8")
    with pytest.raises(BoardImportError) as caught:
        read_geometry(odd)
    for suffix in READERS:
        assert suffix in str(caught.value)


def test_no_suffix_is_both_readable_and_refused():
    overlap = set(READERS) & set(REFUSED)
    assert not overlap, f"{overlap} would be read or refused depending on order"


def test_every_refused_format_says_what_it_is():
    """A refusal that does not say what the file *is* leaves nowhere to go."""
    for suffix, reason in REFUSED.items():
        assert suffix.startswith("."), suffix
        assert len(reason) > 15, f"{suffix}: {reason!r} does not explain anything"


# --- the importer above the parsers -----------------------------------------


def test_an_ambiguous_eagle_board_refuses_and_lists_the_candidates():
    """Three elements on this board carry through-hole pads. Guessing is wrong.

    Taking the one with the most pads would be right here and wrong on a board
    with a DIP socket, which is the shape of every heuristic that works until
    it does not.
    """
    with pytest.raises(BoardImportError) as caught:
        read_geometry(_brd())
    message = str(caught.value)
    assert "--select" in message
    for name in ("J1", "J2", "MEAS"):
        assert name in message, f"{name} has through-hole pads and is not offered"


def test_the_eagle_import_flips_y_exactly_once():
    """EAGLE counts up from the bottom; the board JSON counts down from the top.

    Pad 1 sits 52.07 mm up a 58.42 mm board, so it belongs near the top of the
    output. Flipping twice, or not at all, puts the header upside down and
    nothing downstream would notice.
    """
    geometry = read_geometry(_brd(), select="J1")
    pad = next(p for p in geometry.pads if p.number == "1")
    assert pad.y_mm == pytest.approx(58.42 - 52.07 + 1.0)
    assert pad.y_mm < geometry.height_mm / 2, "the top pad came out in the bottom half"


def test_the_eagle_import_names_pads_after_their_nets():
    """A package pad is a number. The name only exists in the signals."""
    geometry = read_geometry(_brd(), select="J1")
    labels = {pad.label for pad in geometry.pads}
    assert {"GND", "3.3V", "IO6/SDA"} <= labels, sorted(labels)
    assert len(geometry.pads) == 28


def test_every_imported_pad_refuses_a_simulator_pin_index():
    """The same refusal 25 board files already make, and for the same reason."""
    geometry = read_geometry(_brd(), select="J1")
    board = build_board(geometry, VENDOR_BRD, {"vendor": "SparkFun"})
    assert all(pad["pin"] is None for pad in board["pads"])
    assert "guessed number would wire the circuit wrongly" in board["assumption"]


def test_the_derivation_states_that_nothing_was_measured_off_an_image():
    geometry = read_geometry(_brd(), select="J1")
    board = build_board(geometry, VENDOR_BRD, {"vendor": "SparkFun"})
    assert board["derivation"].count("Nothing here was measured off an image.") == 1
    assert "EAGLE 9.6.2" in board["derivation"]
    assert "layer 20" in board["derivation"], "the outline provenance is part of it"


def test_the_board_records_the_file_it_came_from():
    """A path is always right; a name recorded from CAD may not be."""
    geometry = read_geometry(_brd(), select="J1")
    board = build_board(geometry, VENDOR_BRD, {"vendor": "SparkFun"})
    assert board["source"]["file"].endswith("Thing_Plus_ESP32_C6.brd")


# --- the KiCad reader, through the same front end ---------------------------


def test_the_generic_importer_reproduces_a_committed_kicad_board_exactly():
    """One importer, two formats, and the KiCad half must not have drifted.

    webui/boards/XIAO-RP2040-DIP.json was produced by
    tools/import_kicad_board.py, a different tool. Every pad this importer
    emits has to land on the same pixel, or the generalisation changed the
    answer while claiming only to widen the input.
    """
    footprint = _kicad("XIAO-RP2040-DIP")
    committed = json.loads(
        (REPO / "webui" / "boards" / "XIAO-RP2040-DIP.json").read_text(encoding="utf-8")
    )
    geometry = read_geometry(footprint, select="XIAO-RP2040-SMD")
    board = build_board(geometry, footprint, {"vendor": "Seeed Studio"})

    assert board["image"]["width"] == committed["image"]["width"]
    assert board["image"]["height"] == committed["image"]["height"]

    mine = {pad["pad"]: pad for pad in board["pads"]}
    theirs = {pad["pad"]: pad for pad in committed["pads"]}
    assert set(mine) == set(theirs)
    for number, pad in theirs.items():
        assert (mine[number]["x"], mine[number]["y"]) == (pad["x"], pad["y"]), (
            f"pad {number} moved from {pad['x']},{pad['y']} to "
            f"{mine[number]['x']},{mine[number]['y']}"
        )
        assert mine[number]["label"] == pad["label"]
        assert mine[number]["group"] == pad["group"]


def test_a_footprint_whose_declared_name_is_not_its_filename_is_not_used_silently():
    """Note 4 on this ticket, reproduced and then refused.

    The vendor file declares (footprint "XIAO-XIAO STM32C5-SMD") and is the
    only one of the 37 in that library that disagrees with its own filename.
    tools/import_kicad_board.py took the declared name for both the board name
    and source.footprint and never noticed. Here the join to the symbol
    library fails on it, loudly, and offers the name that does exist.
    """
    footprint = _kicad("XIAO-STM32C5-SMD")
    with pytest.raises(BoardImportError) as caught:
        read_geometry(footprint)
    message = str(caught.value)
    assert "XIAO-XIAO STM32C5-SMD" in message, "the wrong name it tried is not shown"
    assert "XIAO-STM32C5-SMD" in message, "nor the right one, which the library has"

    geometry = read_geometry(footprint, select="XIAO-STM32C5-SMD")
    assert geometry.declared_name == "XIAO-XIAO STM32C5-SMD"
    board = build_board(geometry, footprint, {"vendor": "Seeed Studio"})
    assert board["board"] == "XIAO-STM32C5-SMD", "the board is named after its file"
    assert board["source"]["declared_name"] == "XIAO-XIAO STM32C5-SMD"


def test_a_kicad_footprint_with_no_symbol_library_beside_it_says_so(tmp_path):
    lonely = tmp_path / "thing.kicad_mod"
    lonely.write_text(
        '(footprint "thing" (pad "1" thru_hole circle (at 0 0) (size 1 1)))',
        encoding="utf-8",
    )
    with pytest.raises(BoardImportError, match="holds 0 of them"):
        read_geometry(lonely)


# --- grouping ---------------------------------------------------------------


def test_header_runs_are_read_from_the_pads_not_assumed(tmp_path):
    """Two columns become left and right; two rows become top and bottom.

    tools/import_kicad_board.py decides with "header-top if y < 0", which is
    true of a footprint centred on its origin and meaningless for an EAGLE
    board whose origin is a corner. Reading the runs works for both, and the
    committed-board test above pins that KiCad still gets the same answer.
    """
    path = _synthetic(tmp_path, [("1", 0.0, 0.0), ("2", 0.0, 2.54), ("3", 5.0, 0.0)])
    geometry = read_geometry(path, select="J1")
    assert {pad.group for pad in geometry.pads} == {"header-left", "header-right"}


def test_more_than_two_runs_are_numbered_rather_than_named(tmp_path):
    """A "header-top" for one of four columns would be a guess wearing a label."""
    grid = [
        (f"{row}{column}", column * 3.0, row * 3.0)
        for row in range(3)
        for column in range(3)
    ]
    geometry = read_geometry(_synthetic(tmp_path, grid), select="J1")
    groups = {pad.group for pad in geometry.pads}
    assert groups == {"header-column-1", "header-column-2", "header-column-3"}, groups
