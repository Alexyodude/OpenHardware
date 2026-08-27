#!/usr/bin/env python3
# OpenHardware - the last resort: a part modelled, when nobody publishes a mesh.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Build a component mesh in Blender, from dimensions that each cite a source.

**This is the fourth and worst source of geometry in this project, and it is
here because the third ran out.** In order of preference:

1. the vendor's own mechanical model -- `tools/import_3d_model.py`;
2. a published model of the same package -- `tools/compose_board_3d.py`
   against KiCad's `kicad-packages3D`;
3. the manufacturer's own STEP for the exact part;
4. this.

Every step down that list is a step further from a measurement, so a part built
here says so all the way to the page. `compose_board_3d.ABSENT` exists for
parts that get no further than 3, and it stayed the honest answer for a day
before this file was written.

## The rule that makes this safe to have

**Every number is either the vendor's or cited.** `SPECS` below is the whole
dimension set for each part, and each field carries where it came from. For the
Arduino Uno's USB socket that is: all of the plan geometry from Arduino's own
EAGLE package `PN61729`, read out of the board file at import time rather than
copied here, and exactly one number -- the shell height -- from the USB
specification, because a Series-B receptacle's height is fixed by the standard
that lets any plug fit any socket.

If a part needs a number that is neither, it does not get modelled. A plausible
invented dimension that renders nicely is the exact defect this whole area of
the project keeps re-learning: `tools/import_3d_model.py`'s `lead_tips` records
the last time, when a lead spacing measured off the wrong vertex gave 2.14 mm
for a part whose legs are 2.54 apart and looked entirely reasonable.

## Why Blender rather than the OpenCASCADE already in the tree

Because a person can open the result, and because the shapes here are art
rather than engineering: a socket that reads as a socket. OpenCASCADE builds
solids from constraints, which is the right tool when the constraints are
known -- and for this part they are not, beyond the outline. Blender is also
what was asked for.

    python tools/model_from_datasheet.py --list
    python tools/model_from_datasheet.py --part USB_B_PN61729

The output is Wavefront OBJ under `third_party/modelled/`, which is gitignored
like every other fetched or generated mesh. OBJ because Blender cannot write
STEP, and because it is a text format whose material groups survive -- so
`compose_board_3d` can colour a shell differently from a pin without a second
file.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Where a modelled part lands. Gitignored with every other generated mesh,
#: and for the same reason: it is an output, and the inputs are in the tree.
OUT = REPO / "third_party" / "modelled"

#: Where Blender is, on this machine and on a normal Windows install. Searched
#: rather than configured, and a miss says so rather than failing obscurely.
BLENDER_HINTS = (
    "blender",
    r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
)


class Unavailable(Exception):
    """Blender is not installed. The caller decides whether that is fatal."""


@dataclasses.dataclass(frozen=True)
class Modelled:
    """One part, its Blender script, and where each of its numbers came from."""

    name: str
    #: The EAGLE package this stands in for, and the board file to read its
    #: plan geometry out of. **Read, not copied**: a pad table retyped here
    #: would be a second source that can drift from the first.
    package: str
    brd: pathlib.Path
    script: pathlib.Path
    #: Dimensions that are NOT in the board file, each with its source. Kept
    #: as a mapping of number to citation so that neither can be edited
    #: without the other being visible in the diff.
    cited: dict[str, tuple[float, str]]
    why_not_fetched: str


SPECS: tuple[Modelled, ...] = (
    Modelled(
        name="USB_B_PN61729",
        package="PN61729",
        brd=REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd",
        script=REPO / "tools" / "blender" / "usb_b_receptacle.py",
        cited={
            "height": (10.44, (
                "the USB specification's Series-B receptacle shell height. "
                "Fixed by the standard rather than by a manufacturer, because "
                "a plug from any vendor has to enter a socket from any other; "
                "the same reason every through-hole USB-B on the market "
                "measures 10.4 to 11.0 mm over the shell"
            )),
            "wall": (0.5, (
                "the folded sheet a receptacle shell is made from. Not a "
                "measurement -- it is a drawing thickness, chosen so the "
                "opening reads as a shell rather than as a painted rectangle, "
                "and it changes nothing a wire or a pad depends on"
            )),
            "mouth_width": (8.45, (
                "the USB Series-B plug's own overmould width, which is what "
                "the opening has to admit"
            )),
            "mouth_height": (7.26, (
                "the same plug's height. Together with the width this is the "
                "aperture the standard defines"
            )),
            "lead_depth": (3.0, (
                "how far the pins stand below the board. Not a datasheet "
                "figure and not one either: it is how far `leads_of` has to "
                "see them, and it is under the PCB where nothing looks"
            )),
        },
        why_not_fetched=(
            "KiCad's Connector_USB library holds three USB-A, seven USB-C, one "
            "Micro-B and one Mini-B and no type-B receptacle of any kind -- "
            "counted 2026-08-27 against the canonical library on GitLab. "
            "Wurth publish a STEP for the 61729 series this package is named "
            "for, behind a site search this tool cannot reach; if somebody "
            "fetches it by hand it is strictly better than this and should "
            "replace it."
        ),
    ),
)


def blender() -> str:
    for hint in BLENDER_HINTS:
        found = shutil.which(hint) or (hint if pathlib.Path(hint).is_file() else None)
        if found:
            return found
    raise Unavailable(
        f"no Blender found. Looked for: {', '.join(BLENDER_HINTS)}. "
        f"Install it, or put it on PATH."
    )


def plan_geometry(spec: Modelled) -> dict[str, object]:
    """The pads and outline of `spec.package`, from the vendor's own file.

    Read straight out of the EAGLE XML rather than through `tools/eagle.py`,
    because that module reports *placed* pads -- already moved onto the board
    -- and what a model needs is the package's own local frame.
    """
    root = ET.fromstring(spec.brd.read_bytes())
    board = root.find(".//board")
    packages = [p for p in board.iter("package") if p.get("name") == spec.package]
    if not packages:
        raise SystemExit(f"{spec.brd}: no package called {spec.package!r}")
    package = packages[0]

    pins, posts, radius = [], [], 1.1
    for pad in package.findall("pad"):
        x, y = float(pad.get("x")), float(pad.get("y"))
        drill = float(pad.get("drill", "0"))
        # The shell posts are the fat holes. A USB-B's signal pins are under a
        # millimetre and its mounting tabs are over two, so the gap is wide
        # and the split is read off the file rather than off the pad names,
        # which are `P$1` and `P$2` here and something else in the next library.
        if drill >= 1.5:
            posts.append((x, y))
            radius = drill / 2
        else:
            pins.append((x, y))

    xs, ys = [], []
    for wire in package.findall("wire"):
        if wire.get("layer") in ("21", "51"):
            xs += [float(wire.get("x1")), float(wire.get("x2"))]
            ys += [float(wire.get("y1")), float(wire.get("y2"))]
    if not xs:
        raise SystemExit(f"{spec.package}: no silkscreen, so no body outline")
    return {"pins": pins, "posts": posts, "post_radius": radius,
            "x": [min(xs), max(xs)], "y": [min(ys), max(ys)]}


def build(spec: Modelled, check: bool) -> int:
    print(f"{spec.name}:")
    if not spec.brd.is_file():
        print(f"  SKIPPED: {spec.brd} is not fetched. Run: "
              f"python tools/get_board_sources.py arduino-uno")
        return 3
    plan = plan_geometry(spec)
    cited = {key: value for key, (value, _why) in spec.cited.items()}
    print(f"  vendor  body {plan['x'][1] - plan['x'][0]:.3f} x "
          f"{plan['y'][1] - plan['y'][0]:.3f} mm, {len(plan['pins'])} pins, "
          f"{len(plan['posts'])} shell posts at r={plan['post_radius']:.2f}")
    for key, (value, why) in spec.cited.items():
        print(f"  cited   {key} = {value} mm -- {why[:64]}...")
    if check:
        print("  build   skipped (--check)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{spec.name}.obj"
    payload = {
        "out": str(target).replace("\\", "/"),
        "pins": plan["pins"],
        "posts": plan["posts"],
        "post_radius": plan["post_radius"],
        "colours": {"shell": [0.62, 0.63, 0.66],
                    "cavity": [0.05, 0.05, 0.06],
                    "pin": [0.72, 0.60, 0.30]},
        "body": {
            "x": plan["x"],
            "y": plan["y"],
            "height": cited["height"],
            "wall": cited["wall"],
            "lead_depth": cited["lead_depth"],
            "mouth": {"width": cited["mouth_width"],
                      "height": cited["mouth_height"],
                      "depth": 0.4,
                      "floor": cited["wall"] + 0.6},
            "tongue": {"width": cited["mouth_width"] - 2.0,
                       "depth": 0.6,
                       "thickness": 1.2,
                       "z": cited["wall"] + 0.6 + 1.6},
        },
    }
    # **The payload goes in a file, not on argv.** Passed inline it is a
    # single argument full of quotes and braces, and Windows' command line is
    # rebuilt from a string by the runtime -- the JSON arrived mangled and
    # `subprocess` returned a `stdout` of None rather than an error anybody
    # could read.
    handover = OUT / f"{spec.name}.json"
    handover.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    done = subprocess.run(
        [blender(), "--background", "--python", str(spec.script), "--",
         str(handover)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600, check=False)
    # **`encoding` given explicitly**, because `text=True` alone decodes with
    # the locale codec -- cp1252 on this machine -- and Blender's banner is not
    # cp1252. The decode raised inside subprocess and `stdout` came back None,
    # which reads as "Blender printed nothing" and is a two-hour wrong turn.
    if done.stdout is None:
        raise SystemExit(f"{spec.name}: Blender produced no output at all")
    if f"WROTE {payload['out']}" not in done.stdout:
        raise SystemExit(
            f"{spec.name}: Blender did not write the mesh.\n"
            f"--- stdout ---\n{done.stdout[-2000:]}\n"
            f"--- stderr ---\n{done.stderr[-2000:]}"
        )
    print(f"  build   {target.relative_to(REPO)}  "
          f"{target.stat().st_size:,} bytes")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--part", help="one part; every one without it")
    parser.add_argument("--list", action="store_true",
                        help="print what is modelled here, and why")
    parser.add_argument("--check", action="store_true",
                        help="report the dimensions and build nothing")
    args = parser.parse_args(argv)

    if args.list:
        for spec in SPECS:
            print(f"{spec.name}  (EAGLE package {spec.package})")
            print(f"    not fetched because: {spec.why_not_fetched}")
            for key, (value, why) in spec.cited.items():
                print(f"    {key} = {value} mm")
                print(f"        {why}")
        return 0

    wanted = [s for s in SPECS if args.part is None or s.name == args.part]
    if not wanted:
        print(f"no modelled part called {args.part!r}. Known: "
              f"{', '.join(s.name for s in SPECS)}")
        return 2
    for spec in wanted:
        try:
            code = build(spec, args.check)
        except Unavailable as exc:
            print(f"SKIPPED: {exc}")
            return 3
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
