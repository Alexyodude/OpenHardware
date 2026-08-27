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
LED = {
    "label": "5 mm LED", "terminals": ["cathode", "anode"],
    "model": {"kind": "diode", "from": "anode", "to": "cathode",
              "forwardVolts": 2.2, "seriesOhms": 30.0, "ratedAmps": 0.020},
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


def test_an_led_wired_to_ground_lights(tmp_path):
    """The other half of the same report: a complete circuit still works.

    A fix that made everything dark would satisfy the test above and be worse
    than the bug.
    """
    got = run(tmp_path, bench("""[
        {pad: "13", part: 0, terminal: "anode"},
        {pad: "GND", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["drive"] == "lit"
    assert got["amps"] > 0.02


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
    assert got["drive"] == "lit"
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
    assert got["drive"] == "lit"


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


def test_the_warning_names_the_rating_it_passed(tmp_path):
    """**The payoff the whole exercise was for.**

    An LED straight across a pin with no series resistor draws forty
    milliamps by the most pessimistic reckoning available, against the twenty
    Arduino rates an UNO pin for. The page says that in words, with both
    numbers in it, rather than lighting it prettily.

    And it says it only in that direction: every resistance in `UNO` is the
    upper bound a datasheet guarantees, so the current is a lower bound — over
    a rating is a fact, under one is not a clean bill of health.
    """
    got = run(tmp_path, bench("""[
        {pad: "13", part: 0, terminal: "anode"},
        {pad: "GND", part: 0, terminal: "cathode"},
    ]""") + """
        console.log(JSON.stringify(report.parts[0]));
    """)
    assert got["warning"]
    assert "20 mA" in got["warning"]
    assert "40 mA" in got["warning"]
    assert "limiting" in got["warning"]


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
    assert [part["drive"] for part in got["one"]] == ["lit", "lit"]


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
    values = {name: value for name, (value, _why) in LED_ELECTRICAL.cited.items()}
    assert LED_ELECTRICAL.kind == LED["model"]["kind"]
    assert list(LED_ELECTRICAL.forward) == [LED["model"]["from"], LED["model"]["to"]]
    assert values["forward_volts"] == LED["model"]["forwardVolts"]
    assert values["series_ohms"] == LED["model"]["seriesOhms"]
    # And every LED in the catalogue has one, while the buzzer deliberately
    # does not -- see its comment, and `test_a_part_with_no_electrical_model`.
    for part in PARTS:
        published = part.electrical is not None
        assert published == part.name.startswith("LED_"), part.name
        if published:
            for name, (_value, why) in part.electrical.cited.items():
                assert len(why) > 40, f"{part.name}: {name} has no real citation"
