# OpenHardware - tests for the multi-format board importer.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import json
import math
import pathlib

import pytest

from tools import eagle, kicad
from tools.import_board import (
    MARGIN_MM,
    READERS,
    REFUSED,
    UNDERSIDE,
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

    Turn, then mirror, then translate is a convention the file never states.
    But a routed signal's copper has to end on the pads it connects, and the
    wire coordinates are independent of the element placement arithmetic. So
    the two are compared.

    Nets with a copper pour are excluded: there is no wire to land on, only a
    polygon.

    The negative controls are the point. A threshold on its own proves
    nothing — so the same score is recomputed with the mirror taken FIRST
    (the order `place` used until OH-211), with the turn taken clockwise,
    with the mirror dropped and with the rotation dropped, and every one has
    to be worse. A check that cannot fail is not evidence. Mirroring first
    scores the same whichever way it turns, which is why the direction was
    not pinned here until the order was right.
    """
    path = _brd()
    assert _coincident(path, eagle.place) == (131, 0.0), (
        "the transform, or the vendor's file, is not what this was measured on"
    )

    def mirrored_first(x, y, origin, rot, sense=1.0):
        degrees, mirrored = eagle._rotation(rot)
        x = -x if mirrored else x
        angle = math.radians(sense * degrees)
        return (origin[0] + x * math.cos(angle) - y * math.sin(angle),
                origin[1] + x * math.sin(angle) + y * math.cos(angle))

    def mirrored_first_clockwise(x, y, origin, rot):
        return mirrored_first(x, y, origin, rot, sense=-1.0)

    def clockwise(x, y, origin, rot):
        degrees, mirrored = eagle._rotation(rot)
        return eagle.place(x, y, origin, ("MR" if mirrored else "R") + str(-degrees))

    def unmirrored(x, y, origin, rot):
        return eagle.place(x, y, origin, (rot or "").replace("M", ""))

    def unrotated(x, y, origin, rot):
        return (origin[0] + x, origin[1] + y)

    assert _coincident(path, mirrored_first) == (120, 2.0828), (
        "mirroring before turning should miss the mirrored parts at MR90 and "
        "MR270, every one of them half a turn round"
    )
    assert _coincident(path, mirrored_first_clockwise)[0] == 120, (
        "mirroring first should score the same whichever way it turns, which "
        "is why it could not pin the direction"
    )
    assert _coincident(path, clockwise) == (109, 7.4848), (
        "turning clockwise should miss every part whose pads a turn moves"
    )
    worse_mirror, gap_mirror = _coincident(path, unmirrored)
    worse_rot, _ = _coincident(path, unrotated)
    assert (worse_mirror, gap_mirror) == (104, 10.7), (
        f"dropping the mirror gave {worse_mirror} coincident and a worst gap of "
        f"{gap_mirror}, so this check is not sensitive to the mirror as measured"
    )
    assert worse_rot == 88, (
        f"dropping the rotation gave {worse_rot} coincident, which should be "
        f"worse than dropping only the mirror ({worse_mirror})"
    )


#: Every EAGLE board file this project reads, by the source
#: `tools/get_board_sources.py` fetches it as and its path inside that source.
EAGLE_BOARDS = (
    ("adafruit-feather-esp32-c6", "Adafruit Feather ESP32-C6.brd"),
    ("adafruit-huzzah32", "Adafruit HUZZAH32 ESP32 Feather.brd"),
    ("adafruit-kb2040", "Adafruit KB2040.brd"),
    ("adafruit-qt-py-esp32-c3", "Adafruit QT Py ESP32-C3.brd"),
    ("arduino-uno", "UNO-TH_Rev3e.brd"),
    ("sparkfun-pro-micro-esp32-c3", "Hardware/SparkFun_Dev_ESP32_C3_MINI.brd"),
    ("sparkfun-qwiic-pocket-esp32-c6", "Hardware/Qwiic_Pocket_Dev_ESP32_C6.brd"),
    ("sparkfun-thing-plus-esp32-c6", "Hardware/Thing_Plus_ESP32_C6.brd"),
)


def test_every_routed_contact_of_a_mirrored_eagle_part_lands_on_its_own_nets_copper():
    """**EAGLE's `MRd` turns a package by d and then mirrors it in x** (OH-211),
    and the vendors' own copper says so. Every pad of every mirrored element
    the reader places, on all eight EAGLE boards, whose net is routed and
    not poured, lands within 0.01 mm of a wire end or a via of that net.
    Mirroring first and turning second agrees at MR0 and MR180 and puts a
    part at MR90 or MR270 half a turn round, which is what this caught: 26
    of these 132 contacts missed, by up to 2.08 mm on the Thing Plus C6 and
    1.78 mm on the Pro Micro C3.

    The pads are the reader's, `eagle.read_board`'s `Element.pads`; only the
    copper is read raw here, because `Board.traces` carries no net. Copper is
    a `<wire>` on layers 1 to 16, EAGLE's top, inner and bottom copper, or a
    `<via>`; layer 19 is `Unrouted`, an airwire, and is not copper. A pad is
    one contact however many times its signal lists it -- the HUZZAH32 lists
    some twice in one `<signal>` -- because the pads counted are the
    reader's, one per pad.

    **Pours are excluded, and this is exactly how:** a net is poured when any
    `<signal>` of its name holds a `<polygon>`, and then every pad on it is
    left out, whether or not a wire also reaches it. EAGLE stores a pour as
    its outline and computes the fill when it ratsnests, so a pad can join
    its net through copper the file does not carry and there is no wire end
    for it to land on. A pad on no net, or on a net with no copper at all,
    is not a routed contact and is not counted either.
    """
    import xml.etree.ElementTree as ET

    copper = {str(layer) for layer in range(1, 17)}
    landed, missed, unfetched = 0, [], []
    for source, name in EAGLE_BOARDS:
        path = REPO / "third_party" / source / name
        if not path.is_file():
            unfetched.append(source)
            continue
        signals = ET.parse(path).getroot().findall("drawing/board/signals/signal")
        poured = {signal.get("name") for signal in signals
                  if signal.find("polygon") is not None}
        ends: dict[str, list[tuple[float, float]]] = {}
        for signal in signals:
            on = ends.setdefault(signal.get("name"), [])
            on += [(float(wire.get(x)), float(wire.get(y)))
                   for wire in signal.findall("wire") if wire.get("layer") in copper
                   for x, y in (("x1", "y1"), ("x2", "y2"))]
            on += [(float(via.get("x")), float(via.get("y")))
                   for via in signal.findall("via")]
        for element in eagle.read_board(path).elements:
            if not element.mirrored:
                continue
            for pad in element.pads:
                if pad.net is None or pad.net in poured or not ends.get(pad.net):
                    continue
                gap = min(math.hypot(pad.x_mm - x, pad.y_mm - y)
                          for x, y in ends[pad.net])
                if gap < 0.01:
                    landed += 1
                else:
                    missed.append(f"{path.name} {element.name} "
                                  f"(MR{element.rotation:g}) pad {pad.number} on "
                                  f"{pad.net}: {gap:.3f} mm")
    assert not missed, (
        f"{len(missed)} contact(s) of mirrored parts miss their own net's "
        f"copper and {landed} land: {missed}"
    )
    if unfetched:
        pytest.skip(f"SKIPPED: {landed} contacts land; not fetched: {unfetched}. "
                    f"Run: python tools/get_board_sources.py <source>")
    assert landed == 132, f"{landed} contacts of mirrored parts were measured, not 132"


# --- placement, on fixtures that need no vendor tree ------------------------


def test_placement_rotates_counter_clockwise():
    """R90 takes (1, 0) to (0, 1). Stated so the convention is testable."""
    x, y = eagle.place(1.0, 0.0, (0.0, 0.0), "R90")
    assert (round(x, 9), round(y, 9)) == (0.0, 1.0)


def test_placement_turns_before_it_mirrors_in_x():
    """MRd is the package turned by d and then mirrored in x (OH-211), the
    order KiCad 7's own EAGLE importer reads it in: `orientFootprintAndText`
    sets the orientation to d + 180 and then flips top to bottom
    (pcbnew/plugins/eagle/eagle_plugin.cpp at 7.0.0, lines 1563-1566), and a
    flip top to bottom after a half turn is a mirror in x. The two orders
    agree at MR0 and MR180 and are half a turn apart at MR90 and MR270, so
    those are where it is visible: mirroring first would put (1, 0) at
    (0, -1) and (0, 1) at (-1, 0)."""
    def at(x, y, rot):
        return tuple(round(v, 9) + 0.0 for v in eagle.place(x, y, (0.0, 0.0), rot))

    assert at(1.0, 0.0, "MR0") == (-1.0, 0.0)
    assert at(1.0, 0.0, "MR180") == (1.0, 0.0)
    assert at(1.0, 0.0, "MR90") == (0.0, 1.0)
    assert at(0.0, 1.0, "MR90") == (1.0, 0.0)
    assert at(1.0, 0.0, "MR270") == (0.0, -1.0)
    assert at(0.0, 1.0, "MR270") == (-1.0, 0.0)


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
    for suffix in READERS:
        assert suffix in message, f"refusing has to say what would have worked: {suffix}"
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


def test_a_footprint_pad_with_no_number_is_refused_where_it_sits(tmp_path):
    """A lone footprint's pads are on no net, so the number is all a pad has
    to be joined to its symbol's pin by; one without it would be labelled ""."""
    footprint = tmp_path / "thing.kicad_mod"
    footprint.write_text(
        '(footprint "thing" (pad "1" thru_hole circle (at 0 0) (size 1 1)) '
        '(pad "" thru_hole circle (at 2.54 0) (size 1 1)))',
        encoding="utf-8",
    )
    (tmp_path / "thing.kicad_sym").write_text(
        '(kicad_symbol_lib (symbol "thing" (symbol "thing_1_1" (pin power_in line '
        '(at 0 0 0) (length 2.54) (name "VCC") (number "1")))))',
        encoding="utf-8",
    )
    with pytest.raises(BoardImportError) as caught:
        read_geometry(footprint)
    assert (f"{footprint}: footprint thing has a thru_hole pad at (2.54, 0) in its own "
            f"millimetres that the file gives neither a number nor a net"
            ) in str(caught.value), caught.value


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


# --- which pads are on a module's underside (OH-216) --------------------------


def _module_footprint(tmp_path) -> pathlib.Path:
    """A 10 x 8 mm module's footprint, with its symbol beside it naming pin
    n `Pn`: castellation lands 1 and 2 reaching past the F.Fab outline's left
    and right sides, 5 at its left edge where the module carries a back-side
    pad, and 3, 4, 6, 7 and 8 wholly inside it. Turned half way round the
    outline's centre, 3 and 4 swap places, so do 6 and 7, and so do 2 and 5."""
    lands = (("1", 0.3, 2), ("2", 9.7, 2), ("3", 3, 3), ("4", 7, 5), ("5", 0.3, 6),
             ("6", 3, 5), ("7", 7, 3), ("8", 5, 6.5))
    path = tmp_path / "mod.kicad_mod"
    path.write_text(
        '(footprint "mod" (layer "F.Cu")'
        ' (fp_rect (start 0 0) (end 10 8) (layer "F.Fab"))'
        + "".join(f' (pad "{n}" smd rect (at {x} {y}) (size {1.5 if x < 1 or x > 9 else 1} 1)'
                  f' (layers "F.Cu" "F.Mask"))' for n, x, y in lands)
        + ")",
        encoding="utf-8",
    )
    (tmp_path / "mod.kicad_sym").write_text(
        '(kicad_symbol_lib (symbol "mod" (symbol "mod_1_1"'
        + "".join(f' (pin passive line (at 0 0 0) (length 2.54) (name "P{n}") (number "{n}"))'
                  for n, _, _ in lands)
        + ")))",
        encoding="utf-8",
    )
    return path


def _module_board(tmp_path, back: tuple[tuple[float, float, str], ...]) -> pathlib.Path:
    """The module's own board, 10 x 8 mm at (100, 100): plated castellations
    under lands 1 and 2 -- 1 over a pad on `B.Cu` alone as well, as a
    castellation's own land on a module's underside is -- and a pad on
    `B.Cu` alone at each `(x, y, net)` of `back`."""
    parts = [
        ('(footprint "L:CASTEL" (layer "F.Cu") (at 100.3 102)'
         ' (pad "1" thru_hole circle (at 0 0) (size 1 1) (drill 0.6) (layers "*.Cu") (net "P1"))'
         ' (pad "1" smd rect (at 0 0) (size 1 1) (layers "B.Cu" "B.Mask") (net "P1")))'),
        ('(footprint "L:CASTEL" (layer "F.Cu") (at 109.7 102)'
         ' (pad "1" thru_hole circle (at 0 0) (size 1 1) (drill 0.6) (layers "*.Cu") (net "P2")))'),
    ]
    parts += [f'(footprint "L:TP" (layer "B.Cu") (at {x} {y})'
              f' (pad "1" smd circle (at 0 0) (size 1 1) (layers "B.Cu" "B.Mask") (net "{net}")))'
              for x, y, net in back]
    path = tmp_path / "mod.kicad_pcb"
    path.write_text(
        "(kicad_pcb (version 20241229)"
        ' (gr_rect (start 100 100) (end 110 108) (layer "Edge.Cuts")) '
        + " ".join(parts) + ")",
        encoding="utf-8",
    )
    return path


def _underside(geometry) -> list[str]:
    return sorted(pad.number for pad in geometry.pads if pad.group == UNDERSIDE)


def test_a_pin_under_the_module_is_grouped_underside_by_the_footprints_own_outline(
        tmp_path):
    """**OH-216: a footprint's layers cannot say which pads are under the
    module**, because it is the HOST's land pattern: every land of a XIAO SMD
    footprint is on `F.Cu`, castellations and underside test points alike.
    Its `F.Fab` outline is the module's, and a pin whose every land lies
    wholly inside it is covered by the module, so it meets the module's
    underside. Those are grouped `underside` and kept out of the header runs.

    Seen red (2026-10-09): with `_under_the_module` returning no pins, the
    pins under the module were grouped into header columns with the rest;
    again on this fixture as it now is (review round, 2026-10-09)."""
    geometry = read_geometry(_module_footprint(tmp_path))
    assert _underside(geometry) == ["3", "4", "6", "7", "8"], geometry.pads
    assert {pad.group for pad in geometry.pads if pad.number in "125"} == {
        "header-left", "header-right"}, geometry.pads
    assert "wholly inside the footprint's F.Fab outline" in geometry.derivation


#: Back-side copper of the module board under `_module_footprint`'s pins
#: unturned, each on its own pin's net, and under land 5 at the edge.
NAMED_UNDERSIDE = ((103, 103, "P3"), (107, 105, "P4"), (103, 105, "P6"), (107, 103, "P7"),
                   (100.3, 106, "P5"))


def test_a_pin_at_the_edge_is_underside_where_the_modules_own_board_puts_back_side_copper(
        tmp_path):
    """**The outline cannot place a pad at the module's edge**: the
    nRF54L15's NFC pads reach past it as a castellation's land does. The
    module's own board file can: a land over a plated-through pad is a
    castellation, one over copper on `B.Cu` alone, and over no plated-through
    pad, is on the underside. Land 5 stands over such a pad and is underside
    with the module read, and not without it; land 2 stands over a
    castellation and is not, and nor is land 1, though its castellation has
    a pad of its own on `B.Cu` alone under it.

    Seen red (2026-10-09): with the edge rule removed, land 5 stayed out. In
    review (2026-10-09), with the plated-through check removed, land 1 was
    underside too; before land 1 had back-side copper, removing that check
    failed no test that runs without Seeed's files."""
    footprint = _module_footprint(tmp_path)
    module = _module_board(tmp_path, NAMED_UNDERSIDE)
    assert _underside(read_geometry(footprint, module=module)) == ["3", "4", "5", "6", "7", "8"]
    assert _underside(read_geometry(footprint)) == ["3", "4", "6", "7", "8"]


def test_a_module_is_placed_by_the_turn_naming_its_pins_and_not_the_one_answering_most(
        tmp_path):
    """**A half turn can stand MORE of the pins under a module on back-side
    copper than the right turn does, each on another pin's net** -- Seeed's
    RP2350 and MG24 DIPs do (OH-216 review) -- so the module is placed by
    the turn under which the pins stand on copper their own symbol names.
    Here a half turn stands pins 3, 4, 6 and 7 on one another's copper, and
    pin 8 on copper on a net called `X`; unturned, 3, 4, 6 and 7 stand on
    their own nets and 8 on nothing. Which turn it is decides land 5 or land
    2 at the edge: placed by the half turn, land 2 -- a castellation --
    would be called underside.

    Seen red (2026-10-09), on `_under_the_module` as it was before review:
    it took the half turn, answering five pins to four, and put land 2
    under the module in place of land 5."""
    footprint = _module_footprint(tmp_path)
    module = _module_board(tmp_path, NAMED_UNDERSIDE + ((105, 101.5, "X"),))
    assert _underside(read_geometry(footprint, module=module)) == ["3", "4", "5", "6", "7", "8"]


def test_a_module_whose_turns_its_pins_names_cannot_tell_apart_is_refused_with_its_counts(
        tmp_path):
    """**A turn is taken only where it names `NAME_MARGIN` more pins than
    any other.** Here the module board's back-side copper is on nets naming
    two pins each, `P3/P4` and `P6/P7`, so unturned and turned half way round
    both name four of the pins under the module, and the half turn answers
    one more by copper alone. Refused, naming each turn's counts, rather
    than taking either.

    Seen red (2026-10-09), on `_under_the_module` as it was before review:
    nothing was refused; it took the half turn by copper."""
    footprint = _module_footprint(tmp_path)
    module = _module_board(tmp_path, (
        (103, 103, "P3{slash}P4"), (107, 105, "P3{slash}P4"), (103, 105, "P6{slash}P7"),
        (107, 103, "P6{slash}P7"), (100.3, 106, "P5"), (105, 101.5, "X")))
    with pytest.raises(BoardImportError) as caught:
        read_geometry(footprint, module=module)
    message = str(caught.value)
    assert ("answers {0: 4, 90: 0, 180: 5, 270: 0} of them with back-side copper "
            "and names {0: 4, 90: 0, 180: 4, 270: 0}") in message, message
    assert "must name at least 3 (NAME_MARGIN) more than any other" in message, message


def test_a_module_whose_board_answers_no_pin_under_it_is_refused_with_its_counts(
        tmp_path):
    """A module board that puts back-side copper under none of the pins the
    outline places under the module, at any quarter turn, is not this
    module's board, or not placed as this reads it. Refused, naming the
    pins and what each turn answered and named.

    Seen red (2026-10-09): with `_under_the_module` returning no pins,
    nothing was refused; again on this fixture as it now is (review round,
    2026-10-09)."""
    footprint = _module_footprint(tmp_path)
    module = _module_board(tmp_path, ())
    with pytest.raises(BoardImportError) as caught:
        read_geometry(footprint, module=module)
    message = str(caught.value)
    assert ("the pins ['3', '4', '6', '7', '8'] lie wholly inside its F.Fab "
            "outline") in message, message
    assert ("answers {0: 0, 90: 0, 180: 0, 270: 0} of them with back-side copper "
            "and names {0: 0, 90: 0, 180: 0, 270: 0}") in message, message


#: Each XIAO chip's module board as Seeed publish it, under
#: `third_party/seeed-pcb/` -- fetched by `tools/compose_board_3d.py` or by
#: hand, as `tools/import_pindefs.py` records.
MODULE_BOARDS = {"ESP32-C3": "ESP32-C3", "ESP32-C5": "ESP32-C5", "ESP32-C6": "ESP32-C6",
                 "RP2350": "RP2350", "nRF54l15": "nRF54L15", "MG24": "MG24",
                 "nRF54LM20A": "nRF54LM20A"}


def test_the_committed_xiao_board_files_state_the_importers_underside():
    """**Every XIAO board file groups `underside` exactly the pads the
    importer does** (OH-216), joined on pad number and place, with the
    module's own board read wherever `MODULE_BOARDS` names one. Written into
    the committed files once, group by group, because none of them is what
    `tools/import_board.py` regenerates today: they carry the retired
    importer's `header-top`/`header-bottom`, and nothing else was changed.

    Seen red (2026-10-09): with the files' underside pads back to
    `header-top`, every XIAO SMD board and three DIPs failed by name."""
    lib = KICAD_LIB
    if not lib.is_dir():
        pytest.skip(f"SKIPPED: {lib} is not fetched. Run: "
                    f"python tools/get_board_sources.py seeed-xiao")
    wrong, left_out = [], []
    for board in sorted((REPO / "webui" / "boards").glob("XIAO-*.json")):
        stated = json.loads(board.read_text(encoding="utf-8"))
        # OH-171: one footprint declares itself with its prefix doubled.
        name = stated["source"]["footprint"].replace("XIAO-XIAO ", "XIAO-")
        chip = next((chip for chip in MODULE_BOARDS if f"-{chip}-" in f"{board.stem}-"),
                    None)
        module = (REPO / "third_party" / "seeed-pcb" / f"{MODULE_BOARDS[chip]}.kicad_pcb"
                  if chip else None)
        if module is not None and not module.is_file():
            left_out.append(f"{board.stem}: {module.name} is not fetched")
            continue
        # A DIP footprint's pins are its SMD sibling's: two ways of mounting
        # one module (OH-200). The symbol only names the pads, which are
        # joined here on number and place and not on name.
        root = name if _has_symbol(name) else f"{name.split('-DIP')[0].split('-SMD')[0]}-SMD"
        geometry = read_geometry(KICAD_LIB / f"{name}.kicad_mod", select=(root,),
                                 module=module)
        fresh = build_board(geometry, KICAD_LIB / f"{name}.kicad_mod", {})
        want = sorted((pad["pad"], pad["x"], pad["y"]) for pad in fresh["pads"]
                      if pad["group"] == UNDERSIDE)
        have = sorted((pad["pad"], pad["x"], pad["y"]) for pad in stated["pads"]
                      if pad["group"] == UNDERSIDE)
        if want != have:
            wrong.append(f"{board.stem}: the importer puts {[w[0] for w in want]} "
                         f"under the module, the file {[h[0] for h in have]}")
    assert not wrong, "\n".join(wrong)
    if left_out:
        pytest.skip(f"SKIPPED in part: every other XIAO board file held; "
                    f"left out: {left_out}")


def _has_symbol(root: str) -> bool:
    library = KICAD_LIB / "Seeed_Studio_XIAO_Series.kicad_sym"
    try:
        kicad.read_symbol_pins(library, root)
    except kicad.KicadError:
        return False
    return True


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


# --- one pin is one pad, by the schematic's word (OH-177) ----------------------

#: A castellated board: each 1X07_CASTEL pin is a hole and a half-hole at the
#: edge, `1` and `1C`, and its schematic's device connects both to one pin.
QTPY_BRD = REPO / "third_party" / "adafruit-qt-py-esp32-c3" / "Adafruit QT Py ESP32-C3.brd"
#: `Adafruit QT Py ESP32-C3.sch`'s HEADER-1X7 _CASTEL device, as it reads.
CASTEL = ("1X07_CASTEL", tuple((f"{n}", f"{n}C") for n in range(1, 8)))


def _qtpy() -> pathlib.Path:
    if not QTPY_BRD.is_file():
        pytest.skip(
            f"SKIPPED: {QTPY_BRD.name} is not fetched. Run: "
            f"python tools/get_board_sources.py adafruit-qt-py-esp32-c3"
        )
    return QTPY_BRD


def test_the_pads_one_connect_names_are_one_pad_at_the_first_it_names():
    geometry = read_geometry(_qtpy(), ("JP1",), connects={"JP1": CASTEL})
    element = eagle.read_board(QTPY_BRD).element("JP1")
    min_x, _, _, max_y = eagle.read_board(QTPY_BRD).extent_mm()
    assert sorted(pad.number for pad in geometry.pads) == [str(n) for n in range(1, 8)]
    for pad in geometry.pads:
        (vendor,) = [one for one in element.pads if one.number == pad.number]
        assert pad.x_mm == round(vendor.x_mm - min_x + 1.0, 4), pad
        assert pad.y_mm == round(max_y - vendor.y_mm + 1.0, 4), pad
    assert ("at the pad its <connect> names first; 7 pads were merged so"
            in geometry.derivation), geometry.derivation


def test_two_pins_on_one_net_stay_two_pads():
    """`1` and `1C` are both on A0. Stated as two pins, they stay two pads:
    a net or a name is never what makes pads one pin."""
    apart = ("1X07_CASTEL", tuple((pad,) for n in range(1, 8) for pad in (f"{n}", f"{n}C")))
    geometry = read_geometry(_qtpy(), ("JP1",), connects={"JP1": apart})
    assert len(geometry.pads) == 14
    assert [pad.label for pad in geometry.pads].count("A0") == 2
    assert "merged" not in geometry.derivation


def test_a_schematic_that_names_another_footprint_is_refused():
    with pytest.raises(BoardImportError) as caught:
        read_geometry(_qtpy(), ("JP1",), connects={"JP1": ("1X07", CASTEL[1])})
    assert "a 1X07_CASTEL on the board and a 1X07 in the schematic" in str(caught.value)


def test_a_pad_in_no_connect_or_in_two_is_refused():
    missing = ("1X07_CASTEL", CASTEL[1][:-1] + (("7",),))
    with pytest.raises(BoardImportError) as caught:
        read_geometry(_qtpy(), ("JP1",), connects={"JP1": missing})
    assert "pads ['7C'] are not each in exactly one" in str(caught.value), caught.value

    twice = ("1X07_CASTEL", CASTEL[1] + (("1",),))
    with pytest.raises(BoardImportError) as caught:
        read_geometry(_qtpy(), ("JP1",), connects={"JP1": twice})
    assert "pads ['1'] are not each in exactly one" in str(caught.value), caught.value


def test_an_element_the_schematic_states_no_device_for_is_refused():
    with pytest.raises(BoardImportError) as caught:
        read_geometry(_qtpy(), ("JP1", "JP3"), connects={"JP1": CASTEL})
    assert "states no device for JP3" in str(caught.value), caught.value


def test_a_kicad_footprint_takes_no_connects():
    with pytest.raises(BoardImportError) as caught:
        read_geometry(_kicad("XIAO-RP2040-SMD"), connects={"J1": CASTEL})
    assert "connects are an EAGLE board's" in str(caught.value), caught.value


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


def test_the_unos_artwork_is_not_uniformly_scaled_and_the_file_says_so():
    """A real finding, and the only one the cross-check turned up.

    `board.svg` is 5.6616 px/mm across and 5.6382 px/mm down -- 0.41%, or
    0.28 mm over the board's 68.58 mm width. Nothing depends on it today, and
    an importer that assumed one scale for both axes would be wrong by that
    much, so the board file records it and this keeps that sentence true.

    It is also the tightest of the three tests the board file's `derivation`
    names as holding the spacing between the two rows, which no residual can
    show: the down scale it reads, to four decimals, moves with that spacing.
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

    Neither is. tests/rules/test_uno_geometry.py fits one scale per axis,
    which is the honest fit but not the one the page performs:
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


# --- the ink an EAGLE board prints (OH-122) ----------------------------------


def test_the_unos_silkscreen_is_gathered_into_strokes():
    """**The Uno was the only composed board with no white ink at all** --
    `read_board` built `Board` with the silk default, so the most
    recognisable board here had no part outlines, no polarity marks, and the
    composer said `ink front 0` without even a `not ink` line. OH-110
    recorded the gap and scoped it out; OH-122 closes it.

    The counts are pinned to the vendor's file as it is: 428 package wires
    plus 4 board-level on layer 21 minus the curved ones, and every unread
    kind counted -- the same contract `kicad._silk_of` keeps. Its 16
    rectangles, marks on the LEDs and passives, are read as filled quads
    since OH-163, and are no longer among the unread.
    """
    board = eagle.read_board(_brd_uno())
    front = [s for s in board.silk if s.layer == "F.SilkS"]
    back = [s for s in board.silk if s.layer == "B.SilkS"]
    assert len(front) == 407, f"front ink is {len(front)} strokes"
    assert len(back) == 4, f"back ink is {len(back)} strokes"
    assert len(board.silk_fills) == 16, f"{len(board.silk_fills)} filled quads"
    unread = dict(board.silk_unread)
    assert unread == {"arc": 21, "circle": 5, "text": 24}, (
        f"the unread tally moved: {unread}. If the vendor file changed, "
        f"re-measure; if the reader changed, something stopped being counted"
    )


def test_a_package_stroke_is_placed_exactly_as_its_pads_are():
    """The DIP-28's long body line, checked against NUMBERS and not against
    `place` -- a right-hand side computed by the transform under test would
    agree with itself however wrong it was.

    ZU4 sits at (46.355, 16.383) R180, and the package draws its body line
    from (-18.542, -2.794) to (18.542, -2.794) at 0.1524 mm. Rotated half a
    turn about the element origin that is (64.897, 19.177) to (27.813,
    19.177): origin + (18.542, 2.794) and origin - (18.542 - ... ) -- worked
    by hand, and 64.897 = 46.355 + 18.542 while 19.177 = 16.383 + 2.794.
    """
    board = eagle.read_board(_brd_uno())
    ends = {
        frozenset({(round(s.x1_mm, 3), round(s.y1_mm, 3)),
                   (round(s.x2_mm, 3), round(s.y2_mm, 3))})
        for s in board.silk if abs(s.width_mm - 0.1524) < 1e-6
    }
    assert frozenset({(64.897, 19.177), (27.813, 19.177)}) in ends, (
        "ZU4's body line is not where R180 about (46.355, 16.383) puts it -- "
        "package ink is not being transformed the way the pads are"
    )


def test_a_mirrored_elements_ink_moves_to_the_other_face(tmp_path):
    """EAGLE's MR puts the whole package on the underside, ink included. A
    reader that kept tPlace ink on the front for a mirrored element would
    print a bottom-mounted part's outline on the top of the board."""
    path = tmp_path / "mirrored.brd"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eagle version="9.6.2"><drawing><board>'
        '<plain><wire x1="0" y1="0" x2="10" y2="0" width="0.2" layer="20"/>'
        '<wire x1="0" y1="10" x2="10" y2="10" width="0.2" layer="20"/></plain>'
        '<libraries><library name="L"><packages><package name="P">'
        '<pad name="1" x="0" y="0" drill="1.016" diameter="1.8796"/>'
        '<wire x1="-1" y1="0" x2="1" y2="0" width="0.15" layer="21"/>'
        "</package></packages></library></libraries>"
        '<elements>'
        '<element name="A" library="L" package="P" x="2" y="2"/>'
        '<element name="B" library="L" package="P" x="8" y="8" rot="MR0"/>'
        "</elements><signals/>"
        "</board></drawing></eagle>",
        encoding="utf-8",
    )
    board = eagle.read_board(path)
    layers = sorted(s.layer for s in board.silk)
    assert layers == ["B.SilkS", "F.SilkS"], (
        f"one plain element and one mirrored one should print one stroke a "
        f"face, not {layers}"
    )
    mirrored = next(s for s in board.silk if s.layer == "B.SilkS")
    # MR0 mirrors x about the element origin: the wire's ends land at 8 -/+ 1.
    assert {round(mirrored.x1_mm, 3), round(mirrored.x2_mm, 3)} == {7.0, 9.0}


def _brd_uno():
    path = (REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd")
    if not path.is_file():
        pytest.skip(
            "SKIPPED: UNO-TH_Rev3e.brd is not fetched. Run: "
            "python tools/get_board_sources.py arduino-uno for the URL"
        )
    return path


# --- merged pads share a net, on both paths (OH-182) -------------------------


def test_an_eagle_connect_whose_pads_are_on_two_nets_is_refused_naming_both(tmp_path):
    """OH-177's review: a connect like '1 1C 2 2C' would make one pin of two
    pins' pads, keep the first pad's net and drop the other's without a word.
    One pin is on one net."""
    path = _synthetic(tmp_path, [("1", 0.0, 0.0), ("2", 0.0, 2.54)])
    with pytest.raises(BoardImportError) as caught:
        read_geometry(path, ("J1",), connects={"J1": ("P", (("1", "2"),))})
    assert ("J1's connect '1 2' makes one pin of pads on different nets: "
            "1 on NET1, 2 on NET2") in str(caught.value), caught.value


def test_an_eagle_connect_after_the_first_is_held_to_one_net_too(tmp_path):
    """The first connect is a pin of one pad and passes; the second joins two
    pads on two nets and is the one refused."""
    path = _synthetic(tmp_path, [("1", 0.0, 0.0), ("2", 0.0, 2.54), ("3", 0.0, 5.08)])
    with pytest.raises(BoardImportError) as caught:
        read_geometry(path, ("J1",), connects={"J1": ("P", (("1",), ("2", "3")))})
    assert "connect '2 3' makes one pin of pads on different nets" in str(caught.value)


# --- a whole KiCad board, as an EAGLE one (OH-182) ----------------------------

#: PCBCUPID's Glyph Mini RP2040, which publishes this board file and no
#: footprint of the board. Fetched, so absent from a fresh clone.
GLYPH = REPO / "third_party" / "pcbcupid-glyph-mini-2040" / "glyph-mini-rp2040.kicad_pcb"
#: The references of the three castellated headers its pins are on.
GLYPH_HEADERS = ("J3", "J4", "J5")
#: Olimex's ESP32-PoE, revision M2, whose two headers are on the BACK.
OLIMEX_M2 = (REPO / "third_party" / "olimex-esp32-poe" / "HARDWARE"
             / "ESP32-PoE-hardware-revision-M2" / "ESP32-PoE_Rev_M2.kicad_pcb")
OLIMEX_HEADERS = ("EXT1", "EXT2")


def _glyph() -> pathlib.Path:
    if not GLYPH.is_file():
        pytest.skip(
            f"SKIPPED: {GLYPH.name} is not fetched. Run: "
            f"python tools/get_board_sources.py pcbcupid-glyph-mini-2040"
        )
    return GLYPH


def _olimex_m2() -> pathlib.Path:
    if not OLIMEX_M2.is_file():
        pytest.skip(
            f"SKIPPED: {OLIMEX_M2.name} is not fetched. Run: "
            f"python tools/get_board_sources.py olimex-esp32-poe"
        )
    return OLIMEX_M2


def _edge_extent(tree: list) -> tuple[float, float, float, float]:
    """`(min_x, min_y, max_x, max_y)` of every point the board's own
    `gr_*` graphics on Edge.Cuts name, read off the raw tree.

    Written apart from `kicad.Board.extent_mm` on purpose, so that the frame a
    test moves copper into is not the reader's own answer. Both boards read
    here draw their outline at the top level; were the reader's corner
    anywhere else, every pad would miss its copper by the difference.
    """
    xs, ys = [], []
    for node in tree:
        if not isinstance(node, list) or not kicad.head(node).startswith("gr_"):
            continue
        layer = kicad.first(node, "layer")
        if not (layer and layer[1] == "Edge.Cuts"):
            continue
        for tag in ("start", "mid", "end"):
            point = kicad.first(node, tag)
            if point is not None:
                xs.append(float(point[1]))
                ys.append(float(point[2]))
    return min(xs), min(ys), max(xs), max(ys)


def _copper_ends(path: pathlib.Path) -> dict[str, list[tuple[float, float]]]:
    """Every track end and via of each net, by net name, in the import's frame.

    Off the raw tree rather than the reader. Up to KiCad 9 a track names its
    net by number, `(net 29)`, and the board's own `(net 29 "/GPIO-14")` table
    names that; from KiCad 10 it names it outright, `(net "GND")`. Moved into
    the import's frame by `_edge_extent`'s corner and `MARGIN_MM`.
    """
    tree = kicad.parse_sexp(path.read_text(encoding="utf-8"))
    names = {node[1]: node[2] for node in kicad.children(tree, "net") if len(node) > 2}
    min_x, min_y, _, _ = _edge_extent(tree)
    ends: dict[str, list[tuple[float, float]]] = {}
    for tag, points in (("segment", ("start", "end")), ("arc", ("start", "end")),
                        ("via", ("at",))):
        for node in kicad.children(tree, tag):
            stated = kicad.first(node, "net")[1]
            for point in points:
                x, y = (float(value) for value in kicad.first(node, point)[1:3])
                ends.setdefault(names.get(stated, stated), []).append(
                    (x - min_x + MARGIN_MM, y - min_y + MARGIN_MM))
    return ends


def test_copper_ends_are_named_whichever_way_the_track_names_its_net(tmp_path):
    """One track in each spelling, both under the net `GND`."""
    path = tmp_path / "nets.kicad_pcb"
    path.write_text(
        '(kicad_pcb (net 0 "") (net 7 "GND")'
        '(gr_rect (start 0 0) (end 10 10) (layer "Edge.Cuts"))'
        '(segment (start 1 1) (end 2 1) (width 0.2) (layer "F.Cu") (net 7))'
        '(segment (start 3 3) (end 4 3) (width 0.2) (layer "F.Cu") (net "GND")))',
        encoding="utf-8",
    )
    assert sorted(_copper_ends(path)["GND"]) == [(2.0, 2.0), (3.0, 2.0), (4.0, 4.0), (5.0, 4.0)]


def test_a_kicad_boards_header_pads_sit_on_their_own_nets_copper():
    """The placement transform, checked against data it does not use: the
    KiCad twin of `test_routed_copper_lands_on_the_computed_pad_centres`.

    A track has to end on the pad it connects, and a track's coordinates are
    the board's own, placed by no footprint. The Glyph Mini's three headers
    are turned 0, 180 and -90 degrees, so a rotation read wrongly or not at all
    moves two of them off their copper; and each pin is a hole and a half-hole
    1.5 mm apart, so keeping the wrong one of the two misses too.
    """
    path = _glyph()
    turns = sorted(placed.rotation_deg for placed in kicad.read_board(path).placements
                   if placed.reference in GLYPH_HEADERS)
    assert turns == [-90.0, 0.0, 180.0], turns
    ends = _copper_ends(path)
    geometry = read_geometry(path, select=GLYPH_HEADERS)
    off = [
        (pad.number, pad.label, round(min(math.hypot(pad.x_mm - x, pad.y_mm - y)
                                          for x, y in ends[pad.label]), 3))
        for pad in geometry.pads
    ]
    assert len(off) == 23
    assert [miss for miss in off if miss[2] >= 0.01] == [], off


def test_a_back_side_headers_pads_sit_on_their_own_nets_copper():
    """The same check on the underside, where the transform was wrong.

    KiCad stores a flipped footprint's pad offsets already flipped, and this
    importer mirrored them a second time: each of the Olimex's two back-side
    headers, turned -90 degrees, came out end to end backwards, pin 1 where
    pin 10 is. Every pad of both has a track or via of its own net ending on
    its centre only when it is turned and moved and not mirrored.
    """
    path = _olimex_m2()
    placed = [one for one in kicad.read_board(path).placements
              if one.reference in OLIMEX_HEADERS]
    assert [(one.back, one.rotation_deg) for one in placed] == [(True, -90.0)] * 2
    ends = _copper_ends(path)
    geometry = read_geometry(path, select=OLIMEX_HEADERS)
    off = [
        (pad.group, pad.number, pad.label,
         round(min(math.hypot(pad.x_mm - x, pad.y_mm - y) for x, y in ends[pad.label]), 3))
        for pad in geometry.pads
    ]
    assert len(off) == 20
    assert [miss for miss in off if miss[3] >= 0.01] == [], off


def test_a_net_name_with_a_backslash_keeps_one():
    """KiCad writes a backslash doubled inside a quoted string, and reading it
    back must halve it: Olimex's `/GPIO5\\SPI_CS` is one backslash."""
    geometry = read_geometry(_olimex_m2(), select=OLIMEX_HEADERS)
    assert "/GPIO5\\SPI_CS" in {pad.label for pad in geometry.pads}
    assert "\\\\" not in "".join(pad.label for pad in geometry.pads)


def test_the_glyph_minis_pins_are_one_pad_each_named_after_their_nets():
    """Each castellated pin is two pads numbered alike, and one pad here. The
    labels are the nets, `/GPIO-n` and the three supplies; which chip pin a
    `/GPIO-n` is, is OH-178's work."""
    geometry = read_geometry(_glyph(), select=GLYPH_HEADERS)
    gpios = [f"/GPIO-{n}" for n in (*range(16), *range(26, 30))]
    assert sorted(pad.label for pad in geometry.pads) == sorted(gpios + ["+3V3", "GND", "/5V"])
    assert "; 23 pads were merged so." in geometry.derivation, geometry.derivation


def test_the_glyph_minis_pads_are_grouped_by_the_header_they_are_on():
    """Its headers make a U, two columns and a row along the bottom, and a
    reading of runs split the row into five one-pad columns."""
    geometry = read_geometry(_glyph(), select=GLYPH_HEADERS)
    groups = {}
    for pad in geometry.pads:
        groups[pad.group] = groups.get(pad.group, 0) + 1
    assert groups == {"J3": 5, "J4": 9, "J5": 9}, groups


def test_the_glyph_minis_outline_is_its_edge_cuts():
    """18.00 x 23.50 mm from the raw tree's own Edge.Cuts points, and the
    import's size and derivation are that plus the margin on each side."""
    path = _glyph()
    min_x, min_y, max_x, max_y = _edge_extent(kicad.parse_sexp(path.read_text(encoding="utf-8")))
    assert (round(max_x - min_x, 6), round(max_y - min_y, 6)) == (18.0, 23.5)
    geometry = read_geometry(path, select=GLYPH_HEADERS)
    assert (round(geometry.width_mm, 6), round(geometry.height_mm, 6)) == (
        18.0 + 2 * MARGIN_MM, 23.5 + 2 * MARGIN_MM)
    assert "a 18.00 x 23.50 mm outline taken from Edge.Cuts" in geometry.derivation


def _pad(number, x, y, net="", kind="thru_hole", extra=""):
    """One `(pad ...)` as KiCad 9 writes it, on `net` unless that is empty."""
    on = f' (net 1 "{net}")' if net else ""
    return (f'(pad "{number}" {kind} circle (at {x} {y}) (size 1.7 1.7) (drill 1) '
            f'(layers "*.Cu" "*.Mask"){on}{extra})')


def _kicad_board(tmp_path, pads, rotation=0, beside="R1"):
    """A minimal `.kicad_pcb`: a 20 x 10 mm outline, header J1 at (5, 5)
    carrying `pads`, and a resistor referenced `beside` next to it. Written
    as the text KiCad 9 writes, so a reviewer can see it is one."""
    path = tmp_path / "probe.kicad_pcb"
    path.write_text(
        '(kicad_pcb (version 20241229) (generator "pcbnew")'
        '(gr_rect (start 0 0) (end 20 10) (stroke (width 0.05) (type solid)) '
        '(layer "Edge.Cuts"))'
        f'(footprint "Connector:Header" (layer "F.Cu") (at 5 5 {rotation})'
        f'(property "Reference" "J1") {"".join(pads)})'
        '(footprint "Resistor_SMD:R_0402" (layer "F.Cu") (at 15 5)'
        f'(property "Reference" "{beside}")'
        '(pad "1" smd rect (at 0 0) (size 0.5 0.5) (layers "F.Cu")))'
        ")",
        encoding="utf-8",
    )
    return path


CASTELLATED = " (property pad_prop_castellated)"


def test_a_pin_is_kept_at_its_whole_hole_placed_by_hand(tmp_path):
    """Pad 1 is a half-hole KiCad flags castellated, written first, and a
    whole hole: the whole hole is kept, whatever the file's order.

    J1 at (5, 5) turned 90 degrees, worked by hand: KiCad turns a footprint
    counter-clockwise as drawn, so its pad 2.54 mm below the origin lands
    2.54 mm right of it, at (7.54, 5); the 1 mm margin makes that (8.54, 6).
    The whole hole at the origin is (6, 6)."""
    path = _kicad_board(tmp_path, [
        _pad("1", 1.5, 0, "A", extra=CASTELLATED), _pad("1", 0, 0, "A"),
        _pad("2", 0, 2.54, "B")], rotation=90)
    geometry = read_geometry(path, select=("J1",))
    assert {(pad.label, pad.number, pad.x_mm, pad.y_mm, pad.group) for pad in geometry.pads} == {
        ("A", "1", 6.0, 6.0, "J1"), ("B", "2", 8.54, 6.0, "J1")}
    assert "at the first of them KiCad does not flag castellated" in geometry.derivation
    assert "; 1 pads were merged so." in geometry.derivation, geometry.derivation


def test_a_pin_whose_pads_are_all_castellated_is_kept_at_the_first(tmp_path):
    path = _kicad_board(tmp_path, [
        _pad("1", 1.5, 0, "A", extra=CASTELLATED), _pad("1", 3, 0, "A", extra=CASTELLATED)])
    geometry = read_geometry(path, select=("J1",))
    assert [(pad.x_mm, pad.y_mm) for pad in geometry.pads] == [(7.5, 6.0)]


def test_pads_one_number_on_two_nets_are_refused_naming_each(tmp_path):
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A"), _pad("1", 1.5, 0, "B")])
    with pytest.raises(BoardImportError) as caught:
        read_geometry(path, select=("J1",))
    assert ("J1 numbers 2 pads 1, which makes them one pin, and puts them on "
            "different nets: pad 1 at (0, 0) on A, pad 1 at (1.5, 0) on B"
            ) in str(caught.value), caught.value


def test_three_pads_one_number_are_refused_when_only_the_last_is_elsewhere(tmp_path):
    path = _kicad_board(tmp_path, [
        _pad("1", 0, 0, "A"), _pad("1", 1.5, 0, "A"), _pad("1", 3, 0, "B")])
    with pytest.raises(BoardImportError, match="J1 numbers 3 pads 1"):
        read_geometry(path, select=("J1",))


def test_a_pin_on_a_net_beside_its_twin_on_none_is_refused(tmp_path):
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A"), _pad("1", 1.5, 0)])
    with pytest.raises(BoardImportError, match="pad 1 at \\(1.5, 0\\) on no net"):
        read_geometry(path, select=("J1",))


def test_unnumbered_pads_are_never_one_pin(tmp_path):
    """Two plated holes numbered "" and 10 mm apart are two pads, even on
    one net: an unnumbered pad is no pin at all."""
    path = _kicad_board(tmp_path, [_pad("", 0, 0, "GND"), _pad("", 10, 0, "GND")])
    geometry = read_geometry(path, select=("J1",))
    assert sorted(pad.x_mm for pad in geometry.pads) == [6.0, 16.0]
    assert {pad.label for pad in geometry.pads} == {"GND"}, "an unnumbered pad is named by its net"
    assert "merged" not in geometry.derivation


def test_a_plated_pad_with_neither_a_number_nor_a_net_is_refused_where_it_sits(tmp_path):
    """**A pad with neither has no name to carry**: it would be labelled ""
    and nothing should invent one. J1 at (5, 5) turned 90 degrees puts its
    pad 2.54 mm below the origin 2.54 mm right of it, at (7.54, 5) on the
    board, which is the position the refusal names."""
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A"), _pad("", 0, 2.54)], rotation=90)
    with pytest.raises(BoardImportError) as caught:
        read_geometry(path, select=("J1",))
    assert (f"{path}: J1 (Header) has a plated through-hole pad at (7.54, 5) on the "
            f"board that the file gives neither a number nor a net"
            ) in str(caught.value), caught.value


def test_pads_one_number_on_no_net_are_never_one_pin(tmp_path):
    """A connector's two `MP` tabs connect nothing and are two pads."""
    path = _kicad_board(tmp_path, [_pad("MP", 0, 0), _pad("MP", 10, 0)])
    geometry = read_geometry(path, select=("J1",))
    assert len(geometry.pads) == 2
    assert "merged" not in geometry.derivation


def test_a_pad_on_no_net_is_named_by_its_number(tmp_path):
    path = _kicad_board(tmp_path, [_pad("3", 0, 0)])
    assert [pad.label for pad in read_geometry(path, select=("J1",)).pads] == ["3"]


def test_a_non_plated_hole_is_not_a_pad(tmp_path):
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A"), _pad("", 5, 0, kind="np_thru_hole")])
    assert [pad.number for pad in read_geometry(path, select=("J1",)).pads] == ["1"]


def test_a_kicad_board_reference_not_in_the_file_is_refused_naming_it(tmp_path):
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A")])
    with pytest.raises(BoardImportError) as caught:
        read_geometry(path, select=("J1", "J9"))
    assert ("0 footprints have the reference 'J9', and --select needs exactly "
            "one. Those with through-hole pads: J1 (1 pads, Header)"
            ) in str(caught.value), caught.value


def test_a_reference_two_footprints_share_is_refused(tmp_path):
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A")], beside="J1")
    with pytest.raises(BoardImportError, match="2 footprints have the reference 'J1'"):
        read_geometry(path, select=("J1",))


def test_a_kicad_board_without_select_lists_the_footprints_to_choose_from(tmp_path):
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A")])
    with pytest.raises(BoardImportError) as caught:
        read_geometry(path)
    assert "Name them by reference with --select: J1 (1 pads, Header)" in str(caught.value)


def test_a_kicad_board_reference_named_twice_is_refused(tmp_path):
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A")])
    with pytest.raises(BoardImportError, match="--select names J1 more than once"):
        read_geometry(path, select=("J1", "J1"))


def test_a_kicad_board_footprint_with_no_through_hole_pad_is_refused(tmp_path):
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A")])
    with pytest.raises(BoardImportError, match="R1 is a R_0402, which has no through-hole pads"):
        read_geometry(path, select=("R1",))


def test_a_kicad_board_takes_no_symbols_and_no_connects(tmp_path):
    path = _kicad_board(tmp_path, [_pad("1", 0, 0, "A")])
    with pytest.raises(BoardImportError, match="nothing to join"):
        read_geometry(path, select=("J1",), symbols=tmp_path / "any.kicad_sym")
    with pytest.raises(BoardImportError, match="nothing to join"):
        read_geometry(path, select=("J1",), connects={"J1": ("P", (("1",),))})
