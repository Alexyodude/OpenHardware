# OpenHardware - tools/eagle.py reads an outline wire's curve (OH-235).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""An EAGLE board's outline, curves included, held to something outside it.

`tools/eagle.py` used to take a Dimension wire's endpoints and ignore its
`curve` attribute, so the QT Py ESP32-C3's four r = 2.54 mm corners were drawn
as 45-degree chamfers. Three oracles hold the fix:

  * Adafruit's own whole-board STEP of that board, whose corners are r = 2.54
    mm cylinders (needs OCP and the fetched file, and skips by name without);
  * the arc-exact area of every board's outline, computed here from the raw
    wires and not from the reader, within the bound the chord rule allows;
  * the list of boards that have a curved outline, computed from the files.
"""

import hashlib
import itertools
import math
import pathlib
import xml.etree.ElementTree as ET

import pytest

from tools import compose_board_3d as compose
from tools import eagle

REPO = pathlib.Path(__file__).resolve().parents[2]
THIRD_PARTY = REPO / "third_party"
CACHE = THIRD_PARTY / "seeed-3d"
QTPY_BRD = THIRD_PARTY / "adafruit-qt-py-esp32-c3" / "Adafruit QT Py ESP32-C3.brd"
#: Adafruit's stated corner radius on the QT Py: 0.1 inch.
CORNER_RADIUS_MM = 2.54


def _boards() -> list[pathlib.Path]:
    """Every EAGLE board file fetched into this tree."""
    return sorted(THIRD_PARTY.rglob("*.brd"))


def _curved_dimension_wires(path: pathlib.Path) -> list[ET.Element]:
    """The Dimension wires of one board's `<plain>` that carry a curve, read
    from the XML directly, not through the reader under test."""
    root = ET.parse(path).getroot()
    return [wire for wire in root.findall("drawing/board/plain/wire")
            if wire.get("layer") == eagle.DIMENSION_LAYER
            and wire.get("curve") is not None]


def _curved_boards() -> list[pathlib.Path]:
    found = [path for path in _boards() if _curved_dimension_wires(path)]
    if not found:
        pytest.skip("SKIPPED: no EAGLE board is fetched into third_party/, "
                    "so none can be checked for a curved outline")
    return found


def _arc_of(wire: ET.Element) -> tuple[float, float, float, float, float]:
    return (float(wire.get("x1")), float(wire.get("y1")),
            float(wire.get("x2")), float(wire.get("y2")),
            float(wire.get("curve") or 0.0))


def _shoelace(segments: list[tuple[float, float, float, float]]) -> float:
    """Signed area under a path of straight segments, as a sum of
    cross(p1, p2) / 2, which is additive per segment."""
    return sum((ax * by - bx * ay) / 2 for ax, ay, bx, by in segments)


# --- the sign and the shape of one arc ---------------------------------------


def test_a_negative_curve_goes_clockwise_and_stays_on_its_circle():
    # The QT Py's lower right corner as the file writes it: (17.78, 2.54) to
    # (15.24, 0), curve -90, round a centre at (15.24, 2.54).
    points = eagle.arc_points(17.78, 2.54, 15.24, 0.0, -90.0)
    assert points[0] == (17.78, 2.54) and points[-1] == (15.24, 0.0)
    for x, y in points:
        assert math.hypot(x - 15.24, y - 2.54) == pytest.approx(2.54, abs=1e-9)
    # Clockwise from due east: y only ever falls, x only ever falls.
    assert all(b[1] < a[1] and b[0] < a[0] for a, b in itertools.pairwise(points))


def test_a_positive_curve_is_the_same_arc_walked_the_other_way():
    # Reversing a wire flips the sign of its curve and nothing else.
    forward = eagle.arc_points(17.78, 2.54, 15.24, 0.0, -90.0)
    backward = eagle.arc_points(15.24, 0.0, 17.78, 2.54, 90.0)
    assert len(forward) == len(backward)
    for (ax, ay), (bx, by) in zip(forward, reversed(backward)):
        assert (ax, ay) == pytest.approx((bx, by), abs=1e-9)


def test_a_reflex_arc_takes_the_long_way_round_its_centre():
    # 270 degrees counter-clockwise from (1, 0) to (0, -1) is three quarters
    # of the unit circle round the origin, through (-1, 0).
    points = eagle.arc_points(1.0, 0.0, 0.0, -1.0, 270.0)
    for x, y in points:
        assert math.hypot(x, y) == pytest.approx(1.0, abs=1e-9)
    assert any(x == pytest.approx(-1.0, abs=1e-9) for x, _ in points)


def test_a_flattened_arc_stands_off_its_circle_by_no_more_than_the_chord_allows():
    radius = 2.54
    points = eagle.arc_points(17.78, 2.54, 15.24, 0.0, -90.0)
    bound = radius * (1 - math.cos(min(eagle.ARC_CHORD_MM / (2 * radius), math.pi / 2)))
    for (ax, ay), (bx, by) in itertools.pairwise(points):
        middle = math.hypot((ax + bx) / 2 - 15.24, (ay + by) / 2 - 2.54)
        assert radius - middle <= bound + 1e-12


def test_an_arc_reaches_the_extremes_of_its_circle():
    # A half turn over the top of the unit circle: its bounding box is the
    # arc's, to the last digit, not the sagitta short.
    points = eagle.arc_points(1.0, 0.0, -1.0, 0.0, 180.0)
    assert max(y for _, y in points) == pytest.approx(1.0, abs=1e-12)


def test_a_reflex_arc_that_passes_a_full_turn_of_angle_keeps_its_extremes():
    # Start 170 degrees round the unit circle, sweep 300 counter-clockwise: it
    # ends at 110 degrees having passed 180, 270 and 0 -- past 2 pi -- and 90.
    a, b = math.radians(170), math.radians(110)
    points = eagle.arc_points(math.cos(a), math.sin(a), math.cos(b),
                              math.sin(b), 300.0)
    for x, y in points:
        assert math.hypot(x, y) == pytest.approx(1.0, abs=1e-9)
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    assert (min(xs), max(xs)) == pytest.approx((-1.0, 1.0), abs=1e-9)
    assert (min(ys), max(ys)) == pytest.approx((-1.0, 1.0), abs=1e-9)


def test_a_short_arc_still_gets_two_segments():
    # 0.1 mm of chord is less than one 0.2 mm step, and the docstring
    # promises at least two segments. Slanted, so no axis crossing splits it.
    points = eagle.arc_points(0.0, 0.0, 0.0707, 0.0707, 10.0)
    assert len(points) == 3, points


def test_no_flattened_arc_has_a_segment_the_composer_would_chain_through():
    # Turned about a centre, an arc no longer starts and ends on an axis, so
    # its axis crossings land anywhere, including a hair from an end.
    cases = [(66.04, 1.0001, 65.04, 0.0, -90.0)]
    for degrees in range(0, 360, 3):
        for curve in (-90.0, 90.0):
            turn = math.radians(degrees)
            far = turn + math.radians(curve)
            cases.append((10 + 2.54 * math.cos(turn), 10 + 2.54 * math.sin(turn),
                          10 + 2.54 * math.cos(far), 10 + 2.54 * math.sin(far),
                          curve))
    for x1, y1, x2, y2, curve in cases:
        points = eagle.arc_points(x1, y1, x2, y2, curve)
        shortest = min(math.dist(a, b) for a, b in itertools.pairwise(points))
        assert shortest > compose.CHAIN_TOLERANCE_MM, (
            f"wire ({x1}, {y1}) -> ({x2}, {y2}) curve {curve}: a segment of "
            f"{shortest:.6f} mm is not over the composer's "
            f"{compose.CHAIN_TOLERANCE_MM}")


def test_a_curved_outline_is_one_ring_whatever_its_turn():
    # A 10 mm square with its (10, 10) corner rounded to r = 2.54, turned
    # about the origin: the composer must find one ring, not also a one-point
    # ring from a sliver of a segment.
    for degrees in range(0, 360, 7):
        turn = math.radians(degrees)

        def at(x: float, y: float) -> tuple[float, float]:
            return (x * math.cos(turn) - y * math.sin(turn) + 20,
                    x * math.sin(turn) + y * math.cos(turn) + 20)

        paths = [[at(0, 0), at(10, 0)], [at(10, 0), at(10, 7.46)],
                 eagle.arc_points(*at(10, 7.46), *at(7.46, 10), 90.0),
                 [at(7.46, 10), at(0, 10)], [at(0, 10), at(0, 0)]]
        segments = tuple(
            eagle.Segment(eagle.DIMENSION_LAYER, ax, ay, bx, by)
            for path in paths for (ax, ay), (bx, by) in itertools.pairwise(path))
        rings = compose.contours(segments)
        assert len(rings) == 1, (
            f"turn {degrees}: {len(rings)} rings: {[len(r) for r in rings]}")


def test_a_bad_curve_is_refused_naming_the_file_and_the_value(tmp_path):
    for curve in ("nan", "400", "-361"):
        brd = tmp_path / "bad.brd"
        brd.write_text(
            '<eagle version="9"><drawing><board><plain>'
            f'<wire x1="0" y1="0" x2="1" y2="1" width="0" layer="20" curve="{curve}"/>'
            '</plain><libraries><library name="l"><packages><package name="p"/>'
            '</packages></library></libraries><elements><element name="J1" '
            'library="l" package="p" value="" x="0" y="0"/></elements>'
            '</board></drawing></eagle>', encoding="utf-8")
        with pytest.raises(eagle.EagleError) as raised:
            eagle.read_board(brd)
        message = str(raised.value)
        assert str(brd) in message and f"curve {curve}" in message, message


def test_the_two_chord_constants_agree():
    # eagle.py cannot import the composer, so it holds its own copy.
    assert eagle.ARC_CHORD_MM == compose.ARC_CHORD_MM


# --- every board with a curved outline ---------------------------------------


def test_every_board_with_a_curved_outline_is_listed_and_counted(capsys):
    curved = {path: _curved_dimension_wires(path) for path in _curved_boards()}
    with capsys.disabled():
        print(f"\nOH-235: {len(curved)} of {len(_boards())} fetched EAGLE boards "
              f"have a curved Dimension wire:")
        for path, wires in curved.items():
            print(f"  {path.name}: {len(wires)} curved wires, curves "
                  f"{sorted({float(w.get('curve')) for w in wires})}")
    assert QTPY_BRD in curved or not QTPY_BRD.is_file()


def test_the_reader_replaces_each_curved_wire_with_the_points_of_its_arc():
    for path in _curved_boards():
        wires = [w for w in ET.parse(path).getroot().findall("drawing/board/plain/wire")
                 if w.get("layer") == eagle.DIMENSION_LAYER]
        expected = sum(len(eagle.arc_points(*_arc_of(w))) - 1 for w in wires)
        board = eagle.read_board(path)
        assert len(board.outline) == expected, (
            f"{path.name}: {len(wires)} Dimension wires should read as "
            f"{expected} segments, got {len(board.outline)}")
        assert len(board.outline) > len(wires), (
            f"{path.name}: a curved outline read as {len(board.outline)} "
            f"segments from {len(wires)} wires, so no curve was read")


def test_the_outline_area_is_the_arc_exact_area_within_the_chord_bound():
    for path in _curved_boards():
        wires = [w for w in ET.parse(path).getroot().findall("drawing/board/plain/wire")
                 if w.get("layer") == eagle.DIMENSION_LAYER]
        exact = 0.0
        bound = 0.0
        for wire in wires:
            x1, y1, x2, y2, curve = _arc_of(wire)
            exact += _shoelace([(x1, y1, x2, y2)])
            if curve:
                sweep = math.radians(curve)
                radius = math.hypot(x2 - x1, y2 - y1) / (2 * abs(math.sin(sweep / 2)))
                exact += radius * radius / 2 * (sweep - math.sin(sweep))
                sagitta = radius * (1 - math.cos(min(
                    eagle.ARC_CHORD_MM / (2 * radius), math.pi / 2)))
                bound += sagitta * radius * abs(sweep)
        board = eagle.read_board(path)
        drawn = _shoelace([(s.x1_mm, s.y1_mm, s.x2_mm, s.y2_mm)
                           for s in board.outline])
        # Two-sided: an inscribed polyline is off by a sliver per arc, to
        # one side or the other as the arc bulges out of the outline or into
        # it (a cutout), and by no more than the chord rule allows.
        assert abs(exact - drawn) <= bound, (
            f"{path.name}: arc-exact area {exact:.4f} mm2, drawn "
            f"{drawn:.4f} mm2: off by {abs(exact - drawn):.4f}, more than "
            f"the {bound:.4f} the chord rule allows")


def test_extent_is_exact_for_an_outline_that_is_only_arcs(tmp_path):
    # Two half circles of radius 5: the chords alone give a 10 x 0 box.
    text = (
        '<eagle version="9.6.2"><drawing><board><plain>'
        '<wire x1="5" y1="0" x2="-5" y2="0" width="0" layer="20" curve="180"/>'
        '<wire x1="-5" y1="0" x2="5" y2="0" width="0" layer="20" curve="180"/>'
        '</plain></board></drawing></eagle>'
    )
    board = eagle.Board("round", "9.6.2", (), tuple(
        eagle.Segment(eagle.DIMENSION_LAYER, ax, ay, bx, by)
        for wire in ET.fromstring(text).findall("drawing/board/plain/wire")
        for (ax, ay), (bx, by) in _pairs(eagle.arc_points(*_arc_of(wire)))))
    min_x, min_y, max_x, max_y = board.extent_mm()
    assert (min_x, max_x) == pytest.approx((-5.0, 5.0), abs=1e-9)
    assert (min_y, max_y) == pytest.approx((-5.0, 5.0), abs=1e-9)


def _pairs(points: list[tuple[float, float]]
           ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return list(itertools.pairwise(points))


# --- Adafruit's own STEP of the QT Py ----------------------------------------


def _qtpy_step() -> pathlib.Path:
    size, sha = compose.ADAFRUIT_QTPY_PINNED
    for path in sorted(CACHE.glob("component-Adafruit_CAD_Parts-*.step")):
        if path.stat().st_size == size and hashlib.sha256(
                path.read_bytes()).hexdigest() == sha:
            return path
    pytest.skip(
        "SKIPPED: Adafruit's whole-board STEP of the QT Py ESP32-C3 is not in "
        "third_party/seeed-3d/ (a component-Adafruit_CAD_Parts-*.step of "
        f"{size} bytes, sha256 {sha}); `python tools/compose_board_3d.py` "
        "fetches it, and a test never does")


def _step_corner_centres(path: pathlib.Path) -> list[tuple[float, float]]:
    """The (x, y) of every r = 2.54 mm cylinder whose axis is along z."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    reader = STEPControl_Reader()
    status = reader.ReadFile(str(path))
    assert status == 1, f"{path.name}: OpenCASCADE read status {status}"
    reader.TransferRoots()
    explorer = TopExp_Explorer(reader.OneShape(), TopAbs_FACE)
    centres: set[tuple[float, float]] = set()
    while explorer.More():
        surface = BRepAdaptor_Surface(TopoDS.Face_s(explorer.Current()), True)
        if surface.GetType() == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            axis = cylinder.Axis().Direction()
            where = cylinder.Axis().Location()
            if (abs(cylinder.Radius() - CORNER_RADIUS_MM) < 1e-6
                    and abs(abs(axis.Z()) - 1.0) < 1e-9):
                centres.add((round(where.X(), 3), round(where.Y(), 3)))
        explorer.Next()
    return sorted(centres)


def _circumcentre(a: tuple[float, float], b: tuple[float, float],
                  c: tuple[float, float]) -> tuple[float, float]:
    (ax, ay), (bx, by), (cx, cy) = a, b, c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    assert abs(d) > 1e-9, f"corner points {a}, {b}, {c} are collinear: no arc"
    ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay)
          + (cx**2 + cy**2) * (ay - by)) / d
    uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx)
          + (cx**2 + cy**2) * (bx - ax)) / d
    return ux, uy


def _outline_corner_centres(board: eagle.Board) -> list[tuple[float, float]]:
    """The centre of each rounded corner of the drawn outline, found from the
    outline's own vertices on its slanted segments, one cluster a quadrant."""
    min_x, min_y, max_x, max_y = board.extent_mm()
    middle = ((min_x + max_x) / 2, (min_y + max_y) / 2)
    clusters: dict[tuple[bool, bool], set[tuple[float, float]]] = {}
    for seg in board.outline:
        if seg.x1_mm == seg.x2_mm or seg.y1_mm == seg.y2_mm:
            continue
        for x, y in ((seg.x1_mm, seg.y1_mm), (seg.x2_mm, seg.y2_mm)):
            clusters.setdefault((x > middle[0], y > middle[1]), set()).add((x, y))
    assert len(clusters) == 4, (
        f"{board.name}: slanted outline segments in {len(clusters)} quadrants, "
        f"expected 4 rounded corners")
    centres = []
    for points in clusters.values():
        ordered = sorted(points)
        assert len(ordered) >= 3, (
            f"{board.name}: a corner is {len(ordered)} points {ordered}: a "
            f"chamfer, not an arc")
        centre = _circumcentre(ordered[0], ordered[len(ordered) // 2], ordered[-1])
        for x, y in ordered:
            assert math.hypot(x - centre[0], y - centre[1]) == pytest.approx(
                CORNER_RADIUS_MM, abs=1e-6)
        centres.append(centre)
    return sorted(centres)


def test_the_qt_py_outline_corners_are_the_r_2_54_cylinders_of_adafruits_own_step():
    pytest.importorskip("OCP")
    if not QTPY_BRD.is_file():
        pytest.skip(f"SKIPPED: {QTPY_BRD.relative_to(REPO).as_posix()} is not fetched")
    step = _step_corner_centres(_qtpy_step())
    assert len(step) == 4, f"the STEP has {len(step)} r = 2.54 cylinders: {step}"
    drawn = _outline_corner_centres(eagle.read_board(QTPY_BRD))

    # The two files do not share an origin, so compare each corner against the
    # lowest-left of its own set.
    def relative(centres):
        return sorted((round(x - min(c[0] for c in centres), 3),
                       round(y - min(c[1] for c in centres), 3))
                      for x, y in centres)

    for (sx, sy), (dx, dy) in zip(relative(step), relative(drawn)):
        assert (dx, dy) == pytest.approx((sx, sy), abs=5e-3), (
            f"outline corner centres (relative) {relative(drawn)} against "
            f"Adafruit's STEP {relative(step)}")
