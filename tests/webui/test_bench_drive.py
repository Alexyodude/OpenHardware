# OpenHardware — what the bench drives onto an input, posted by the page's own code.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why these tests run the page
#
# OH-161's step 3 closes a loop that crosses four files: `circuit.js` solves
# what the bench puts on each input, `board3d.js` posts it, the server's
# `/api/board/drive` hands it to `BoardSession.drive`, and a sketch's
# `digitalRead` sees it. A grep of `board3d.js` can find a `fetch` and cannot
# say when it fires, what it carries, or in what order two of them land.
#
# So these run `webui/static/board3d.js` itself under node -- `showBoard`,
# `addPart`, `connect`, `disconnect` and `setLevels`, through hooks that
# resolve the page's import map, the way OH-215's tests in `test_board3d.py`
# and OH-227's in `test_board_led.py` do. The file on disk is not touched: the
# hooks append one line naming `view` and the chain of posts.
#
# The part is a resistor GLB written here, carrying the electrical model
# `tools/import_3d_model.py`'s `RESISTOR_ELECTRICAL` gives the real one (the
# real meshes are fetched, not committed, so CI has none).
#
# The last test is the slice end to end: the page's code against a real
# server on a loopback port, a sketch compiled for the XIAO ESP32-C3 copying
# D1 to D10, and a resistor from D1 to GND that the page wires and unwires.

import base64
import json
import pathlib
import shutil
import struct
import subprocess
import threading
import urllib.request

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
STATIC = REPO / "webui" / "static"
BOARD = "XIAO-ESP32-C3-DIP"

#: Node module hooks: the page's import map, and the probe's handle on `view`
#: and on the chain of drives in flight, appended to board3d.js as it loads.
#: `typeof` so that a page with no such chain loads and is seen to post
#: nothing, rather than failing to load at all.
HOOKS = r"""
import { pathToFileURL } from "node:url";
import path from "node:path";

let vendor = null;
export async function initialize(data) { vendor = path.join(data.static, "vendor"); }

const MAP = { "three": "three.module.js",
              "three/addons/controls/OrbitControls.js": "OrbitControls.js" };

export async function resolve(specifier, context, next) {
  if (specifier in MAP) {
    return { url: pathToFileURL(path.join(vendor, MAP[specifier])).href,
             shortCircuit: true };
  }
  return next(specifier, context);
}

export async function load(url, context, next) {
  const result = await next(url, context);
  if (!url.endsWith("/board3d.js")) return result;
  const text = typeof result.source === "string"
    ? result.source : new TextDecoder().decode(result.source);
  return { ...result, format: "module", shortCircuit: true,
           source: text + "\nexport const __probe = { view, settled: () => " +
                   "(typeof posting === 'undefined' ? Promise.resolve() : posting) };\n" };
}
"""

#: What every probe starts with: the page module, a `fetch` that serves the
#: part's mesh off disk and hands every `/api/` request to `api` (each probe
#: defines it), and enough of what `mount` would have made for `showBoard`
#: and `addPart` to draw in.
PRELUDE = r"""
import { register } from "node:module";
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import path from "node:path";

const [STATIC, HOOKS, CASE] = process.argv.slice(2);
register(pathToFileURL(HOOKS).href, { data: { static: STATIC } });
const THREE = await import(
  pathToFileURL(path.join(STATIC, "vendor", "three.module.js")).href);
const page = await import(pathToFileURL(path.join(STATIC, "board3d.js")).href);
const { view, settled } = page.__probe;
const given = JSON.parse(readFileSync(CASE, "utf-8"));

const network = globalThis.fetch;
let api = null;
globalThis.fetch = async (url, options = {}) => {
  if (url.startsWith("/models/parts/")) {
    const kind = url.slice("/models/parts/".length, -".glb".length);
    const bytes = readFileSync(given.parts[kind]);
    return { ok: true, arrayBuffer: async () => bytes.buffer.slice(
      bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
  }
  return api(url, options);
};
const warned = [];
console.warn = (...words) => warned.push(words.map(String).join(" "));

view.renderer = {};
view.scene = new THREE.Scene();
view.camera = new THREE.PerspectiveCamera();
view.controls = { target: new THREE.Vector3(), update() {} };
view.bench = new THREE.Group();
view.scene.add(view.bench);
const grey = new THREE.Color(0.5, 0.5, 0.5);
view.palette = { surface: grey, line: grey, halt: grey, ground: grey,
                 states: { unknown: grey, high: grey, low: grey, input: grey } };
"""


def resistor_glb(path: pathlib.Path) -> None:
    """The narrowest part `readGlb` and `dressPart` accept: one triangle,
    two leads, and the 220 ohm resistor's electrical model as the importer
    writes it into `asset.extras`."""
    write_glb(path, {
        "chip": "probe_resistor", "label": "220 ohm resistor", "lens": None,
        "terminals": [{"name": "lead A", "at": [-3.8, -0.5, 0]},
                      {"name": "lead B", "at": [3.8, -0.5, 0]}],
        "electrical": {"kind": "resistor", "ohms": 231.0, "note": "",
                       "cited": {"ohms": "RESISTOR_ELECTRICAL's"}}})


#: An MCP9808's pins in DS25095A Table 3-1's order (p.11).
MCP9808_PINS = ("SDA", "SCL", "Alert", "GND", "A2", "A1", "A0", "VDD")


def mcp9808_glb(path: pathlib.Path) -> None:
    """The same narrow part with an MCP9808's eight terminals and the model
    the importer will write for it (OH-161 step 5, slice 4d), in the
    spellings `parts.js`'s `electricalOf` reads.

    The terminals stand 0.65 mm apart along two rows, the pitch the 4d
    design gives an MSOP-8's leads. The geometry is a stand-in: all the
    tests need is that neighbours be closer than two default targets
    (2 x 0.55), so the targets a wire is dropped on have to shrink to stay
    apart. The numbers are the datasheet's: IDD typical 200 uA (p.3,
    "Operating Current"), and for
    "Serial Input/Output (SCL, SDA, A0, A1, A2)" VIH at least 0.7 VDD and
    VIL at most 0.3 VDD (p.4)."""
    pitch = 0.65
    at = [[(number - 1.5) * pitch if number < 4 else (5.5 - number) * pitch,
           -0.5, 1.5 if number < 4 else -1.5] for number in range(8)]
    write_glb(path, {
        "chip": "probe_mcp9808", "label": "MCP9808", "lens": None,
        "terminals": [{"name": name, "at": at[number]}
                      for number, name in enumerate(MCP9808_PINS)],
        "electrical": {"kind": "i2c_device", "device": "MCP9808",
                       "supply_amps": 200e-6,
                       "input_high_ratio": 0.7, "input_low_ratio": 0.3,
                       "note": "", "cited": {}}})


def write_glb(path: pathlib.Path, extras: dict) -> None:
    """A one-triangle glTF with `extras` as its `asset.extras`."""
    binary = (struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 0, 1)
              + struct.pack("<9f", 0, 1, 0, 0, 1, 0, 0, 1, 0)
              + struct.pack("<3I", 0, 1, 2))
    document = json.dumps({
        "asset": {"version": "2.0", "extras": extras},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": offset, "byteLength": length}
                        for offset, length in ((0, 36), (36, 36), (72, 12))],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5125, "count": 3, "type": "SCALAR"},
        ],
        "materials": [{"name": "body", "pbrMetallicRoughness": {
            "baseColorFactor": [0.5, 0.5, 0.5, 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 0.5}}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                    "indices": 2, "material": 0}]}],
    }).encode("utf-8")
    document += b" " * (-len(document) % 4)
    body = (struct.pack("<II", len(document), 0x4E4F534A) + document
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def run_page(directory: pathlib.Path, probe: str, case: dict) -> dict:
    """Run `PRELUDE` and `probe` under node with `case` beside them, and
    parse the last line it prints; skips without node, as OH-215's do."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; the bench's post is the page's own JS "
                    "and needs one to run")
    hooks = directory / "hooks.mjs"
    script = directory / "probe.mjs"
    listing = directory / "case.json"
    resistor = directory / "resistor.glb"
    mcp9808 = directory / "mcp9808.glb"
    resistor_glb(resistor)
    mcp9808_glb(mcp9808)
    # A file whose two terminals are at one point, which is no part.
    twin = directory / "twin.glb"
    write_glb(twin, {"chip": "probe_twin", "label": "twin", "lens": None,
                     "terminals": [{"name": "one", "at": [1, -0.5, 0]},
                                   {"name": "two", "at": [1, -0.5, 0]}]})
    hooks.write_text(HOOKS, encoding="utf-8")
    script.write_text(PRELUDE + probe, encoding="utf-8")
    listing.write_text(json.dumps({**case, "parts": {
        "probe_resistor": str(resistor), "probe_mcp9808": str(mcp9808),
        "probe_twin": str(twin)}}), encoding="utf-8")
    done = subprocess.run([node, str(script), str(STATIC), str(hooks), str(listing)],
                          capture_output=True, text=True, check=False, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def layout(board: str = BOARD) -> dict:
    """The board as `/api/board/pins?board=` sends it with no program
    running: `webui/api.py`'s own `pad_view`, supply and all."""
    from webui import api
    return api.pad_view(board, api.description_for(board), None)


#: Steps a probe takes through the page's own exports, recording after each
#: how many posts there have been and what the bench note says. `steps` is a
#: list of `[verb, ...]`: `show` draws `given.layouts[n]` (the first is drawn
#: before the steps), `connect` and `disconnect` take a part's index, the last
#: added by default. `add` takes the kind (the resistor by default), `unwire`
#: a terminal and an index, `celsius` an index and a temperature, and
#: `remove` an index; `returned` collects what `celsius` and `remove` answer
#: and `listing` is `parts()` at the end. `api` refuses the first `given.refusing` posts with
#: `given.refusal`, answers 200 to the rest, and keeps them all, in order.
STEPS = r"""
const posted = [];
api = async (url, options) => {
  if (url !== "/api/board/drive") throw new Error(`unexpected ${url}`);
  posted.push(JSON.parse(options.body));
  if (posted.length <= (given.refusing ?? 0)) {
    return { ok: false, json: async () => ({ error: given.refusal, reason: "drive-refused" }) };
  }
  return { ok: true, json: async () => ({}) };
};
const layouts = given.layouts ?? [given.layout];
page.showBoard(layouts[0], null);
await settled();
const parts = [];
const wires = {};
const named = {};
const returned = [];
const after = [];
const notes = [];
const refused = [];
const last = (at) => at ?? parts.length - 1;
for (const [verb, ...rest] of given.steps) {
  if (verb === "show") page.showBoard(layouts[rest[0]], null);
  if (verb === "levels") page.setLevels(rest[0]);
  if (verb === "add") parts.push(await page.addPart(rest[0] ?? "probe_resistor"));
  if (verb === "connect") {
    const wire = page.connect(rest[0], parts[last(rest[2])], rest[1]);
    wires[`${rest[0]}@${last(rest[2])}`] = wire.id;
    named[`${rest[1]}@${last(rest[2])}`] = wire.id;
  }
  if (verb === "disconnect") page.disconnect(wires[`${rest[0]}@${last(rest[1])}`]);
  if (verb === "unwire") page.disconnect(named[`${rest[0]}@${last(rest[1])}`]);
  if (verb === "celsius") returned.push(page.setCelsius(rest[0], rest[1]));
  if (verb === "remove") returned.push(page.removePart(rest[0]));
  await settled();
  after.push(posted.length);
  notes.push(page.circuit()?.note ?? null);
  refused.push(page.circuit()?.refused ?? null);
}
console.log(JSON.stringify({ posted, after, notes, refused, warned, returned,
                             listing: page.parts() }));
"""


def test_the_bench_posts_what_it_drives_onto_the_inputs_when_that_changes(tmp_path):
    """**The wiring of `analyse`'s inputs to the post** (OH-161).

    The first state with an input in it is posted whole -- the page cannot
    know what the board already holds -- and after that only a change in
    what is DRIVEN is: the same poll again, a part arriving, one lead wired,
    or a pad leaving the inputs while it is open, each post nothing. A
    resistor from D1 to GND drives it low and the post says so with D2 open
    beside it; unwiring it lets D1 go and the post says that. Every post
    names the board the bench was solved on."""
    running = {"D1": "input", "D2": "input", "D10": "high"}
    got = run_page(tmp_path, STEPS, {"layout": layout(), "steps": [
        ["levels", running],                       # 1: first inputs, posted
        ["levels", running],                       # 2: the same poll
        ["add"],                                   # 3: a part on the bench
        ["connect", "D1", "lead A"],               # 4: one lead
        ["connect", "GND", "lead B"],              # 5: D1 low
        ["levels", running],                       # 6: the same poll
        ["disconnect", "GND"],                     # 7: D1 let go
        ["levels", {**running, "D1": "high"}],     # 8: D1 an output now
    ]})
    every = {pad: "open" for pad, state in running.items() if state == "input"}
    assert [(post["board"], post["levels"]) for post in got["posted"]] == [
        (BOARD, every), (BOARD, {**every, "D1": "low"}), (BOARD, every),
    ], got["posted"]
    # The voltage the solve put on each decided input, posted beside the
    # levels (OH-161 step 4): none before the resistor, D1 at ground through
    # it, and none once it is let go.
    volts = [post["volts"] for post in got["posted"]]
    assert volts[0] == {} and volts[2] == {}, volts
    assert volts[1] == {"D1": 0}, volts
    assert got["after"] == [1, 1, 1, 1, 2, 2, 3, 3], got["after"]
    assert got["warned"] == []


def test_a_board_that_states_no_input_levels_is_posted_nothing(tmp_path):
    """The Arduino Uno's supply states no input levels and its description
    reads no input, so a resistor from an input pin to ground is solved for
    its current and nothing is posted: there would be nowhere to send it."""
    got = run_page(tmp_path, STEPS, {"layout": layout("Arduino Uno"), "steps": [
        ["levels", {"11": "input", "13": "high"}],
        ["add"],
        ["connect", "11", "lead A"],
        ["connect", "GND", "lead B"],
    ]})
    assert got["posted"] == [], got["posted"]


def test_a_refused_drive_is_reported_once_and_not_retried(tmp_path):
    """The server refuses a bench solved for a board it is not running. The
    page says so in the console, and the next poll does not post the same
    map again -- a retry per poll would be a refusal many times a second."""
    running = {"D1": "input", "D2": "input"}
    got = run_page(tmp_path, STEPS, {
        "layout": layout(), "refusing": 99,
        "refusal": "the bench was solved for another board",
        "steps": [["levels", running], ["levels", running], ["levels", running]]})
    assert len(got["posted"]) == 1, got["posted"]
    assert len(got["warned"]) == 1 and "another board" in got["warned"][0], got["warned"]


def test_a_refused_drive_is_said_in_the_bench_note_until_one_is_accepted(tmp_path):
    """**The console is not where a reader looks** (OH-161's review). A
    refusal leads the bench note, which the panel shows under the canvas,
    from the moment it arrives until a post is accepted -- here the next one,
    when a resistor takes D1 low."""
    running = {"D1": "input", "D2": "input"}
    refusal = "the bench was solved for 'XIAO-ESP32-C6-DIP'"
    got = run_page(tmp_path, STEPS, {
        "layout": layout(), "refusing": 1, "refusal": refusal,
        "steps": [["levels", running], ["levels", running], ["add"],
                  ["connect", "D1", "lead A"], ["connect", "GND", "lead B"]]})
    assert got["after"] == [1, 1, 1, 1, 2], got["after"]
    for note in got["notes"][:4]:
        assert note and note.startswith("The board refused what the bench drives: "
                                        + refusal), note
    assert not (got["notes"][4] or "").startswith("The board refused"), got["notes"][4]
    # And `circuit()` says in a field, not only in the note's words, that the
    # board refused: the panel tells a refused part from one not yet told of.
    assert got["refused"] == [True, True, True, True, False], got["refused"]


def test_a_bench_that_does_not_solve_lets_go_of_nothing(tmp_path):
    """**"open" from a bench that did not solve is unknown, not let go**
    (OH-161's review). D1 is held low through a resistor, and then a second
    resistor's lead is wired to both `3V3_OUT` and `GND` -- a short, which
    `analyse` refuses to solve and answers with every input open. Posting
    that would release D1 on the board while the bench still holds it, so
    nothing is posted; once the short is taken off, D1 is still low, which
    is what the board was last told, and nothing is posted either."""
    running = {"D1": "input", "D2": "input", "D10": "high"}
    got = run_page(tmp_path, STEPS, {"layout": layout(), "steps": [
        ["levels", running],                       # 1: first inputs, posted
        ["add"],
        ["connect", "D1", "lead A"],
        ["connect", "GND", "lead B"],              # 4: D1 low, posted
        ["add"],
        ["connect", "3V3_OUT", "lead A"],
        ["connect", "GND", "lead A"],              # 7: a short
        ["disconnect", "GND"],                     # 8: the short off
    ]})
    assert got["after"] == [1, 1, 1, 2, 2, 2, 2, 2], (got["after"], got["posted"])
    assert got["posted"][-1]["levels"]["D1"] == "low", got["posted"]
    assert "short circuit" in got["notes"][6], got["notes"][6]


def test_drawing_a_board_rearms_the_post_and_states_the_bench_once_where_it_runs(tmp_path):
    """**A load or a pick is a session the page has told nothing** (OH-161's
    review). `reload` draws after both, so `showBoard` forgets what it posted
    and solves the bench against the pads it drew: where the drawn board is
    the one running -- its pads carry levels, as `/api/board/pins` sends them
    only then -- the bench is stated once, and polls after it post nothing
    new. Drawn again, it is stated again. Where the drawn board is not
    running, its pads carry no level and nothing is posted."""
    idle = layout()
    running = layout()
    for pad in running["pads"]:
        if pad["pin"] in ("D1", "D2"):
            pad["state"] = "input"
    got = run_page(tmp_path, STEPS, {"layouts": [idle, running], "steps": [
        ["show", 1],                               # 1: drawn, running: stated
        ["levels", {"D1": "input", "D2": "input"}],
        ["show", 1],                               # 3: drawn again: stated again
        ["show", 0],                               # 4: a board not running
    ]})
    every = {"D1": "open", "D2": "open"}
    assert got["after"] == [1, 1, 2, 2], (got["after"], got["posted"])
    assert got["posted"] == [{"board": BOARD, "levels": every, "volts": {},
                              "devices": {}}] * 2, got["posted"]


def test_a_pad_that_drives_unlike_the_rest_is_solved_at_its_own_resistance(tmp_path):
    """**Each pad at its own reset drive** (OH-161's review). A XIAO
    ESP32-C3's D1 is GPIO3, which comes out of reset at ~10 mA where D10 is
    at ~20 mA (C3 TRM v1.4, Table 5.12-1's legend, p.174). `webui/api.py`
    names D1's resistances in the supply it sends, `supplyOf` carries them,
    and `circuit.js` solves a 220 ohm resistor (231 at the top of its band)
    from each to GND at its own: 3.3 / (66 + 231) through D1 and
    3.3 / (33 + 231) through D10."""
    probe = r"""
    api = async () => ({ ok: true, json: async () => ({}) });
    page.showBoard(given.layout, null);
    page.setLevels({ D1: "high", D10: "high" });
    const one = await page.addPart("probe_resistor");
    page.connect("D1", one, "lead A");
    page.connect("GND", one, "lead B");
    const other = await page.addPart("probe_resistor");
    page.connect("D10", other, "lead A");
    page.connect("GND", other, "lead B");
    console.log(JSON.stringify({ pins: view.supply.pins,
                                 amps: page.parts().map((part) => part.amps) }));
    """
    got = run_page(tmp_path, probe, {"layout": layout()})
    assert got["pins"]["D1"] == {"sourceOhms": 66.0, "sinkOhms": 70.7}, got["pins"]
    assert "D10" not in got["pins"], got["pins"]
    want = [3.3 / (66.0 + 231.0), 3.3 / (33.0 + 231.0)]
    assert all(abs(seen - wanted) < 1e-9 for seen, wanted in zip(got["amps"], want)), got["amps"]


def test_two_drives_reach_the_board_in_the_order_they_were_stated(tmp_path):
    """**A press and its release, a few milliseconds apart.** Each drive
    replaces the last, so if the release reached the board first the board
    would be left holding the press. The page chains them: the second post
    does not leave until the first has been answered, however slow it is."""
    probe = r"""
    const events = [];
    let first = true;
    api = async (url, options) => {
      const levels = JSON.parse(options.body).levels;
      events.push(["sent", levels.D1]);
      if (first) { first = false; await new Promise((done) => setTimeout(done, 50)); }
      events.push(["answered", levels.D1]);
      return { ok: true, json: async () => ({}) };
    };
    page.showBoard(given.layout, null);
    page.setLevels({ D1: "input" });
    await settled();
    events.length = 0;
    first = true;
    const part = await page.addPart("probe_resistor");
    page.connect("D1", part, "lead A");
    const ground = page.connect("GND", part, "lead B");
    page.disconnect(ground.id);
    await settled();
    console.log(JSON.stringify({ events }));
    """
    got = run_page(tmp_path, probe, {"layout": layout()})
    assert got["events"] == [["sent", "low"], ["answered", "low"],
                             ["sent", "open"], ["answered", "open"]], got["events"]


def test_a_voltage_that_moves_is_posted_though_its_level_does_not(tmp_path):
    """**A divider's midpoint moves when a resistor does, and its level does
    not** (OH-161 step 4). One resistor from `3V3_OUT` holds D1 high at the
    rail; a second from D1 to GND makes a divider, 1.65 V, which no digital
    level reads -- "open" -- and which is posted for the ADC; a third in
    parallel with the second takes D1 to 1.1 V, still "open", and is posted
    because the voltage changed. A lead in mid-air moves nothing and posts
    nothing."""
    running = {"D1": "input", "D2": "input", "D10": "high"}
    got = run_page(tmp_path, STEPS, {"layout": layout(), "steps": [
        ["levels", running],                       # 1: first inputs, posted
        ["add"],
        ["connect", "3V3_OUT", "lead A", 0],
        ["connect", "D1", "lead B", 0],            # 4: D1 high, at the rail
        ["add"],
        ["connect", "D1", "lead A", 1],            # 6: a lead in mid-air
        ["connect", "GND", "lead B", 1],           # 7: the divider, 1.65 V
        ["levels", running],                       # 8: the same poll
        ["add"],
        ["connect", "D1", "lead A", 2],
        ["connect", "GND", "lead B", 2],           # 11: 1.1 V, still open
    ]})
    assert got["after"] == [1, 1, 1, 2, 2, 2, 3, 3, 3, 3, 4], (got["after"], got["posted"])
    levels = [post["levels"]["D1"] for post in got["posted"]]
    volts = [post["volts"].get("D1") for post in got["posted"]]
    assert levels == ["open", "high", "open", "open"], levels
    assert volts == [None, 3.3, 1.65, 1.1], volts
    assert "analogRead of it" in got["notes"][6], got["notes"][6]


# --- an I2C device on the bench (OH-161 step 5, slice 4a) ---------------------

#: What the bench states of the MCP9808 once all seven of its wires are
#: made, and the temperature the page gives a part that arrives.
MCP_POSTED = {"part": "MCP9808", "sda": "D4", "scl": "D5", "vdd": 3.3,
              "address_pins": {"A0": "low", "A1": "low", "A2": "low"},
              "celsius": 25.0}

#: Add an MCP9808, wire SDA, SCL, VDD, GND and A0 to A2 to ground.
SEVEN_WIRES = [
    ["add", "probe_mcp9808"],
    ["connect", "D4", "SDA"], ["connect", "D5", "SCL"],
    ["connect", "3V3_OUT", "VDD"], ["connect", "GND", "GND"],
    ["connect", "GND", "A0"], ["connect", "GND", "A1"],
    ["connect", "GND", "A2"],
]


def test_six_wires_post_no_device_and_the_seventh_posts_it(tmp_path):
    """**The bench states a device when it has every fact the board needs.**
    A first state with an input in it is posted, with `devices` in the body
    and empty. The part arriving and each of its first six wires post
    nothing -- the address pin still open says so in the bench note -- and
    the seventh posts the part under the id the bench gave it, with the
    pads it is on, its supply, its address pins and the 25 C a part is given
    when it arrives. A part with no wires has no id in the post to lose."""
    got = run_page(tmp_path, STEPS, {"layout": layout(), "steps": [
        ["levels", {"D1": "input"}],               # 1: first inputs, posted
        *SEVEN_WIRES,                              # 2 to 9
    ]})
    assert got["after"] == [1, 1, 1, 1, 1, 1, 1, 1, 2], (got["after"], got["posted"])
    assert got["posted"][0]["devices"] == {}, got["posted"][0]
    assert got["posted"][1]["devices"] == {"part-1": MCP_POSTED}, got["posted"][1]
    assert "A2" in got["notes"][7], got["notes"][7]
    assert got["warned"] == []


def test_a_change_of_celsius_alone_is_posted_and_the_same_celsius_is_not(tmp_path):
    """The temperature is a fact about the part and nothing else about the
    bench moves when it changes, so the post's `stated` has to include the
    devices or a celsius-only change posts nothing. `setCelsius` answers true
    for a part that has one, and false for one that has none."""
    got = run_page(tmp_path, STEPS, {"layout": layout(), "steps": [
        ["levels", {"D1": "input"}],
        *SEVEN_WIRES,
        ["celsius", 0, 30.0],                      # 10: posted
        ["celsius", 0, 30.0],                      # 11: the same, nothing
        ["celsius", 0, -10.5],                     # 12: posted
        ["add"],                                   # 13: a resistor, index 1
        ["celsius", 1, 30.0],                      # 14: no temperature to set
    ]})
    assert got["after"][8:] == [2, 3, 3, 4, 4, 4], (got["after"], got["posted"])
    assert [post["devices"]["part-1"]["celsius"] for post in got["posted"][1:]] == [
        25.0, 30.0, -10.5], got["posted"]
    assert got["returned"] == [True, True, True, False], got["returned"]
    assert [part["celsius"] for part in got["listing"]] == [-10.5, None], got["listing"]


def test_whenposted_resolves_only_once_the_last_post_has_been_answered(tmp_path):
    """The panel refetches the board's state after an accepted temperature,
    and the state is only the new one once the drive has landed: a board that
    is stopped has no poll to bring it. `whenPosted` is the chain of posts."""
    probe = r"""
    let answered = false;
    api = async () => {
      await new Promise((done) => setTimeout(done, 40));
      answered = true;
      return { ok: true, json: async () => ({}) };
    };
    page.showBoard(given.layout, null);
    page.setLevels({ D1: "input" });
    const before = answered;
    await page.whenPosted();
    console.log(JSON.stringify({ before, answered }));
    """
    got = run_page(tmp_path, probe, {"layout": layout()})
    assert got == {"before": False, "answered": True}, got


def test_unwiring_an_address_pin_posts_the_part_away(tmp_path):
    """A0 let go leaves the part with no address, so the bench states no
    device: the post that says so is `devices: {}`, which is what takes the
    part off the board's bus."""
    got = run_page(tmp_path, STEPS, {"layout": layout(), "steps": [
        ["levels", {"D1": "input"}],
        *SEVEN_WIRES,
        ["unwire", "A0", 0],                       # 10
    ]})
    assert got["after"][8:] == [2, 3], (got["after"], got["posted"])
    assert got["posted"][2]["devices"] == {}, got["posted"][2]
    assert "A0" in got["notes"][9], got["notes"][9]


def test_a_part_keeps_its_id_when_an_earlier_part_is_taken_off_the_bench(tmp_path):
    """**The id is minted, not the part's index.** A resistor, then the
    MCP9808 wired in full under `part-2`; taking the resistor off moves the
    MCP9808 to index 0, and a post keyed by index would move its registers
    onto another part. Nothing is posted -- the statement is the same -- and
    the part that arrives next is `part-3`, not a second `part-2`."""
    got = run_page(tmp_path, STEPS, {"layout": layout(), "steps": [
        ["levels", {"D1": "input"}],
        ["add"],                                   # 2: a resistor, part-1
        *SEVEN_WIRES,                              # 3 to 10, part-2
        ["remove", 0],                             # 11
        ["add"],                                   # 12: part-3
    ]})
    assert got["after"][9:] == [2, 2, 2], (got["after"], got["posted"])
    assert list(got["posted"][1]["devices"]) == ["part-2"], got["posted"][1]
    assert got["returned"] == [True], got["returned"]
    assert [(part["kind"], part["id"]) for part in got["listing"]] == [
        ("probe_mcp9808", "part-2"), ("probe_resistor", "part-3")], got["listing"]
    assert got["listing"][0]["device"] == {k: v for k, v in MCP_POSTED.items()
                                           if k != "celsius"}, got["listing"][0]


def test_an_i2c_devices_model_reaches_the_bench_in_the_spelling_analyse_reads(tmp_path):
    """`electricalOf` renames the importer's keys across the glTF: a key it
    forgets is dropped silently (`absolute_amps` was, once), and a device
    whose ratios went missing would have no address to read."""
    probe = r"""
    api = async () => ({ ok: true, json: async () => ({}) });
    page.showBoard(given.layout, null);
    const part = await page.addPart("probe_mcp9808");
    console.log(JSON.stringify(part.userData.electrical));
    """
    got = run_page(tmp_path, probe, {"layout": layout()})
    assert got == {"kind": "i2c_device", "device": "MCP9808", "supplyAmps": 200e-6,
                   "inputHighRatio": 0.7, "inputLowRatio": 0.3, "note": "", "cited": {}}, got


def test_two_terminals_a_pitch_apart_have_targets_that_do_not_overlap(tmp_path):
    """**A wire is dropped on a sphere at a terminal**, 0.55 radius by default.
    An MSOP-8's leads are 0.65 apart, so the default spheres overlap by most
    of their width and a drop on one lands on its neighbour. The radius is
    capped to under half the nearest pair, and a resistor's, 7.6 apart, keeps
    the default."""
    probe = r"""
    api = async () => ({ ok: true, json: async () => ({}) });
    page.showBoard(given.layout, null);
    const radii = async (kind) => {
      const part = await page.addPart(kind);
      const targets = [...part.userData.terminals.values()].map((anchor) =>
        ({ at: anchor.position, radius: anchor.children.find((c) => c.isMesh).geometry.parameters.radius }));
      let gap = Infinity;
      for (const [i, one] of targets.entries()) {
        for (const other of targets.slice(i + 1)) {
          gap = Math.min(gap, one.at.distanceTo(other.at) - one.radius - other.radius);
        }
      }
      return { gap, radius: Math.max(...targets.map((target) => target.radius)) };
    };
    console.log(JSON.stringify({ chip: await radii("probe_mcp9808"),
                                 resistor: await radii("probe_resistor") }));
    """
    got = run_page(tmp_path, probe, {"layout": layout()})
    assert got["chip"]["gap"] > 0, got["chip"]
    assert got["resistor"]["radius"] == 0.55, got["resistor"]


def test_a_part_whose_terminals_are_at_one_point_is_refused_naming_them(tmp_path):
    """Two terminals at one point would get a target of radius zero and no
    target at all, silently. The part is refused, by the names of the two and
    where they are, and is not put on the bench."""
    probe = r"""
    api = async () => ({ ok: true, json: async () => ({}) });
    page.showBoard(given.layout, null);
    let message = null;
    try { await page.addPart("probe_twin"); } catch (error) { message = error.message; }
    console.log(JSON.stringify({ message, parts: page.parts().length }));
    """
    got = run_page(tmp_path, probe, {"layout": layout()})
    assert got["parts"] == 0, got
    assert all(word in got["message"] for word in ("probe_twin", "one", "two", "1,-0.5,0")), got


def test_a_device_is_not_posted_while_no_pad_has_a_state_of_its_own(tmp_path):
    """**Every pad is `unknown` while no program runs**, and a device posted
    then reaches a server with nothing loaded, whose 400 would lead the bench
    note. Seven wires post nothing; the first state a pad takes -- D1 an
    input, as a program leaves it -- posts the device with the first inputs."""
    got = run_page(tmp_path, STEPS, {"layout": layout(), "steps": [
        *SEVEN_WIRES,                              # 1 to 8
        ["levels", {"D1": "input"}],               # 9: a pad has a state
    ]})
    assert got["after"] == [0] * 8 + [1], (got["after"], got["posted"])
    assert got["posted"][0]["devices"] == {"part-1": MCP_POSTED}, got["posted"]
    assert got["warned"] == [] and got["notes"][7] is None, got["notes"]


def test_a_device_is_posted_though_no_pad_is_an_input_where_a_pad_has_a_state(tmp_path):
    """**The device clause of the first-post gate is the only thing that
    posts here.** A sketch whose pads are all outputs leaves `analyse` no
    input to state, so the first post would wait for one forever; a pad that
    is high or low is a program running, and the seventh wire states the
    part with `levels` empty. Without the clause nothing is ever posted."""
    for level in ("high", "low"):
        directory = tmp_path / level
        directory.mkdir()
        got = run_page(directory, STEPS, {"layout": layout(), "steps": [
            ["levels", {"D1": level}],             # 1: a pad drives, none is an input
            *SEVEN_WIRES,                          # 2 to 9
        ]})
        assert got["after"] == [0] * 8 + [1], (level, got["after"], got["posted"])
        assert got["posted"] == [{"board": BOARD, "levels": {}, "volts": {},
                                  "devices": {"part-1": MCP_POSTED}}], (level, got["posted"])
        assert got["warned"] == [], (level, got["warned"])


# --- the slice, end to end: the page's code against a real server -----------

#: An input pulled up, and an output copying it, in each board's own names.
ECHO_SKETCH = """
void setup() {{ pinMode({input}, INPUT_PULLUP); pinMode({output}, OUTPUT); }}
void loop() {{ digitalWrite({output}, digitalRead({input})); }}
"""

#: Each board the slice is watched on, with the input and the output its
#: sketch names. The three XIAOs' are their `HEADER`'s; the two manifest rows'
#: are their own board files' labels, which their Arduino variants spell the
#: same -- and on the QT Py, `A1` is GPIO3, the pin a XIAO ESP32-C3 calls D1.
WATCHED = (
    ("XIAO-ESP32-C3-DIP", "D1", "D10"),
    ("XIAO-ESP32-C5-DIP", "D1", "D10"),
    ("XIAO-ESP32-C6-DIP", "D1", "D10"),
    ("Adafruit QT Py ESP32-C3", "A1", "A0"),
    ("Adafruit Feather ESP32-C6", "A1", "A0"),
)

#: The page's own path, as `emulator.js` and `board3d-panel.js` walk it: the
#: pad map from `/api/board/pins`, a run, a state poll handed to `setLevels`
#: -- which solves the bench and posts -- and the output read off the next
#: poll. Every `/api/` request goes to the live server.
END_TO_END = r"""
api = (url, options) => network(given.server + url, options);
const json = async (url, body) => (await api(url, body === undefined ? {} : {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body) })).json();
page.showBoard(await json(`/api/board/pins?board=${encodeURIComponent(given.board)}`), null);
const poll = async () => {
  await json("/api/board/run", { steps: 2000 });
  page.setLevels((await json("/api/board/state")).pins);
  await settled();
  await json("/api/board/run", { steps: 2000 });
  return (await json("/api/board/state")).pins[given.output];
};
const seen = [await poll()];
const part = await page.addPart("probe_resistor");
page.connect(given.input, part, "lead A");
const ground = page.connect("GND", part, "lead B");
seen.push(await poll());
page.disconnect(ground.id);
seen.push(await poll());
console.log(JSON.stringify({ seen, warned }));
"""


def test_the_page_drives_a_sketch_through_the_server(tmp_path):
    """**The slice, watched.** On each board in `WATCHED`, a sketch compiled
    for it and loaded on a real server copies an input, pulled up, to an
    output. The page's own code draws the board from `/api/board/pins`, puts
    a 220 ohm resistor on the bench and wires it from the input to GND:
    `circuit.js` solves the input low, `board3d.js` posts it, and the next
    state poll reads the output low. Unwired, the input is open again, the
    pull-up wins, and the output goes high. The session's record holds
    exactly the drives the page made, in order."""
    from webui import compile as compiler
    from webui import emulator_server, targets

    # riscv32 and not cortexm0: every board watched here is an ESP32.
    target = targets.find("riscv32")
    if target is None or not target.selectable:
        pytest.skip("riscv32 is not built; run python tools/build_core.py")
    server = emulator_server.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    watched = {}
    try:
        host, port = server.server_address[:2]
        base = f"http://{host}:{port}"
        for board, pin_in, pin_out in WATCHED:
            try:
                built = compiler.build(board, ECHO_SKETCH.format(input=pin_in, output=pin_out))
            except compiler.ToolchainMissing as exc:
                pytest.skip(str(exc))
            assert built.ok, (board, built.diagnostics)
            request = urllib.request.Request(
                base + "/api/board/load", method="POST",
                headers={"Content-Type": "application/json"},
                data=json.dumps({"board": board,
                                 "image": base64.b64encode(built.image).decode(),
                                 "base": hex(compiler.recipe_for(board).base)}).encode())
            with urllib.request.urlopen(request, timeout=30):
                pass
            directory = tmp_path / str(len(watched))
            directory.mkdir()
            got = run_page(directory, END_TO_END, {
                "server": base, "board": board, "input": pin_in, "output": pin_out})
            record = [levels.get(pin_in) for _, levels, _volts, _devices
                      in server.RequestHandlerClass.boards.session.inputs]
            watched[board] = (got["seen"], got["warned"], record)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    for board, (seen, warned, record) in watched.items():
        assert seen == ["high", "low", "high"], (board, seen)
        assert warned == [], (board, warned)
        assert record == ["open", "low", "open"], (board, record)


# --- a voltage, end to end (OH-161 step 4) -----------------------------------

#: Prints each code `analogRead(A0)` gives that differs from the last.
ANALOG_SKETCH = """
int last = -1;
void setup() { }
void loop() {
  int code = analogRead(A0);
  if (code != last) { Serial.println(code); last = code; }
}
"""

#: Each board the voltage is watched on, with the pad its `A0` is.
ANALOG_WATCHED = (
    ("XIAO-ESP32-C3-DIP", "D0"),
    ("XIAO-ESP32-C5-DIP", "D0"),
    ("XIAO-ESP32-C6-DIP", "D0"),
)

#: The page's own path again, reading the console instead of a pin: the
#: board drawn from `/api/board/pins`, a run and a state poll handed to
#: `setLevels`, then a divider built on the bench a lead at a time -- each
#: `connect` solves and posts -- and the console read after the next run.
#: **The posts are let land before the run**: a run sent while they are in
#: flight would run between two of them, and print the rail the divider's
#: upper resistor held A0 at for an instant (measured, 3071).
ANALOG_END_TO_END = r"""
api = (url, options) => network(given.server + url, options);
const json = async (url, body) => (await api(url, body === undefined ? {} : {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body) })).json();
page.showBoard(await json(`/api/board/pins?board=${encodeURIComponent(given.board)}`), null);
const poll = async () => {
  await json("/api/board/run", { steps: 2000 });
  page.setLevels((await json("/api/board/state")).pins);
  await settled();
  await json("/api/board/run", { steps: 2000 });
  return (await json("/api/board/state")).uart.text;
};
const seen = [await poll()];
const top = await page.addPart("probe_resistor");
page.connect("3V3_OUT", top, "lead A");
page.connect(given.input, top, "lead B");
const bottom = await page.addPart("probe_resistor");
page.connect(given.input, bottom, "lead A");
page.connect("GND", bottom, "lead B");
await settled();
seen.push(await poll());
const parallel = await page.addPart("probe_resistor");
page.connect(given.input, parallel, "lead A");
page.connect("GND", parallel, "lead B");
await settled();
seen.push(await poll());
console.log(JSON.stringify({ seen, warned }));
"""


def test_the_page_holds_a_voltage_a_sketch_converts_through_the_server(tmp_path):
    """**The voltage, watched.** A sketch printing `analogRead(A0)` whenever
    it changes, loaded on a real server; the page's own code draws the
    board, and two 220 ohm resistors from `3V3_OUT` and GND meeting on A0's
    pad make a divider. `circuit.js` solves 1.65 V there, `board3d.js` posts
    it, and the sketch prints 1536. A third resistor in parallel with the
    lower one takes A0 to 1.1 V, and it prints 1024. The session's record
    holds the voltages the page posted, in order: nothing, the rail while
    only the upper resistor was wired, the divider, the divider changed."""
    from webui import compile as compiler
    from webui import emulator_server, targets

    target = targets.find("riscv32")
    if target is None or not target.selectable:
        pytest.skip("riscv32 is not built; run python tools/build_core.py")
    server = emulator_server.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    watched = {}
    try:
        host, port = server.server_address[:2]
        base = f"http://{host}:{port}"
        for board, pad in ANALOG_WATCHED:
            try:
                built = compiler.build(board, ANALOG_SKETCH)
            except compiler.ToolchainMissing as exc:
                pytest.skip(str(exc))
            assert built.ok, (board, built.diagnostics)
            request = urllib.request.Request(
                base + "/api/board/load", method="POST",
                headers={"Content-Type": "application/json"},
                data=json.dumps({"board": board,
                                 "image": base64.b64encode(built.image).decode(),
                                 "base": hex(compiler.recipe_for(board).base)}).encode())
            with urllib.request.urlopen(request, timeout=30):
                pass
            directory = tmp_path / str(len(watched))
            directory.mkdir()
            got = run_page(directory, ANALOG_END_TO_END,
                           {"server": base, "board": board, "input": pad})
            record = [volts.get(pad) for _, _levels, volts, _devices
                      in server.RequestHandlerClass.boards.session.inputs]
            watched[board] = (got["seen"], got["warned"], record)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    for board, (seen, warned, record) in watched.items():
        assert seen == ["0\r\n", "0\r\n1536\r\n", "0\r\n1536\r\n1024\r\n"], (board, seen)
        assert warned == [], (board, warned)
        assert record == [None, 3.3, 1.65, 1.1], (board, record)


# --- a temperature, end to end (OH-161 step 5, slice 4a) ----------------------

#: DS25095A Example 5-1's TA read (p.25), with one difference: the pointer
#: write ends in a STOP (4.1.1, p.13: the part keeps the pointer across it)
#: and the read follows, as `test_board_run.py`'s `WIRE_READ16` does. It
#: returns -1 where the part did not answer. The loop prints the whole
#: register, 16 bits, each time it differs from the last: -1 first, with
#: nothing on the bus.
TA_SKETCH = """
#include <Wire.h>
static int read16(uint8_t pointer) {
  Wire.beginTransmission(0x18);
  Wire.write(pointer);
  Wire.endTransmission();
  if (Wire.requestFrom(0x18, 2) != 2) return -1;
  int high = Wire.read();
  int low = Wire.read();
  return (high << 8) | low;
}
int last = -2;
void setup() { Wire.begin(); }
void loop() {
  int ta = read16(5);
  if (ta != last) { Serial.println(ta); last = ta; }
  delay(2);
}
"""

#: Each board the temperature is watched on: the pads Wire's default SDA and
#: SCL are, D4 and D5, on all three XIAOs.
TEMPERATURE_WATCHED = ("XIAO-ESP32-C3-DIP", "XIAO-ESP32-C5-DIP", "XIAO-ESP32-C6-DIP")

#: The page's own path, as the two end-to-end probes above walk it, with a
#: part that is a device: the sketch runs with nothing on the bus, an
#: MCP9808 is added and wired in full, and its temperature is changed twice.
#: **The posts are let land before each run**, as `ANALOG_END_TO_END` says,
#: and each run is two of run's ceiling, which passes a `delay(2)`.
TEMPERATURE_END_TO_END = r"""
api = (url, options) => network(given.server + url, options);
const json = async (url, body) => (await api(url, body === undefined ? {} : {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body) })).json();
page.showBoard(await json(`/api/board/pins?board=${encodeURIComponent(given.board)}`), null);
const run = async () => {
  await json("/api/board/run", { steps: 200000 });
  await json("/api/board/run", { steps: 200000 });
};
const poll = async () => {
  await run();
  page.setLevels((await json("/api/board/state")).pins);
  await settled();
  await run();
  return (await json("/api/board/state")).uart.text;
};
const seen = [await poll()];
const part = await page.addPart("probe_mcp9808");
for (const [pad, terminal] of [["D4", "SDA"], ["D5", "SCL"], ["3V3_OUT", "VDD"],
                               ["GND", "GND"], ["GND", "A0"], ["GND", "A1"],
                               ["GND", "A2"]]) {
  page.connect(pad, part, terminal);
}
await settled();
seen.push(await poll());
const set = [];
for (const celsius of [30.0, -10.5]) {
  set.push(page.setCelsius(0, celsius));
  await settled();
  seen.push(await poll());
}
const devices = (await json("/api/board/state")).devices;
console.log(JSON.stringify({ seen, set, warned, devices }));
"""


def test_the_page_holds_a_temperature_a_sketch_reads_through_the_server(tmp_path):
    """**The temperature, watched.** A sketch reading the MCP9808's TA register
    over `Wire` and printing it when it changes, loaded on a real server;
    the page's own code draws the board and runs it with nothing on the bus,
    so the sketch prints -1. An MCP9808 added to the bench and wired by its
    seven pins is stated to the board at 25.0 C and the sketch prints 49552
    (0xC190: 400 sixteenths, with TA >= TCRIT and TA > TUPPER in bits 15:13,
    Register 5-4 p.24, at the power-on limits of Table 5-3 p.33). 30.0 C
    prints 49632 (0xC1E0) and -10.5 C prints 16216 (0x3F58, TA < TLOWER). The
    session's record holds the temperatures the page posted, in order."""
    from webui import compile as compiler
    from webui import emulator_server, targets

    target = targets.find("riscv32")
    if target is None or not target.selectable:
        pytest.skip("riscv32 is not built; run python tools/build_core.py")
    server = emulator_server.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    watched = {}
    try:
        host, port = server.server_address[:2]
        base = f"http://{host}:{port}"
        for board in TEMPERATURE_WATCHED:
            try:
                built = compiler.build(board, TA_SKETCH)
            except compiler.ToolchainMissing as exc:
                pytest.skip(str(exc))
            assert built.ok, (board, built.diagnostics)
            request = urllib.request.Request(
                base + "/api/board/load", method="POST",
                headers={"Content-Type": "application/json"},
                data=json.dumps({"board": board,
                                 "image": base64.b64encode(built.image).decode(),
                                 "base": hex(compiler.recipe_for(board).base)}).encode())
            with urllib.request.urlopen(request, timeout=30):
                pass
            directory = tmp_path / str(len(watched))
            directory.mkdir()
            got = run_page(directory, TEMPERATURE_END_TO_END,
                           {"server": base, "board": board})
            record = [devices.get("part-1", {}).get("celsius")
                      for _, _levels, _volts, devices
                      in server.RequestHandlerClass.boards.session.inputs]
            watched[board] = (got["seen"], got["set"], got["warned"], record,
                              got["devices"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    for board, (seen, set_, warned, record, devices) in watched.items():
        assert [text.split() for text in seen] == [
            ["-1"], ["-1", "49552"], ["-1", "49552", "49632"],
            ["-1", "49552", "49632", "16216"]], (board, seen)
        assert set_ == [True, True], (board, set_)
        assert warned == [], (board, warned)
        # Before the part there is the one post that states the inputs the
        # sketch left (no device in it), and nothing is posted for the six
        # wires that do not yet make a device.
        assert record[-3:] == [25.0, 30.0, -10.5], (board, record)
        assert set(record[:-3]) == {None}, (board, record)
        # And what the page's poll reads back (slice 4c): the part as the
        # sketch last found it, at the pointer the sketch left on TA, with
        # the very word the sketch printed last.
        assert devices == {"part-1": {
            "address": 0x18, "powered": True, "celsius": -10.5, "pointer": 5,
            "config": 0, "resolution": 3, "ta": 16216}}, (board, devices)
