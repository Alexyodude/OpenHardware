# OpenHardware — the circuit a bench is, checked by solving it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this file runs node
#
# The same reason `tests/webui/test_wires.py` does, and that file's header
# argues it at length: `tests/webui/test_board3d.py` checks its renderer by
# reading the source, because a WebGL scene cannot be rendered from Python.
# **A circuit has no such excuse.** `webui/static/circuit.js` imports nothing,
# so its arithmetic can be executed and its answers compared with numbers.
#
# It matters more here than it did for the rope. A rope that is subtly wrong
# looks like a slightly different rope; a circuit that is subtly wrong lights an
# LED that is not connected to anything, which is what OH-79 exists to fix and
# what no amount of grepping the source would have caught.
#
# ## What is asserted
#
# Three kinds of thing, and the middle one is the important one:
#
#   * the three cases the user can see — one leg in mid-air, wired to ground,
#     wired backwards
#   * **invariants that hold whatever the solver does inside**: current is
#     conserved at every node, a series pair carries one current, two parts in
#     parallel each carry less than one alone, and the answer does not depend on
#     the order the wires were made in
#   * that the honest-degradation paths degrade — no supply, no part model, an
#     unanswerable pad, a short across a rail
#
# Node voltages are never pinned. They are an emergent property of the netlist
# and pinning them would fail on any change and say nothing about whether the
# change was right — the same rule `test_wires.py` states about rope positions.

import json
import pathlib
import shutil
import subprocess
import textwrap

import pytest

CIRCUIT = (pathlib.Path(__file__).resolve().parents[2]
           / "webui" / "static" / "circuit.js")

#: The Arduino Uno's own numbers, as `webui/boards/atmega328p.py` publishes
#: them. Copied here rather than imported so that a test failing says which of
#: the two moved: if this file and that constant disagree,
#: `test_the_bench_uses_the_boards_own_published_supply` is the one that fails.
UNO = {
    "chip": "ATmega328P", "volts": 5.0, "sourceOhms": 40.0, "sinkOhms": 45.0,
    "ratedAmps": 0.020, "absoluteAmps": 0.040,
}

#: A 5 mm LED as `tools/import_3d_model.py`'s `LED_ELECTRICAL` describes it.
#:
#: **`absoluteAmps` is the only one taken at the generous end of its band**, and
#: the inversion is deliberate: the other two make the computed CURRENT a lower
#: bound, this makes the LIMIT an upper bound, so "past it" holds under every
#: reading of both. It is also the only number that can license the word
#: `damaged`.
LED = {
    "label": "5 mm LED", "terminals": ["cathode", "anode"],
    "model": {"kind": "diode", "from": "anode", "to": "cathode",
              "forwardVolts": 2.2, "seriesOhms": 30.0, "ratedAmps": 0.020,
              "absoluteAmps": 0.030},
}

#: How `webui/static/parts.js` spells each of `LED_ELECTRICAL`'s numbers on the
#: other side of the glTF. Listed so that a parameter added to the part without
#: a name here fails a test rather than being silently dropped in transit --
#: which is what happened to `absolute_amps` on the first pass, and every test
#: in this file went on passing against an LED the page no longer loads.
JS_NAME = {
    "forward_volts": "forwardVolts",
    "series_ohms": "seriesOhms",
    "rated_amps": "ratedAmps",
    "absolute_amps": "absoluteAmps",
    "ohms": "ohms",
}

#: The 220 Ω resistor, as `tools/import_3d_model.py`'s `RESISTOR_ELECTRICAL`
#: describes it — and **231 is not a typo for 220**.
#:
#: A resistor entered at its nominal value would break the one invariant this
#: file rests on. Every resistance the solver is handed is a worst corner, so
#: every current it computes is a lower bound and the page may warn but never
#: reassure. A real 220 Ω ±5% part may be 209 Ω, and 209 passes MORE current
#: than 220 — so a bench modelled at 220 would print "at least 9.7 mA" about a
#: circuit that can carry 10.0. 231 is the top of the band.
#:
#: **No `ratedAmps` and no `absoluteAmps`, deliberately.** A resistor's limit is
#: power, and on a 5 V bench this one cannot dissipate more than 108 mW against
#: the 250 mW its body is sold at, so no circuit here can reach it.
#: `test_a_resistor_publishes_no_limit_because_none_is_reachable` is the guard.
RESISTOR = {
    "label": "220 Ω resistor", "terminals": ["lead A", "lead B"],
    "model": {"kind": "resistor", "ohms": 231.0},
}

#: An Uno's power and digital pads, as `webui/api.py` sends them. **Three GND
#: pads, because an Uno has three** — the pad map carries one on the digital
#: header and two on the power header, and a circuit has to treat them as one
#: net or a reader who picks the wrong one gets a wrong answer.
PADS = [
    {"name": "13", "state": "high"},
    {"name": "12", "state": "low"},
    {"name": "11", "state": "input"},
    {"name": "A0", "state": "unknown"},
    {"name": "GND", "state": "unknown"},
    {"name": "5V", "state": "unknown"},
    {"name": "3V3", "state": "unknown"},
    {"name": "VIN", "state": "unknown"},
]


def run(tmp_path: pathlib.Path, body: str) -> dict:
    """Run a fragment against the real `circuit.js` under node, and parse it.

    A `file://` URL because node resolves a bare relative path against the
    *entry* module, and the entry module is in a temporary directory that knows
    nothing about this repository. `test_wires.py` learned that first.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; circuit.js is ES module arithmetic and "
                    "needs one to run")
    if not CIRCUIT.is_file():
        pytest.skip(f"no {CIRCUIT}")

    script = tmp_path / "probe.mjs"
    script.write_text(
        f"import {{ analyse, solve, RAILS, LIT_AMPS, GMIN, OFF_OHMS, "
        f"MAX_PASSES, ASSUMED_OHMS, milliamps }} from {CIRCUIT.as_uri()!r};\n"
        f"const UNO = {json.dumps(UNO)};\n"
        f"const LED = {json.dumps(LED)};\n"
        f"const RESISTOR = {json.dumps(RESISTOR)};\n"
        f"const PADS = {json.dumps(PADS)};\n"
        + textwrap.dedent(body),
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(f"node exited {done.returncode}\n{done.stderr}")
    # node warns about module type on stderr for a file outside any package;
    # the answer is the last line of stdout, so a stray log cannot break it.
    return json.loads(done.stdout.strip().splitlines()[-1])


def bench(wires: str, parts: str = "[LED]", supply: str = "UNO") -> str:
    """The three lines every case below shares."""
    return (f"const report = analyse({{supply: {supply}, pads: PADS, "
            f"parts: {parts}, wires: {wires}}});\n")


def test_an_led_with_one_leg_in_mid_air_does_not_light(tmp_path):
    """**The bug the user reported, in one assertion.**

    Verbatim: *"the led is lighting up even though not grounded"*. Before
    OH-79 `applyState` read the pad the one wire came from and drove the part
    with its logic level, so an LED with its anode on D13 and its cathode
    nowhere lit exactly as brightly as one in a real circuit.

    It is dark now for a reason that can be said out loud, and the reason is
    asserted too: an answer that happened to be dark for the wrong cause would
    pass a check on the colour alone.
    """
    got = run(tmp_path, bench('[{pad: "13", part: 0, terminal: "anode"}]') + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "off"
    assert got["amps"] is None
    assert "mid-air" in got["reason"]
    assert "cathode" in got["reason"]


def test_an_led_wired_to_ground_conducts(tmp_path):
    """The other half of the same report: a complete circuit still carries
    current.

    A fix that made everything dark would satisfy the test above and be worse
    than the bug. **It does not come out `lit`**, and that is not this test's
    subject -- 40 mA through a part whose absolute maximum is 30 destroys it,
    which `test_a_part_past_its_absolute_maximum_is_destroyed` is about. What
    is asserted here is that the circuit closed and current flowed.
    """
    got = run(tmp_path, bench("""[
        {pad: "13", part: 0, terminal: "anode"},
        {pad: "GND", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] != "off"
    assert got["amps"] > 0.02


def test_a_complete_circuit_inside_every_rating_is_simply_lit(tmp_path):
    """And this is the one that shows a working LED, which is the point.

    Two in series on one pin draw 6 mA -- under the part's rating, under the
    board's, under every absolute maximum. No verdict, no warning, just a lit
    LED, which is what the bench is for.
    """
    got = run(tmp_path, """
        const report = analyse({supply: UNO, pads: PADS, parts: [LED, LED], wires: [
          {pad: "13",  part: 0, terminal: "anode"},
          {pad: "j",   part: 0, terminal: "cathode"},
          {pad: "j",   part: 1, terminal: "anode"},
          {pad: "GND", part: 1, terminal: "cathode"},
        ]});
        console.log(JSON.stringify(report.parts));
    """)
    assert [part["drive"] for part in got] == ["lit", "lit"]
    assert [part["destroyed"] for part in got] == [False, False]
    assert [part["warning"] for part in got] == [None, None]


def test_an_led_wired_backwards_does_not_light(tmp_path):
    """A diode conducts one way, and this is the only test of that.

    Cathode on the driven pin, anode on ground. Every *topological* check would
    pass this — two legs, a return path, a driven pin — so it is the case that
    separates a circuit from a connectivity rule, which is the thing the user
    chose over the cheaper fix.
    """
    got = run(tmp_path, bench("""[
        {pad: "13", part: 0, terminal: "cathode"},
        {pad: "GND", part: 0, terminal: "anode"},
    ]""") + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "off"
    assert "reversed" in got["reason"]


def test_a_pin_driven_low_carries_no_current_to_ground(tmp_path):
    """Both ends at zero volts, so nothing flows. Dark for the right reason.

    This is the case that used to be right by accident: `DRIVE` mapped `low` to
    `off`, so the picture agreed with the physics without any physics.
    """
    got = run(tmp_path, bench("""[
        {pad: "12", part: 0, terminal: "anode"},
        {pad: "GND", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "off"
    assert got["reason"] == "no current: nothing is driving it"


def test_a_pin_configured_as_an_input_carries_nothing_away(tmp_path):
    """An input is high impedance and stamps no element at all.

    **Wired from the rail rather than to ground, and that is the whole test.**
    An LED from an input pin to ground is dark whether the pin is high
    impedance or a dead short, so that arrangement cannot tell the two apart --
    checked by mutation on 2026-08-27, where treating `input` as a pin driven
    low passed it. From `5V` through the LED into the pin, a short would light
    it at 5V / (30 + 45) and high impedance leaves it dark.
    """
    got = run(tmp_path, bench("""[
        {pad: "5V", part: 0, terminal: "anode"},
        {pad: "11", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "off"
    assert got["amps"] is None


def test_the_current_is_the_series_circuit_it_claims_to_be(tmp_path):
    """**The arithmetic, against a number worked out by hand.**

    A pin driven high is the rail behind `sourceOhms`; a conducting LED is
    `forwardVolts` behind `seriesOhms`; ground is ground. So

        I = (5.0 - 2.2) / (40 + 30) = 40.000 mA

    and if the solver disagrees with that to nine decimal places it is not
    solving the circuit it says it is. Measured 2026-08-27: 0.04 exactly.
    """
    got = run(tmp_path, bench("""[
        {pad: "13", part: 0, terminal: "anode"},
        {pad: "GND", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify({amps: report.parts[0].amps}));
    """)
    want = (UNO["volts"] - LED["model"]["forwardVolts"]) / (
        UNO["sourceOhms"] + LED["model"]["seriesOhms"])
    assert abs(got["amps"] - want) < 1e-9


def test_a_pin_sinking_from_the_rail_lights_it_too(tmp_path):
    """The other direction: 5V through the LED into a pin driven low.

    A real sketch does this, and it exercises the ideal rail source rather than
    the Thevenin pin — a different path through the stamping code, and one that
    a bench wired only from pins to ground would never reach.

        I = (5.0 - 2.2) / (30 + 45) = 37.333 mA
    """
    got = run(tmp_path, bench("""[
        {pad: "5V", part: 0, terminal: "anode"},
        {pad: "12", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    want = (UNO["volts"] - LED["model"]["forwardVolts"]) / (
        LED["model"]["seriesOhms"] + UNO["sinkOhms"])
    # 37 mA is past this LED's 30 mA absolute maximum too, so the verdict is
    # the same as sourcing. The current is what this test is about.
    assert got["drive"] == "damaged"
    assert abs(got["amps"] - want) < 1e-9


def test_a_diode_below_its_forward_drop_carries_nothing(tmp_path):
    """**A diode is a threshold, not a one-way resistor.**

    Forward biased at one volt against a 2.2 V drop: a real LED passes
    essentially nothing, and the piecewise-linear model has to agree. Asserted
    on `solve` rather than through a bench because no board here has a rail low
    enough to build it -- and it is the case that catches a diode which is
    always conducting.

    Every case reachable from the bench masks that fault: a reversed LED comes
    out with a negative current and reads `off` either way. Found by mutation
    on 2026-08-27, where forcing every diode to conduct killed no test.
    """
    got = run(tmp_path, """
        const under = solve({nodes: 2, elements: [
          {kind: "source", id: "v", a: 1, b: 0, volts: 1.0},
          {kind: "diode",  id: "d", a: 1, b: 0, volts: 2.2, ohms: 30},
        ]});
        const over = solve({nodes: 2, elements: [
          {kind: "source", id: "v", a: 1, b: 0, volts: 5.0},
          {kind: "diode",  id: "d", a: 1, b: 0, volts: 2.2, ohms: 30},
        ]});
        console.log(JSON.stringify({under: under.amps.d, over: over.amps.d,
                                    ok: under.ok && over.ok}));
    """)
    assert got["ok"] is True
    # A nanoamp, which is `OFF_OHMS` and not a conducting diode.
    assert 0 < got["under"] < 1e-6
    # And the same diode over its knee carries what the arithmetic says.
    assert abs(got["over"] - (5.0 - 2.2) / 30) < 1e-9


def test_current_is_conserved_at_every_node(tmp_path):
    """**Kirchhoff, over a netlist assembled by hand.**

    The one property that is true of any correct solution to any circuit, and
    it does not depend on a single number in this repository. If the matrix is
    stamped wrongly — a sign flipped, a source's column in the wrong place —
    current appears from nowhere at some node, and nothing else here would
    notice.

    Measured 2026-08-27: worst residual 3.5e-18 A across six nodes.
    """
    got = run(tmp_path, """
        // 5V -> R1 -> node2 -> diode -> node3 -> R2 -> ground, and a second
        // resistor from node2 to ground so a node has three branches on it.
        const net = {nodes: 4, elements: [
          {kind: "source",   id: "rail", a: 1, b: 0, volts: 5},
          {kind: "resistor", id: "r1",   a: 1, b: 2, ohms: 100},
          {kind: "resistor", id: "r3",   a: 2, b: 0, ohms: 470},
          {kind: "diode",    id: "d1",   a: 2, b: 3, volts: 2.2, ohms: 30},
          {kind: "resistor", id: "r2",   a: 3, b: 0, ohms: 220},
        ]};
        const got = solve(net);
        const sum = new Array(net.nodes).fill(0);
        for (const e of net.elements) { sum[e.a] += got.amps[e.id]; sum[e.b] -= got.amps[e.id]; }
        // Ground is where everything returns to, so its own sum is the negative
        // of all the others and is not an independent check.
        console.log(JSON.stringify({ok: got.ok, worst: Math.max(...sum.slice(1).map(Math.abs)),
                                    conducting: got.amps.d1 > 1e-6}));
    """)
    assert got["ok"] is True
    assert got["conducting"] is True
    assert got["worst"] < 1e-9


def test_two_leds_in_series_carry_one_current(tmp_path):
    """Series is series, and it needs the diode iteration to get there.

    Both start off, so the first pass says the chain is open; the second turns
    them on together. Two forward drops fit under five volts, so it conducts:

        I = (5.0 - 2.2 - 2.2) / (40 + 30 + 30) = 6.000 mA

    which is also the case that shows why the current is a *lower* bound worth
    having: six milliamps lights an LED and is under every rating on the board.
    """
    got = run(tmp_path, bench("""[
        {pad: "13", part: 0, terminal: "anode"},
        {pad: "GND", part: 1, terminal: "cathode"},
    ]""", parts="[LED, LED]") + """
        // The join between the two, made by a wire that touches no pad: the
        // bench cannot build this today and the solver must not care.
        const net = analyse({supply: UNO, pads: PADS, parts: [LED, LED], wires: [
          {pad: "13",  part: 0, terminal: "anode"},
          {pad: "j",   part: 0, terminal: "cathode"},
          {pad: "j",   part: 1, terminal: "anode"},
          {pad: "GND", part: 1, terminal: "cathode"},
        ]});
        console.log(JSON.stringify(net.parts.map((p) => ({drive: p.drive, amps: p.amps}))));
    """)
    first, second = got
    want = (UNO["volts"] - 2 * LED["model"]["forwardVolts"]) / (
        UNO["sourceOhms"] + 2 * LED["model"]["seriesOhms"])
    assert first["drive"] == "lit" and second["drive"] == "lit"
    assert abs(first["amps"] - want) < 1e-9
    # **Not equal, and the residue is worth naming**: measured 2.4e-12 A, which
    # is `GMIN` leaking the node between them to ground. A picoamp of leakage
    # is what that conductance is, and a test demanding bit-equality here would
    # be demanding the solver pretend it is not there.


def test_two_leds_in_parallel_each_carry_less_than_one_alone(tmp_path):
    """A pin's output resistance is shared, so a second LED dims the first.

    **An inequality rather than a number**, because it is true of any correct
    solution and would survive a change to every parameter in the file. It is
    also the property that a per-wire model cannot have at all: two independent
    lookups of one pad's level give both LEDs the same brightness for ever.
    """
    got = run(tmp_path, """
        const one = analyse({supply: UNO, pads: PADS, parts: [LED], wires: [
          {pad: "13", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
        ]});
        const two = analyse({supply: UNO, pads: PADS, parts: [LED, LED], wires: [
          {pad: "13", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
          {pad: "13", part: 1, terminal: "anode"},
          {pad: "GND", part: 1, terminal: "cathode"},
        ]});
        console.log(JSON.stringify({
          alone: one.parts[0].amps,
          each: two.parts.map((p) => p.amps),
          lit: two.parts.every((p) => p.drive === "lit"),
        }));
    """)
    assert got["lit"] is True
    assert got["each"][0] < got["alone"]
    assert abs(got["each"][0] - got["each"][1]) < 1e-12
    # And the pin's total is more than one LED drew but less than twice it,
    # which is what sharing a source resistance means.
    assert got["alone"] < sum(got["each"]) < 2 * got["alone"]


def test_the_three_ground_pads_are_one_net(tmp_path):
    """An Uno has three pads labelled `GND` and one ground.

    `webui/api.py` sends a pad's label as its name, so all three arrive as the
    string `GND` — and `view.pads` in `board3d.js` is keyed by that name, so
    they were already one entry there. This asserts the circuit agrees: an LED
    returned to any of them is returned to the same node the others are.
    """
    got = run(tmp_path, """
        const pads = [{name: "13", state: "high"},
                      {name: "GND", state: "unknown"},
                      {name: "GND", state: "unknown"},
                      {name: "GND", state: "unknown"}];
        const report = analyse({supply: UNO, pads, parts: [LED], wires: [
          {pad: "13", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
        ]});
        console.log(JSON.stringify(report.parts[0]));
    """)
    # It conducts, which is the whole question here: an LED returned to the
    # wrong one of three GND pads would have found no path at all.
    assert got["drive"] != "off"
    assert got["amps"] > 0.02


def test_a_pad_this_repository_cannot_answer_for_stays_unanswerable(tmp_path):
    """`unknown` is a claim about this repository and it propagates.

    `webui/api.py`'s `PIN_STATES` keeps `unknown` separate from `low` precisely
    so a pad nobody models is not drawn as a pad driven off. A part reaching
    one inherits that, and does not become an LED that is merely dark.
    """
    got = run(tmp_path, bench("""[
        {pad: "A0", part: 0, terminal: "anode"},
        {pad: "GND", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "unanswerable"
    assert "cannot answer for" in got["reason"]


def test_a_rail_the_board_does_not_name_drives_nothing(tmp_path):
    """`VIN` is whatever somebody plugged in, and this simulation has no jack.

    It is a pad, it is not in `RAILS`, and its state is `unknown` — so a part
    wired to it is unanswerable rather than lit off a number invented here.
    """
    got = run(tmp_path, bench("""[
        {pad: "VIN", part: 0, terminal: "anode"},
        {pad: "GND", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify({part: report.parts[0], rails: Object.keys(RAILS)}));
    """)
    assert got["part"]["drive"] == "unanswerable"
    assert "VIN" not in got["rails"]
    assert "VBUS" not in got["rails"]
    for named in ("GND", "5V", "3V3"):
        assert named in got["rails"]


def test_a_board_with_no_supply_model_computes_nothing(tmp_path):
    """Nine of the ten boards with a 3D model publish no `SUPPLY`.

    They get no circuit and say so, which is the same honest degradation the
    panel's three model captions make. **Not `off`**: a part that would light
    on a real board is not a part that is dark.
    """
    got = run(tmp_path, bench("""[
        {pad: "13", part: 0, terminal: "anode"},
        {pad: "GND", part: 0, terminal: "cathode"},
    ]""", supply="null") + """
        console.log(JSON.stringify({part: report.parts[0], note: report.note}));
    """)
    assert got["part"]["drive"] == "unanswerable"
    assert got["part"]["amps"] is None
    assert "no supply" in got["part"]["reason"]
    assert got["note"]


def test_a_part_with_no_electrical_model_suppresses_every_current(tmp_path):
    """The buzzer, and why it takes the LED's number with it.

    `tools/import_3d_model.py` publishes no `Electrical` for a 12 mm buzzer
    because a generic mesh does not say whether it drew a magnetic coil or a
    piezo element, and those differ by three orders of magnitude. So it is a
    conductor of unknown value — and a value nobody can state, standing in a
    circuit, decides the current through everything else in it. Reporting the
    LED's amps beside it would be reporting `ASSUMED_OHMS`.
    """
    got = run(tmp_path, """
        const buzzer = {label: "12 mm buzzer",
                        terminals: ["negative", "positive"], model: null};
        const report = analyse({supply: UNO, pads: PADS, parts: [LED, buzzer], wires: [
          {pad: "13", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
          {pad: "13", part: 1, terminal: "positive"},
          {pad: "GND", part: 1, terminal: "negative"},
        ]});
        console.log(JSON.stringify({parts: report.parts, note: report.note,
                                    assumed: ASSUMED_OHMS}));
    """)
    led, buzzer = got["parts"]
    assert led["drive"] == "lit"
    assert led["amps"] is None
    assert buzzer["drive"] == "lit"
    assert buzzer["amps"] is None
    assert "no electrical model" in got["note"]


def test_an_unmodelled_part_still_needs_a_complete_circuit(tmp_path):
    """It has no numbers and it is still not exempt from the rule.

    A buzzer with one leg on a pin and one in mid-air was the same lie as the
    LED, and a part with no datasheet is the case most likely to be given a
    pass by accident.
    """
    got = run(tmp_path, """
        const buzzer = {label: "12 mm buzzer",
                        terminals: ["negative", "positive"], model: null};
        const report = analyse({supply: UNO, pads: PADS, parts: [buzzer], wires: [
          {pad: "13", part: 0, terminal: "positive"},
        ]});
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "off"
    assert "mid-air" in got["reason"]


def test_shorting_a_supply_to_ground_is_refused_rather_than_solved(tmp_path):
    """Two wires build it, and no solution of it exists to report.

    An ideal five-volt source across an ideal ground is a contradiction, not a
    large current: the matrix is singular and any number printed from it would
    be an artefact. Named before the solve rather than discovered inside it, so
    the sentence says what a reader did rather than "could not be solved".
    """
    got = run(tmp_path, """
        const report = analyse({supply: UNO, pads: PADS, parts: [LED], wires: [
          {pad: "5V", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "anode"},
        ]});
        console.log(JSON.stringify({ok: report.ok, note: report.note,
                                    part: report.parts[0]}));
    """)
    assert got["ok"] is False
    assert "short circuit" in got["note"]
    assert got["part"]["drive"] != "lit"


def test_a_part_over_its_rating_and_inside_its_absolute_maximum_is_warned(tmp_path):
    """**Warned, and not condemned.** The two limits are different claims.

    Two LEDs in parallel across one pin draw 25 mA each: past the 20 mA a 5 mm
    indicator is sold against, and short of the 30 mA absolute maximum. So they
    are lit with a sentence, not destroyed, which is what the datasheet
    supports and is the distinction the whole of `damaged` rests on.

    Only in that direction: every resistance behind the current is a
    datasheet's worst corner, so it is a lower bound. Over a rating is a fact,
    under one is not a clean bill of health.
    """
    got = run(tmp_path, """
        const report = analyse({supply: UNO, pads: PADS, parts: [LED, LED], wires: [
          {pad: "13", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
          {pad: "13", part: 1, terminal: "anode"},
          {pad: "GND", part: 1, terminal: "cathode"},
        ]});
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "lit"
    assert got["destroyed"] is False
    assert "past the 20 mA this part is rated for" in got["warning"]
    assert "limiting" in got["warning"]


def test_the_warning_measures_a_pin_by_the_pins_own_current(tmp_path):
    """**A pin carries what everything on it draws, not what one part draws.**

    Two LEDs across pad 13 take 25 mA each and the pad delivers 51 mA. A
    warning that compared one part's 25 mA against the pin's ratings would say
    the pin was inside its absolute maximum when it is past it by a quarter.
    Found while writing the test above, by no assertion that existed.

    The two sentences are separate because the two objects are: the part is
    inside its own absolute maximum here and the pin driving it is not.
    """
    got = run(tmp_path, """
        const report = analyse({supply: UNO, pads: PADS, parts: [LED, LED], wires: [
          {pad: "13", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
          {pad: "13", part: 1, terminal: "anode"},
          {pad: "GND", part: 1, terminal: "cathode"},
        ]});
        console.log(JSON.stringify({one: report.parts[0].amps,
                                    warning: report.parts[0].warning}));
    """)
    assert got["one"] < UNO["absoluteAmps"]
    assert "Pin 13 carries at least 51 mA" in got["warning"]
    assert "40 mA absolute maximum" in got["warning"]


def test_a_current_inside_every_rating_raises_nothing(tmp_path):
    """The negative control, and it is the reason the test above means anything.

    A warning that fired on every circuit would pass that test while saying
    nothing. Two LEDs in series on the same pin draw six milliamps, under both
    of the Uno's ratings, and nothing is said — which is not the same as saying
    it is safe, and the file's header is careful about the difference.
    """
    got = run(tmp_path, """
        const report = analyse({supply: UNO, pads: PADS, parts: [LED, LED], wires: [
          {pad: "13",  part: 0, terminal: "anode"},
          {pad: "j",   part: 0, terminal: "cathode"},
          {pad: "j",   part: 1, terminal: "anode"},
          {pad: "GND", part: 1, terminal: "cathode"},
        ]});
        console.log(JSON.stringify(report.parts.map((p) => p.warning)));
    """)
    assert got == [None, None]


def test_a_weaker_pin_drives_less_current(tmp_path):
    """The XIAO SAMD21 against the Uno, and the numbers say what the parts are.

    A SAM D21 pin at its reset drive strength is specified to source two
    milliamps; an ATmega328P pin twenty. So the same LED on the same wires is
    an order of magnitude dimmer, and it is still lit — which is why the
    threshold is a visibility threshold and not a rating.
    """
    got = run(tmp_path, """
        const xiao = {chip: "SAMD21", volts: 3.3, sourceOhms: 330.0,
                      sinkOhms: 264.0, ratedAmps: 0.002, absoluteAmps: null};
        const pads = [{name: "D10", state: "high"}, {name: "GND", state: "unknown"}];
        const wires = [{pad: "D10", part: 0, terminal: "anode"},
                       {pad: "GND", part: 0, terminal: "cathode"}];
        const weak = analyse({supply: xiao, pads, parts: [LED], wires});
        const strong = analyse({supply: UNO, pads: PADS, parts: [LED], wires: [
          {pad: "13", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
        ]});
        console.log(JSON.stringify({weak: weak.parts[0], strong: strong.parts[0].amps,
                                    lit: LIT_AMPS}));
    """)
    want = (3.3 - LED["model"]["forwardVolts"]) / (330.0 + LED["model"]["seriesOhms"])
    assert got["weak"]["drive"] == "lit"
    assert abs(got["weak"]["amps"] - want) < 1e-9
    assert got["weak"]["amps"] < got["strong"] / 10
    assert got["weak"]["amps"] > got["lit"]
    # A board with no per-pin absolute maximum still warns on the one it has.
    assert "2.0 mA" in got["weak"]["warning"]
    assert "absolute maximum" not in got["weak"]["warning"]


def test_the_answer_does_not_depend_on_the_order_the_wires_were_made(tmp_path):
    """**Determinism, and it is not free.**

    The netlist is built by union-find over wires and the diode states are
    iterated from a starting guess; both are places where the order parts
    arrived on the bench could leak into the answer. `rules/determinism.md`
    forbids exactly that, and a picture that differed depending on which leg a
    reader wired first would be the least debuggable kind of wrong.

    All twenty-four orderings of four wires across two LEDs, one answer.
    """
    got = run(tmp_path, """
        const wires = [
          {pad: "13",  part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
          {pad: "5V",  part: 1, terminal: "anode"},
          {pad: "12",  part: 1, terminal: "cathode"},
        ];
        const permute = (rest) => rest.length <= 1 ? [rest]
          : rest.flatMap((head, at) => permute(rest.filter((_, k) => k !== at))
                                        .map((tail) => [head, ...tail]));
        const seen = new Set();
        for (const order of permute(wires)) {
          const report = analyse({supply: UNO, pads: PADS, parts: [LED, LED], wires: order});
          seen.add(JSON.stringify(report.parts));
        }
        console.log(JSON.stringify({orders: permute(wires).length, answers: seen.size,
                                    one: JSON.parse([...seen][0])}));
    """)
    assert got["orders"] == 24
    assert got["answers"] == 1
    # Both are past their absolute maximum on these wires, and the point is
    # that all twenty-four orderings agree rather than which word it is.
    assert [part["drive"] for part in got["one"]] == ["damaged", "damaged"]


def test_a_bench_with_nothing_on_it_is_not_an_error(tmp_path):
    """No parts, no wires, no supply. Every one of those is a normal state.

    `board3d.js` solves on every state poll, so this runs many times a second
    on a page nobody has dropped a part onto yet.
    """
    got = run(tmp_path, """
        const empty = analyse({supply: null, pads: [], parts: [], wires: []});
        const parts = analyse({supply: UNO, pads: PADS, parts: [LED], wires: []});
        console.log(JSON.stringify({empty, parts}));
    """)
    assert got["empty"]["ok"] is True
    assert got["empty"]["parts"] == []
    assert got["parts"]["parts"][0]["drive"] == "unanswerable"
    assert got["parts"]["parts"][0]["reason"] == "not wired to anything"


def test_the_solver_reports_rather_than_guesses_when_it_cannot_settle(tmp_path):
    """A netlist with no solvable form must come back `ok: false`.

    Two nodes with nothing joining them to ground but `GMIN` still solve, so
    the singular case has to be built deliberately: two ideal sources of
    different voltage across the same pair of nodes is a contradiction with no
    node voltage in it.
    """
    got = run(tmp_path, """
        const clash = solve({nodes: 2, elements: [
          {kind: "source", id: "a", a: 1, b: 0, volts: 5},
          {kind: "source", id: "b", a: 1, b: 0, volts: 3},
        ]});
        const floating = solve({nodes: 3, elements: [
          {kind: "resistor", id: "r", a: 1, b: 2, ohms: 100},
        ]});
        console.log(JSON.stringify({clash: clash.ok, floating: floating.ok,
                                    gmin: GMIN, off: OFF_OHMS, passes: MAX_PASSES}));
    """)
    assert got["clash"] is False
    # An island is solvable and its answer is zero volts everywhere, which is
    # what `GMIN` is for: the part with one leg in mid-air is exactly this.
    assert got["floating"] is True
    assert got["gmin"] < 1e-9
    assert got["off"] > 1e6


def test_the_bench_uses_the_boards_own_published_supply(tmp_path):
    """The numbers in this file are the board module's, or this fails.

    `UNO` above is a copy, kept so a failing assertion says which side moved.
    `webui/boards/atmega328p.py` is the source, and `webui/api.py` sends it to
    the page — so if the two disagree, the tests above are checking a circuit
    the browser never builds.
    """
    from webui.boards import atmega328p, samd21
    for module, want in ((atmega328p, UNO), (samd21, None)):
        supply = module.SUPPLY
        # Every value carries its provenance, the rule `Electrical` and `SPECS`
        # both keep: a number without one is the defect this area re-learns.
        for name in ("volts", "source_ohms", "sink_ohms", "rated_amps",
                     "absolute_amps"):
            assert name in supply, f"{module.__name__} publishes no {name}"
            assert supply["cited"].get(name), f"{module.__name__}: {name} uncited"
        if want is None:
            continue
        assert supply["volts"] == want["volts"]
        assert supply["source_ohms"] == want["sourceOhms"]
        assert supply["sink_ohms"] == want["sinkOhms"]
        assert supply["rated_amps"] == want["ratedAmps"]
        assert supply["absolute_amps"] == want["absoluteAmps"]


def test_the_led_the_page_loads_carries_the_parameters_the_tests_use():
    """`LED` above is `tools/import_3d_model.py`'s, or this fails.

    The same join as the test above, on the other side of the circuit. A part
    whose GLB said 1.8 V while this file assumed 2.2 would make every current
    here fiction.
    """
    from tools.import_3d_model import LED_ELECTRICAL, PARTS
    assert LED_ELECTRICAL.kind == LED["model"]["kind"]
    assert list(LED_ELECTRICAL.forward) == [LED["model"]["from"], LED["model"]["to"]]
    # **Every published number, not a chosen few.** The first version checked
    # two of them by name; `absolute_amps` was then added to the part and none
    # of the twenty-odd tests here noticed they were exercising an LED the page
    # no longer loads. A check made insensitive to a difference cannot report
    # it, and the difference here is "a parameter appeared".
    for name, (value, _why) in LED_ELECTRICAL.cited.items():
        assert name in JS_NAME, f"{name} has no spelling on the JavaScript side"
        assert LED["model"][JS_NAME[name]] == value, name
    # And every part in the catalogue publishes a model except the buzzer,
    # which deliberately does not -- see its comment, and
    # `test_a_part_with_no_electrical_model_suppresses_every_current`. Stated
    # as "the buzzer and nothing else" rather than "the LEDs and nothing else",
    # which is what it said until a resistor joined them: the rule was never
    # about the word LED, it is that a part whose behaviour cannot be stated
    # gets no model, and exactly one part is in that position.
    silent = {part.name for part in PARTS if part.electrical is None}
    assert silent == {"Buzzer_12x9.5RM7.6"}, silent
    for part in PARTS:
        if part.electrical is None:
            continue
        for name, (_value, why) in part.electrical.cited.items():
            assert name in JS_NAME, f"{part.name}: {name} has no JavaScript spelling"
            assert len(why) > 40, f"{part.name}: {name} has no real citation"


# --- a part past its absolute maximum ---------------------------------------


def test_a_part_past_its_absolute_maximum_is_destroyed_not_lit(tmp_path):
    """**The user's second report, and it is the picture disagreeing with the
    words.**

    Verbatim: *"you should calculate the current that's flowing through and put
    a broken indicator for the broken item according to the datasheet."* The
    current was already calculated and the part was still drawn glowing beside
    a paragraph saying it would be destroyed. When a picture and a caption
    disagree the picture wins, which is the same defect as the ungrounded LED
    in a smaller window.

    40.0 mA against a 30 mA absolute maximum, and the sentence names both.
    """
    got = run(tmp_path, bench("""[
        {pad: "13", part: 0, terminal: "anode"},
        {pad: "GND", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "damaged"
    assert got["destroyed"] is True
    assert "Destroyed" in got["reason"]
    assert "30 mA" in got["reason"]
    assert "40 mA" in got["reason"]
    # One sentence, not the same fact twice: the verdict replaces the warning.
    assert got["warning"] is None


def test_only_an_absolute_maximum_can_declare_a_part_destroyed(tmp_path):
    """A rated current is what a part is sold against; it is not destruction.

    A part that publishes no absolute maximum can be warned about and can never
    be condemned here, however much current it carries. The claim is that a
    physical object is ruined, and the only number that supports it is the one
    whose datasheet says so.
    """
    got = run(tmp_path, """
        const bare = JSON.parse(JSON.stringify(LED));
        delete bare.model.absoluteAmps;
        const report = analyse({supply: UNO, pads: PADS, parts: [bare], wires: [
          {pad: "13", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
        ]});
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "lit"
    assert got["destroyed"] is False
    assert "past the 20 mA this part is rated for" in got["warning"]


def test_a_destroyed_part_stays_destroyed_when_the_pin_goes_low(tmp_path):
    """**The latch, and without it the indicator would be a flicker.**

    A blink drives pin 13 high and then low. A verdict recomputed from the
    circuit alone would show a destroyed LED as merely dark half a second
    later, which is the same lie in a smaller window -- and it is what an
    absolute maximum MEANS: past it is not reversible.

    The caller carries the latch, so this asserts the contract rather than a
    clock: a bench whose part arrives `destroyed` stays destroyed on a pin that
    is driven low, and its current is not reported, because what a burnt LED
    does electrically is not something this can say.
    """
    got = run(tmp_path, """
        const dead = {...LED, destroyed: true};
        const quiet = [{name: "13", state: "low"}, {name: "GND", state: "unknown"}];
        const report = analyse({supply: UNO, pads: quiet, parts: [dead], wires: [
          {pad: "13", part: 0, terminal: "anode"},
          {pad: "GND", part: 0, terminal: "cathode"},
        ]});
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "damaged"
    assert got["destroyed"] is True
    assert got["amps"] is None
    assert "destroyed earlier" in got["reason"]
    assert "not modelled" in got["reason"]


def test_a_destroyed_part_is_not_revived_by_unwiring_it(tmp_path):
    """Taking the wires off a burnt LED does not unburn it.

    `disconnect` re-solves, and every other part goes back to being one nothing
    can be said about. This one does not, and the only thing that clears it is
    taking it off the bench -- which is what a person does with a burnt LED.
    """
    got = run(tmp_path, """
        const dead = {...LED, destroyed: true};
        const report = analyse({supply: UNO, pads: PADS, parts: [dead], wires: []});
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "damaged"
    assert got["destroyed"] is True


def test_three_parts_inside_their_ratings_can_still_overload_the_pin(tmp_path):
    """**The case that separates the two objects completely.**

    Three LEDs across one pad draw 18.7 mA each -- under the 20 mA a 5 mm
    indicator is sold against, under its 30 mA absolute maximum, so not one of
    them is warned about and not one is destroyed. The pad delivers 56 mA,
    past everything the ATmega328P publishes.

    So the whole warning is about the pin, and it is the case that catches a
    version of `warn` measuring the pin's ratings against a part's current:
    18.7 mA is inside both of them and the sentence would lose half its
    clauses. Found by mutation on 2026-08-27, when the two-LED case turned out
    to fire the same clause either way.
    """
    got = run(tmp_path, """
        const parts = [LED, LED, LED];
        const wires = parts.flatMap((_, at) => [
          {pad: "13", part: at, terminal: "anode"},
          {pad: "GND", part: at, terminal: "cathode"},
        ]);
        const report = analyse({supply: UNO, pads: PADS, parts, wires});
        console.log(JSON.stringify(report.parts));
    """)
    assert [part["drive"] for part in got] == ["lit", "lit", "lit"]
    assert [part["destroyed"] for part in got] == [False, False, False]
    for part in got:
        # Every one of them is inside its own rating, so nothing is said about
        # the parts at all -- the whole sentence is the pin's.
        assert part["amps"] < LED["model"]["ratedAmps"]
        assert "this part is rated for" not in part["warning"]
        assert "past the 20 mA this board rates a pin for" in part["warning"]
        assert "40 mA absolute maximum" in part["warning"]


# --- a resistor, so the warning can be made to stop -------------------------


def test_a_resistor_makes_an_led_on_an_uno_a_circuit_that_warns_about_nothing(tmp_path):
    """**OH-80's done-when, and it is the first quiet circuit this bench has.**

    Before this part existed there was no way to light an LED on an Arduino Uno
    without destroying it. An LED straight across a pin carries at least 40 mA
    against the 20 mA the board rates a pin for and the 30 mA the LED's own
    absolute maximum allows, so `circuit.js` correctly reported a ruined part —
    and every LED circuit a reader could build was one the page warned about.
    Two LEDs in series at 6 mA was the only intact circuit available, which is
    the physically right answer and a bench nobody can demonstrate.

    D13 → resistor → LED → GND is 2.8 V across 40 + 231 + 30 Ω, which is
    9.3 mA: inside the pin's rating, inside the LED's, inside both absolute
    maximums. **Nothing is said, and that is not the same as saying it is
    safe** — the file's header is careful about the difference, and 9.3 mA is
    still a lower bound.
    """
    got = run(tmp_path, """
        const report = analyse({supply: UNO, pads: PADS,
                                parts: [RESISTOR, LED], wires: [
          {pad: "13",  part: 0, terminal: "lead A"},
          {pad: "j",   part: 0, terminal: "lead B"},
          {pad: "j",   part: 1, terminal: "anode"},
          {pad: "GND", part: 1, terminal: "cathode"},
        ]});
        console.log(JSON.stringify({parts: report.parts, note: report.note}));
    """)
    resistor, led = got["parts"]
    assert led["drive"] == "lit"
    assert [resistor["warning"], led["warning"]] == [None, None]
    assert [resistor["destroyed"], led["destroyed"]] == [False, False]
    assert got["note"] is None
    # 2.8 / 301, and both parts carry it because they are in series.
    for part in (resistor, led):
        assert part["amps"] == pytest.approx(2.8 / 301, rel=1e-9)
        assert "at least 9.3 mA" in part["reason"]
    # And it is under every number either the board or the part publishes.
    assert led["amps"] < UNO["ratedAmps"] and led["amps"] < UNO["absoluteAmps"]
    assert led["amps"] < LED["model"]["ratedAmps"]
    assert led["amps"] < LED["model"]["absoluteAmps"]


def test_a_resistor_does_not_suppress_the_current_through_the_led_beside_it(tmp_path):
    """**The fault the netlist branch was one line away from having.**

    `analyse` counted every non-diode part as `assumed` — a conductor of
    unknown value, which suppresses the reported current through *everything*
    on the bench, because a stand-in resistance decides them all. That branch
    was written when no part had a stated resistance, and the first one added
    would have turned every LED beside it into a part with no number.

    A current-limiting resistor whose presence deletes the current it limits is
    the opposite of the thing. The buzzer is still `assumed` and still does
    exactly that, which is what makes this test about the distinction rather
    than about the flag: the same bench, one part swapped.
    """
    got = run(tmp_path, """
        const buzzer = {label: "12 mm buzzer",
                        terminals: ["negative", "positive"], model: null};
        const wires = [
          {pad: "13",  part: 0, terminal: "lead A"},
          {pad: "j",   part: 0, terminal: "lead B"},
          {pad: "j",   part: 1, terminal: "anode"},
          {pad: "GND", part: 1, terminal: "cathode"},
        ];
        const withR = analyse({supply: UNO, pads: PADS,
                               parts: [RESISTOR, LED], wires});
        const swapped = wires.map((w) => (w.part === 0
          ? {...w, terminal: w.terminal === "lead A" ? "positive" : "negative"}
          : w));
        const withB = analyse({supply: UNO, pads: PADS,
                               parts: [buzzer, LED], wires: swapped});
        console.log(JSON.stringify({resistor: withR.parts, buzzer: withB.parts,
                                    noteR: withR.note, noteB: withB.note}));
    """)
    assert got["resistor"][1]["amps"] is not None
    assert got["noteR"] is None
    # The unmodelled part still takes the LED's number with it, unchanged.
    assert got["buzzer"][1]["amps"] is None
    assert "no electrical model" in got["noteB"]


def test_a_resistor_conducts_whichever_way_round_it_is_wired(tmp_path):
    """**It has no forward direction, so it cannot be wired backwards.**

    An LED wired the wrong way round is off and the page says `reversed`. A
    resistor turned end for end is the same circuit, and this is the case that
    catches a version reporting a diode's *signed* current for it: the two
    wirings differ only in the sign, so one of them would come out negative,
    below `LIT_AMPS`, and be reported as a part carrying nothing.

    `tools/import_3d_model.py` publishes no `forward` for it for the same
    reason — naming one lead as the one current enters by would state a
    polarity the part does not have.
    """
    got = run(tmp_path, """
        const one = [
          {pad: "13",  part: 0, terminal: "lead A"},
          {pad: "GND", part: 0, terminal: "lead B"},
        ];
        const other = one.map((w) => ({...w,
          terminal: w.terminal === "lead A" ? "lead B" : "lead A"}));
        const answer = (wires) => analyse({supply: UNO, pads: PADS,
                                           parts: [RESISTOR], wires}).parts[0];
        console.log(JSON.stringify([answer(one), answer(other)]));
    """)
    forwards, backwards = got
    assert forwards["drive"] == backwards["drive"] == "lit"
    assert forwards["amps"] == pytest.approx(backwards["amps"], rel=1e-12)
    assert forwards["amps"] == pytest.approx(5.0 / 271, rel=1e-9)
    for part in got:
        assert "reversed" not in part["reason"]
        assert "at least 18 mA" in part["reason"]


def test_a_resistor_at_rest_says_why_in_its_own_words_and_not_the_diodes(tmp_path):
    """Off, and for the reason that is true of a resistor rather than a diode.

    A pin driven low and a ground pad are one net at zero volts, so a resistor
    across them carries nothing — and the reason is that its two leads are at
    one potential, which is a solved fact. A diode carrying nothing may instead
    be reversed, or below its forward drop, so its sentence is the weaker "no
    current: nothing is driving it".

    **The two sentences are compared here rather than each checked alone**, and
    that is the whole point of the test. Deleting the resistor's branch leaves
    it falling through to the diode's, which reads `model.from` — undefined for
    a part with no forward direction — subtracts two `undefined`s into `NaN`,
    finds `NaN < 0` false and prints the *other* sentence, looking correct. The
    two answers being different is the only observable that separates them.
    """
    got = run(tmp_path, """
        const at = (parts, wires) => analyse({supply: UNO, pads: PADS,
                                              parts, wires}).parts[0];
        console.log(JSON.stringify({
          resistor: at([RESISTOR], [
            {pad: "12",  part: 0, terminal: "lead A"},
            {pad: "GND", part: 0, terminal: "lead B"},
          ]),
          diode: at([LED], [
            {pad: "12",  part: 0, terminal: "anode"},
            {pad: "GND", part: 0, terminal: "cathode"},
          ]),
        }));
    """)
    assert got["resistor"]["drive"] == got["diode"]["drive"] == "off"
    assert got["resistor"]["reason"] == (
        "no current: both its leads are at the same voltage")
    assert got["diode"]["reason"] == "no current: nothing is driving it"
    assert got["resistor"]["reason"] != got["diode"]["reason"]
    assert "NaN" not in got["resistor"]["reason"]


def test_resistors_inside_their_own_ratings_still_overload_the_pin(tmp_path):
    """The pin sentence is not the diode's either, and a resistor reaches it.

    Three 220 Ω resistors across one pad are 77 Ω in parallel, so the pad
    delivers 5 / (40 + 77) = 42.7 mA — past the ATmega328P's 40 mA absolute
    maximum — while each part carries 14 mA and publishes no limit of its own
    to exceed. So the whole warning is the pin's, on a part that can never be
    declared destroyed, which is the combination `warn` has to keep separate.
    """
    got = run(tmp_path, """
        const parts = [RESISTOR, RESISTOR, RESISTOR];
        const wires = parts.flatMap((_, at) => [
          {pad: "13",  part: at, terminal: "lead A"},
          {pad: "GND", part: at, terminal: "lead B"},
        ]);
        console.log(JSON.stringify(
          analyse({supply: UNO, pads: PADS, parts, wires}).parts));
    """)
    assert [part["destroyed"] for part in got] == [False, False, False]
    for part in got:
        assert part["amps"] == pytest.approx(5.0 / (40 + 231 / 3) / 3, rel=1e-9)
        assert "this part is rated for" not in part["warning"]
        assert "Pin 13 carries at least 43 mA" in part["warning"]
        assert "40 mA absolute maximum" in part["warning"]


def test_a_resistor_publishes_no_limit_because_none_is_reachable(tmp_path):
    """**A measured absence, not a missing number**, and this is the measurement.

    A resistor's limit is power rather than current, and `circuit.js` models no
    power at all. `RESISTOR_ELECTRICAL` states that adding one would be a limit
    no circuit on this bench can approach: 5 V is the largest any rail offers,
    so the worst case is the part straight across the supply.

    That claim is checked here rather than asserted in a comment. 5 / 231 is
    21.6 mA, and 21.6 mA through 231 Ω is 108 mW against the 250 mW the
    smallest part sold in a 6.3 × 2.5 mm body is rated for.
    """
    from tools.import_3d_model import RESISTOR_ELECTRICAL

    assert set(RESISTOR_ELECTRICAL.cited) == {"ohms"}
    assert RESISTOR_ELECTRICAL.forward is None

    got = run(tmp_path, """
        const report = analyse({supply: UNO, pads: PADS,
                                parts: [RESISTOR], wires: [
          {pad: "5V",  part: 0, terminal: "lead A"},
          {pad: "GND", part: 0, terminal: "lead B"},
        ]});
        console.log(JSON.stringify(report.parts[0]));
    """)
    ohms = RESISTOR["model"]["ohms"]
    assert got["amps"] == pytest.approx(5.0 / ohms, rel=1e-9)
    assert got["destroyed"] is False and got["warning"] is None
    watts = got["amps"] ** 2 * ohms
    assert watts == pytest.approx(0.108, abs=0.001)
    assert watts < 0.25


def test_the_resistor_the_page_loads_carries_the_value_the_tests_use():
    """`RESISTOR` above is `tools/import_3d_model.py`'s, or this fails.

    The same join `test_the_led_the_page_loads_carries_the_parameters_the_tests_use`
    makes for the LED. **231 rather than 220 is the whole point of checking
    it**: a later edit "correcting" the constant to its nominal value would
    make every current on a bench with a resistor on it larger than the page
    reports, and the one thing this file guarantees is that they are smaller.
    """
    from tools.import_3d_model import PARTS, RESISTOR_ELECTRICAL

    assert RESISTOR_ELECTRICAL.kind == RESISTOR["model"]["kind"]
    for name, (value, _why) in RESISTOR_ELECTRICAL.cited.items():
        assert name in JS_NAME, f"{name} has no spelling on the JavaScript side"
        assert RESISTOR["model"][JS_NAME[name]] == value, name
    part = next(p for p in PARTS if p.electrical is RESISTOR_ELECTRICAL)
    assert part.label == RESISTOR["label"]
    assert list(part.terminals) == RESISTOR["terminals"]
    # The one part on the bench that shows nothing, and it names no lens.
    assert part.lens is None
    assert [p.name for p in PARTS if p.lens is None] == [part.name]

def test_a_resistor_on_the_weakest_pin_is_still_well_clear_of_the_threshold(tmp_path):
    """**The paragraph over `LIT_AMPS`, as two numbers rather than a claim.**

    That comment used to say no circuit this bench could build landed anywhere
    near the visibility threshold, *because there was no resistor to build a dim
    one with*. Adding one made the sentence load-bearing instead of idle, so it
    is measured here.

    The dimmest ordinary circuit is this: the weakest pin in the catalogue — a
    SAM D21 at its reset drive strength, specified to source 2 mA — with a
    220 Ω resistor and an LED on it. 1.1 V across 330 + 231 + 30 Ω is 1.86 mA,
    nearly four times the threshold and still inside the 2 mA the part is rated
    for, so nothing is warned about either. Crossing the threshold takes eight
    resistors in series, which nobody wires by accident.
    """
    got = run(tmp_path, """
        const xiao = {chip: "SAMD21", volts: 3.3, sourceOhms: 330.0,
                      sinkOhms: 264.0, ratedAmps: 0.002, absoluteAmps: null};
        const pads = [{name: "D10", state: "high"},
                      {name: "D9", state: "input"},
                      {name: "GND", state: "unknown"}];
        const chain = (count) => {
          const parts = Array.from({length: count}, () => RESISTOR).concat([LED]);
          const wires = [{pad: "D10", part: 0, terminal: "lead A"}];
          for (let at = 1; at < count; at++) {
            wires.push({pad: `n${at}`, part: at - 1, terminal: "lead B"},
                       {pad: `n${at}`, part: at, terminal: "lead A"});
          }
          wires.push({pad: "D9", part: count - 1, terminal: "lead B"},
                     {pad: "D9", part: count, terminal: "anode"},
                     {pad: "GND", part: count, terminal: "cathode"});
          return analyse({supply: xiao, pads, parts, wires}).parts[count];
        };
        console.log(JSON.stringify({one: chain(1), eight: chain(8),
                                    lit: LIT_AMPS, rated: xiao.ratedAmps}));
    """)
    # `rel=1e-6` rather than the `1e-9` the other cases use, because this one
    # has a floating junction in it: the spare input pad joining the resistor
    # to the LED carries `GMIN` to ground like every other node, which bleeds
    # about two parts in a billion out of the series current. That is the
    # constant doing its job, not a disagreement.
    one = (3.3 - 2.2) / (330.0 + 231.0 + 30.0)
    assert got["one"]["amps"] == pytest.approx(one, rel=1e-6)
    assert got["one"]["drive"] == "lit"
    assert got["one"]["warning"] is None
    # Four times the threshold, and inside the pin's own rating.
    assert got["one"]["amps"] > 3.5 * got["lit"]
    assert got["one"]["amps"] < got["rated"]
    # And eight of them in series is where it finally goes dark, which is the
    # other half of the claim: the margin is large but it is not infinite.
    assert got["eight"]["drive"] == "off"
    assert got["eight"]["amps"] is None
