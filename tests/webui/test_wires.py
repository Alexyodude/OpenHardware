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


def test_the_distance_between_two_segments_is_the_one_worked_out_by_hand(tmp_path):
    """**OH-162 step 2 rests on this and nothing else in the file needed it.**

    Two leads crossing at right angles have no node anywhere near each other
    and still occupy the same space, so wire against wire is a test between
    SEGMENTS. That is a different piece of arithmetic from anything here: the
    squared distance minimised over a unit square, clamped back onto it where
    the free minimum falls outside.

    Five placements, each with an answer that can be checked without running
    a solver:

    | placement                        | distance   |
    |----------------------------------|------------|
    | perpendicular, one above         | 0.5        |
    | parallel, side by side           | 0.75       |
    | skew, closest at neither middle  | sqrt(13)   |
    | one stopping short of the other  | 16         |
    | a lead whose nodes all coincide  | 3          |

    **They do NOT reach five different branches, and a first version of this
    table said they did.** `nearestNeighbour` measures from a NODE, so the
    first of the two things is always a point, and the solver returns at its
    zero-length guard on every row above -- including the first. What the
    five check is the answer, not the path to it; the paragraph below says
    which test reaches which branch.

    Nothing is stepped. Every node is placed, so each answer is arithmetic and
    not the emergent shape of a settle, and a reader can check the table with
    a pencil.

    **The third and fourth were wrong when first written down and the code was
    right.** `nearestNeighbour` measures from this wire's FREE nodes, and a
    three-node rope has one; the numbers assumed an endpoint. Recorded because
    the temptation on a disagreement is to trust the expectation.

    **What this catches, and what it does NOT, run rather than assumed**
    (2026-09-05). One mutation dies here: `clamped` returning its argument,
    which fails `stoppingShort`. Four that a first draft of this docstring
    claimed do not -- the parallel guard, either zero-length guard, and both
    end clamps all survive every assertion above.

    The reason is structural and worth knowing before writing another case
    into this test. `nearestNeighbour` measures from a NODE, so the first of
    the two things is always a point, and the solver takes its zero-length
    branch before any of those four can run. Reaching them needs two real
    segments, which means going through the pushing path:
    `test_the_solver_parts_the_shapes_with_no_single_closest_point` and
    `test_a_contact_off_the_end_of_a_segment_is_measured_to_the_end` are
    where they die.
    """
    result = run(tmp_path, """
        // A rope with every node placed rather than solved.
        function laid(points) {
          const rope = new Rope(points[0], points[points.length - 1],
                                points.length);
          for (let i = 0; i < points.length; i++) {
            for (let axis = 0; axis < 3; axis++) {
              rope.position[i * 3 + axis] = points[i][axis];
              rope.previous[i * 3 + axis] = points[i][axis];
            }
          }
          return rope;
        }
        function apart(oneAt, twoAt) {
          const one = laid(oneAt);
          const two = laid(twoAt);
          // The array a caller hands every wire includes the wire itself.
          one.neighbours = [one, two];
          return one.nearestNeighbour();
        }
        console.log(JSON.stringify({
          perpendicular: apart([[-5, 0.5, 0], [0, 0.5, 0], [5, 0.5, 0]],
                               [[0, 0, -5], [0, 0, 0], [0, 0, 5]]),
          parallel: apart([[-5, 0, 0], [0, 0, 0], [5, 0, 0]],
                          [[-5, 0, 0.75], [0, 0, 0.75], [5, 0, 0.75]]),
          skew: apart([[-5, 0, 0], [0, 0, 0], [5, 0, 0]],
                      [[3, 2, -5], [3, 2, 0], [3, 2, 5]]),
          stoppingShort: apart([[0, 0, 0], [4, 0, 0], [8, 0, 0]],
                               [[20, 0, 0], [23, 0, 0], [26, 0, 0]]),
          coincident: apart([[-5, 0, 0], [0, 0, 0], [5, 0, 0]],
                            [[0, 3, 0], [0, 3, 0], [0, 3, 0]]),
        }));
    """)
    assert result["perpendicular"] == 0.5, result["perpendicular"]
    assert result["parallel"] == 0.75, result["parallel"]
    assert abs(result["skew"] - 13 ** 0.5) < 1e-12, result["skew"]
    assert result["stoppingShort"] == 16, result["stoppingShort"]
    assert result["coincident"] == 3, result["coincident"]


def test_one_pass_parts_a_crossing_and_leaves_the_other_wire_where_it_was(tmp_path):
    """**This wire moves and the other does not, which looks one-sided.**

    It is not. Every wire on the bench is advanced every frame in the
    renderer's own loop, so each pushes itself off the others in its turn and
    the pair separates. Writing into another rope's array would make `step`
    depend on the order the caller happens to step in, and would let one
    rope's step change a rope the caller has already stepped this frame.

    So one unstepped pass, on a crossing 0.1 apart that wants 0.32: the
    pushed wire must clear, and the other must be untouched to the bit.

    **A contact at a pinned end moves nothing**, which is the same rule the
    rest of this file follows -- a pad and a terminal are placed by whoever
    placed them. The share of a correction is weighted by how near the contact
    is to each end of the segment, so a contact exactly on a pinned node gives
    the free end a share of zero and the pass declines rather than inventing
    somewhere to put it. The other wire will part from it in its own turn.

    **`shares` is the arithmetic with nothing else in it**, and it is here
    because the first version of this test could not see a real defect. Two
    leads crossing touch on several segment pairs at once, so a correction of
    the wrong size still adds up to enough over four pushes, and both a share
    scaled wrongly and a pinned end taking one survived it.

    So the fixture is placed so that each contact is the ONLY pair within a
    tube of its segment: a seven-node lead along x, and three leads standing
    at x = 0.5, 3.5 and 5.5 running away in z. Each meets the middle of one
    segment and is 0.5385 from the next, past the 0.32 that would bring it
    into reach. Every number is then closed form -- 0.2 apart wanting 0.32 is
    a push of 0.12, and each end that may move takes half, which is 0.06.

    **Three shares in one fixture**, which is the point: the first contact is
    on the HEAD segment, the last on the TAIL segment, and the middle one
    between two free nodes. The tail's exemption was asserted by nothing at
    all until this, and the head's only incidentally, through a separation
    bound rather than a statement about where the head is.

    **Nine mutations die here, 2026-09-05, and four of them nowhere else**:
    the wanted separation taken as twice the THICKER lead rather than the sum
    of both, which every other fixture in this file hides by giving the two
    ropes the same radius; the pinned HEAD taking a share; the pinned TAIL
    taking a share, which survived every fixture in the file until the
    seven-node lead above put a contact on the last segment; and a contact
    exactly on a pinned node being resolved rather than declined. The rest
    are the correction written into the other rope, the division restored
    with a floor under its divisor, the separation taken as one radius, and
    either bounds rejection inverted.
    """
    result = run(tmp_path, """
        const R = 0.16;
        function laid(points, radius) {
          const rope = new Rope(points[0], points[points.length - 1],
                                points.length);
          for (let i = 0; i < points.length; i++) {
            for (let axis = 0; axis < 3; axis++) {
              rope.position[i * 3 + axis] = points[i][axis];
              rope.previous[i * 3 + axis] = points[i][axis];
            }
          }
          rope.radius = radius;
          return rope;
        }
        // A crossing 0.1 apart in y, which two 0.16 tubes cannot have.
        const one = laid([[-5, 0.1, 0], [0, 0.1, 0], [5, 0.1, 0]], R);
        const two = laid([[0, 0, -5], [0, 0, 0], [0, 0, 5]], R);
        one.neighbours = [one, two];
        const before = one.nearestNeighbour();
        const twoWas = Array.from(two.position);
        const headWas = one.point(0);
        one.offNeighbours();
        // And the same crossing placed exactly under the pinned head.
        const three = laid([[0, 0.1, 0], [5, 0.1, 0], [10, 0.1, 0]], R);
        const four = laid([[0, 0, -5], [0, 0, 0], [0, 0, 5]], R);
        three.neighbours = [three, four];
        const threeWas = Array.from(three.position);
        three.offNeighbours();
        // **Two different thicknesses**, which every other fixture in this
        // file gives the same value to -- so `Math.max(a, b) * 2` in place of
        // `a + b` passed the whole suite until the review said so. A 0.16
        // lead against an 0.08 one wants 0.24 between their centres, which
        // is neither twice the one nor twice the other.
        const thick = laid([[-5, 0.1, 0], [0, 0.1, 0], [5, 0.1, 0]], R);
        const thin = laid([[0, 0, -5], [0, 0, 0], [0, 0, 5]], R / 2);
        thick.neighbours = [thick, thin];
        thick.offNeighbours();
        // **One contact on each of three segments, and no two interacting.**
        // A seven-node lead along x, and three leads standing at x = 0.5,
        // 3.5 and 5.5 running away in z, so each meets the middle of exactly
        // one of the lead's segments and is 0.539 from the next -- past the
        // 0.32 that would bring it into reach. Every contact is 0.2 from its
        // neighbour and wants 0.32, so each pushes 0.12 and every end that
        // may move takes half of it.
        //
        // The first lands on the HEAD segment, the last on the TAIL segment,
        // and the middle one between two free nodes, so one fixture pins all
        // three shares at once.
        const lead = laid([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0],
                           [4, 0, 0], [5, 0, 0], [6, 0, 0]], R);
        const standingAt = (x) => laid([[x, 0.2, 0], [x, 0.2, 1], [x, 0.2, 2]], R);
        lead.neighbours = [lead, standingAt(0.5), standingAt(3.5), standingAt(5.5)];
        lead.offNeighbours();
        console.log(JSON.stringify({
          want: R * 2, before, after: one.nearestNeighbour(),
          theOtherMoved: twoWas.some((v, i) => v !== two.position[i]),
          headMoved: headWas.some((v, i) => v !== one.point(0)[i]),
          movedNodeY: one.position[4],
          pinnedHead: [threeWas[0], threeWas[1], threeWas[2]],
          pinnedHeadNow: three.point(0),
          shares: {
            nodes: [lead.point(0), lead.point(1), lead.point(2), lead.point(3),
                    lead.point(4), lead.point(5), lead.point(6)],
          },
          mixed: {
            wanted: R + R / 2, twiceTheThick: R * 2, twiceTheThin: R,
            movedTo: thick.position[4],
          },
        }));
    """)
    # It was too close, and one pass is enough to part it.
    assert result["before"] < result["want"], result["before"]
    assert result["after"] >= result["want"], (
        f"one pass left the crossing {result['after']} apart, and two tubes "
        f"need {result['want']}"
    )
    # The other wire is read and never written.
    assert result["theOtherMoved"] is False
    # Pinned ends are not this file's to move, here as everywhere else.
    assert result["headMoved"] is False
    assert result["pinnedHeadNow"] == result["pinnedHead"], result["pinnedHeadNow"]
    # The crossing opens upward, which is the only way it can: the two leads
    # are along x and along z, so the axis between them is y.
    assert result["movedNodeY"] >= result["want"], result["movedNodeY"]
    # And the closed-form one, exactly. Each contact is 0.2 from its
    # neighbour and wants 0.32, so each pushes 0.12 and every end that may
    # move takes half of it. **Under, and on purpose**: resolving the whole
    # 0.12 in one pass means dividing by how far the contact travels, which
    # is `s * s` on a segment with a pinned end and sends a wire to 1e17.
    #
    # Both pins are asserted, and the tail one is here because a mutation
    # that let the tail take a share survived every other fixture in this
    # file -- all of them put their crossing on a segment away from it.
    assert result["shares"]["nodes"] == [
        [0, 0, 0],        # the pinned head, which takes no share
        [1, -0.06, 0],    # its free neighbour, which takes the whole half
        [2, 0, 0],        # nothing reaches this one
        [3, -0.06, 0],    # two free ends, sharing evenly
        [4, -0.06, 0],
        [5, -0.06, 0],    # the tail's free neighbour
        [6, 0, 0],        # the pinned tail, which takes no share either
    ], result["shares"]["nodes"]
    # Two thicknesses, parted by the SUM and not by twice either of them.
    # Measured 0.24009 against a wanted 0.24, a twice-the-thick 0.32 and a
    # twice-the-thin 0.16, so the three are told apart by one number.
    mixed = result["mixed"]
    assert mixed["movedTo"] >= mixed["wanted"], mixed
    assert mixed["movedTo"] < mixed["twiceTheThick"], (
        "a 0.16 lead and an 0.08 one parted by twice the thicker, so the "
        "separation is a maximum where it should be a sum"
    )
    assert mixed["movedTo"] > mixed["twiceTheThin"], mixed


def test_the_solver_parts_the_shapes_with_no_single_closest_point(tmp_path):
    """**Four placements where "the closest pair of points" is not a pair**,
    and each reaches a branch that the by-hand distance test above cannot.

    That test measures from a NODE, so the first of the two things is always a
    point and three branches are unreachable through it. The mutation run said
    so: dropping the parallel guard, either zero-length guard, or the
    cross-product fallback all survived it. These go through the pushing path
    instead, where both things are real segments.

    | placement                              | branch it reaches         |
    |----------------------------------------|---------------------------|
    | parallel and overlapping, 0.2 apart    | no unique answer at all   |
    | meeting EXACTLY, so the gap is 0       | no direction in the gap   |
    | a wire as it is MADE, every node alike | zero-length on this side  |
    | a real wire against one of those       | zero-length on that side  |

    The third is not contrived, and it is on the live path rather than near
    it. **A wire begins with both ends on the same pad** -- `slacken`'s own
    docstring says so, and `board3d.js`'s `beginWire` builds exactly that,
    `new Rope(start, end ?? start.slice())` -- so every node coincides and
    every segment has zero length for as long as the drag has not moved. That
    rope is pushed into `view.wires` immediately, so on the very next frame
    every other lead on the bench is solving against it. A solver that divides
    by that length answers `NaN`, and a `NaN` position is a wire that vanishes
    from the scene and never comes back.

    Measured 2026-09-05, one pass each, nothing stepped: 0.2 becomes 0.32009,
    0 becomes 0.32066, 0.1 becomes 0.32 exactly, and 0.1 becomes 0.32031. The
    assertion is the bound and not those numbers, because how much past 0.32 a
    pass lands is a property of how many segment pairs happened to be in
    reach. Every coordinate is checked to be a finite number as well, which is
    the assertion the two zero-length guards actually fail.

    **Ten mutations die here, 2026-09-05, and four of them nowhere else**:
    either zero-length guard dropped, the cross-product fallback replaced by
    no push at all, and the same fallback pushing by HALF what it should --
    which survived until `fallbackMagnitude` was added, because a lower bound
    satisfied between several segment pairs cannot see a magnitude. The other
    six die elsewhere too: the parallel guard dropped, `clamped` not
    clamping, the division restored behind a floor, the separation taken as
    one radius, and either bounds rejection inverted.
    """
    result = run(tmp_path, """
        const R = 0.16;
        function laid(points) {
          const rope = new Rope(points[0], points[points.length - 1],
                                points.length);
          for (let i = 0; i < points.length; i++) {
            for (let axis = 0; axis < 3; axis++) {
              rope.position[i * 3 + axis] = points[i][axis];
              rope.previous[i * 3 + axis] = points[i][axis];
            }
          }
          rope.radius = R;
          return rope;
        }
        function finite(rope) {
          for (let i = 0; i < rope.position.length; i++) {
            if (!Number.isFinite(rope.position[i])) return false;
          }
          return true;
        }
        function part(one, two) {
          one.neighbours = [one, two];
          const before = one.nearestNeighbour();
          one.offNeighbours();
          return { before, after: one.nearestNeighbour(), finite: finite(one) };
        }
        // Both ends on the same pad, which is how every wire starts.
        function freshAt(at) {
          const rope = new Rope(at, at);
          rope.radius = R;
          return rope;
        }
        function freshlyMade() { return freshAt([0, 1, 0]); }
        console.log(JSON.stringify({
          want: R * 2,
          parallel: part(laid([[-5, 0, 0], [0, 0, 0], [5, 0, 0]]),
                         laid([[-5, 0.2, 0], [0, 0.2, 0], [5, 0.2, 0]])),
          exactlyCrossing: part(laid([[-5, 0, 0], [0, 0, 0], [5, 0, 0]]),
                                laid([[0, 0, -5], [0, 0, 0], [0, 0, 5]])),
          freshlyMade: part(freshlyMade(),
                            laid([[-5, 0.9, 0], [0, 0.9, 0], [5, 0.9, 0]])),
          againstAFreshOne: part(laid([[-5, 0.9, 0], [0, 0.9, 0], [5, 0.9, 0]]),
                                 freshlyMade()),
          // The same just-made wire placed just PAST the far end of its
          // neighbour, and just before its near end. Both conditions at once
          // -- no length on this side, and a contact off the end of that one
          // -- and it is the pair only the zero-length guard handles.
          freshPastTheEnd: part(freshAt([2.1, 0.1, 0]),
                                laid([[0, 0, 0], [1, 0, 0], [2, 0, 0]])),
          freshBeforeTheStart: part(freshAt([-0.1, 0.1, 0]),
                                    laid([[0, 0, 0], [1, 0, 0], [2, 0, 0]])),
          // The fallback's MAGNITUDE, which the `exactlyCrossing` bound above
          // cannot see. One pair only: a five-node lead along x, and a second
          // starting on it and running away in z, so its first segment meets
          // the middle of a free-free segment exactly and its second is a
          // whole unit away. The push has no direction in the positions, so
          // it is taken perpendicular to both leads at the full separation,
          // shared evenly: each end moves half of 0.32.
          fallbackMagnitude: (() => {
            const along = laid([[0, 0, 0], [1, 0, 0], [2, 0, 0],
                                [3, 0, 0], [4, 0, 0]]);
            const across = laid([[1.5, 0, 0], [1.5, 0, 1], [1.5, 0, 2]]);
            along.neighbours = [along, across];
            along.offNeighbours();
            return {nodes: [along.point(0), along.point(1),
                            along.point(2), along.point(3)]};
          })(),
        }));
    """)
    want = result["want"]
    # Each was too close to begin with, or the fixture proves nothing.
    assert result["parallel"]["before"] < want, result["parallel"]
    assert result["exactlyCrossing"]["before"] == 0, result["exactlyCrossing"]
    assert result["freshlyMade"]["before"] < want, result["freshlyMade"]
    assert result["againstAFreshOne"]["before"] < want, result["againstAFreshOne"]
    # One pass parts every one of them. **The ulp is not slack**: a pass aims
    # a node at exactly `want` from the other lead, and measuring the gap
    # again from the moved coordinates need not give that number back. The
    # just-made wire lands on 0.9 + 0.32, and 1.22 less 0.9 is
    # 0.31999999999999995. Five parts in 10^17 of a tube is not an overlap.
    close = want - 1e-12
    assert result["parallel"]["after"] >= close, result["parallel"]
    assert result["exactlyCrossing"]["after"] >= close, result["exactlyCrossing"]
    assert result["freshlyMade"]["after"] >= close, result["freshlyMade"]
    assert result["againstAFreshOne"]["after"] >= close, result["againstAFreshOne"]
    # And a wire whose position is not a number has left the scene for good.
    assert result["parallel"]["finite"], "a parallel pair divided by zero"
    assert result["exactlyCrossing"]["finite"], "an exact crossing divided by zero"
    assert result["freshlyMade"]["finite"], "a just-made wire divided by zero"
    assert result["againstAFreshOne"]["finite"], "a just-made neighbour did"
    # **These two are the ones that actually fail without the guard**, and the
    # first three do not: a zero-length segment only reaches the division when
    # the contact ALSO falls off the end of the other segment. Every
    # coordinate of the wire becomes NaN, which is a lead that leaves the
    # scene and never comes back.
    assert result["freshPastTheEnd"]["finite"], (
        "a just-made wire past the end of its neighbour divided by zero"
    )
    assert result["freshBeforeTheStart"]["finite"], (
        "a just-made wire before the start of its neighbour divided by zero"
    )
    assert result["freshPastTheEnd"]["after"] >= close, result["freshPastTheEnd"]
    assert result["freshBeforeTheStart"]["after"] >= close, (
        result["freshBeforeTheStart"]
    )
    # **And the fallback's magnitude, exactly.** A bound cannot see it: the
    # crossing above is resolved by several segment pairs between them, so
    # halving the one push that has no direction in the positions is
    # invisible there. Here there is one pair, the contact is the middle of a
    # segment with two free ends, and each end takes half of 0.32.
    assert result["fallbackMagnitude"]["nodes"] == [
        [0, 0, 0], [1, -0.16, 0], [2, -0.16, 0], [3, 0, 0],
    ], result["fallbackMagnitude"]["nodes"]


def test_a_contact_off_the_end_of_a_segment_is_measured_to_the_end(tmp_path):
    """**A segment is not the line through it, and a bound cannot see the
    difference.**

    Where the nearest point of the infinite line lies beyond the segment's
    end, the answer is the end. Drop that and the solver parts the leads along
    the wrong axis -- and it still parts them, by MORE than they need, so
    every "at least two radii" assertion in this file passes and the mutation
    survives. The gap has to be asserted as the number it is.

    Measured 2026-09-05, one unstepped pass on a single pair placed so the
    contact falls 0.25 before the neighbour's first node:

    | | free node lands at | gap |
    |---|---|---|
    | as it stands   | 1.5, 0.0628, -0.3138 | 0.32 exactly |
    | without the pin | 1.5, 0.32, -0.25    | 0.4061       |

    The second is a lead shoved straight up when the thing it is avoiding is
    off to one side, which is both wrong and invisible to a reader looking at
    a settled scene.

    **Mutations run, 2026-09-05**, failing here: the `t < 0` pin dropped, and
    `clamped` returning its argument.
    """
    result = run(tmp_path, """
        const R = 0.16;
        function laid(points) {
          const rope = new Rope(points[0], points[points.length - 1],
                                points.length);
          for (let i = 0; i < points.length; i++) {
            for (let axis = 0; axis < 3; axis++) {
              rope.position[i * 3 + axis] = points[i][axis];
              rope.previous[i * 3 + axis] = points[i][axis];
            }
          }
          rope.radius = R;
          return rope;
        }
        // One lead lying across the z axis short of the origin, and a second
        // that STARTS at the origin and runs away from it. The nearest point
        // of the line through the second is at negative z, off its end.
        const one = laid([[1.5, 0.05, -0.6], [1.5, 0.05, -0.25], [1.5, 0.05, 0.1]]);
        const two = laid([[1.5, 0, 0], [1.5, 0, 1], [1.5, 0, 2]]);
        one.neighbours = [one, two];
        const before = one.nearestNeighbour();
        one.offNeighbours();
        console.log(JSON.stringify({
          want: R * 2, before, after: one.nearestNeighbour(),
          moved: one.point(1),
        }));
    """)
    assert result["before"] < result["want"], result["before"]
    # Exactly the wanted gap, not merely at least it: parting along the wrong
    # axis overshoots to 0.4061 and would satisfy any lower bound.
    assert abs(result["after"] - result["want"]) < 1e-9, (
        f"one pass left the pair {result['after']} apart, wanting exactly "
        f"{result['want']}; a bigger number here means the contact was taken "
        f"off the end of the segment rather than at it"
    )
    # And where it went, which is the other half of the table above and was
    # collected without being asserted until the review said so. Parting
    # along the wrong axis sends it to (1.5, 0.32, -0.25) instead.
    assert result["moved"][0] == 1.5, result["moved"]
    assert abs(result["moved"][1] - 0.062757163) < 1e-9, result["moved"]
    assert abs(result["moved"][2] + 0.313785816) < 1e-9, result["moved"]


def test_a_wire_pushed_off_a_wire_is_never_left_inside_the_board(tmp_path):
    """**A lead pinned LOW across another is what shows this, not a crowd.**

    A lead pushed off a lead can be pushed into the board, so `step` resolves
    the solids once more after the wire pass. Finding a fixture that proves
    that line is needed took three tries, and the two that failed are worth
    recording because both looked convincing.

    Leads crossing each other in mid-air push each other sideways and upward
    and their ends rise out of the way, so it takes a great many of them
    before the board is reached at all. A lead whose own ends are PINNED at
    the height the lower one rests at has nowhere to send it but down, and
    four of those do what twelve of the others barely manage.

    Measured 2026-09-05, worst `contact().inside` over 600 frames, watched on
    every frame because the transient is where a push is largest:

    | fixture                                   | with it | without it |
    |-------------------------------------------|---------|------------|
    | six leads crossing on a slab              | 0       | 0          |
    | six dropped on a chip                     | 0       | 0          |
    | twelve leads crossing on a slab           | 0       | 0.2273     |
    | four pinned at 0.16 over a resting lead   | 0       | 0.0853     |
    | ten pinned at 0.16 over a resting lead    | 0       | 0.1057     |

    **A first version of this docstring said mid-air crossings never reach
    the board however many there are.** They do at twelve; six was simply too
    few. The fixture below is the pinned one because four of those is cheaper
    than twelve of anything.

    Zero is the pass, as everywhere `inside` appears in this file.

    **The first two rows used to read 0.1834 and 0.2614**, and they did while
    a pass resolved each contact in full. The review's blocker took that
    division out, corrections got smaller, and the fixture that had been
    catching this stopped catching anything -- which is why the numbers above
    are the second set measured and not the first.

    Two mutations die here, 2026-09-05: the solids never resolved again after
    the wire pass, and a rope offered itself as a neighbour. Neither only
    here, but this is the fixture the first was written for.
    """
    result = run(tmp_path, """
        const R = 0.16;
        const slab = {kind: "box", min: [-20, -0.9, -20], max: [20, 0, 20]};
        // One lead along x, which settles resting on the slab.
        const under = new Rope([-8, 0.04, 0], [8, 0.04, 0]);
        under.colliders = [slab];
        under.floor = -2;
        under.radius = R;
        under.slacken();
        const ropes = [under];
        // Four crossing it, pinned at the height it rests at, so their ends
        // cannot rise out of the way and it has nowhere to go but down.
        for (let w = 0; w < 4; w++) {
          const z = -6 + w * 3;
          const rope = new Rope([-1 + w * 0.3, R, z], [1 + w * 0.3, R, z + 12]);
          rope.colliders = [slab];
          rope.floor = -2;
          rope.radius = R;
          rope.slacken();
          ropes.push(rope);
        }
        for (const rope of ropes) rope.neighbours = ropes;
        let worst = 0;
        let worstFrame = -1;
        for (let f = 0; f < 600; f++) {
          for (const rope of ropes) rope.advance(1 / 60);
          for (const rope of ropes) {
            const inside = rope.contact().inside;
            if (inside > worst) { worst = inside; worstFrame = f; }
          }
        }
        console.log(JSON.stringify({worst, worstFrame, wires: ropes.length}));
    """)
    assert result["worst"] == 0, (
        f"a node was {result['worst']} inside the board on frame "
        f"{result['worstFrame']}; the solids are not resolved again after the "
        f"wire pass"
    )


def test_two_leads_crossed_at_right_angles_do_not_occupy_the_same_space(tmp_path):
    """**The ticket's own Done-when for OH-162 step 2, in its own words:**
    "two leads crossed at right angles settle with a centre gap of at least
    2 x radius at the crossing".

    Measured 2026-09-05, two 16-unit leads pinned on pads over a board slab,
    crossed at the middle, 900 frames at 1/60:

    | | never told a radius | told 0.16 |
    |---|---|---|
    | nearest centre to centre | 0.2243 | 0.4086 |
    | needed for two tubes     | --     | 0.32   |
    | `inside`, both wires     | 0      | 0      |

    0.4086 rather than something nearer 0.32 because a lead that has been
    pushed off another is also being held up by it: the upper one rests on
    the lower and the pair sits a little further apart than the minimum. What
    is asserted is the minimum, since where above it they land is the shape
    the solver finds and not a specification.

    **The minimum is exact for two leads left alone and approximate under a
    sustained press**, which is the price of under-correcting rather than
    resolving each contact in full. The resting state is where one pass's
    push balances one frame of gravity: measured at 1,200 frames, one lead
    pressing on another settles 0.3293 apart, four 0.3203 and ten 0.3192, the
    last a quarter of one per cent short of what two tubes want. Bounded, not
    drifting, and `partSegments` says so beside the arithmetic.

    The control is the point: without it they settle 0.2243 apart, which is
    less than one tube across, so the two leads really are in the same place
    and a picture of them is a lie. It is not zero because two leads sagging
    onto a board cross at slightly different heights anyway -- which is
    exactly why "they look about right" was never evidence.

    `inside` staying 0 is the other half. A lead pushed off a lead can be
    pushed into the board, so `step` resolves the solids once more after the
    wire pass, and this is the assertion that says it worked.

    `clear` is the fixture that must report nothing: two leads told a radius
    with forty units between them, neither moved by a single bit.

    **Four mutations die here, 2026-09-05**: the wire pass never called from
    `step`; either bounds rejection inverted, whole-rope or per-segment,
    which drops the pairs that are actually close; and `clamped` not
    clamping. None of the four dies only here.

    **Two that a first draft claimed die here and do not.** The pass called
    but its result ignored, so the solids never resolve again: two leads do
    not push each other into the board, and what does is a lead pinned low
    across another, in
    `test_a_wire_pushed_off_a_wire_is_never_left_inside_the_board`. And the
    correction written into the other rope as well, which this fixture is too
    forgiving to notice.
    """
    result = run(tmp_path, """
        const R = 0.16;
        const slab = {kind: "box", min: [-20, -0.9, -20], max: [20, 0, 20]};
        function crossed(radius) {
          const one = new Rope([-8, 0.04, 0], [8, 0.04, 0]);
          const two = new Rope([0, 0.04, -8], [0, 0.04, 8]);
          for (const rope of [one, two]) {
            rope.colliders = [slab];
            rope.floor = -2;
            rope.radius = radius;
            rope.slacken();
          }
          one.neighbours = [one, two];
          two.neighbours = [one, two];
          for (let f = 0; f < 900; f++) { one.advance(1 / 60); two.advance(1 / 60); }
          return {
            nearest: one.nearestNeighbour(),
            oneInside: one.contact().inside,
            twoInside: two.contact().inside,
          };
        }
        // Forty units apart and told a radius: nothing may happen at all.
        const far = new Rope([-5, 0.04, 0], [5, 0.04, 0]);
        const alsoFar = new Rope([-5, 40, 0], [5, 40, 0]);
        for (const rope of [far, alsoFar]) { rope.radius = R; rope.floor = -50; }
        far.neighbours = [far, alsoFar];
        const farWas = Array.from(far.position);
        far.offNeighbours();
        console.log(JSON.stringify({
          want: R * 2, bare: crossed(0), told: crossed(R),
          clearMoved: farWas.some((v, i) => v !== far.position[i]),
          clearApart: far.nearestNeighbour(),
        }));
    """)
    # The control: two leads in the same place, and it is not zero, which is
    # why looking at them was never going to settle it.
    assert result["bare"]["nearest"] < result["want"], result["bare"]
    # The ticket's sentence.
    assert result["told"]["nearest"] >= result["want"], (
        f"two crossed leads settled {result['told']['nearest']} apart, and "
        f"two tubes need {result['want']}"
    )
    # Pushed off a wire, not into the board.
    assert result["told"]["oneInside"] == 0, result["told"]
    assert result["told"]["twoInside"] == 0, result["told"]
    # The fixture that must report nothing. 39.96 and not 40: the near wire
    # is pinned at a pad's own height, 0.04 above the slab, like the others.
    assert result["clearMoved"] is False
    assert abs(result["clearApart"] - (40 - 0.04)) < 1e-12, result["clearApart"]


def test_a_wire_pushed_off_another_wire_still_comes_to_rest(tmp_path):
    """**The one way a Verlet chain fails, asked again now that two of them
    push each other.**

    `test_a_hanging_wire_loses_energy_rather_than_gaining_it` covers a wire on
    its own. Two wires resolving against each other are a different system:
    each treats the other as fixed for the length of its own step, so each can
    overshoot what the other has just done, and a pair like that can sit in a
    limit cycle for ever without either one gaining energy on its own.

    Measured 2026-09-05, the crossed pair above. It does not settle as flatly
    as a lone wire and it does settle: energy peaks at 5.4e-4 after the first
    two hundred frames, wanders down unevenly, and reaches 1.9e-13 by three
    thousand frames and 2.1e-27 by six thousand.

    **That wander is the price of resolving wire against wire once a step
    instead of once a constraint pass**, and the trade is recorded in `step`
    with the numbers behind it. Once a pass is 5.2 times dearer and settles a
    crowded bench WORSE, not better.

    Asserted as a bound and a decay rather than a fixed number, because the
    exact figure is a property of the damping. Three thousand frames of two
    ropes is about a fifth of a second here.

    **Nine mutations die here, 2026-09-05**, none of them only here: the
    `t < 0` clamp dropped, `clamped` not clamping, the correction written into
    the other rope, the separation taken as one radius, the pass never
    running, the solids never resolved again after it, either bounds
    rejection inverted, and a rope offered ITSELF as a neighbour -- a wire
    resolving against its own segments pushes every node away from its own
    neighbours for ever, which no gap assertion notices because the gap it
    reports is to another wire.
    """
    result = run(tmp_path, """
        const R = 0.16;
        const slab = {kind: "box", min: [-20, -0.9, -20], max: [20, 0, 20]};
        const one = new Rope([-8, 0.04, 0], [8, 0.04, 0]);
        const two = new Rope([0, 0.04, -8], [0, 0.04, 8]);
        for (const rope of [one, two]) {
          rope.colliders = [slab];
          rope.floor = -2;
          rope.radius = R;
          rope.slacken();
        }
        one.neighbours = [one, two];
        two.neighbours = [one, two];
        let peak = 0;
        for (let f = 0; f < 3000; f++) {
          one.advance(1 / 60);
          two.advance(1 / 60);
          // After the drop, which is a real transient and not the question.
          if (f > 200) peak = Math.max(peak, one.energy(), two.energy());
        }
        console.log(JSON.stringify({
          peak, one: one.energy(), two: two.energy(),
          nearest: one.nearestNeighbour(), want: R * 2,
        }));
    """)
    assert result["peak"] < 1e-3, f"the pair is swapping pushes: peak {result['peak']}"
    assert result["one"] < 1e-6, f"one wire is still moving: {result['one']}"
    assert result["two"] < 1e-6, f"the other is still moving: {result['two']}"
    # And it settled where it should have, not merely quietly.
    assert result["nearest"] >= result["want"], result["nearest"]


def test_two_wires_pinned_too_close_do_not_leave_the_scene(tmp_path):
    """**The defect the OH-162 step 2 review found, and it was catastrophic.**

    A pass shared its correction between a segment's two ends and then divided
    by how far the contact point itself travels, so that one pass resolved the
    whole overlap. On a HEAD segment that divisor is `s * s`, because the
    pinned end takes no share -- and a contact near the pinned end therefore
    sent the free end `push / s` away.

    Two wires can be pinned at the same terminal: `onPointerUp` refuses only a
    wire's own starting post. Measured on the shipped file, two leads pinned
    side by side and stepped 600 frames, worst absolute coordinate reached:

    | heads apart | before the fix | now  |
    |-------------|----------------|------|
    | 0           | 6.4e17         | 8.23 |
    | 0.1         | 5.3e6          | 8.26 |
    | 0.2         | 6.0e4          | 8.16 |
    | 0.31        | 45.2           | 8.09 |
    | 0.32        | 8.24           | 8.24 |

    Every separation under the 0.32 two tubes want blew up, not merely the
    degenerate one, and 8.2 is where the wire actually is: its own length.
    A reviewer swept the whole range at 0.01 and found the worst of it is not
    at zero but in the band from 0.12 to 0.18, at 3.7e13; the rows above are
    four samples of a curve, not its peak. After the fix the same sweep's
    worst is 8.2607, at 0.11.
    Nothing saw it -- `nearestNeighbour` excludes pinned ends by design, a
    finiteness check passes because 1e17 is a number, and the energy bounds
    were only ever asserted on the crossed pair.

    The fix is not a floor on the divisor. A floor at 1e-6 still let 0.1 apart
    reach 220, because the band between is bad too. The division went instead:
    a pass under-corrects and the overlap comes out over the following steps,
    which cannot diverge because nothing is divided.

    **Three mutations die here, 2026-09-05**: the division restored, the
    division restored while declining whenever its divisor is under 1e-6 --
    which is the fix that looks obvious and is not enough -- and the parallel
    guard dropped. None only here; the two division mutations also fail
    `test_a_crowded_bench_comes_to_rest_and_does_not_stir_for_ever`, which is
    the same defect showing up as noise rather than as flight.
    """
    result = run(tmp_path, """
        const R = 0.16;
        function pinnedApart(apartBy) {
          const one = new Rope([0, 0.04, 0], [8, 0.04, 0]);
          const two = new Rope([0, 0.04, apartBy], [8, 0.04, apartBy]);
          for (const rope of [one, two]) {
            rope.floor = -2;
            rope.radius = R;
            rope.slacken();
          }
          one.neighbours = [one, two];
          two.neighbours = [one, two];
          let worst = 0;
          for (let f = 0; f < 600; f++) {
            one.advance(1 / 60);
            two.advance(1 / 60);
            for (const rope of [one, two]) {
              for (let i = 0; i < rope.position.length; i++) {
                worst = Math.max(worst, Math.abs(rope.position[i]));
              }
            }
          }
          return worst;
        }
        console.log(JSON.stringify({
          want: R * 2, span: 8,
          together: pinnedApart(0),
          tenth: pinnedApart(0.1),
          fifth: pinnedApart(0.2),
          nearlyEnough: pinnedApart(0.31),
          enough: pinnedApart(0.32),
        }));
    """)
    # Nothing may travel further than the wire is long. Ten times its span is
    # a loose bound on purpose: what this catches is 1e4 and upwards, and a
    # tight one would fail on a wire that merely swings wide.
    roomy = result["span"] * 10
    assert result["together"] < roomy, result["together"]
    assert result["tenth"] < roomy, result["tenth"]
    assert result["fifth"] < roomy, result["fifth"]
    assert result["nearlyEnough"] < roomy, result["nearlyEnough"]
    assert result["enough"] < roomy, result["enough"]


def test_a_crowded_bench_comes_to_rest_and_does_not_stir_for_ever(tmp_path):
    """**Twelve leads through one point, which is the case that broke twice.**

    Two wires resolving against each other are a different system from one
    wire, and twelve are a different system again: each treats the others as
    fixed for the length of its own step, so a crowded pile can keep swapping
    pushes long after any one of them would have stopped.

    It did. Measured 2026-09-05, peak total energy per thousand frames, while
    a pass still resolved each contact in full by dividing by how far the
    contact travels:

    | frames    | six wires | twelve wires |
    |-----------|-----------|--------------|
    | 0-1000    | 58.5      | 116          |
    | 1000-2000 | 2.0e-5    | 10           |
    | 2000-3000 | 6.2e-8    | 0.316        |
    | 3000-7000 | to 8.1e-12| between 2.4e-4 and 3.6e-3 |
    | 7000-8000 | 1.1e-12   | 6.8e-5       |

    Twelve fell five orders and then wandered in a band for five thousand
    frames. **That was not a property of a crowded bench, which is what a
    first draft of this docstring said it was. It was the over-correction**,
    and it went when the division did -- the same change the review's blocker
    forced. It did settle in the end, about five orders of magnitude more
    slowly; "for ever" was this docstring overstating its own measurement,
    which a second reviewer caught by running it to eight thousand frames.
    The same measurement on the same fixtures now:

    | frames    | six wires | twelve wires |
    |-----------|-----------|--------------|
    | 0-1000    | 58.4      | 113          |
    | 1000-2000 | 9.0e-4    | 1.5e-4       |
    | 2000-3000 | 1.6e-4    | 5.8e-6       |
    | 7000-8000 | 1.3e-9    | 8.9e-10      |

    So this asserts rest, not a bound: the last thousand frames of three
    thousand hold under 1e-3, measured at 5.8e-6, where the first thousand
    contain a drop of 113.

    Three thousand frames of twelve ropes is about three seconds here, which
    makes this the most expensive test in the file and is why it stops there
    rather than at the eight thousand the tables needed.

    **Eight mutations die here, 2026-09-05, and one of them nowhere else**:
    the `t > 1` clamp dropped. A crowded pile is where a wrong closest point
    shows up as motion that never stops, and it is the only fixture patient
    enough to see it. The other seven are the `t < 0` clamp, `clamped` not
    clamping, the correction written into the other rope, both division
    mutations, the solids never resolved again, and a rope offered itself.
    """
    result = run(tmp_path, """
        const R = 0.16;
        const slab = {kind: "box", min: [-20, -0.9, -20], max: [20, 0, 20]};
        const ropes = [];
        for (let w = 0; w < 12; w++) {
          const angle = (w / 12) * Math.PI;
          const rope = new Rope([-Math.cos(angle) * 8, 0.04, -Math.sin(angle) * 8],
                                [Math.cos(angle) * 8, 0.04, Math.sin(angle) * 8]);
          rope.colliders = [slab];
          rope.floor = -2;
          rope.radius = R;
          rope.slacken();
          ropes.push(rope);
        }
        for (const rope of ropes) rope.neighbours = ropes;
        let dropping = 0;
        let holding = 0;
        for (let f = 0; f < 3000; f++) {
          for (const rope of ropes) rope.advance(1 / 60);
          let total = 0;
          for (const rope of ropes) total += rope.energy();
          if (f < 1000) dropping = Math.max(dropping, total);
          else if (f >= 2000) holding = Math.max(holding, total);
        }
        console.log(JSON.stringify({dropping, holding, wires: ropes.length}));
    """)
    assert result["holding"] < 1e-3, (
        f"twelve crossed leads are still carrying {result['holding']} of "
        f"energy after two thousand frames, against the drop's "
        f"{result['dropping']}; a crowded bench has to come to rest and not "
        f"merely stay bounded"
    )


def test_a_settled_lead_takes_the_shape_its_two_ends_give_it(tmp_path):
    """**OH-162 step 3's own test, answering what is true rather than what was
    hoped for.** The step asked for plastic set -- "record the rest angle at
    each node when a wire stops moving and relax toward it, so a bent lead
    stays bent; the test is that a lead dragged into an arc does not return to
    a catenary". It does return, this is the number, and the mechanism was
    measured and declined. `stiffen` carries the reason.

    The manoeuvre is the only one a PERSON can perform on a finished lead.
    `board3d.js` places a part once from the bench slot its index gives,
    `removePart` splices the list without re-laying out the rest, no pointer
    handler reaches a part at all, and a wire touching a removed part is
    discarded rather than left to swing. `moveHead` and `moveTail` are called
    every frame and hand over the same point every frame -- measured over six
    hundred frames of the animation loop's own calls, an end moves by exactly
    0. What CAN change is what is underneath, because `refreshColliders` runs
    on every add and every remove.

    **Two paths do move an end, and a first draft of this said none did.**
    `placeModel` raises every pad to the real board's top face, and on the Uno
    that is 0.68 to 5.12 scene units, so the head of a wire made while the
    model was still in flight jumps 4.44 -- six times what a part lifts a lead
    in the fixture below. `carvePins` then swaps that wire's `post` to the
    carved pin, which sits at the model's own millimetre position. Both fire
    once per board load, for a wire made during the fetch, which is OH-129's
    case and is tested at `test_board3d.py`'s own OH-129 test.

    **That is where a bend memory would have had its best case, and it is
    still not one.** Retention on the pad raise reaches 0.209 units at a rate
    of 0.01, twenty times the 0.0106 the decline rests on. But a lead cannot
    be dragged into that shape on purpose, it happens once and never again,
    and what would be remembered is the bend a pad had before it moved to
    where it belongs. A shape nobody asked for, kept from a position that no
    longer exists, is a defect rather than the feature step 3 wanted.

    So: a lead hangs, a part arrives under it, the lead drapes over it, the
    part goes. Measured 2026-09-05, a 10-unit lead with the file's own slack:

    | | |
    |---|---|
    | hanging free, lowest node | 1.9629 |
    | resting on the part | 2.6600 |
    | after the part goes | 1.9629 |
    | worst node moved between the first and the last | 6.7e-8 |

    Six parts in ten million of a unit, on a lead the same solver moves 0.7 of
    a unit while the part is there.

    **"Nothing else" would be wrong, and the second arm is why.** A lead does
    carry one memory: its own length. `payOut` only ever grows, so a tail
    dragged out to 16 and brought back to 10 leaves the rest length 21% longer
    and the settled shape **1.75 units** from where it hung. That is the same
    measurement on the same fixture, and it is seven orders of magnitude above
    the drape's. It is here so that "the lead came back" is a measurement and
    not a blunt instrument -- a test that cannot see a memory that is there
    says nothing about one that is not.

    It is also this test's live mutation. Take the `if (needed > this.segment)`
    guard out of `payOut` and the lead shortens on the way back instead of
    keeping its length, so `lengthKept` goes negative.

    **The part has to be wider than the lead dips into it or this measures the
    collider instead.** `outOfBox` sends a node out by its NEAREST face, so two
    neighbours inside a narrow solid leave by opposite ones and are held apart
    at its width: a first version of this fixture used a box three units across
    under a lead dipping two and a half into it, and the SHIPPED solver
    reported 416% over rest for as long as the box was there. This one is eight
    across and two and a half tall, five nodes come to rest on its top face,
    and the worst stretch is 0.55%.

    **Why the node count is asserted at three when the fixture gives five.**
    It is a precondition and not a detector. The stretch while on the part is
    what separates a drape from a tear -- 0.55% here against the 199% and 417%
    of parts too narrow to drape over -- and `returnedTo` is what detects a
    memory. All this one has to say is that the lead really touches the part,
    and it fails readily: dropping the part's top from 2.5 to 2.2 takes the
    count from five to two, and a narrow part takes it to zero.

    It sits one node above its margin deliberately. A patched-in plastic set
    at a rate of 0.01 leaves exactly three, so asserting four would make a
    precondition fire on a mechanism change and hand the next reader two
    failures with no way to tell which is the signal. `returnedTo` already
    kills that rate.

    `clear` is the fixture that must report nothing: the same part arriving
    twenty units to the side, where the lead cannot reach it, against the same
    lead with no part at all -- every bit the same. Not "nothing moves": a
    settled lead still creeps by parts in a billion under its own weight, and
    a first draft of this asserted that and failed on it.

    **What a plastic set would do to this test is break it, deliberately.**
    Anyone implementing OH-162 step 3 should expect this assertion to fail and
    should replace it, not repair it -- it says the shape has no memory, which
    is the thing that step exists to change.

    **And that is checked rather than hoped for.** The mechanism was patched
    into a copy of `wires.js` -- a per-pair remembered rest length creeping
    toward the bend the wire has -- and this test's own body run against it,
    with every one of the assertions below evaluated at each rate:

    | rate | 1e-5 | 1e-4 | 3e-4 | 1e-3 | 3e-3 | 0.01 | 0.1 | 1 |
    |---|---|---|---|---|---|---|---|---|
    | returned to | 8.3e-4 | 6.2e-3 | 1.0e-2 | 1.1e-2 | 2.6e-3 | 3.5e-4 | 8.2e-9 | 2.4e-9 |
    | at a bound of 1e-4 | kill | kill | kill | kill | kill | kill | -- | -- |
    | at a bound of 1e-3 | -- | kill | kill | kill | kill | -- | -- | -- |

    Killed at every rate from 1e-5 to 0.01, which is the whole band in which
    the mechanism does anything.

    **The second row is why the bound is 1e-4 and not the 1e-3 a first draft
    shipped.** That draft loosened the bound on a review's advice and did not
    re-derive this table, so it claimed six kills while making four: at 1e-5
    and at 0.01 the memory is doing real work -- at 0.01 the nodes resting on
    the part drop from five to three and the stretch there from 0.55% to
    0.11% -- and the test could not see it. Loosening an assertion without
    re-running the evidence written beside it is the whole of that mistake.

    **The two survivors are a test gap and are recorded as one.** A first draft
    called them equivalent, on the grounds that at 0.1 and 1 the memory tracks
    so closely that the constraint is always satisfied and there is nothing
    left to see. The review measured the second half of that and it is false:
    the bendless wire is a DIFFERENT wire, and the same memory moves a lead
    nobody has touched by 0.0095 units. They survive because **nothing in this
    file checks what the bending constraint is FOR.** Stub `stiffen` with an
    early return and 23 of the 25 tests here pass, including
    `test_a_stiff_wire_hangs_less_deeply_than_a_limp_one`, which is the one
    named for it -- few 2.85 against many 3.24, energy still falling, stretch
    still under one per cent.

    **Two do fail, and how they fail is the point.** The wire-wire pair reaches
    0.31995 where two tubes need 0.32, short by sixteen parts in a hundred
    thousand, because a bendless lead drapes a little differently. That is an
    accident of the drape rather than a check on bending, so it is not the
    check that is missing. A first draft of this paragraph said nothing kills
    it at all -- a claim about the whole file taken from a review that had run
    one test, which is the same mistake as the bound, twenty lines above.
    """
    result = run(tmp_path, """
        const R = 0.16;
        // Wider than the lead dips into it, so every node it catches leaves
        // by the top face and the lead drapes rather than being torn across.
        const PART = {kind: "box", min: [1, 0, -3], max: [9, 2.5, 3]};
        const BESIDE = {kind: "box", min: [20, 0, -3], max: [28, 2.5, 3]};
        function lead() {
          const rope = new Rope([0, 6, 0], [10, 6, 0]);
          rope.slacken();
          rope.floor = 0;
          rope.radius = R;
          return rope;
        }
        function settle(rope, frames) {
          for (let f = 0; f < frames; f++) rope.advance(1 / 60);
        }
        function lowest(rope) {
          let low = Infinity;
          for (let i = 0; i < rope.count; i++) low = Math.min(low, rope.point(i)[1]);
          return low;
        }
        function apart(a, b) {
          let worst = 0;
          for (let i = 0; i < a.length; i += 3) {
            worst = Math.max(worst, Math.hypot(
              a[i] - b[i], a[i + 1] - b[i + 1], a[i + 2] - b[i + 2]));
          }
          return worst;
        }
        // On its top face, within a rounding of a radius above it.
        function restingOn(rope, solid) {
          let count = 0;
          for (let i = 0; i < rope.count; i++) {
            const p = rope.point(i);
            if (Math.abs(p[1] - (solid.max[1] + R)) < 1e-6
                && p[0] > solid.min[0] && p[0] < solid.max[0]) count += 1;
          }
          return count;
        }

        const rope = lead();
        settle(rope, 900);
        const hanging = Array.from(rope.position);
        const hungAt = lowest(rope);
        const segment = rope.segment;

        rope.colliders = [PART];
        settle(rope, 3600);
        const onIt = {lowest: lowest(rope), stretch: rope.worstStretch(),
                      nodes: restingOn(rope, PART)};

        rope.colliders = [];
        settle(rope, 1800);

        // The part that arrives out of reach must make no difference at all.
        // Not "nothing moves" -- a settled lead still creeps by parts in a
        // billion under its own weight, and a first draft of this asserted
        // that and failed. Two leads, the same frames, one of them given a
        // part it cannot reach: every bit the same.
        const clear = lead();
        const alsoClear = lead();
        settle(clear, 900);
        settle(alsoClear, 900);
        clear.colliders = [BESIDE];
        settle(clear, 600);
        settle(alsoClear, 600);
        const clearDiffers = Array.from(clear.position)
          .some((v, i) => v !== alsoClear.position[i]);

        // **The one memory a lead really does have**, so that "returns to
        // where it was" is a measurement and not a blunt instrument. `payOut`
        // only ever grows, so an end dragged past the lead's reach and brought
        // back leaves it longer, and a longer lead hangs somewhere else.
        const pulled = lead();
        settle(pulled, 900);
        const hungBefore = Array.from(pulled.position);
        const wasSegment = pulled.segment;
        for (let f = 1; f <= 90; f++) {
          pulled.moveTail([10 + 6 * (f / 90), 6, 0]);
          pulled.advance(1 / 60);
        }
        settle(pulled, 300);
        for (let f = 1; f <= 90; f++) {
          pulled.moveTail([16 - 6 * (f / 90), 6, 0]);
          pulled.advance(1 / 60);
        }
        settle(pulled, 900);

        console.log(JSON.stringify({
          hungAt, onIt, afterAt: lowest(rope),
          returnedTo: apart(hanging, Array.from(rope.position)),
          paidOut: rope.segment - segment,
          stretchAfter: rope.worstStretch(),
          energyAfter: rope.energy(),
          clearDiffers,
          lengthKept: pulled.segment - wasSegment,
          lengthShowsAs: apart(hungBefore, Array.from(pulled.position)),
        }));
    """)
    # The part really did hold the lead up -- without this the return below is
    # a lead that never went anywhere.
    assert result["onIt"]["lowest"] - result["hungAt"] > 0.5, result["onIt"]
    assert result["onIt"]["nodes"] >= 3, (
        f"only {result['onIt']['nodes']} nodes came to rest on the part's top "
        f"face, so the lead is not draped over it and this fixture measures "
        f"the collider rather than the shape"
    )
    # And the collider is not tearing it, which is what makes the rest mean
    # anything: 0.55% measured, against 0.27% for the same lead hanging free.
    assert result["onIt"]["stretch"] < 0.02, result["onIt"]
    # The lead is not longer than it was: a pay-out would be a second memory
    # and would answer this question the wrong way for the wrong reason.
    assert result["paidOut"] == 0, result["paidOut"]
    # The shape has no memory of the part. The bound is 1e-4 rather than the
    # 6.7e-8 measured, because pinning float noise as a requirement makes a
    # test fail on any harmless change -- and rather than the 1e-3 a first
    # draft used, which let the mechanism through at two of the eight rates it
    # was checked against. 1e-4 is 1,490 times the noise and still kills every
    # rate that does anything. See the table in the docstring.
    assert result["returnedTo"] < 1e-4, (
        f"the lead came back {result['returnedTo']} from where it hung before "
        f"the part arrived, and the solver has no plastic set, so it should "
        f"come back to itself"
    )
    assert abs(result["afterAt"] - result["hungAt"]) < 1e-4, result
    # Still a wire afterwards, and still. Collected without being asserted in
    # a first draft, which is the exact pattern a step-2 review already caught
    # on this ticket.
    assert result["stretchAfter"] < 0.01, (
        f"the lead is {result['stretchAfter'] * 100:.2f}% over its rest length "
        f"once the part has gone, against 0.27% for one that never saw a part"
    )
    assert result["energyAfter"] < 1e-9, (
        f"the lead is still moving at {result['energyAfter']} after eighteen "
        f"hundred frames, so nothing above was measured on a settled shape"
    )
    # The fixture that must report nothing.
    assert result["clearDiffers"] is False
    # And the memory a lead DOES have, which is what makes the above a
    # measurement rather than a blunt instrument. Only ever longer: with
    # `payOut`'s guard removed the lead shrinks on the way back instead.
    assert result["lengthKept"] > 0, (
        f"the lead came back from being dragged past its reach with its rest "
        f"length changed by {result['lengthKept']}, and `payOut` only grows"
    )
    assert result["lengthShowsAs"] > 0.1, (
        f"being paid out moved the settled shape by only "
        f"{result['lengthShowsAs']}, so this test cannot see a memory that is "
        f"there and its answer about plastic set means nothing"
    )
