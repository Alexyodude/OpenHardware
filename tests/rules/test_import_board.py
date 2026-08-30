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
    geometry = read_geometry(_brd(), select=("J1",))
    pad = next(p for p in geometry.pads if p.number == "1")
    assert pad.y_mm == pytest.approx(58.42 - 52.07 + 1.0)
    assert pad.y_mm < geometry.height_mm / 2, "the top pad came out in the bottom half"


def test_the_eagle_import_names_pads_after_their_nets():
    """A package pad is a number. The name only exists in the signals."""
    geometry = read_geometry(_brd(), select=("J1",))
    labels = {pad.label for pad in geometry.pads}
    assert {"GND", "3.3V", "IO6/SDA"} <= labels, sorted(labels)
    assert len(geometry.pads) == 28


def test_every_imported_pad_refuses_a_simulator_pin_index():
    """The same refusal 25 board files already make, and for the same reason."""
    geometry = read_geometry(_brd(), select=("J1",))
    board = build_board(geometry, VENDOR_BRD, {"vendor": "SparkFun"})
    assert all(pad["pin"] is None for pad in board["pads"])
    assert "guessed number would wire the circuit wrongly" in board["assumption"]


def test_the_derivation_states_that_nothing_was_measured_off_an_image():
    geometry = read_geometry(_brd(), select=("J1",))
    board = build_board(geometry, VENDOR_BRD, {"vendor": "SparkFun"})
    assert board["derivation"].count("Nothing here was measured off an image.") == 1
    assert "EAGLE 9.6.2" in board["derivation"]
    assert "layer 20" in board["derivation"], "the outline provenance is part of it"


def test_the_board_records_the_file_it_came_from():
    """A path is always right; a name recorded from CAD may not be."""
    geometry = read_geometry(_brd(), select=("J1",))
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
    geometry = read_geometry(footprint, select=("XIAO-RP2040-SMD",))
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

    geometry = read_geometry(footprint, select=("XIAO-STM32C5-SMD",))
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
    geometry = read_geometry(path, select=("J1",))
    assert {pad.group for pad in geometry.pads} == {"header-left", "header-right"}


def test_more_than_two_runs_are_numbered_rather_than_named(tmp_path):
    """A "header-top" for one of four columns would be a guess wearing a label."""
    grid = [
        (f"{row}{column}", column * 3.0, row * 3.0)
        for row in range(3)
        for column in range(3)
    ]
    geometry = read_geometry(_synthetic(tmp_path, grid), select=("J1",))
    groups = {pad.group for pad in geometry.pads}
    assert groups == {"header-column-1", "header-column-2", "header-column-3"}, groups


# --- a board whose pads span several placed elements (OH-75) ----------------------


def test_several_elements_can_carry_one_boards_pads():
    """The Arduino Uno is why this reader stopped taking a single name.

    It breaks its 32 pads across four placed elements -- IOH and IOL along the
    top edge, POWER and AD along the bottom -- and there is no correct quarter
    of an Uno to describe. The SparkFun board stands in for it here because it
    is the fetched fixture: J1 carries 28 header pads and MEAS two jumper pads,
    and asking for both must produce all thirty rather than the first element's.
    """
    both = read_geometry(_brd(), select=("J1", "MEAS"))
    one = read_geometry(_brd(), select=("J1",))

    assert len(both.pads) == 30
    assert len(one.pads) == 28
    # Order must not matter: these are two placed elements, not a sequence.
    reversed_order = read_geometry(_brd(), select=("MEAS", "J1"))
    assert {(p.label, p.x_mm, p.y_mm) for p in reversed_order.pads} == {
        (p.label, p.x_mm, p.y_mm) for p in both.pads
    }


def test_the_derivation_names_every_element_it_read():
    """A board file that read four headers must not claim it read one.

    The derivation is what a reader checks a board description against, and it
    is the only place the element names survive.
    """
    geometry = read_geometry(_brd(), select=("J1", "MEAS"))
    assert "elements J1 (THING_PLUS), MEAS (COMBO-JUMPER_2_NC_TRACE)" in (
        geometry.derivation
    ), geometry.derivation

    single = read_geometry(_brd(), select=("J1",))
    assert "element J1 (THING_PLUS)" in single.derivation, single.derivation


def test_naming_the_same_element_twice_is_refused():
    """An element is placed once, so its pads are read once.

    Silently deduplicating would agree with half of what the caller believes:
    somebody who names it twice thinks it holds two different things, and the
    useful answer is that it does not.
    """
    with pytest.raises(BoardImportError, match="more than once"):
        read_geometry(_brd(), select=("J1", "J1"))


def test_a_bare_string_where_a_tuple_belongs_is_refused_by_name():
    """The mistake this repository made the hour the signature changed.

    A string is iterable, so `select="J1"` reads as the elements J and 1 and
    fails with "no element called 'J'" -- naming an element nobody wrote and
    sending the reader to the vendor's file to look for it. Nine tests here and
    one in `test_kicad.py` did exactly that on 2026-08-27.
    """
    with pytest.raises(BoardImportError, match="must be a tuple"):
        read_geometry(_brd(), select="J1")


def test_a_kicad_footprint_takes_one_symbol_root():
    """Several is an EAGLE answer. A footprint is one part.

    Letting the first quietly win would turn a caller's confusion between a
    footprint and a board into a board description of half of one.
    """
    footprint = _kicad("XIAO-RP2040-SMD")
    with pytest.raises(BoardImportError, match="one symbol root"):
        read_geometry(footprint, select=("XIAO-RP2040-SMD", "XIAO-SAMD21-SMD"))


def test_the_arduino_unos_thirty_two_pads_come_off_its_four_headers():
    """The board this change exists for, against the vendor's own file.

    32 is exactly what `webui/boards/Arduino Uno.json` has, and it is 10 + 8 on
    the top edge and 8 + 6 on the bottom. The labels are the nets the vendor's
    own <signals> put those pads on, which is what makes them evidence rather
    than a reading of a silkscreen: D13 is SCK because that is what D13 is.
    """
    brd = REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd"
    if not brd.is_file():
        pytest.skip(
            "SKIPPED: UNO-TH_Rev3e.brd is not fetched. Run: "
            "python tools/get_board_sources.py arduino-uno, which prints the "
            "URL to download by hand -- it is an https-archive, like the Pico"
        )
    geometry = read_geometry(brd, select=("IOH", "IOL", "POWER", "AD"))

    assert len(geometry.pads) == 32
    rows = {}
    for pad in geometry.pads:
        rows[pad.group] = rows.get(pad.group, 0) + 1
    assert rows == {"header-top": 18, "header-bottom": 14}, rows

    labels = {pad.label for pad in geometry.pads}
    assert {"IO0", "IO9", "SCK", "MISO", "MOSI", "SS"} <= labels, labels
    assert {"AD0", "AD5/SCL", "AREF", "RESET", "VIN", "+3V3"} <= labels, labels
    assert "68.58 x 53.34 mm outline" in geometry.derivation, geometry.derivation


#: Least-squares scale and offset taking `source` onto `target`. One axis at a
#: time, because `board.svg` is not uniformly scaled -- see the test below.
def _fit(source: list[float], target: list[float]) -> tuple[float, float]:
    count = len(source)
    mean_s = sum(source) / count
    mean_t = sum(target) / count
    across = sum((s - mean_s) * (t - mean_t) for s, t in zip(source, target))
    along = sum((s - mean_s) ** 2 for s in source)
    return across / along, mean_t - (across / along) * mean_s


def _uno_pairs():
    """The landed Uno pads beside the vendor's, paired by row and by order.

    Paired by position rather than by name on purpose: GND appears three times,
    +5V twice and AD4/SDA twice, so a name join would need the very
    correspondence this is checking.
    """
    brd = REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd"
    if not brd.is_file():
        pytest.skip(
            "SKIPPED: UNO-TH_Rev3e.brd is not fetched. Run: "
            "python tools/get_board_sources.py arduino-uno for the URL"
        )
    landed = json.loads(
        (REPO / "webui" / "boards" / "Arduino Uno.json").read_text(encoding="utf-8")
    )
    height = landed["image"]["height"]
    geometry = read_geometry(brd, select=("IOH", "IOL", "POWER", "AD"))

    landed_top = sorted((p for p in landed["pads"] if p["y"] / height < 0.5),
                        key=lambda p: p["x"])
    landed_bottom = sorted((p for p in landed["pads"] if p["y"] / height >= 0.5),
                           key=lambda p: p["x"])
    vendor_top = sorted(
        (p for p in geometry.pads if p.y_mm / geometry.height_mm < 0.5),
        key=lambda p: p.x_mm)
    vendor_bottom = sorted(
        (p for p in geometry.pads if p.y_mm / geometry.height_mm >= 0.5),
        key=lambda p: p.x_mm)
    return list(zip(landed_top, vendor_top)) + list(zip(landed_bottom, vendor_bottom))


def test_the_unos_traced_pads_still_agree_with_the_vendors_board_file():
    """The check that turned an assumption in that file into a fact.

    `webui/boards/Arduino Uno.json` is the ONLY one of 26 whose pad centres
    were not derived from vendor CAD: they were traced out of PICSimLab's
    `board.svg`, and the file carried an `assumption` about which pad was
    which. Arduino's own EAGLE board file settles it.

    The residual is what is left after the one scale and offset per axis that
    separates artwork pixels from millimetres is fitted out -- subtracting raw
    coordinates would report that frame difference on every pad and say nothing
    about the trace. Measured 2026-08-27: median 0.005 mm, worst 0.008 mm,
    against a 2.540 mm header pitch. The bound here is loose against that; what
    would be a defect is a fraction of a pitch, which is what a mis-ordered pad
    produces.
    """
    pairs = _uno_pairs()
    assert len(pairs) == 32, f"paired {len(pairs)} pads, not 32"

    scale_x, offset_x = _fit([v.x_mm for _, v in pairs], [l["x"] for l, _ in pairs])
    scale_y, offset_y = _fit([v.y_mm for _, v in pairs], [l["y"] for l, _ in pairs])
    residuals = [
        max(abs((scale_x * v.x_mm + offset_x) - l["x"]) / scale_x,
            abs((scale_y * v.y_mm + offset_y) - l["y"]) / scale_y)
        for l, v in pairs
    ]
    assert max(residuals) < 0.1, (
        f"worst pad is {max(residuals):.3f} mm from where the vendor puts it, "
        f"against a 2.540 mm pitch"
    )


def test_the_unos_pad_labels_are_the_nets_the_vendor_put_them_on():
    """Every label confirmed against the vendor, with no disagreements.

    The three that look wrong and are not: D13..D10 carry SCK, MISO, MOSI and
    SS because that is what those pins are on an Uno; A4 and A5 appear twice
    because the R3 repeats them beside AREF; and IOREF sits on the +5V net
    because the R3 ties it there.
    """
    expected = {
        "SCL": "AD5/SCL", "SDA": "AD4/SDA", "AREF": "AREF", "GND": "GND",
        "13": "SCK", "12": "MISO", "~11": "MOSI", "~10": "SS",
        "~9": "IO9", "8": "IO8", "7": "IO7", "~6": "IO6", "~5": "IO5",
        "4": "IO4", "~3": "IO3", "2": "IO2", "1": "IO1", "0": "IO0",
        "NC": "1", "IOREF": "+5V", "RESET": "RESET", "3V3": "+3V3",
        "5V": "+5V", "VIN": "VIN",
        "A0": "AD0", "A1": "AD1", "A2": "AD2", "A3": "AD3",
        "A4": "AD4/SDA", "A5": "AD5/SCL",
    }
    disagreed = [
        (landed["label"], vendor.label)
        for landed, vendor in _uno_pairs()
        if expected[landed["label"]] != vendor.label
    ]
    assert not disagreed, disagreed


def test_the_unos_artwork_is_not_uniformly_scaled_and_the_file_says_so():
    """A real finding, and the only one the cross-check turned up.

    `board.svg` is 5.6616 px/mm across and 5.6382 px/mm down -- 0.41%, or
    0.28 mm over the board's 68.58 mm width. Nothing depends on it today, and
    an importer that assumed one scale for both axes would be wrong by that
    much, so the board file records it and this keeps that sentence true.
    """
    pairs = _uno_pairs()
    scale_x, _ = _fit([v.x_mm for _, v in pairs], [l["x"] for l, _ in pairs])
    scale_y, _ = _fit([v.y_mm for _, v in pairs], [l["y"] for l, _ in pairs])
    assert abs(scale_x - scale_y) > 0.01, (
        f"the artwork is uniformly scaled after all ({scale_x:.4f} vs "
        f"{scale_y:.4f} px/mm); the board file claims otherwise and should be "
        f"corrected"
    )

    landed = json.loads(
        (REPO / "webui" / "boards" / "Arduino Uno.json").read_text(encoding="utf-8")
    )
    assert f"{scale_x:.4f} px/mm" in landed["assumption"], (
        f"the board file does not record the measured {scale_x:.4f} px/mm"
    )
    assert f"{scale_y:.4f} px/mm" in landed["assumption"]


def test_the_unos_traced_pads_agree_under_one_scale_too_which_is_what_the_page_uses():
    """**The measurement that settles OH-96, and it settles it as "neither".**

    That ticket measured, in the browser, that five of the Uno's pads sit
    1.21 to 3.84 mm from the nearest pin the vendor's model puts there and
    eleven more are out by 0.7 -- and asked which of the two sources is wrong.

    Neither is. The test above fits ONE SCALE PER AXIS and gets a worst of
    0.008 mm, which is the honest fit but not the one the page performs:
    `webui/static/board3d.js` calls `group.scale.setScalar(...)`, a single
    isotropic scale for both axes, taken from `scaleFromPads`. So the question
    that matters is whether the two sources still agree under THAT
    simplification, given the artwork's 0.41% anisotropy.

    They do, by a factor of nine: worst 0.072 mm, median 0.032, against the
    0.65 mm that is the smallest disagreement the browser reported. Whatever
    produces those, it is not the traced pad map and it is not the vendor's
    board file -- so the disagreement is introduced downstream, where the model
    group is aligned to the pad field's BOUNDING BOX rather than fitted to the
    pads themselves.

    Recorded here rather than left in a ticket because it is the fact that
    stops the pad map being "corrected" into agreement with a placement bug.
    """
    pairs = _uno_pairs()
    xs = [v.x_mm for _, v in pairs]
    ys = [v.y_mm for _, v in pairs]
    px = [landed["x"] for landed, _ in pairs]
    py = [landed["y"] for landed, _ in pairs]
    count = len(pairs)
    mean_x, mean_y = sum(xs) / count, sum(ys) / count
    mean_px, mean_py = sum(px) / count, sum(py) / count

    # One magnitude for both axes, solved together -- which is what makes it
    # ONE number rather than the two the test above fits. **No reflection
    # here**: `read_geometry` has already flipped the board's y into the
    # artwork's downward sense, which `test_the_eagle_import_flips_y_exactly_once`
    # is the authority on, so both per-axis scales come out positive (5.6616
    # and 5.6382). Flipping again was the first version of this and it
    # reported a 68.9 mm residual, which is the board's own width.
    across = (sum((x - mean_x) * (p - mean_px) for x, p in zip(xs, px))
              + sum((y - mean_y) * (p - mean_py) for y, p in zip(ys, py)))
    along = (sum((x - mean_x) ** 2 for x in xs)
             + sum((y - mean_y) ** 2 for y in ys))
    scale = across / along
    offset_x = mean_px - scale * mean_x
    offset_y = mean_py - scale * mean_y

    residuals = [
        max(abs((scale * v.x_mm + offset_x) - landed["x"]),
            abs((scale * v.y_mm + offset_y) - landed["y"])) / abs(scale)
        for landed, v in pairs
    ]
    worst = max(residuals)
    assert worst < 0.2, (
        f"under the single isotropic scale the page applies, the worst pad is "
        f"{worst:.3f} mm from where Arduino's own board file puts it. It was "
        f"0.076 mm when OH-96 was settled, so either the trace or the vendor "
        f"reading has changed -- and OH-96's conclusion that neither source is "
        f"wrong no longer holds"
    )
    # And it really is much smaller than what the browser reported, which is
    # the whole argument: 0.65 mm was the SMALLEST disagreement there.
    assert worst < 0.65 / 4, (
        f"the single-scale residual is {worst:.3f} mm, which is no longer "
        f"comfortably inside the 0.65 mm the browser reported -- so the two "
        f"can no longer be told apart and OH-96's attribution is in doubt"
    )


def test_every_generated_map_states_the_scale_its_own_derivation_claims():
    """**A generated map states its scale as a FIELD, and the field is held to
    the map's own prose** (OH-121).

    Every derivation always ended "scaled at 8.0 px/mm" and the page could
    not read prose, so it re-derived the number by dividing its pixel span by
    a `pad_span` measured off a DIFFERENT pad field -- 28 castellation
    sub-pads against one pad per castellation -- and drew every composed SMD
    model 9% small, leaving their outermost pads past `PIN_REACH_MM`.

    The one map that states nothing is the traced Uno's, on purpose: its
    artwork is anisotropic by 0.41%, so it HAS no single true scale, and the
    page fits one from the pads -- measured exact to 0.093 mm there.
    """
    import re

    boards = REPO / "webui" / "boards"
    checked = 0
    for path in sorted(boards.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        stated = re.search(r"[Ss]caled at ([0-9.]+) px/mm",
                           doc.get("derivation", ""))
        if stated is None:
            assert "px_per_mm" not in doc, (
                f"{path.name} carries a px_per_mm its derivation does not "
                f"claim -- the field must restate the file's own sentence, "
                f"never invent"
            )
            continue
        checked += 1
        assert doc.get("px_per_mm") == float(stated.group(1)), (
            f"{path.name}: px_per_mm {doc.get('px_per_mm')!r} does not match "
            f"the {stated.group(1)} its own derivation states"
        )
    assert checked >= 25, f"only {checked} generated maps found"


def test_the_pin_map_refuses_a_nonsense_scale_and_allows_none():
    """`px_per_mm` is optional -- a traced map states none -- but a stated one
    must be a positive number, because 0 would divide the page by it."""
    from webui import pinmap

    base = {"board": "X", "image": {"width": 10, "height": 10},
            "pads": [{"label": "A", "pin": 1, "x": 1, "y": 1}]}
    assert pinmap.parse(base, "here").px_per_mm is None
    assert pinmap.parse({**base, "px_per_mm": 8.0}, "here").px_per_mm == 8.0
    with pytest.raises(pinmap.PinMapError):
        pinmap.parse({**base, "px_per_mm": 0}, "here")
    with pytest.raises(pinmap.PinMapError):
        pinmap.parse({**base, "px_per_mm": "eight"}, "here")
