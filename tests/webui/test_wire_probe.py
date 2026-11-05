# OpenHardware — a lead's segments, checked against the solids they cross.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this file is for
#
# `Rope.contact()` and `worstStretch()` are about NODES, and a solid narrower
# than the gap between two nodes falls between them (OH-165). So
# `webui/static/wire_probe.js` asks the question about the segments, and this
# file holds it to two things: that its answer is exact on shapes whose answer
# is known by hand, and that on a real settled lead it sees what the node
# readings cannot.
#
# It runs node for the reason `tests/webui/test_wires.py` gives: both files
# import nothing, so their arithmetic can be executed rather than grepped.
#
# ## The fixture
#
# One Arduino Uno female header -- IOL, IOH, AD and POWER are each 2.54 mm
# across and 11.54 mm tall in the Uno's composed model -- at the Uno's own
# scale of 0.5638 scene units per mm, standing on a bench at y = 0, with a
# lead of radius 0.16 pinned 8 units up either side of it. That is the
# fixture whose free and over stretch columns reproduce OH-165's table to the
# digit; its `through` column was measured another way and agrees to within
# 0.01 of a unit, the 28-span row being the header's own half-width.

import json
import pathlib
import shutil
import subprocess
import textwrap

import pytest

STATIC = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
WIRES = STATIC / "wires.js"
PROBE = STATIC / "wire_probe.js"

#: Scene units per mm on the Uno, and the header's half-width in them.
SCALE = 0.5638
HALF = 2.54 * SCALE / 2

#: Builds a lead over one header and settles it. A fragment that uses it
#: calls `settle(span, solids)`; ten seconds at 60 Hz is far past settling --
#: 400 frames give the same readings to four places.
FIXTURE = f"""
const SCALE = {SCALE}, HALF = 2.54 * SCALE / 2, TALL = 11.54 * SCALE;
const HEADER = {{ kind: "box", min: [-10, 0, -HALF], max: [10, TALL, HALF] }};
function settle(span, solids) {{
  const rope = new Rope([0, 8, -span / 2], [0, 8, span / 2]);
  rope.floor = 0;
  rope.radius = 0.16;
  rope.colliders = solids;
  for (let frame = 0; frame < 600; frame++) rope.advance(1 / 60);
  return rope;
}}
"""


def run(tmp_path: pathlib.Path, body: str) -> dict:
    """Run a fragment against the real `wires.js` and `wire_probe.js`.

    The imports are `file://` URLs for the reason `test_wires.run` gives.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; wire_probe.js is ES module arithmetic "
                    "and needs one to run")
    for path in (WIRES, PROBE):
        if not path.is_file():
            pytest.skip(f"no {path}")

    script = tmp_path / "probe.mjs"
    script.write_text(
        f"import {{ Rope }} from {WIRES.as_uri()!r};\n"
        f"import {{ segmentThroughSolid, segmentInBox, segmentInSphere }} "
        f"from {PROBE.as_uri()!r};\n" + FIXTURE + textwrap.dedent(body),
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True)
    if done.returncode != 0:
        # Not AssertionError, which the xfail below expects: a crash in the
        # probe must fail that test, not satisfy it.
        raise RuntimeError(f"node exited {done.returncode}\n{done.stderr}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_segment_through_a_box_reports_its_depth_exactly(tmp_path):
    """Shapes whose answer is known by hand, each to the last place.

    The thin-box case is the one sampling misses: a slab 0.01 thick crossed
    between two ends 10 apart has no sample anywhere near it unless there are
    a thousand of them, and its depth is half its thickness.
    """
    result = run(tmp_path, """
        const box = { min: [-1, -2, -3], max: [1, 2, 3] };
        const slab = { min: [-5, -5, -0.005], max: [5, 5, 0.005] };
        console.log(JSON.stringify({
          centre: segmentInBox([-9, 0, 0], [9, 0, 0], box),
          offCentre: segmentInBox([0.5, -9, 0], [0.5, 9, 0], box),
          outside: segmentInBox([-9, 5, 0], [9, 5, 0], box),
          onFace: segmentInBox([-9, 2, 0], [9, 2, 0], box),
          endInside: segmentInBox([0.25, 0, 0], [9, 9, 9], box),
          point: segmentInBox([0.25, 0, 0], [0.25, 0, 0], box),
          slab: segmentInBox([0, 0, -5], [0, 0, 5], slab),
          diagonal: segmentInBox([-9, -9, 0], [9, 9, 0], box),
          lopsided: segmentInBox([-9, 0, 0], [1.5, 0, 0], box),
          across: segmentInBox([1, 5, 5], [5, 1, 5],
                               { min: [0, 0, 0], max: [10, 10, 10] }),
        }));
    """)
    assert result["centre"] == 1, "the nearest faces of the centre are x = +-1"
    assert result["offCentre"] == 0.5, "0.5 from the +X face"
    assert result["outside"] == 0
    assert result["onFace"] == 0, "lying on a face is not inside"
    assert result["endInside"] == 0.75, "the inside end, 0.75 from +X"
    assert result["point"] == 0.75, "a point is its own segment"
    assert abs(result["slab"] - 0.005) < 1e-12
    # Through the centre on the diagonal x = y: the point (0,0,0) is 1 from
    # the X faces, and nowhere along x = y is any deeper.
    assert result["diagonal"] == 1
    # Deepest at x = 0, which is 6/7 of the way along and nowhere near the
    # middle, whose point x = -3.75 is outside: a probe that tried the
    # midpoint for the crossing would report nothing.
    assert abs(result["lopsided"] - 1) < 1e-12
    # Deepest where the -X face and the -Y face cross, at (3, 3, 5): two
    # faces on DIFFERENT axes, so a probe that only tried crossings of a
    # face with its own opposite would report 1 from the ends instead of 3.
    assert abs(result["across"] - 3) < 1e-12


def test_the_segments_at_the_pinned_ends_are_probed_too(tmp_path):
    """A lead whose ends are clear and whose first or last segment is not.

    Built by hand as the duck type the probe reads, so each one has exactly
    one segment through the box and that segment is at an end.
    """
    result = run(tmp_path, """
        const box = { min: [-1, -1, -1], max: [1, 1, 1] };
        const lead = (points) => ({ position: Float64Array.from(points.flat()),
                                    count: points.length, colliders: [box] });
        console.log(JSON.stringify({
          first: segmentThroughSolid(lead([[-9, 0, 0], [9, 0, 0], [9, 9, 0]])),
          last: segmentThroughSolid(lead([[9, 9, 0], [9, 0, 0], [-9, 0, 0]])),
          neither: segmentThroughSolid(lead([[-9, 5, 0], [9, 5, 0], [9, 9, 0]])),
        }));
    """)
    assert result["first"] == 1
    assert result["last"] == 1
    assert result["neither"] == 0


def test_every_collider_is_probed_and_the_worst_one_reported(tmp_path):
    """A sphere is probed as a sphere and not as its bounding box, and the
    answer is the deepest of all the solids rather than the first or last."""
    result = run(tmp_path, """
        const lead = (colliders) => ({
          position: Float64Array.from([-9, 0, 0, 9, 0, 0]), count: 2, colliders });
        const shallow = { min: [-1, -0.5, -9], max: [1, 9, 9] };
        const deep = { min: [3, -2, -2], max: [7, 2, 2] };
        console.log(JSON.stringify({
          order: [segmentThroughSolid(lead([shallow, deep])),
                  segmentThroughSolid(lead([deep, shallow]))],
          ball: segmentThroughSolid(lead([{ kind: "sphere", at: [0, 0.4, 0], r: 1 }])),
          // 1.5 from the centre of a radius-1 ball, and so 0.5 inside the
          // ball's bounding box: a sphere probed as a box would say 0.5.
          missed: segmentThroughSolid(lead([{ kind: "sphere", at: [0, 1.5, 0], r: 1 }])),
        }));
    """)
    assert result["order"] == [2, 2], "the deep box is 2 from its nearest face"
    assert abs(result["ball"] - 0.6) < 1e-12
    assert result["missed"] == 0


def test_a_segment_through_a_sphere_reports_its_depth_exactly(tmp_path):
    result = run(tmp_path, """
        const ball = { kind: "sphere", at: [0, 0, 0], r: 2 };
        console.log(JSON.stringify({
          centre: segmentInSphere([-9, 0, 0], [9, 0, 0], ball),
          grazing: segmentInSphere([-9, 1.5, 0], [9, 1.5, 0], ball),
          tangent: segmentInSphere([-9, 2, 0], [9, 2, 0], ball),
          short: segmentInSphere([5, 0, 0], [9, 0, 0], ball),
          point: segmentInSphere([1, 0, 0], [1, 0, 0], ball),
        }));
    """)
    assert result["centre"] == 2
    assert result["grazing"] == 0.5
    assert result["tangent"] == 0, "touching the surface is not inside"
    assert result["short"] == 0, "the nearest point is the end, 3 off the surface"
    assert result["point"] == 1


def test_a_short_lead_over_a_header_reports_nothing(tmp_path):
    """The 3-span row of OH-165's table: segments of 0.193 units, far under
    the header's 1.432 width, so the nodes catch it and no segment is in it.
    A probe that reported a depth here would be measuring its own error."""
    result = run(tmp_path, """
        const rope = settle(3, [HEADER]);
        console.log(JSON.stringify({
          through: segmentThroughSolid(rope), segment: rope.segment }));
    """)
    assert abs(result["segment"] - 0.193) < 5e-4
    assert result["through"] == 0


def test_the_probe_sees_a_lead_the_node_readings_call_clean(tmp_path):
    """OH-165's table, row by row, at the fixture's own numbers.

    Measured 2026-11-05 with this fixture:

        span  segment  free %  over %  through  /half
           3   0.193    0.58    0.58   0.0000   0.000
           5   0.321    0.36    0.92   0.0000   0.000
           8   0.514    0.30    1.99   0.0000   0.000
          12   0.771    0.26    1.67   0.0632   0.088
          20   1.286    0.24    1.33   0.2469   0.345
          28   1.800    0.65    1.46   0.7160   1.000

    with `contact()` reading no node inside and none proud in every row.
    What is asserted is the shape of that, not its digits: every row's node
    readings are clean -- `proud` measured at the lead's own radius, since
    at none it is not measured -- and its stretch a couple of per cent at
    most (8 reads 1.99), the probe finds nothing
    where segments are short against the header, and from 12 on it finds
    the lead going deeper as the segment grows -- to the header's exact
    centre at 28, where a node either side of it is clear.

    **This test records the defect, and OH-251's fix will make it fail.**
    That is right: once a segment cannot be inside a solid, the rows from 12
    on read 0, and the fix rewrites the last three assertions as "every row
    reads 0" -- which is the xfail below, generalised to every span.
    """
    result = run(tmp_path, """
        const rows = [];
        for (const span of [3, 5, 8, 12, 20, 28]) {
          const rope = settle(span, [HEADER]);
          const c = rope.contact(rope.radius);
          rows.push({ span, inside: c.inside, proud: c.proud,
                      stretch: rope.worstStretch(),
                      through: segmentThroughSolid(rope) });
        }
        console.log(JSON.stringify(rows));
    """)
    for row in result:
        assert row["inside"] == 0, row
        assert row["proud"] == 0, row
        assert row["stretch"] < 0.025, row
    by_span = {row["span"]: row["through"] for row in result}
    for span in (3, 5, 8):
        assert by_span[span] == 0, (span, by_span)
    assert 0 < by_span[12] < by_span[20] < by_span[28], by_span
    assert abs(by_span[28] - HALF) < 1e-3, (
        f"a 28-span lead's worst segment should pass through the header's "
        f"centre, {HALF:.4f} from its faces; it reached {by_span[28]:.4f}")


@pytest.mark.xfail(strict=True, reason=(
    "OH-165 step 2, a statement of the defect: the solver keeps nodes out of "
    "solids and nothing keeps segments out, so a 28-unit lead threads an Uno "
    "header. Passing is the fix (OH-251); strict so the fix has to remove "
    "this mark."), raises=AssertionError)
def test_a_lead_over_the_narrowest_real_solid_does_not_pass_through_it(tmp_path):
    result = run(tmp_path, """
        const rope = settle(28, [HEADER]);
        console.log(JSON.stringify({ through: segmentThroughSolid(rope) }));
    """)
    # Not `== 0`: a fix that leaves a segment lying on a face may leave it a
    # rounding error inside, and that is not a lead through a header.
    assert result["through"] < 1e-9, (
        f"a segment of the lead is {result['through']:.4f} units inside the "
        f"header")
