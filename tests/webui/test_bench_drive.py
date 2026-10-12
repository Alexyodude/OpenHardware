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
    const bytes = readFileSync(given.part);
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
    binary = (struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 0, 1)
              + struct.pack("<9f", 0, 1, 0, 0, 1, 0, 0, 1, 0)
              + struct.pack("<3I", 0, 1, 2))
    document = json.dumps({
        "asset": {"version": "2.0", "extras": {
            "chip": "probe_resistor", "label": "220 ohm resistor", "lens": None,
            "terminals": [{"name": "lead A", "at": [-3.8, -0.5, 0]},
                          {"name": "lead B", "at": [3.8, -0.5, 0]}],
            "electrical": {"kind": "resistor", "ohms": 231.0, "note": "",
                           "cited": {"ohms": "RESISTOR_ELECTRICAL's"}}}},
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
    part = directory / "resistor.glb"
    resistor_glb(part)
    hooks.write_text(HOOKS, encoding="utf-8")
    script.write_text(PRELUDE + probe, encoding="utf-8")
    listing.write_text(json.dumps({**case, "part": str(part)}), encoding="utf-8")
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
#: added by default. `api` refuses the first `given.refusing` posts with
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
const after = [];
const notes = [];
const last = (at) => at ?? parts.length - 1;
for (const [verb, ...rest] of given.steps) {
  if (verb === "show") page.showBoard(layouts[rest[0]], null);
  if (verb === "levels") page.setLevels(rest[0]);
  if (verb === "add") parts.push(await page.addPart("probe_resistor"));
  if (verb === "connect") {
    wires[`${rest[0]}@${last(rest[2])}`] = page.connect(rest[0], parts[last(rest[2])], rest[1]).id;
  }
  if (verb === "disconnect") page.disconnect(wires[`${rest[0]}@${last(rest[1])}`]);
  await settled();
  after.push(posted.length);
  notes.push(page.circuit()?.note ?? null);
}
console.log(JSON.stringify({ posted, after, notes, warned }));
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
    assert got["posted"] == [
        {"board": BOARD, "levels": every},
        {"board": BOARD, "levels": {**every, "D1": "low"}},
        {"board": BOARD, "levels": every},
    ], got["posted"]
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
    assert got["posted"] == [{"board": BOARD, "levels": every}] * 2, got["posted"]


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
            record = [levels.get(pin_in) for _, levels, _volts
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
