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
# So these tests run `setPartState` itself under node, on a lens of every
# colour a part in `tools/import_3d_model.py`'s `PARTS` names, in both of the
# stylesheet's palettes, and read back the material it leaves.
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
#
# **How far off that is, measured**, against the page's own pixels at `LIT`
# 1.2: lit, the proxy lands 0.5 (the LED) and 2.2 (the buzzer) from the page
# in CIE76, and its contrast ratio 0.03 and 0.05 UNDER the page's, which is
# the strict direction for a lower bound. Its chroma is over the page's lit
# (74.0 against 73.7, 59.0 against 57.1) and further over it unlit (50.1
# against 46.5, 53.4 against 46.6) -- the page adds the room's grey
# reflection to the dark lens -- so lit-less-unlit chroma is 23.9 and 5.6 in
# the proxy against 27.2 and 10.5 in the page. So no error is added to either
# bar: each is harder in the proxy than in the page.

import json
import math
import pathlib
import shutil
import subprocess

import pytest

from tests.webui.test_board_led import (HOOKS, encoded, lab, linear, neutral,
                                        stylesheet_themes)

STATIC = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"

#: Each lens unlit, as the page draws it: measured 2026-10-13, Playwright's
#: headless Chromium at DPR 1 against `python webui/emulator_server.py`, the
#: Arduino Uno, a 5 mm LED and the 12 mm buzzer added with "Add a part" and
#: wired from pin 13 by pointer drags, the default blink built and run, and
#: stopped by the page's Run/Stop when `/api/board/pins` said pin 13 was low.
#: The mean sRGB over the pixels that change when the lens is hidden, less a
#: pixel at every edge -- 886 for the LED's lens, 34 for the buzzer's mark --
#: at the page's own framing, and the same in both themes.
LENS_SEEN = {"#b2190d": (100, 11, 7), "#ce6d26": (134, 68, 20)}

#: How far a lit lens's luminance must stand from its unlit one, as a WCAG
#: contrast ratio: **3:1, the bar WCAG 2.2 sets for a state change on the same
#: pixels** -- SC 2.4.13, Focus Appearance, "a contrast ratio of at least 3:1
#: between the same pixels in the focused and unfocused states".
#:
#: **Luminance, and not OH-227's CIE76 bar of pin 13's post (47.7)**, because a
#: lens is a lamp: what says it is on is that it is brighter. The post's bar is
#: a change of hue, near-white to green. A lens that stays its own hue cannot
#: move that far: at every glow the page was measured at from 0 to 2.0, by
#: halves, the buzzer's mark was at most CIE76 38.6 from its unlit look, and
#: it reached 47.7 only at 4, as (253, 186, 160) -- pressed to peach, chroma 30.9 against its unlit
#: 46.6, which `test_a_lit_lens_is_still_its_own_colour` refuses. At `LIT`
#: the page measured the LED's change at 47.5 and the mark's at 35.8.
STATE_CONTRAST = 3.0

#: For each lens and each theme, puts a mesh with that lens's material through
#: `dressPart`, then `setPartState` off and lit, and prints the material each
#: leaves. The palette is the two colours `parts.js` reads from it, made as
#: `board3d.js`'s `readPalette` makes them: `new THREE.Color` on the
#: stylesheet's value.
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

const { themes, lenses } = JSON.parse(readFileSync(CASES, "utf-8"));
const out = [];
for (const [theme, sheet] of Object.entries(themes)) {
  const palette = { line: new THREE.Color(sheet["--line"]),
                    halt: new THREE.Color(sheet["--halt"]) };
  for (const { lens, linear } of lenses) {
    const group = new THREE.Group();
    group.add(new THREE.Mesh(new THREE.BufferGeometry(),
      new THREE.MeshStandardMaterial({ name: lens,
                                       color: new THREE.Color(...linear) })));
    dressPart(group, { chip: lens, lens, terminals: [] }, palette);
    for (const drive of ["off", "lit"]) {
      setPartState(group, drive, palette);
      const material = group.userData.lens.material;
      out.push({ theme, lens, drive, base: linear,
                 color: material.color.toArray(),
                 emissive: material.emissive.toArray(),
                 intensity: material.emissiveIntensity });
    }
  }
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def materials(tmp_path_factory) -> list[dict]:
    """What `setPartState` leaves on every lens a part names, off and lit, in
    both themes. The lens colours are `PARTS`', converted by the importer's
    own `linear` -- what it writes into the mesh's `baseColorFactor`."""
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


def by_lens(materials: list[dict]) -> dict[tuple[str, str], dict[str, dict]]:
    """The materials keyed by (theme, lens), then by drive."""
    pairs = {}
    for each in materials:
        pairs.setdefault((each["theme"], each["lens"]), {})[each["drive"]] = each
    return pairs


def seen(material: dict, light: float) -> tuple[int, int, int]:
    """The sRGB the page comes to on a material: its colour under `light`,
    plus its emission, through the tone curve the page sets."""
    rgb = [light * base + glow * material["intensity"]
           for base, glow in zip(material["color"], material["emissive"])]
    return tuple(encoded(value) for value in neutral(rgb))


def luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.2's relative luminance of sRGB bytes."""
    red, green, blue = (linear(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: tuple[int, int, int], other: tuple[int, int, int]) -> float:
    """WCAG 2.2's contrast ratio, (L1 + 0.05) / (L2 + 0.05), lighter over darker."""
    lighter, darker = sorted((luminance(one), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def chroma(rgb: tuple[int, int, int]) -> float:
    """CIELAB chroma: how far from grey."""
    _, a, b = lab(rgb)
    return math.hypot(a, b)


def light_on(lens: str, off: dict) -> float:
    """The light under which the proxy draws this lens unlit at the page's
    luminance, `LENS_SEEN`. Found by halving: the proxy's luminance only
    rises with the light."""
    if lens not in LENS_SEEN:
        raise AssertionError(
            f"{lens} is a lens a part names and the page was never measured "
            f"drawing it; measure it unlit as `LENS_SEEN` says, and add it")
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


def test_a_lit_lens_is_as_bright_as_a_surface_can_be_and_no_brighter(materials):
    """**A lit lens's colour is an albedo, so no channel of it passes 1.0**
    (OH-217), and it is its own hue: every channel over the lens's own
    brightest. That brightest is then exactly 1.0, the most light a surface
    can send back -- so a gain cut further than the bound needs fails too.

    One shared constant, 3.0, put `#b2190d` at 1.34 and `#ce6d26` at 1.85.
    """
    failures = []
    for (theme, lens), drives in sorted(by_lens(materials).items()):
        lit, base = drives["lit"]["color"], drives["lit"]["base"]
        peak = max(base)
        own = [value / peak for value in base]
        if max(lit) > 1.0:
            failures.append(f"{theme}, {lens}: lit, its colour is {lit}, which "
                            f"sends back more light than reaches it")
        if any(abs(a - b) > 1e-9 for a, b in zip(lit, own)):
            failures.append(f"{theme}, {lens}: lit, its colour is {lit}, not "
                            f"its own {base} over its brightest channel, {own}")
    assert not failures, "\n".join(failures)


def test_a_lit_lens_is_unmistakable_from_an_unlit_one(materials):
    """**Lit against unlit, the same pixels, at least `STATE_CONTRAST`** in
    luminance, in both themes, for every lens a part names -- each under the
    light the page puts on it."""
    failures = []
    for (theme, lens), drives in sorted(by_lens(materials).items()):
        light = light_on(lens, drives["off"])
        off, lit = seen(drives["off"], light), seen(drives["lit"], light)
        ratio = contrast(off, lit)
        if luminance(lit) <= luminance(off) or ratio < STATE_CONTRAST:
            failures.append(
                f"{theme}, {lens}: under light {light:.3f}, unlit {off} and lit "
                f"{lit} are {ratio:.2f}:1 apart, under {STATE_CONTRAST:.1f}:1; "
                f"lit, {drives['lit']}")
    assert not failures, "\n".join(failures)


def test_a_lit_lens_is_still_its_own_colour(materials):
    """**Lit, a lens is at least as colourful as it is unlit**, in CIELAB
    chroma -- the same hue brighter, which is what `setPartState` says a lit
    LED is. Past the tone curve's knee Khronos PBR Neutral presses a colour
    toward white, and a glow strong enough clears `STATE_CONTRAST` easily by
    drawing a red LED pink and the buzzer's orange mark peach: the blowout
    `LIT` stops short of, and what the shared 3.0 drew."""
    failures = []
    for (theme, lens), drives in sorted(by_lens(materials).items()):
        light = light_on(lens, drives["off"])
        off, lit = seen(drives["off"], light), seen(drives["lit"], light)
        if chroma(lit) < chroma(off):
            failures.append(
                f"{theme}, {lens}: under light {light:.3f}, lit {lit} has chroma "
                f"{chroma(lit):.1f}, under unlit {off}'s {chroma(off):.1f}; "
                f"lit, {drives['lit']}")
    assert not failures, "\n".join(failures)
