# OpenHardware — the rope a jumper lead is, checked by running it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this file runs node and the other JavaScript tests do not
#
# `tests/webui/test_board3d.py` checks its renderer by reading the source,
# because a WebGL scene cannot be rendered from Python and there was nothing
# else to do. **A rope has no such excuse.** `webui/static/wires.js` imports
# nothing -- not three.js, not the DOM -- precisely so that its arithmetic can
# be executed and its answers compared with numbers, which is a far stronger
# check than grepping for the word `gravity`.
#
# So each test below writes a few lines of ES module into `tmp_path`, imports
# the real file from `webui/static/`, prints JSON, and asserts on it. It skips
# where node is absent, the same rule `tools/gen_avr_corpus.mjs` follows.
#
# ## What is asserted, and why not positions
#
# A settled rope's node positions are an emergent property of fourteen
# constraint passes and are not a specification: pinning them would fail on any
# change to the solver and say nothing about whether the change was right. What
# is asserted is what a wire has to be true of **whatever shape it finds**:
#
#   * it does not gain energy -- the one failure a Verlet chain has, and it is
#     silent until the cable leaves the screen
#   * its segments stay near their rest length
#   * its pinned ends stay exactly where they were put
#   * two displays a bit over twice as fast as each other agree
#   * it does not end a step inside something solid
#
# Every one of those was measured before it was written down. The numbers in
# the docstrings are from those runs.

import json
import pathlib
import shutil
import subprocess
import textwrap

import pytest

WIRES = (pathlib.Path(__file__).resolve().parents[2]
         / "webui" / "static" / "wires.js")


def run(tmp_path: pathlib.Path, body: str) -> dict:
    """Run a fragment against the real `wires.js` under node, and parse it.

    The import is a `file://` URL because node resolves a bare relative path
    against the *entry* module, and the entry module is in a temporary
    directory that knows nothing about this repository.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; wires.js is ES module arithmetic and "
                    "needs one to run")
    if not WIRES.is_file():
        pytest.skip(f"no {WIRES}")

    script = tmp_path / "probe.mjs"
    script.write_text(
        f'import {{ Rope, SUBSTEP, MAX_SUBSTEPS, GRAVITY, SLACK, STIFFNESS }} '
        f'from {WIRES.as_uri()!r};\n' + textwrap.dedent(body),
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(f"node exited {done.returncode}\n{done.stderr}")
    # node warns about module type on stderr for a file outside any package;
    # the answer is the last line of stdout, so a stray log cannot break it.
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_hanging_wire_loses_energy_rather_than_gaining_it(tmp_path):
    """**The one way a Verlet chain fails, and it fails silently.**

    Too stiff a constraint or too large a step and each pass adds a little
    energy; the cable swings wider, then leaves the screen. The frames before
    that look completely normal, which is why this is a test and not something
    anybody would notice.

    Measured 2026-08-27: 1.8e-2 at the first frame, 3.8e-12 by the six
    hundredth. The assertion is only that it falls, because the exact rate is
    a property of the damping and would have to be edited to change it.
    """
    result = run(tmp_path, """
        const rope = new Rope([0, 1, 0], [8, 1, 0]);
        const trace = [];
        for (let frame = 0; frame < 600; frame++) {
          rope.advance(1 / 60);
          if (frame % 150 === 0) trace.push(rope.energy());
        }
        console.log(JSON.stringify({trace, final: rope.energy()}));
    """)
    assert result["trace"] == sorted(result["trace"], reverse=True), result["trace"]
    assert result["final"] < 1e-6, "the wire is still moving after ten seconds"


def test_a_settled_wire_keeps_its_own_length(tmp_path):
    """A rope whose segments drift is a rope that will look like elastic.

    Under 1%: measured 0.30% with nothing in the way. The bound is loose
    against that on purpose -- what would be a defect is a percentage in the
    tens, which is what an unresolved conflict between two constraints
    produces, and this repository has now measured three of those.
    """
    result = run(tmp_path, """
        const rope = new Rope([0, 1, 0], [8, 1, 0]);
        for (let frame = 0; frame < 400; frame++) rope.advance(1 / 60);
        console.log(JSON.stringify({stretch: rope.worstStretch()}));
    """)
    assert result["stretch"] < 0.01, f"{result['stretch'] * 100:.2f}% over rest"


def test_the_pinned_ends_do_not_move(tmp_path):
    """A wire's ends are a pad and a terminal, and neither is a suggestion.

    Exactly, not nearly: the integrator never touches them and the constraint
    skips them, so any drift at all would mean one of those two is wrong.
    """
    result = run(tmp_path, """
        const head = [1, 2, 3];
        const tail = [9, 2, -4];
        const rope = new Rope(head, tail);
        for (let frame = 0; frame < 200; frame++) rope.advance(1 / 60);
        console.log(JSON.stringify({
          head: rope.point(0), tail: rope.point(rope.count - 1),
        }));
    """)
    assert result["head"] == [1, 2, 3]
    assert result["tail"] == [9, 2, -4]


def test_two_displays_of_different_speeds_hang_the_same_wire(tmp_path):
    """**What the fixed substep is for.**

    Integrating by the frame's own delta gives a cable that hangs differently
    at 60 Hz and at 144 Hz, and no assertion is true of both. Five seconds of
    each, measured 2026-08-27, differ by 3.5e-5 scene units -- which is the
    accumulator's leftover and not a drift.
    """
    result = run(tmp_path, """
        function settle(hz, seconds) {
          const rope = new Rope([0, 1, 0], [8, 1, 0]);
          for (let i = 0; i < hz * seconds; i++) rope.advance(1 / hz);
          let lowest = Infinity;
          for (let i = 0; i < rope.count; i++) {
            lowest = Math.min(lowest, rope.point(i)[1]);
          }
          return lowest;
        }
        console.log(JSON.stringify({at60: settle(60, 5), at144: settle(144, 5)}));
    """)
    assert abs(result["at60"] - result["at144"]) < 0.01, result


def test_a_frame_that_never_came_does_not_run_the_whole_minute(tmp_path):
    """A backgrounded tab reports a sixty-second frame.

    Without a cap that is 7,200 steps in one call -- a freeze, and then a cable
    that has swung for a minute. The simulation lags reality after a stall
    instead, which for a picture of a wire is the right trade.
    """
    result = run(tmp_path, """
        const rope = new Rope([0, 0, 0], [1, 0, 0]);
        console.log(JSON.stringify({
          taken: rope.advance(60), cap: MAX_SUBSTEPS,
          none: new Rope([0, 0, 0], [1, 0, 0]).advance(-5),
        }));
    """)
    assert result["taken"] == result["cap"]
    assert result["none"] == 0, "a negative delta stepped the simulation"


def test_a_wire_pulled_beyond_its_reach_is_paid_out_rather_than_stretched(tmp_path):
    """**Measured before it was written:** an end teleported nine units past
    where the wire reached left the worst segment 140% over rest -- a rubber
    band. Paying out gives the rope a shape it can take.

    The assertion is on a *dragged* end rather than a teleported one, because
    that is what a pointer does: ninety frames of smooth movement, which never
    exceeded 1.66%.
    """
    result = run(tmp_path, """
        const rope = new Rope([0, 1, 0], [8, 1, 0]);
        for (let i = 0; i < 200; i++) rope.advance(1 / 60);
        const before = rope.segment;
        let worst = 0;
        for (let i = 0; i < 90; i++) {
          const t = i / 90;
          rope.moveTail([8 + 6 * t, 1 + 5 * t, 3 * t]);
          rope.advance(1 / 60);
          worst = Math.max(worst, rope.worstStretch());
        }
        console.log(JSON.stringify({worst, before, after: rope.segment}));
    """)
    assert result["after"] > result["before"], "the wire never paid out"
    assert result["worst"] < 0.05, f"{result['worst'] * 100:.2f}% over rest while dragged"


def test_a_wire_does_not_end_a_step_inside_a_solid(tmp_path):
    """**The user asked for a wire that collides and this is that.**

    A box in its way, and after it has settled no free node may be inside.
    Contact is resolved last in each pass for exactly this reason: a node
    pushed out and then pulled back by its neighbours would satisfy the
    constraint and fail here.
    """
    result = run(tmp_path, """
        const rope = new Rope([-6, 4, 0], [6, 4, 0]);
        rope.colliders = [{kind: "box", min: [-3, -2, -3], max: [3, 1, 3]}];
        rope.floor = -8;
        for (let frame = 0; frame < 400; frame++) rope.advance(1 / 60);
        let inside = 0;
        let lowest = Infinity;
        for (let i = 1; i < rope.count - 1; i++) {
          const [x, y, z] = rope.point(i);
          lowest = Math.min(lowest, y);
          if (x > -3 && x < 3 && y > -2 && y < 1 && z > -3 && z < 3) inside += 1;
        }
        console.log(JSON.stringify({inside, lowest, stretch: rope.worstStretch()}));
    """)
    assert result["inside"] == 0, f"{result['inside']} nodes ended inside the box"
    assert result["lowest"] >= -8, "a node fell through the bench"


def test_a_wire_lands_on_the_bench_rather_than_falling_out_of_the_scene(tmp_path):
    """A wire with nothing under it falls forever. `floor` is the bench top,
    and a cable lying on a table is a better picture than one that has left.

    **The span has to be wide enough for the wire to reach**, and getting that
    wrong is what this test did first: ends one unit apart make a wire 1.35
    units long, which can hang 0.67 below them and no further, so it settled at
    5.59 with a floor at -2 and the test called it a failure to fall. A rope
    cannot reach further than it is long, and a test that asks it to is
    asserting something about arithmetic rather than about the code.
    """
    result = run(tmp_path, """
        // Twelve apart, so the wire is 16.2 long and can hang about 8 -- which
        // is further than the four it needs to fall to reach the bench.
        const rope = new Rope([-6, 6, 0], [6, 6, 0]);
        rope.floor = 2;
        for (let frame = 0; frame < 400; frame++) rope.advance(1 / 60);
        let lowest = Infinity;
        for (let i = 1; i < rope.count - 1; i++) {
          lowest = Math.min(lowest, rope.point(i)[1]);
        }
        console.log(JSON.stringify({lowest, reach: rope.segment * (rope.count - 1)}));
    """)
    assert result["reach"] > 8, "the wire is too short to reach the bench at all"
    assert result["lowest"] >= 1.999999, "a node fell through the bench"
    assert result["lowest"] < 5.9, "the wire never fell at all"


def test_a_stiff_wire_hangs_less_deeply_than_a_limp_one(tmp_path):
    """**The user asked for stiffness and this is what it buys.**

    A jumper lead has a copper core: it springs, it holds a bend, and it does
    not pool. Modelled as a distance constraint between every node and the one
    two along, weighted -- so this compares the same wire with the constraint
    doing something and doing nothing, by giving one of them so few nodes that
    there is nothing for it to bend between.

    Asserted as an inequality rather than a depth, because the depth is the
    solver's answer and the *direction* is the physics.
    """
    result = run(tmp_path, """
        function sag(nodes) {
          const rope = new Rope([0, 1, 0], [8, 1, 0], nodes);
          for (let frame = 0; frame < 400; frame++) rope.advance(1 / 60);
          let lowest = Infinity;
          for (let i = 0; i < rope.count; i++) {
            lowest = Math.min(lowest, rope.point(i)[1]);
          }
          return 1 - lowest;
        }
        console.log(JSON.stringify({stiffness: STIFFNESS, many: sag(22), few: sag(4)}));
    """)
    assert result["stiffness"] > 0, "the wire has no bending resistance at all"
    assert result["few"] < result["many"], (
        "a four-node wire sags further than a twenty-two node one, so the "
        "bending constraint is doing nothing"
    )


def test_the_constants_are_the_ones_the_scene_was_tuned_against(tmp_path):
    """Not a restatement of the source: **the units are the claim.**

    `GRAVITY` is not 9.81 and must not become it. The scene's unit is an image
    pixel at 8 px/mm, so a real metre is 8,000 units and real gravity would be
    78,480 -- a wire that falls the width of a board in three milliseconds.
    Anyone who "corrects" this to 9.81 will have made the cable float.
    """
    result = run(tmp_path, """
        console.log(JSON.stringify({
          gravity: GRAVITY, substep: SUBSTEP, slack: SLACK,
        }));
    """)
    assert result["gravity"] < 0, "gravity points up"
    assert abs(result["gravity"]) > 20, (
        "gravity is small enough to be metres per second squared; this scene "
        "is in image pixels at 8 px/mm and a wire will float"
    )
    assert result["substep"] <= 1 / 60, "the substep is coarser than a frame"
    assert result["slack"] > 1.0, "a wire with no slack is a wire under tension"


def test_a_wire_resting_on_a_box_reports_the_contact_the_collider_resolved(tmp_path):
    """**The defect OH-132 found: the probe was blind to what it measured.**

    `outOfBox` snaps a colliding node exactly onto the face and `collide` runs
    last in every pass, so at the end of a step no free node is strictly
    inside anything -- and a min-distance-inside probe answers 0.0000 for
    exactly the nodes the collider handled. Measured 2026-09-04 on a settled
    28-unit wire over a 12 x 3.5 x 6 box: the old probe reported 0.0000 while
    node 5 sat at x = -6.000, flush in the box's -X face with the whole tube
    radius, 0.16 units, inside it.

    So the one number becomes three. `inside` staying 0 is the collider
    working. `proud` is what a lead resting on a chip does, and is bounded by
    the tube. `pinned` is the anchor's fault and not the wire's -- and it is
    the only thing the old number could ever see, which is why the long-lived
    "wire penetration 0.289 mm" residual was a pinned end and not a contact
    tolerance. Measured here: a head pinned at the box's centre reports 1.7500
    units, 0.3104 mm at the Uno's 5.638 scale.

    **Which mutations this catches, run rather than assumed** (2026-09-04):
    `contact` never reporting `proud` fails the `proud > 0` assertion;
    `proudOfBox` dropping its other-two-slabs test fails the `beside`
    assertion; pinned ends counted as free nodes fails `into.inside == 0`;
    the whole fix reverted fails on `rope.contact is not a function`; and,
    after the review, `proudOfBox` measuring against the far face (the
    first version) or ignoring the gap entirely each fails the `above` and
    `near` assertions.
    **One it does NOT catch**: `depthInBox` with strict comparisons, because
    a node on the face then reads depth 0 a line later and `contact` counts
    only `depth > 0` -- the caller's gate, not this test, is what keeps a
    snapped node out of `inside`. Recorded because the first draft of this
    docstring claimed the opposite.
    """
    result = run(tmp_path, """
        const box = {kind: "box", min: [-6, 0, -3], max: [6, 3.5, 3]};
        const R = 0.16;
        function settle(head) {
          const rope = new Rope(head, [14, 4, 0]);
          rope.colliders = [box];
          rope.floor = -5;
          rope.slacken();
          for (let f = 0; f < 600; f++) rope.advance(1 / 60);
          return rope;
        }
        const over = settle([-14, 4, 0]);
        const into = settle([0, 1.75, 0]);
        // A node level with the box's top face but well off to the side is
        // not touching it, and saying so is what keeps `proud` a measurement
        // rather than a count of everything at the same height.
        const beside = new Rope([-40, 3.5, 0], [-30, 3.5, 0]);
        beside.colliders = [box];
        // Two more that the OH-132 review found the first version blind to:
        // a wire in clear air ABOVE the box, within its x and z spans, and a
        // wire whose centres sit 0.1 above the top face -- less than the
        // tube's radius, so the tube reaches 0.06 in. Neither is stepped, so
        // the nodes lie exactly where the endpoints put them.
        const above = new Rope([-14, 40, 0], [14, 40, 0]);
        above.colliders = [box];
        const near = new Rope([-2, 3.6, 0], [2, 3.6, 0]);
        near.colliders = [box];
        console.log(JSON.stringify({
          radius: R, over: over.contact(R), into: into.contact(R),
          beside: beside.contact(R), centres: over.contact(),
          above: above.contact(R), near: near.contact(R),
        }));
    """)
    # The collider did its job on both wires, which is exactly why one number
    # was not enough: this is 0 whether a wire rests correctly on the box or
    # has no colliders at all.
    assert result["over"]["inside"] == 0
    assert result["into"]["inside"] == 0
    # ...and the contact it resolved is visible now. THIS is the ticket.
    assert result["over"]["proud"] > 0, (
        "a wire draped over a box reports no contact at all; the probe is "
        "still blind to exactly the nodes the collider handled"
    )
    assert result["over"]["proud"] <= result["radius"] + 1e-9, (
        "contact deeper than the tube is interpenetration and belongs in "
        "`inside`, not in `proud`"
    )
    # A pinned end is not the wire's contact tolerance. 0.289 mm was this.
    assert result["over"]["pinned"] == 0
    assert result["into"]["pinned"] > 1.0, result["into"]
    # A wire that never reaches the box says nothing about it.
    assert result["beside"] == {"inside": 0, "proud": 0, "pinned": 0}
    # And a caller that draws no tube gets centres, not contact.
    assert result["centres"]["proud"] == 0
    # Clear air over the box is not contact either -- the review's case: the
    # first `proudOfBox` measured against the FAR face and reported the whole
    # tube for a wire 33 units up. Contact is the radius less the gap, so 0.1
    # above the face with a 0.16 tube is 0.06 in, and 36.5 above is nothing.
    assert result["above"] == {"inside": 0, "proud": 0, "pinned": 0}, result["above"]
    assert abs(result["near"]["proud"] - (result["radius"] - 0.1)) < 1e-9, result["near"]
