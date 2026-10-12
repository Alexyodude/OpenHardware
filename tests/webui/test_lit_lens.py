# OpenHardware — a bench part's lens, lit and unlit, by running the page's own code.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What OH-217 split, and why these tests run parts.js rather than read it
#
# `webui/static/parts.js` used to draw a lit lens with one constant, 3.0,
# multiplying both its colour and its glow. The colour is an albedo, the
# fraction of the light reaching a surface that it sends back, so no channel
# of it can pass 1.0 -- and 3.0 put KiCad's LED lens `#b2190d` at 1.34 and the
# buzzer's mark `#ce6d26` at 1.85. The glow is radiance, which can. Cutting the
# one constant to bound the colour halved the glow (OH-214), so the two are
# now separate: the colour's gain is each lens's own, one over its brightest
# channel, and the glow is `LIT`, chosen for the look.
#
# So these tests run `dressPart` and `setPartState` themselves under node, on
# a lens of every colour a part in `tools/import_3d_model.py`'s `PARTS` names,
# in both of the stylesheet's palettes, and read back the material they leave.
#
# ## How the glow is judged, and the light it is judged under
#
# **The proxy is `test_board_led.py`'s (OH-227)**: a material's base colour
# under white light plus its emission, through the page's tone curve (Khronos
# PBR Neutral), encoded to sRGB. **With one change, and it is measured: the
# light is not one.** A lens is a glossy dome standing beside the board, not a
# face looking up at the lamp, and the page draws KiCad's LED lens unlit at
# (100, 11, 7) where unit light gives (177, 17, 0) -- 36.5 apart in CIE76,
# which is most of the change being judged. So each lens is lit by the light
# that makes the proxy's unlit luminance the page's, found from `LENS_SEEN`.
# That fits luminance exactly and not colour: what is left over unlit is
# CIE76 3.8 for the LED and 7.2 for the mark, mostly the room's grey
# reflection, which the page adds to a dark lens and the proxy does not.
#
# **How far off that is lit, measured**, against the page's own pixels at
# `LIT` 1.2: the proxy lands 0.5 (the LED) and 2.2 (the buzzer) from the page
# in CIE76, and its contrast ratio 0.03 and 0.05 UNDER the page's, which is
# the strict direction for a lower bound. Its chroma is over the page's lit
# (74.0 against 73.7, 59.0 against 57.1) and further over it unlit (50.1
# against 46.5, 53.4 against 46.6), so lit-less-unlit chroma is 23.9 and 5.6
# in the proxy against 27.2 and 10.5 in the page. So no error is added to
# either bar: each is harder in the proxy than in the page.

import json
import math
import pathlib
import re
import shutil
import subprocess

import pytest

from tests.webui.test_board_led import (HOOKS, encoded, lab, linear, neutral,
                                        stylesheet_themes)

STATIC = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
BOARD3D = STATIC / "board3d.js"

#: Each lens unlit, as the page draws it: measured 2026-10-13, Playwright's
#: headless Chromium at DPR 1 against `python webui/emulator_server.py`, the
#: Arduino Uno, a 5 mm LED and the 12 mm buzzer added with "Add a part" and
#: wired from pin 13 by pointer drags, the default blink built and run, and
#: stopped by the page's Run/Stop when `/api/board/pins` said pin 13 was low.
#: The mean sRGB over the pixels that change when the lens is hidden, less a
#: pixel at every edge -- 886 for the LED's lens, 34 for the buzzer's mark --
#: at the page's own framing, and the same in both themes.
#:
#: **Keyed by colour, so one colour stands for every part that carries it**:
#: the 3 mm and 10 mm LEDs are judged under the light measured on the 5 mm
#: one, whose lens is the same `#b2190d`. And measured under `LENS_LIGHTING`
#: and `LENS_FINISH`, which a test below compares with the page as it is now.
LENS_SEEN = {"#b2190d": (100, 11, 7), "#ce6d26": (134, 68, 20)}

#: The page's light, framing and tone curve when `LENS_SEEN` was measured, as
#: `webui/static/board3d.js` declares them: each declaration's value with its
#: whitespace collapsed, every occurrence of it, and none for one the page
#: does not set. **A pixel is a fact about this lighting and no other**: the
#: buzzer's mark falls under 3:1 at about 13% more light, and a test reading a
#: stale `LENS_SEEN` would pass or fail on pixels the page no longer draws.
LENS_LIGHTING = {
    "const CAMERA_PULL": ("1.5",),
    "const CAMERA_FROM": ("{ x: 0.1, y: 0.85, z: 0.75 }",),
    "const LIGHTS": ("[ { x: 0.42, y: 0.84, z: 0.35, share: 0.50 }, "
                     "{ x: -0.62, y: 0.58, z: -0.52, share: 0.28 }, "
                     "{ x: -0.18, y: 0.46, z: 0.87, share: 0.22 }, ]",),
    "const BOUNCE": ("{ x: 0.12, y: -0.94, z: 0.32, share: 0.25, casts: false }",),
    "const LIGHT_TOTAL": ("7.0",),
    "const ENVIRONMENT_SHARE": ("0.35",),
    "const NEUTRAL_LIGHT": ("0xffffff",),
    "const STUDIO": ("{ ceiling: 1.0, wall: 0.38, floor: 0.06 }",),
    "const STUDIO_BLUR": ("0.04",),
    "const SOFTBOX": ("{ bright: 72.0, radius: 0.08, reach: 0.62, segments: 48 }",),
    "view.renderer.toneMapping": ("THREE.NeutralToneMapping",),
    "view.renderer.toneMappingExposure": (),
}

#: Each lens's finish when `LENS_SEEN` was measured, as the importer's
#: `finish_for` gives it: metalness, roughness, coat, coat roughness. A
#: glossier lens reflects more of the room and draws a different pixel.
LENS_FINISH = {"#b2190d": (0.0, 0.2, 0.0, 0.0), "#ce6d26": (0.1, 0.6, 0.0, 0.0)}

#: How far a lit lens's luminance must stand from its unlit one, as a WCAG
#: contrast ratio: **3:1, borrowed from SC 2.4.13** (Focus Appearance, Level
#: AAA, keyboard focus indicators), "a contrast ratio of at least 3:1 between
#: the same pixels in the focused and unfocused states". It is the only WCAG
#: criterion that compares the same pixels in two states; WCAG sets no such
#: bar for other state changes (Understanding 1.4.11 says that criterion
#: neither requires the colour changes telling states apart to meet 3:1 nor
#: compares a control's focused and unfocused states). So this is a borrowed
#: number, not a WCAG requirement.
#:
#: **Luminance, and not OH-227's CIE76 bar of pin 13's post (47.7)**, because a
#: lens is a lamp: what says it is on is that it is brighter. The post's bar is
#: a change of hue, near-white to green. The buzzer's mark cannot move that far
#: and keep its colour: at every glow the page was measured at from 0 to 2.0,
#: by halves, it was at most CIE76 38.6 from its unlit look, and it reached
#: 47.7 only at 4, as (253, 186, 160) -- pressed to peach, chroma 30.9 against
#: its unlit 46.6, which the chroma test below refuses. At `LIT` the page
#: measured the LED's change at 47.5 and the mark's at 35.8.
STATE_CONTRAST = 3.0

#: The glows the window is searched over, in hundredths.
GLOWS = [step / 100 for step in range(0, 801)]

#: For each lens and each theme, puts a mesh with that lens's material through
#: `dressPart`, then `setPartState` off and lit, and prints the material each
#: leaves. The palette is the two colours `parts.js` reads from it, made as
#: `board3d.js`'s `readPalette` makes them: `new THREE.Color` on the
#: stylesheet's value. Then a black lens, and what `dressPart` says to it.
PROBE = r"""
import { register } from "node:module";
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import path from "node:path";

const [STATIC, HOOKS, CASES] = process.argv.slice(2);
register(pathToFileURL(HOOKS).href, { data: { static: STATIC } });
const THREE = await import(
  pathToFileURL(path.join(STATIC, "vendor", "three.module.js")).href);
const { dressPart, setPartState } = await import(
  pathToFileURL(path.join(STATIC, "parts.js")).href);

const lensOf = (lens, linear) => {
  const group = new THREE.Group();
  group.add(new THREE.Mesh(new THREE.BufferGeometry(),
    new THREE.MeshStandardMaterial({ name: lens,
                                     color: new THREE.Color(...linear) })));
  return group;
};

const { themes, lenses } = JSON.parse(readFileSync(CASES, "utf-8"));
const materials = [];
for (const [theme, sheet] of Object.entries(themes)) {
  const palette = { line: new THREE.Color(sheet["--line"]),
                    halt: new THREE.Color(sheet["--halt"]) };
  for (const { lens, linear } of lenses) {
    const group = lensOf(lens, linear);
    dressPart(group, { chip: lens, lens, terminals: [] }, palette);
    for (const drive of ["off", "lit"]) {
      setPartState(group, drive, palette);
      const material = group.userData.lens.material;
      materials.push({ theme, lens, drive, base: linear,
                       color: material.color.toArray(),
                       emissive: material.emissive.toArray(),
                       intensity: material.emissiveIntensity });
    }
  }
}
let black = null;
try {
  dressPart(lensOf("#000000", [0, 0, 0]),
            { chip: "a black lens", lens: "#000000", terminals: [] },
            { line: new THREE.Color(), halt: new THREE.Color() });
} catch (error) {
  black = error.message;
}
console.log(JSON.stringify({ materials, black }));
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory) -> dict:
    """What `setPartState` leaves on every lens a part names, off and lit, in
    both themes, and what `dressPart` says to a black lens. The lens colours
    are `PARTS`', converted by the importer's own `linear` -- what it writes
    into the mesh's `baseColorFactor`."""
    from tools.import_3d_model import PARTS, linear as written

    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; the lens is the page's own JS and needs "
                    "one to run")
    lenses = sorted({part.lens for part in PARTS if part.lens is not None})
    directory = tmp_path_factory.mktemp("lit_lens")
    hooks = directory / "hooks.mjs"
    probe = directory / "probe.mjs"
    listing = directory / "cases.json"
    hooks.write_text(HOOKS, encoding="utf-8")
    probe.write_text(PROBE, encoding="utf-8")
    listing.write_text(json.dumps({
        "themes": stylesheet_themes(),
        "lenses": [{"lens": lens,
                    "linear": [written(int(lens[at:at + 2], 16)) for at in (1, 3, 5)]}
                   for lens in lenses],
    }), encoding="utf-8")
    done = subprocess.run([node, str(probe), str(STATIC), str(hooks), str(listing)],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def by_lens(page: dict) -> dict[tuple[str, str], dict[str, dict]]:
    """The materials keyed by (theme, lens), then by drive."""
    pairs = {}
    for each in page["materials"]:
        pairs.setdefault((each["theme"], each["lens"]), {})[each["drive"]] = each
    return pairs


def seen(material: dict, light: float) -> tuple[int, int, int]:
    """The sRGB the page comes to on a material: its colour under `light`,
    plus its emission, through the tone curve the page sets."""
    rgb = [light * base + glow * material["intensity"]
           for base, glow in zip(material["color"], material["emissive"])]
    return tuple(encoded(value) for value in neutral(rgb))


def luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG's relative luminance of sRGB bytes."""
    red, green, blue = (linear(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: tuple[int, int, int], other: tuple[int, int, int]) -> float:
    """WCAG's contrast ratio, (L1 + 0.05) / (L2 + 0.05), lighter over darker."""
    lighter, darker = sorted((luminance(one), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def chroma(rgb: tuple[int, int, int]) -> float:
    """CIELAB chroma: how far from grey."""
    _, a, b = lab(rgb)
    return math.hypot(a, b)


def lighting_now(source: str) -> dict[str, tuple[str, ...]]:
    """Each of `LENS_LIGHTING`'s declarations as `source` makes it now."""
    found = {}
    for name in LENS_LIGHTING:
        pattern = (rf"^const {re.escape(name[len('const '):])} = (.*?);\s*$"
                   if name.startswith("const ")
                   else rf"^\s*{re.escape(name)} = (.*?);\s*$")
        found[name] = tuple(" ".join(value.split())
                            for value in re.findall(pattern, source, re.M | re.S))
    return found


def remeasure(lens: str) -> list[str]:
    """Every way the page's lighting, or this lens's finish, is not what
    `LENS_SEEN` was measured under."""
    from tools.import_3d_model import finish_for

    changed = []
    now = lighting_now(BOARD3D.read_text(encoding="utf-8"))
    for name, was in LENS_LIGHTING.items():
        if now[name] != was:
            changed.append(f"board3d.js's {name} was {was} when LENS_SEEN was "
                           f"measured, and is {now[name]} now")
    finish = finish_for(lens)
    finish = (finish.metalness, finish.roughness, finish.coat, finish.coat_roughness)
    if finish != LENS_FINISH.get(lens):
        changed.append(f"{lens}'s finish was {LENS_FINISH.get(lens)} when "
                       f"LENS_SEEN was measured, and is {finish} now")
    return changed


def light_on(lens: str, off: dict) -> float:
    """The light under which the proxy draws this lens unlit at the page's
    luminance, `LENS_SEEN`. Found by halving: the proxy's luminance only
    rises with the light."""
    if lens not in LENS_SEEN:
        raise AssertionError(
            f"{lens} is a lens a part names and the page was never measured "
            f"drawing it; measure it unlit as `LENS_SEEN` says, and add it")
    changed = remeasure(lens)
    if changed:
        raise AssertionError("re-measure LENS_SEEN: " + "; ".join(changed))
    target = luminance(LENS_SEEN[lens])
    low, high = 0.0, 4.0
    if luminance(seen(off, high)) < target:
        raise AssertionError(f"{lens}: no light up to {high} draws it as bright "
                             f"as the page did, {LENS_SEEN[lens]}")
    for _ in range(60):
        middle = (low + high) / 2
        if luminance(seen(off, middle)) < target:
            low = middle
        else:
            high = middle
    return high


def clears(off: dict, lit: dict, light: float) -> bool:
    """Lit brighter than unlit, by at least `STATE_CONTRAST`."""
    dark, bright = seen(off, light), seen(lit, light)
    return (luminance(bright) > luminance(dark)
            and contrast(dark, bright) >= STATE_CONTRAST)


def colourful(off: dict, lit: dict, light: float) -> bool:
    """Lit at least as far from grey as unlit."""
    return chroma(seen(lit, light)) >= chroma(seen(off, light))


def window(page: dict) -> tuple[float | None, float | None, str]:
    """The glows, to a hundredth, that every lens leaves: the least at which
    each `clears`, and the most at which each is still `colourful`, with
    `parts.js`'s own lit colour and emission and only the strength varied.
    Returned with a sentence saying it, per lens, for a failure message."""
    lows, highs, said = [], [], []
    for (theme, lens), drives in sorted(by_lens(page).items()):
        off, lit = drives["off"], drives["lit"]
        light = light_on(lens, off)
        low = next((glow for glow in GLOWS
                    if clears(off, {**lit, "intensity": glow}, light)), None)
        high = next((glow for glow in reversed(GLOWS)
                     if colourful(off, {**lit, "intensity": glow}, light)), None)
        lows.append(low)
        highs.append(high)
        said.append(f"{theme} {lens} {low} to {high}")
    low = None if None in lows else max(lows)
    high = None if None in highs else min(highs)
    return low, high, (f"the window every lens leaves is {low} to {high} "
                       f"({'; '.join(said)})")


def test_a_lit_lens_is_as_bright_as_a_surface_can_be_and_no_brighter(page):
    """**A lit lens's colour is an albedo, so no channel of it passes 1.0**
    (OH-217), and it is its own hue: every channel over the lens's own
    brightest. That brightest is then exactly 1.0, the most light a surface
    can send back -- so a gain cut further than the bound needs fails too.
    Its emission is the same colour, so it glows in the lens's own hue.

    One shared constant, 3.0, put `#b2190d` at 1.34 and `#ce6d26` at 1.85.
    """
    failures = []
    for (theme, lens), drives in sorted(by_lens(page).items()):
        lit, base = drives["lit"], drives["lit"]["base"]
        peak = max(base)
        own = [value / peak for value in base]
        if max(lit["color"]) > 1.0:
            failures.append(f"{theme}, {lens}: lit, its colour is {lit['color']}, "
                            f"which sends back more light than reaches it")
        for name in ("color", "emissive"):
            if any(abs(a - b) > 1e-9 for a, b in zip(lit[name], own)):
                failures.append(f"{theme}, {lens}: lit, its {name} is {lit[name]}, "
                                f"not its own {base} over its brightest "
                                f"channel, {own}")
    assert not failures, "\n".join(failures)


def test_a_black_lens_is_refused_with_its_values(page):
    """A lens is lit by one over its brightest channel, and black has none:
    `dressPart` says so, with the part, the lens and its colour, at the
    boundary where the mesh arrives -- rather than drawing a lit lens of
    NaN."""
    assert page["black"] == ("a black lens's lens #000000 is [0,0,0] linear, "
                             "which has no hue to light"), page["black"]


def test_lens_seen_was_measured_under_the_light_the_page_has(page):
    """**`LENS_SEEN` is pixels, and pixels are a fact about one lighting.**
    Every lens a part names is checked against `LENS_LIGHTING` and its own
    `LENS_FINISH`, so changing the page's light, framing or tone curve, or a
    lens's finish, fails here with "re-measure LENS_SEEN" rather than letting
    the two tests below judge a glow against pixels the page no longer draws.
    """
    lenses = sorted({lens for _, lens in by_lens(page)})
    changed = {lens: remeasure(lens) for lens in lenses}
    assert not any(changed.values()), "re-measure LENS_SEEN: " + "; ".join(
        f"{lens}: {', '.join(each)}" for lens, each in changed.items() if each)


def test_a_lit_lens_is_unmistakable_from_an_unlit_one(page):
    """**Lit against unlit, the same pixels, at least `STATE_CONTRAST`** in
    luminance, in both themes, for every lens a part names -- each under the
    light the page puts on it."""
    failures = []
    for (theme, lens), drives in sorted(by_lens(page).items()):
        light = light_on(lens, drives["off"])
        if not clears(drives["off"], drives["lit"], light):
            off, lit = seen(drives["off"], light), seen(drives["lit"], light)
            failures.append(
                f"{theme}, {lens}: under light {light:.3f}, unlit {off} and lit "
                f"{lit} are {contrast(off, lit):.2f}:1 apart, under "
                f"{STATE_CONTRAST:.1f}:1; lit, {drives['lit']}")
    assert not failures, "\n".join(failures + [window(page)[2]])


def test_a_lit_lens_is_at_least_as_colourful_as_an_unlit_one(page):
    """**Lit, a lens is at least as far from grey as it is unlit**, in CIELAB
    chroma. Past the tone curve's knee Khronos PBR Neutral presses a colour
    toward white, and a glow strong enough clears `STATE_CONTRAST` easily by
    drawing a red LED pink and the buzzer's orange mark peach: the blowout
    `LIT` stops short of, and what the shared 3.0 drew.

    **Chroma, and not hue.** On screen the tone curve turns both lenses a few
    degrees toward red as they brighten -- at `LIT`, 37.7 to 32.0 degrees for
    the LED and 60.5 to 54.5 for the mark in the proxy, 36.0 to 31.6 and 57.7
    to 53.4 in the page -- and nothing here bounds that. The hue that is held
    is the material's, by the first test above."""
    failures = []
    for (theme, lens), drives in sorted(by_lens(page).items()):
        light = light_on(lens, drives["off"])
        if not colourful(drives["off"], drives["lit"], light):
            off, lit = seen(drives["off"], light), seen(drives["lit"], light)
            failures.append(
                f"{theme}, {lens}: under light {light:.3f}, lit {lit} has chroma "
                f"{chroma(lit):.1f}, under unlit {off}'s {chroma(off):.1f}; "
                f"lit, {drives['lit']}")
    assert not failures, "\n".join(failures + [window(page)[2]])


def test_the_glow_is_the_middle_of_the_window_every_lens_leaves(page):
    """**`LIT` is the middle, to a tenth, of the glows that hold both bars on
    every lens**, which is what `parts.js` says it is. The window is printed
    and not written down, because a lens added to `PARTS` moves it.

    **If a lens closes the window**, no one glow serves every lens; the
    fallback `parts.js` names is a glow per lens, each from the same bars."""
    low, high, said = window(page)
    glows = {drives["lit"]["intensity"] for drives in by_lens(page).values()}
    assert len(glows) == 1, f"the lenses glow at {sorted(glows)}, not at one LIT"
    [glow] = glows
    assert low is not None and high is not None and low <= high, (
        f"no one glow holds both bars on every lens: {said}. Give each lens a "
        f"glow of its own")
    assert abs(glow - (low + high) / 2) <= 0.05 + 1e-9, (
        f"LIT is {glow}, not the middle to a tenth of {low} to {high}, which is "
        f"{(low + high) / 2:.3f}: {said}")
