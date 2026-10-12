# OpenHardware — a board's own LED, lit, seen by running the page's own code.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What OH-227 found, and why these tests run the page rather than read it
#
# Seen in the page on 2026-10-12, the Arduino Uno blinking pin 13: the board's
# own "L" LED went from (211, 210, 203) to (209, 215, 204) mean sRGB when the
# pin went high, in both themes, while pin 13's post beside it went from
# (221, 220, 217) to (113, 207, 145). A person watching the blink saw the pin
# and not the lamp.
#
# Two things made it so, and a source grep sees neither. The lamp was a box
# exactly the LED's own measured bounds, so its faces lay on the vendor's own
# faces and the depth buffer chose between them pixel by pixel -- a mottle of
# the vendor's cream body and the box's pale `--line`, lit and unlit alike. And
# where the box did show, it added the palette's `high` as light to a
# near-white surface, which in the light theme, where `high` is the darker
# colour, moves it a few levels.
#
# So these tests run `webui/static/board3d.js` itself under node -- `showBoard`,
# `loadModel`, `setLevels` and `refreshTheme`, through hooks that resolve the
# page's import map, the way OH-215's tests in `test_board3d.py` do -- cast the
# ray the page's own camera sends through the LED, and take the colour of what
# it meets from that surface's material.
#
# ## What the colour is, and what it is not
#
# **A proxy, not a render.** There is no WebGL here. The colour of a surface is
# its base colour under unit white light plus its emission, put through the
# tone curve the page sets (Khronos PBR Neutral, as `three.js` implements it)
# and encoded to sRGB. It leaves out the lights' angles, the room's
# reflection and the shadows. How far off that is was measured where the page
# and the proxy show the same surface -- the LED's body unlit -- and the
# threshold below is raised by exactly that.

import json
import math
import pathlib
import shutil
import struct
import subprocess

import pytest

STATIC = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
SHEET = STATIC / "emulator.css"
UNO_MODEL = STATIC / "models" / "Arduino-Uno.glb"

#: Pin 13's post low and high, as the ticket measured it in the page (OH-227,
#: 2026-10-12), mean sRGB over the same pixels of device-scale screenshots,
#: dark theme. The fix's own look measured the post at (223, 221, 218) and
#: (114, 208, 145).
POST_LOW = (221, 220, 217)
POST_HIGH = (113, 207, 145)

#: The LED's body unlit, as the page draws it with nothing over it: measured
#: 2026-10-12 at b407852, mean sRGB of the 66 pixels inside the projected top
#: face of the Uno's "L" solid inset by a pixel, at the page's own framing,
#: DPR 1, the same in both themes. **Not the ticket's (211, 210, 203)**, which
#: was the mean over the old lamp's mottle -- the vendor's body and the box's
#: `--line` together -- and so not a measurement of the body at all.
BODY_SEEN = (229, 226, 209)

#: The Uno's "L" LED body: KiCad's `PLASTIC-WHITE-01`, the key
#: `tools/import_3d_model.py`'s `FINISHES` gives the chip LEDs' body, as the
#: composed model carries it (and the synthetic model below copies).
BODY = "#e4e3cf"


def linear(byte: int) -> float:
    """One sRGB byte as linear light."""
    value = byte / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def encoded(value: float) -> int:
    """Linear light as one sRGB byte, clipped as the canvas clips it."""
    value = min(1.0, max(0.0, value))
    value = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return round(value * 255)


#: Where Khronos PBR Neutral starts to compress, after its toe offset. A lit
#: lamp held under it is drawn as the stylesheet's own colour and not pressed
#: toward white (`LAMP_GLOW`).
KNEE = 0.8 - 0.04


def toe(rgb: list[float]) -> float:
    """What Khronos PBR Neutral takes off every channel before anything else:
    a curve under the darkest channel near black, 0.04 above it."""
    least = min(rgb)
    return least - 6.25 * least * least if least < 0.08 else 0.04


def neutral(rgb: list[float]) -> list[float]:
    """Khronos PBR Neutral, as `three.js` r185's `NeutralToneMapping` computes
    it (`vendor/three.module.js`'s shader chunk): the page sets this curve, so
    a colour is compared after it and not before."""
    start, desaturation = KNEE, 0.15
    offset = toe(rgb)
    rgb = [value - offset for value in rgb]
    peak = max(rgb)
    if peak < start:
        return rgb
    d = 1 - start
    new_peak = 1 - d * d / (peak + d - start)
    rgb = [value * new_peak / peak for value in rgb]
    g = 1 - 1 / (desaturation * (peak - new_peak) + 1)
    return [value * (1 - g) + new_peak * g for value in rgb]


def lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB bytes as CIELAB under D65."""
    r, g, b = (linear(value) for value in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    return (116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z)))


def delta_e(one: tuple[int, int, int], other: tuple[int, int, int]) -> float:
    """CIE76: the distance between two colours in CIELAB."""
    return math.dist(lab(one), lab(other))


def proxy(surface: dict) -> tuple[int, int, int]:
    """The sRGB a surface's material comes to: base colour under unit white
    light, plus emission, through the page's tone curve. `color` and
    `emissive` are `THREE.Color`'s own components, which are linear."""
    rgb = [base + glow * surface["intensity"]
           for base, glow in zip(surface["color"], surface["emissive"])]
    return tuple(encoded(value) for value in neutral(rgb))


def hex_bytes(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[at:at + 2], 16) for at in (1, 3, 5))


#: The proxy's own error, where it and the page show the same surface: the
#: LED's body, unlit, which the proxy draws from its material alone.
PROXY_ERROR = delta_e(
    proxy({"color": [linear(byte) for byte in hex_bytes(BODY)],
           "emissive": [0.0, 0.0, 0.0], "intensity": 0.0}),
    BODY_SEEN)

#: How far, in CIE76, what the page's camera sees at a board's LED has to move
#: between low and high: **as far as pin 13's post moved in the page, plus the
#: proxy's own error.** The post's change is the one the ticket called plainly
#: green, and the lamp's job is to be at least as plain as the pin beside it.
#:
#: **The error is a bound, not a tolerance.** The lamp's change is computed
#: through the proxy and the post's was measured off pixels, so a proxy that
#: misplaces the unlit end by `PROXY_ERROR` could overstate the lamp's change
#: by as much; adding it means a lamp that clears this in the proxy clears the
#: post in the page. It bounds the unlit end only. The lit end is the lamp's
#: own emission, which the proxy draws without the room's reflection; the
#: fix's look measured it 2.4 (light) and 2.9 (dark) off the proxy, and the
#: page's own change, 57.2 and 51.7, cleared the post directly. The LED as the
#: ticket found it moved 3.5.
UNMISTAKABLE = delta_e(POST_LOW, POST_HIGH) + PROXY_ERROR


def stylesheet_themes() -> dict[str, dict[str, str]]:
    """Each theme's custom properties as `emulator.css` declares them: the
    light theme's `:root` and the dark theme's `[data-theme="dark"]`, which is
    the block the page's own toggle switches to."""
    sheet = SHEET.read_text(encoding="utf-8")

    def block(opening: str) -> dict[str, str]:
        body = sheet.split(opening, 1)[1].split("}", 1)[0]
        pairs = (line.strip().rstrip(";").split(":", 1)
                 for line in body.splitlines() if line.strip().startswith("--"))
        return {name.strip(): value.strip() for name, value in pairs}

    return {"light": block(":root {"), "dark": block(':root[data-theme="dark"] {')}


#: Node module hooks: the page's import map, and the probe's handle on `view`
#: and `loadModel`, appended to board3d.js as it loads. The file on disk is
#: not touched.
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
           source: text + "\nexport const __probe = { view, loadModel };\n" };
}
"""

#: For each case and each pair of themes (drawn in, then switched to with the
#: page's own `refreshTheme`), draws the board with `showBoard` and
#: `loadModel`, sets the LED's pin low and then high with `setLevels`, and
#: casts the ray from where `showBoard` put the camera through the centre of
#: the LED's measured box. Prints, per level, every visible surface that ray
#: meets, nearest first: whether it is the lamp, how far along the ray in
#: model millimetres, and its material's colour, emission and intensity; and
#: the depth buffer's resolution at that distance, in model millimetres.
PROBE = r"""
import { register } from "node:module";
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import path from "node:path";

const [STATIC, HOOKS, CASES] = process.argv.slice(2);
register(pathToFileURL(HOOKS).href, { data: { static: STATIC } });
const THREE = await import(
  pathToFileURL(path.join(STATIC, "vendor", "three.module.js")).href);
const page = await import(pathToFileURL(path.join(STATIC, "board3d.js")).href);
const { view, loadModel } = page.__probe;

globalThis.fetch = async (file) => {
  const bytes = readFileSync(file);
  return { ok: true, arrayBuffer: async () => bytes.buffer.slice(
    bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
};
// The stylesheet the page's own `readPalette` reads, one theme at a time.
let sheet = {};
globalThis.document = { documentElement: {} };
globalThis.getComputedStyle = () => ({
  getPropertyValue: (name) => sheet[name] ?? "" });
// What `mount` would have made: enough of a scene for `showBoard` to draw in
// and frame. three's default near plane, 0.1, is the page's.
view.renderer = {};
view.scene = new THREE.Scene();
view.camera = new THREE.PerspectiveCamera();
view.controls = { target: new THREE.Vector3(), update() {} };

const { themes, cases } = JSON.parse(readFileSync(CASES, "utf-8"));
// `Raycaster` does not test visibility, and the page does not draw a hidden
// mesh, so a surface counts only if it and everything above it is shown.
const shown = (object) => {
  for (let at = object; at; at = at.parent) if (!at.visible) return false;
  return true;
};
const values = (material) => ({
  color: material.color.toArray(), emissive: material.emissive.toArray(),
  intensity: material.emissiveIntensity,
  offsetUnits: material.polygonOffset ? material.polygonOffsetUnits : 0,
  offsetFactor: material.polygonOffset ? material.polygonOffsetFactor : 0 });

const out = [];
for (const { layout, file, component, pin } of cases) {
  for (const [drawn, now] of [["light", "light"], ["light", "dark"],
                              ["dark", "dark"], ["dark", "light"]]) {
    sheet = themes[drawn];
    page.refreshTheme();
    page.showBoard(layout, null);
    await loadModel(layout, { file });
    sheet = themes[now];
    page.refreshTheme();
    const model = view.model;
    const solid = view.solids.find((each) => each.name === component);
    if (!solid) throw new Error(`${layout.board}: no solid named ${component}`);
    const lamp = view.leds.find((led) => led.label === pin)?.mesh ?? null;
    view.board.updateWorldMatrix(true, true);
    const centre = model.localToWorld(new THREE.Vector3(
      ...[0, 1, 2].map((axis) => (solid.min[axis] + solid.max[axis]) / 2)));
    const from = view.camera.position.clone();
    const distance = from.distanceTo(centre);
    const scale = model.scale.x;
    const ray = new THREE.Raycaster(
      from, centre.clone().sub(from).normalize(), 0, distance * 2);
    for (const level of ["low", "high"]) {
      page.setLevels({ [pin]: level });
      const surfaces = ray.intersectObject(model, true)
        .filter((hit) => shown(hit.object))
        .map((hit) => ({ lamp: hit.object === lamp, at: hit.distance / scale,
                         name: hit.object.material.name ?? "",
                         ...values(hit.object.material) }));
      out.push({ board: layout.board, drawn, now, level,
                 high: view.palette.states.high.toArray(),
                 lamp: lamp ? values(lamp.material) : null,
                 resolution: distance ** 2 / (view.camera.near * 2 ** 24) / scale,
                 surfaces });
    }
  }
}
console.log(JSON.stringify(out));
"""


def seen_by_the_page(directory: pathlib.Path, cases: list[dict]) -> list[dict]:
    """The probe's report for each case; skips without node, as OH-215's
    placement tests do."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; the lamp is the page's own JS and needs "
                    "one to run")
    hooks = directory / "hooks.mjs"
    probe = directory / "probe.mjs"
    listing = directory / "cases.json"
    hooks.write_text(HOOKS, encoding="utf-8")
    probe.write_text(PROBE, encoding="utf-8")
    listing.write_text(json.dumps({"themes": stylesheet_themes(), "cases": cases}),
                       encoding="utf-8")
    done = subprocess.run([node, str(probe), str(STATIC), str(hooks), str(listing)],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def seen(look: dict) -> dict:
    """The surface the camera shows at the LED.

    The lamp, where there is one on the ray, **only if it is in front of the
    nearest other surface by more than the depth buffer resolves** at that
    distance -- a 24-bit buffer, `resolution` in the probe. Closer than that
    the GPU picks pixel by pixel, which is how the page came to draw the LED
    as a mottle of the vendor's cream body and the lamp's pale `--line`, lit
    and unlit alike; that case is taken as the other surface, because a lamp
    that only sometimes wins its own pixels is not one a reader can be sure of
    seeing.

    A lamp's polygon offset counts toward its lead as what `glPolygonOffset`
    makes it: `-units` steps of the buffer toward the camera. A slope term
    would only add to that lead, and `held` requires the lamp to have none,
    because at grazing angles it is what drew the lamp through the IOH
    header."""
    surfaces = look["surfaces"]
    if not surfaces:
        raise AssertionError(f"{look['board']}: the camera's ray through the "
                             f"LED meets nothing: {look}")
    lamp = next((each for each in surfaces if each["lamp"]), None)
    other = next((each for each in surfaces if not each["lamp"]), None)
    if lamp is None or other is None:
        return lamp or other
    step = look["resolution"]
    lead = other["at"] - lamp["at"] + max(0.0, -lamp["offsetUnits"]) * step
    return lamp if lead > step else other


def changes(looks: list[dict]) -> list[tuple]:
    """Per board and pair of themes: what is seen low and high, and how far
    apart the two are."""
    pairs = {}
    for look in looks:
        pairs.setdefault((look["board"], look["drawn"], look["now"]), {})[
            look["level"]] = look
    rows = []
    for (board, drawn, now), by in sorted(pairs.items()):
        low, high = proxy(seen(by["low"])), proxy(seen(by["high"]))
        rows.append((board, drawn, now, low, high, delta_e(low, high), by))
    return rows


def body_box_glb(path: pathlib.Path, low: list[float], high: list[float]) -> None:
    """A model that is one chip LED: a box in the KiCad white of the Uno's
    "L", filling exactly the `solids` box it states -- which is what the
    composer measures a placed component's box from, so the lamp and the body
    share their faces as they do on the Uno."""
    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1])
               for z in (low[2], high[2])]
    middle = [(a + b) / 2 for a, b in zip(low, high)]
    normals = []
    for corner in corners:
        out = [c - m for c, m in zip(corner, middle)]
        length = math.hypot(*out)
        normals.append(tuple(value / length for value in out))
    # Corner index = 4x + 2y + z over (low, high) on each axis.
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6),
             (0, 2, 6, 4), (1, 5, 7, 3)]
    indices = [index for a, b, c, d in faces for index in (a, b, c, a, c, d)]
    binary = (b"".join(struct.pack("<3f", *corner) for corner in corners)
              + b"".join(struct.pack("<3f", *normal) for normal in normals)
              + struct.pack(f"<{len(indices)}I", *indices))
    document = json.dumps({
        "asset": {"version": "2.0", "extras": {
            "units": "mm", "pcb": {"long": 20.0, "short": 10.0, "thickness": 1.6},
            "solids": [{"name": "L", "min": low, "max": high}]}},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": offset, "byteLength": length}
                        for offset, length in ((0, 96), (96, 96),
                                               (192, 4 * len(indices)))],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 8, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5125, "count": len(indices),
             "type": "SCALAR"},
        ],
        "materials": [{"name": BODY, "pbrMetallicRoughness": {
            "baseColorFactor": [*(linear(byte) for byte in hex_bytes(BODY)), 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 0.65}}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                    "indices": 2, "material": 0}]}],
    }).encode("utf-8")
    document += b" " * (-len(document) % 4)
    body = (struct.pack("<II", len(document), 0x4E4F534A) + document
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def held(rows: list[tuple]) -> None:
    """Every row's lit-minus-unlit at least `UNMISTAKABLE`; unlit, the
    vendor's own LED seen and nothing drawn over it; and lit, the lamp in the
    theme now on rather than the one it was drawn in.

    And what `LAMP_GLOW`'s comment claims for the lit lamp, which the change
    alone does not hold -- any strength from 0.5 to 2.0 clears it: that it is
    seen as exactly what the tone curve makes of the theme's own `high`, and
    that it is under the curve's `KNEE`, so not pressed toward white. And that
    its polygon offset has no slope term, which drew it through the IOH header
    at grazing angles."""
    failures = []
    for board, drawn, now, low, high, change, by in rows:
        lit = by["high"]["lamp"]
        if lit is not None:
            radiance = [base + glow * lit["intensity"]
                        for base, glow in zip(lit["color"], lit["emissive"])]
            if max(radiance) - toe(radiance) >= KNEE:
                failures.append(
                    f"{board}, drawn {drawn}, shown {now}: lit, the lamp's "
                    f"brightest channel {max(radiance):.3f} less the toe "
                    f"{toe(radiance):.3f} is at or over the knee {KNEE:.2f}, so "
                    f"the tone curve presses it toward white")
            own = proxy({"color": [0.0, 0.0, 0.0], "emissive": by["high"]["high"],
                         "intensity": 1.0})
            if high != own:
                failures.append(
                    f"{board}, drawn {drawn}, shown {now}: lit, the camera sees "
                    f"{high}, not the theme's own `high` through the tone "
                    f"curve, {own}")
            if lit["offsetFactor"] != 0:
                failures.append(
                    f"{board}, drawn {drawn}, shown {now}: the lamp's polygon "
                    f"offset has a slope term, {lit['offsetFactor']}, which "
                    f"draws it through a part in front at grazing angles")
        if seen(by["low"])["lamp"]:
            failures.append(f"{board}, drawn {drawn}, shown {now}: unlit, the "
                            f"camera sees the lamp, {seen(by['low'])}, over "
                            f"the vendor's own LED")
        if change < UNMISTAKABLE:
            failures.append(
                f"{board}, drawn {drawn}, shown {now}: low {low} -> high {high} "
                f"is {change:.1f}, under {UNMISTAKABLE:.1f}; seen low "
                f"{seen(by['low'])}, high {seen(by['high'])}; the lamp "
                f"{by['high']['lamp']}; resolution "
                f"{by['high']['resolution']:.4f} mm")
        lamp = by["high"]["lamp"]
        if lamp is None or any(abs(a - b) > 1e-6 for a, b in
                               zip(lamp["emissive"], by["high"]["high"])):
            failures.append(f"{board}, drawn {drawn}, shown {now}: lit, the "
                            f"lamp emits {lamp and lamp['emissive']}, not the "
                            f"`high` of the theme on, {by['high']['high']}")
    assert not failures, "\n".join(failures)


def test_a_lit_board_led_moves_as_far_as_the_pin_beside_it_in_both_themes(tmp_path):
    """**OH-227: the lamp changed by 3.5 where the pin beside it changed by
    47.7**, both in CIE76 off the page's own pixels.

    One chip LED, 1.25 by 1.1 by 2.0 mm as the Uno's "L" is, in the KiCad
    white its model carries, on a model of nothing else -- so this runs on a
    fresh checkout with no model built. Drawn in each theme and switched to
    each with the page's own `refreshTheme`, because the reader's toggle is
    how a board drawn in one theme comes to be seen in the other.

    Held by `held` in all four.
    """
    model = tmp_path / "lamp.glb"
    body_box_glb(model, [-0.625, 1.6, -1.0], [0.625, 2.7, 1.0])
    layout = {"board": "one chip LED", "width": 200, "height": 100,
              "px_per_mm": 8.0, "supply": None, "led_parts": {"L": "13"},
              "pads": [{"label": label, "pin": label, "chip_pin": None,
                        "x": x, "y": y, "group": "header", "state": "unknown"}
                       for label, x, y in (("A", 30.0, 30.0), ("B", 170.0, 70.0))]}
    looks = seen_by_the_page(tmp_path, [{"layout": layout, "file": str(model),
                                         "component": "L", "pin": "13"}])
    held(changes(looks))


def test_the_unos_own_l_led_moves_as_far_as_its_pin_in_both_themes(tmp_path):
    """The same claim on the board the ticket watched: the composed Arduino
    Uno, its pad map and its `LED_PARTS` as the page is given them, and the
    vendor's own LED body under the lamp. The model is gitignored, so this
    skips where nobody has run `tools/compose_board_3d.py`."""
    if not UNO_MODEL.is_file():
        pytest.skip(f"no {UNO_MODEL}; run tools/compose_board_3d.py")
    from webui import api
    from webui.boards import atmega328p

    layout = api.pad_view("Arduino Uno", atmega328p, None)
    [(component, pin)] = layout["led_parts"].items()
    looks = seen_by_the_page(tmp_path, [{"layout": layout, "file": str(UNO_MODEL),
                                         "component": component, "pin": pin}])
    held(changes(looks))
