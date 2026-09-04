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
    units, which is 3.104 mm on the Uno.

    **That millimetre figure said 0.3104 until OH-162's review, and the slip
    changes an argument.** `view.mmScale` is scene units PER MILLIMETRE and
    the Uno's is `5.638 px/mm * SCALE` = 0.5638, not 5.638, so every scene
    unit here is 1.774 mm and not 0.1774. The consequence is not cosmetic:
    0.16 units of tube is 0.284 mm, so the historical 0.289 is 1.018 wire
    radii and not the 10.2 that OH-132's ticket computes. The pinned-end
    explanation above still stands on its own evidence -- a head at the box's
    centre really does report 1.75 units through this probe -- but the
    arithmetic that ticket offered AGAINST the older "contact tolerance under
    the wire's own radius" reading was wrong, and that reading is arithmetically
    ordinary. Which of the two the 2026-08 number actually was is not decided
    by this file, and the ticket is not this ticket's to edit.

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


def test_a_wire_told_its_thickness_rests_its_tube_on_a_solid_not_its_centre(tmp_path):
    """**OH-162 step 1: the radius was a drawing parameter and now it solves.**

    `collide` moved node CENTRES onto a face, so a settled lead lay with half
    its tube inside whatever it rested on. That is what the OH-132 probe above
    was built to see, and what it saw on a 28-unit wire over a 12 x 3.5 x 6
    box: `proud` 0.16, the whole radius, with `inside` 0. The collider was
    working perfectly and the picture was still wrong.

    `radius` is plain data the caller supplies, exactly like `colliders`, and
    every solid grows by it. Measured 2026-09-04, this fixture:

    | fixture                        | never told | radius 0.16 |
    |--------------------------------|------------|-------------|
    | box drape, `proud`             | 0.16       | 0           |
    | box drape, `inside`            | 0          | 0           |
    | sphere, nearest free centre    | 3.000      | 3.160       |
    | sphere, `proud`                | 0.16       | 0           |
    | bench at 2, lowest free centre | 2.000      | 2.160       |

    **The left column is the control and it is half of this test.** An "after"
    number with nothing to compare against is not a measurement. It is also
    what keeps every test written before OH-162 honest: those ropes are never
    told a radius, so the default has to leave them solving centrelines --
    which is why the control sets nothing rather than setting zero. Setting
    zero was the first version, and a mutation defaulting the field to 0.16
    survived it, because the fixture overwrote the value it was testing.

    **`air` and `beside` are the fixtures that must report nothing** -- the
    OH-132 lesson, where every fixture the author wrote TOUCHED the box and
    the reviewer's clear-air case is what found the bug. Growing a box is
    precisely the change that can shove something it should never have
    reached, so both are stepped through `collide` and checked for movement
    rather than only asked for a contact number.

    `proud` is asserted at exactly 0 rather than under a tolerance because it
    is exactly 0 here: `3.5 + 0.16` less `3.5` is 0.16000000000000014, a hair
    MORE than the radius, so the tube reaches a negative distance in and the
    probe's own `> 0` gate drops it. A box on other coordinates could leave a
    rounding bit; this one does not.

    **Seven mutations run against this, 2026-09-04**, each failing the
    assertion named for it: `outOfBox` snapping to the ungrown face
    (`aboveTheTop`); its early-out testing the ungrown box while its faces
    stay grown, which parks a node in the band between the two
    (`aboveTheTop`); `radius` defaulting to 0.16 rather than 0 (`bare`);
    `collide` leaving the bench where the caller put it (`benchSolved`);
    `outOfSphere` reaching only `solid.r` (`ballSolved`); `collide`'s first
    pass growing every solid by twice the radius (`aboveTheTop`); and the
    whole change reverted (`solved.proud`).

    Two more, against `collide`'s second resolution pass, are in
    `test_a_node_pushed_off_one_solid_is_not_left_inside_the_one_beside_it`,
    which is where that pass is measured.

    **On the one-behaviour rule**: this is one behaviour -- the tube rests on
    a solid rather than the centre -- asserted against the three shapes the
    solver knows, because a growth applied to two of them and not the third
    is exactly the defect worth catching, and a reader comparing the box's
    number with the sphere's needs them side by side. The two things that are
    NOT that behaviour were split out below rather than added here: which
    AXES grow, and the sphere's at-the-centre branch.
    """
    result = run(tmp_path, """
        const R = 0.16;
        const box = {kind: "box", min: [-6, 0, -3], max: [6, 3.5, 3]};
        const ball = {kind: "sphere", at: [0, 0, 0], r: 3};

        // No argument means the rope is never TOLD a radius, which is the
        // state every test written before OH-162 leaves one in and is the
        // whole reason the default is 0. Passing an explicit 0 instead would
        // leave that default unexercised -- which it was, until a mutation
        // setting it to 0.16 survived this test.
        function settle(solid, radius) {
          const rope = new Rope([-14, 6, 0], [14, 6, 0]);
          rope.colliders = [solid];
          rope.floor = -2;
          if (radius !== undefined) rope.radius = radius;
          rope.slacken();
          for (let f = 0; f < 600; f++) rope.advance(1 / 60);
          return rope;
        }

        // How far the lowest free node draped across the box's top face sits
        // above it. Only the nodes within the footprint count: the rest of
        // this wire hangs down the sides and says nothing about the top.
        function aboveTheTop(rope) {
          let lowest = Infinity;
          for (let i = 1; i < rope.count - 1; i++) {
            const [x, y, z] = rope.point(i);
            if (x < box.min[0] || x > box.max[0]) continue;
            if (z < box.min[2] || z > box.max[2]) continue;
            if (y < box.max[1]) continue;
            lowest = Math.min(lowest, y);
          }
          // `null` rather than an Infinity that JSON turns into one anyway:
          // a mutation that sinks the drape leaves nothing on the top face,
          // and the assertion should name that instead of failing on the
          // arithmetic of a missing number.
          return lowest === Infinity ? null : lowest - box.max[1];
        }

        // Nearest a free node's centre gets to the ball's centre.
        function nearestToBall(rope) {
          let nearest = Infinity;
          for (let i = 1; i < rope.count - 1; i++) {
            const [x, y, z] = rope.point(i);
            nearest = Math.min(nearest, Math.hypot(x, y, z));
          }
          return nearest;
        }

        // Nothing in the way at all: the lowest centre is the bench itself.
        // No argument means never told, as above.
        function onTheBench(radius) {
          const rope = new Rope([-6, 6, 0], [6, 6, 0]);
          rope.floor = 2;
          if (radius !== undefined) rope.radius = radius;
          for (let f = 0; f < 400; f++) rope.advance(1 / 60);
          let lowest = Infinity;
          for (let i = 1; i < rope.count - 1; i++) {
            lowest = Math.min(lowest, rope.point(i)[1]);
          }
          return lowest;
        }

        // Neither of these two is stepped: their nodes lie exactly where the
        // endpoints put them, so ANY movement is the grown box reaching
        // something it never touched before.
        function untouched(head, tail) {
          const rope = new Rope(head, tail);
          rope.colliders = [box];
          rope.radius = R;
          const was = [];
          for (let i = 0; i < rope.count * 3; i++) was.push(rope.position[i]);
          rope.collide();
          let moved = 0;
          for (let i = 0; i < rope.count * 3; i++) {
            moved = Math.max(moved, Math.abs(rope.position[i] - was[i]));
          }
          return {moved, contact: rope.contact(R)};
        }

        const bare = settle(box);
        const solved = settle(box, R);
        console.log(JSON.stringify({
          radius: R, ballRadius: ball.r, bench: 2,
          bare: bare.contact(R), solved: solved.contact(R),
          solvedCentres: solved.contact(),
          bareAboveTheTop: aboveTheTop(bare),
          aboveTheTop: aboveTheTop(solved),
          bareStretch: bare.worstStretch(), stretch: solved.worstStretch(),
          ballBare: nearestToBall(settle(ball)),
          ballSolved: nearestToBall(settle(ball, R)),
          ballBareProud: settle(ball).contact(R).proud,
          ballSolvedProud: settle(ball, R).contact(R).proud,
          benchBare: onTheBench(), benchSolved: onTheBench(R),
          air: untouched([-14, 40, 0], [14, 40, 0]),
          beside: untouched([-40, 3.5, 0], [-30, 3.5, 0]),
        }));
    """)
    # Both drapes have to have settled ON the box's top face, or the two
    # numbers below are about nodes that are not there.
    assert result["bareAboveTheTop"] is not None, "the control never reached the box"
    assert result["aboveTheTop"] is not None, "nothing settled on the box's top face"
    # The control: without the radius the solver still buries half the tube,
    # which is the number this whole step exists to move.
    assert result["bare"]["proud"] == result["radius"], result["bare"]
    assert abs(result["bareAboveTheTop"]) < 1e-9, (
        "the control's resting nodes are not on the face, so the 0.16 above "
        "is measuring something other than a buried tube"
    )
    # And with it, the tube rests ON the box: no contact at all, and the
    # centres are a radius clear of the face rather than in it.
    assert result["solved"]["proud"] == 0, result["solved"]
    assert abs(result["aboveTheTop"] - result["radius"]) < 1e-9, result["aboveTheTop"]
    # `inside` was 0 before and must stay 0: pushing a node further out cannot
    # be allowed to leave it further in, and this is the assertion that would
    # catch a sign error in the growth.
    assert result["solved"]["inside"] == 0, result["solved"]
    assert result["solvedCentres"]["inside"] == 0, result["solvedCentres"]
    # A thicker wire is a slightly longer path over the same box, so the
    # segments take up a little more of their slack. 1.38% to 1.51% measured;
    # what would be a defect is the tens a fighting constraint produces.
    assert result["stretch"] < 0.05, f"{result['stretch'] * 100:.2f}% over rest"
    # The sphere is a separate branch and would otherwise go unmeasured.
    assert abs(result["ballBare"] - result["ballRadius"]) < 1e-9, result["ballBare"]
    assert result["ballBareProud"] == result["radius"], result["ballBareProud"]
    assert abs(result["ballSolved"] - (result["ballRadius"] + result["radius"])) < 1e-9
    assert result["ballSolvedProud"] == 0, result["ballSolvedProud"]
    # So is the bench, which is a plane and neither of the two.
    assert abs(result["benchBare"] - result["bench"]) < 1e-9, result["benchBare"]
    assert abs(result["benchSolved"] - (result["bench"] + result["radius"])) < 1e-9, (
        result["benchSolved"]
    )
    # And the two that must report nothing. A grown box is exactly the change
    # that reaches something it should not have.
    assert result["air"]["moved"] == 0, result["air"]
    assert result["air"]["contact"] == {"inside": 0, "proud": 0, "pinned": 0}
    assert result["beside"]["moved"] == 0, result["beside"]
    assert result["beside"]["contact"] == {"inside": 0, "proud": 0, "pinned": 0}


def test_a_node_pushed_off_one_solid_is_not_left_inside_the_one_beside_it(tmp_path):
    """**The defect OH-162's own review found in OH-162's first version.**

    Growing each solid by the radius is done per solid and resolved
    sequentially, so a node ejected onto solid B's grown face can land inside
    solid A's REAL box -- and with A already done, nothing pushes it out
    again. It is not a corner case. A chip sits flush on a board, so the
    chip's grown bottom face is a radius BELOW the slab's top, and every
    resting node in the seam between them went there.

    Measured 2026-09-04 on a wire pinned to two pads over a board slab with
    one chip on it, `contact().inside`, which this file calls the fault and
    for which zero is the pass:

    | version                          | `inside` |
    |----------------------------------|----------|
    | before OH-162                    | 0        |
    | OH-162 with one resolution pass  | 0.16     |
    | OH-162 as it stands              | 0        |

    The fix is that a radius is a preference and being outside a solid is a
    requirement: `collide` resolves the grown solids, then resolves the
    UNGROWN ones again for any node the first pass moved. That second pass is
    what the file did before OH-162, so the invariant is restored rather than
    approximated.

    **`proud` 0.16 in the seam is not a fault and must not be asserted away.**
    A 0.32-wide lead does not fit in a zero gap, and reporting the overlap is
    the honest answer -- the same answer the file gave before any of this.

    `clear` is the fixture that must report nothing: the same two solids, with
    the wire strung far enough away that neither is ever reached.

    **Four mutations run, 2026-09-05**, each failing here: the second pass
    deleted; the second pass run at `this.radius` instead of 0, which is the
    same thing because the first pass already left the node on a grown face;
    the second pass gated on the node having MOVED rather than on a push
    having happened, which is the fixed point above; and `outOfSolids`
    short-circuiting once one solid has pushed, so the node is never offered
    to the solid it was just pushed into.
    """
    result = run(tmp_path, """
        // A board slab with one chip standing on it: the chip's bottom face
        // and the slab's top face are the same plane, which is what makes
        // this the everyday case rather than a contrivance.
        const slab = {kind: "box", min: [-20, -0.9, -20], max: [20, 0, 20]};
        const chip = {kind: "box", min: [-6, 0, -3], max: [6, 3.5, 3]};
        const R = 0.16;
        // A pad's centre: PAD_LIFT + PAD_HEIGHT / 2 in board3d.js, which is
        // where a wire's head is actually anchored.
        const LIFT = 0.04;

        function settle(head, tail, radius) {
          const rope = new Rope(head, tail);
          rope.colliders = [slab, chip];
          rope.floor = -2;
          if (radius !== undefined) rope.radius = radius;
          rope.slacken();
          for (let f = 0; f < 600; f++) rope.advance(1 / 60);
          return rope;
        }

        // **The same defect's other half, and it is a fixed point.** Two
        // solids 0.05 apart push a node out and straight back inside ONE
        // pass, so its coordinates come out identical to what they went in
        // as while both pushes really happened. A guard that skipped the
        // ungrown pass when the node had not MOVED therefore saw nothing to
        // do, and left it 0.11 inside the first box for ever. The guard asks
        // whether a push EXECUTED instead, which cannot be fooled that way.
        const near = {kind: "box", min: [-4, 0, -3], max: [-0.025, 6, 3]};
        const far = {kind: "box", min: [0.025, 0, -3], max: [4, 6, 3]};
        function fromX(startX) {
          const rope = new Rope([-10, 3, 0], [10, 3, 0], 3);
          rope.colliders = [near, far];
          rope.floor = -6.28;
          rope.radius = R;
          rope.position[3] = startX;
          rope.position[4] = 3;
          rope.position[5] = 0;
          for (let pass = 0; pass < 14; pass++) rope.collide();
          return rope.position[3];
        }

        const bare = settle([-14, LIFT, 0], [14, LIFT, 0]);
        const solved = settle([-14, LIFT, 0], [14, LIFT, 0], R);
        // Far from both solids, and high enough that the bench catches it.
        const clear = settle([-60, 8, 0], [-40, 8, 0], R);
        console.log(JSON.stringify({
          radius: R,
          bare: bare.contact(R), solved: solved.contact(R),
          solvedCentres: solved.contact(),
          clear: clear.contact(R),
          nearFace: near.max[0], fixedPoint: far.min[0] - R,
          fromTheFixedPoint: fromX(far.min[0] - R),
          fromWellInside: fromX(-2),
        }));
    """)
    # THIS is the regression. A node the chip pushed down must not be left in
    # the board, and it was: 0.16, exactly one radius.
    assert result["solved"]["inside"] == 0, (
        "a node ejected onto one solid's grown face was left inside another "
        "solid's real box; the second, ungrown resolution pass is not running"
    )
    assert result["solvedCentres"]["inside"] == 0, result["solvedCentres"]
    # And it was 0 before the radius existed, which is the number being kept.
    assert result["bare"]["inside"] == 0, result["bare"]
    # The seam has no room for a tube and saying so is not a fault.
    assert result["solved"]["proud"] == result["radius"], result["solved"]
    # The fixture that must report nothing.
    assert result["clear"] == {"inside": 0, "proud": 0, "pinned": 0}, result["clear"]
    # And the fixed point, which a net-position guard could never leave: the
    # node must end on the near box's face, wherever it started.
    assert result["fromTheFixedPoint"] == result["nearFace"], (
        f"a node starting at the cycle's fixed point {result['fixedPoint']} "
        f"stayed {result['nearFace'] - result['fromTheFixedPoint']} inside the "
        f"box; the second pass is gated on the node having moved rather than "
        f"on a push having happened"
    )
    assert result["fromWellInside"] == result["nearFace"], result["fromWellInside"]


def test_a_solid_is_grown_on_all_three_axes_and_not_only_the_two_drawn(tmp_path):
    """**Every other fixture in this file is planar at z = 0**, and the OH-162
    review is what noticed.

    A drape is measured over a box's top and down its sides, which is x and y;
    `aboveTheTop` filters on z rather than testing it. So `outOfBox` growing x
    and y and leaving z alone passed every assertion in the two tests above,
    while a lead laid diagonally across a chip lands on a z face.

    Three nudges, one per axis, each from a point inside the box nearer to one
    face than to any other: the node must come to rest a radius outside THAT
    face and nowhere else. The three starting points are the same 0.26 from
    their respective grown faces, so the three answers are the same shape and
    a growth applied to two axes out of three cannot hide.

    Not settled, deliberately: one `collide` call on a rope whose nodes were
    placed by hand. A settled drape is an emergent shape and would say less.

    **Mutations run, 2026-09-05**, each failing here: growing only x and y
    (`pushedZ`), only y and z (`pushedX`), only x and z (`pushedY`), and
    growing the min faces without the max ones (all three).
    """
    result = run(tmp_path, """
        const R = 0.16;
        const box = {kind: "box", min: [-6, 0, -3], max: [6, 3.5, 3]};
        // Placed by hand into the middle slot of a three-node rope, then
        // resolved once. The two ends are pinned and far away, so nothing
        // but `collide` touches the node under test.
        function nudge(to) {
          const rope = new Rope([-40, 20, 0], [40, 20, 0], 3);
          rope.colliders = [box];
          rope.floor = -50;
          rope.radius = R;
          rope.position[3] = to[0];
          rope.position[4] = to[1];
          rope.position[5] = to[2];
          rope.collide();
          return [rope.position[3], rope.position[4], rope.position[5]];
        }
        console.log(JSON.stringify({
          radius: R, box,
          pushedX: nudge([5.9, 1.75, 0]),
          pushedY: nudge([0, 3.4, 0]),
          pushedZ: nudge([0, 1.75, 2.9]),
        }));
    """)
    radius = result["radius"]
    top = result["box"]["max"]
    assert result["pushedX"] == [top[0] + radius, 1.75, 0], result["pushedX"]
    assert result["pushedY"] == [0, top[1] + radius, 0], result["pushedY"]
    assert result["pushedZ"] == [0, 1.75, top[2] + radius], result["pushedZ"]


def test_a_node_at_a_spheres_centre_leaves_by_the_two_radii_together(tmp_path):
    """A node exactly at a sphere's centre has no direction to leave by, so
    `outOfSphere` sends it up rather than dividing by zero -- and that branch
    was reached by no test at all until the OH-162 review said so.

    It is not a contrived position. A wire's tail is placed at a part's
    terminal, and a small enough part with a spherical collider puts the next
    node at its centre on the frame it is dropped.

    The distance is both radii together, the same rule the ordinary branch
    follows, which is the whole reason to test it: keeping `solid.r` there
    would leave the tube half inside the ball and no other assertion in this
    file would notice.

    **Mutations run, 2026-09-05**, both failing here: that branch pushing by
    `solid.r`, and pushing by `r` alone.
    """
    result = run(tmp_path, """
        const R = 0.16;
        const ball = {kind: "sphere", at: [0, 0, 0], r: 3};
        const rope = new Rope([-40, 20, 0], [40, 20, 0], 3);
        rope.colliders = [ball];
        rope.floor = -50;
        rope.radius = R;
        rope.position[3] = 0;
        rope.position[4] = 0;
        rope.position[5] = 0;
        rope.collide();
        console.log(JSON.stringify({
          radius: R, ballRadius: ball.r,
          landed: [rope.position[3], rope.position[4], rope.position[5]],
        }));
    """)
    assert result["landed"] == [0, result["ballRadius"] + result["radius"], 0], (
        result["landed"]
    )
