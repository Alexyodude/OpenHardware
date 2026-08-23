#!/usr/bin/env python3
# OpenHardware - turn a vendor KiCad footprint into a board the web UI can draw.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Emit `webui/boards/<name>.json` and a board SVG from `.kicad_mod` + `.kicad_sym`.

`webui/pinmap.py` explains why this exists:

    Nothing upstream knows where a board's pins are. [...] So a UI that lets
    you drag a wire onto a physical header needs data that does not exist yet.

For the Arduino Uno that data was recovered by measuring circles out of
`board.svg` and inferring the header runs from their 0.1 inch pitch. It worked,
and `webui/boards/Arduino Uno.json` records the derivation honestly, but it is
reconstruction.

Any board whose vendor publishes KiCad files needs none of that. A footprint
holds pad centres in millimetres to three decimals, authored by the people who
made the board. This tool reads them.

## What it emits, and what it deliberately leaves blank

**Geometry and labels: exact.** Pad centres come from the footprint, names from
the symbol library, joined on pad number.

**`pin`: always null.** That field is the *simulator's* pin index -- what
`pinsl` reports -- not the connector's pad number. It is defined by a
PICSimLab board implementation, and for these boards none exists yet. Writing
a plausible number would be the exact failure `rules/conformance-fixtures.md`
exists to stop: a config that looks valid and wires the circuit wrongly.

`pinmap.py` already models this: `NC`, `IOREF`, `3V3` and `VIN` on an Uno carry
`pin: null` so the pad draws and a drag onto it is refused for the right
reason. An imported board is that case for every pad until a backend lands.

## The SVG

Generated from the footprint's `F.SilkS` and `F.CrtYd` graphics. It is a real
outline, not a photograph, which suits a schematic-style UI and costs bytes
instead of megabytes -- Seeed's own pinout PNGs are 2-5 MB each.

    python tools/import_kicad_board.py --list
    python tools/import_kicad_board.py XIAO-ESP32-C3-DIP --symbol XIAO-ESP32-C3-SMD
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    from tools.kicad import DEFAULT_PX_PER_MM, Footprint, KicadError, read_footprint, read_symbol_pins, symbol_roots
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools.kicad import DEFAULT_PX_PER_MM, Footprint, KicadError, read_footprint, read_symbol_pins, symbol_roots

REPO = pathlib.Path(__file__).resolve().parents[1]
VENDOR = REPO / "third_party" / "seeed-xiao" / "Seeed Studio XIAO Series Library"
SYMBOL_LIB = VENDOR / "Seeed_Studio_XIAO_Series.kicad_sym"
BOARDS_DIR = REPO / "webui" / "boards"

#: Margin around the board outline, in millimetres, so pads on the very edge
#: are not clipped by the viewBox.
MARGIN_MM = 1.0

#: Silkscreen and courtyard draw the outline. Copper and fabrication layers are
#: skipped: F.Cu duplicates the pads, F.Fab is assembly annotation that reads as
#: noise at board scale.
DRAWN_LAYERS = ("F.SilkS", "F.CrtYd")


class ImportError_(Exception):
    """The footprint and symbol could not be turned into a board."""


def header_pads(footprint: Footprint):
    """The pads a user can wire to.

    Prefers through-hole. A DIP footprint carries both an SMD and a
    through-hole pad for every position -- the same pin, two ways to mount it
    -- so taking all pads would place two draggable dots on every pin, a
    fraction of a millimetre apart. Through-hole is the one a jumper wire
    actually goes into.
    """
    through = footprint.pads_of("thru_hole")
    if through:
        return through
    smd = footprint.pads_of("smd")
    if not smd:
        raise ImportError_(f"{footprint.name}: no through-hole or SMD pads")
    return smd


def build(
    footprint: Footprint,
    pin_names: dict[str, str],
    px_per_mm: float = DEFAULT_PX_PER_MM,
) -> tuple[dict, str]:
    """Return (board JSON, SVG text)."""
    min_x, min_y, max_x, max_y = footprint.extent_mm()
    min_x -= MARGIN_MM
    min_y -= MARGIN_MM
    max_x += MARGIN_MM
    max_y += MARGIN_MM

    width = round((max_x - min_x) * px_per_mm)
    height = round((max_y - min_y) * px_per_mm)

    def to_px(x_mm: float, y_mm: float) -> tuple[float, float]:
        return round((x_mm - min_x) * px_per_mm, 1), round((y_mm - min_y) * px_per_mm, 1)

    pads = header_pads(footprint)
    unnamed = [p.number for p in pads if p.number not in pin_names]

    entries = []
    for pad in sorted(pads, key=lambda p: (p.y_mm, p.x_mm)):
        x, y = to_px(pad.x_mm, pad.y_mm)
        entries.append(
            {
                "label": pin_names.get(pad.number, pad.number),
                "pin": None,
                "x": x,
                "y": y,
                "group": "header-top" if pad.y_mm < 0 else "header-bottom",
                "pad": pad.number,
            }
        )

    board = {
        "board": footprint.name,
        "image": {"width": width, "height": height, "file": f"webui/boards/{footprint.name}.svg"},
        "derivation": (
            f"Generated by tools/import_kicad_board.py from the vendor's own KiCad "
            f"footprint. Pad centres are exact to three decimal places in millimetres, "
            f"scaled at {px_per_mm} px/mm from a {max_x - min_x:.2f} x {max_y - min_y:.2f} mm "
            f"extent including a {MARGIN_MM} mm margin. Pin names joined from the symbol "
            f"library on pad number. Nothing here was measured off an image."
        ),
        "assumption": (
            "Every `pin` is null. That field is the simulator's pin index, defined by a "
            "PICSimLab board implementation, and none exists for this board yet. A pad "
            "with pin null draws and refuses a wire, which is correct; a guessed number "
            "would wire the circuit wrongly and report success."
        ),
        "source": {
            "vendor": "Seeed Studio",
            "repository": "https://github.com/Seeed-Studio/OSHW-XIAO-Series",
            "licence": "MIT",
            "footprint": footprint.name,
        },
        "pads": entries,
    }
    if unnamed:
        board["unnamed_pads"] = unnamed

    return board, _svg(footprint, min_x, min_y, width, height, px_per_mm, entries)


def _svg(footprint, min_x, min_y, width, height, px_per_mm, entries) -> str:
    def to_px(x_mm, y_mm):
        return (x_mm - min_x) * px_per_mm, (y_mm - min_y) * px_per_mm

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f"  <!-- Generated by tools/import_kicad_board.py from {footprint.name}.kicad_mod",
        "       Source: Seeed Studio OSHW-XIAO-Series, MIT. Outline is the vendor's",
        "       F.SilkS and F.CrtYd geometry; nothing here is traced or redrawn. -->",
        f'  <rect x="0" y="0" width="{width}" height="{height}" rx="{2 * px_per_mm:.0f}" '
        f'fill="#1c6b45" stroke="#0d3b26" stroke-width="1"/>',
        '  <g stroke="#e8f3ee" stroke-width="1.2" fill="none" stroke-linecap="round">',
    ]
    for seg in footprint.segments:
        if seg.layer not in DRAWN_LAYERS:
            continue
        x1, y1 = to_px(seg.x1_mm, seg.y1_mm)
        x2, y2 = to_px(seg.x2_mm, seg.y2_mm)
        lines.append(f'    <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
    lines.append("  </g>")

    lines.append('  <g fill="#f2c14e" stroke="#8a6d1f" stroke-width="0.8">')
    for entry in entries:
        lines.append(f'    <circle cx="{entry["x"]}" cy="{entry["y"]}" r="{0.5 * px_per_mm:.1f}"/>')
    lines.append("  </g>")

    lines.append('  <g font-family="monospace" font-size="7" fill="#e8f3ee" text-anchor="middle">')
    for entry in entries:
        dy = -9 if entry["group"] == "header-top" else 15
        lines.append(f'    <text x="{entry["x"]}" y="{entry["y"] + dy}">{entry["label"]}</text>')
    lines.append("  </g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("footprint", nargs="?", help="footprint name, e.g. XIAO-ESP32-C3-DIP")
    parser.add_argument("--symbol", help="symbol root; defaults to the footprint name")
    parser.add_argument("--list", action="store_true", help="list available footprints and symbols")
    parser.add_argument("--scale", type=float, default=DEFAULT_PX_PER_MM, help="pixels per mm")
    parser.add_argument("--out", type=pathlib.Path, default=BOARDS_DIR)
    args = parser.parse_args()

    if not VENDOR.is_dir():
        print(
            f"{VENDOR} is missing. Run: bash tools/get_seeed_hardware.sh",
            file=sys.stderr,
        )
        return 2

    if args.list:
        mods = sorted(p.stem for p in VENDOR.glob("*.kicad_mod"))
        print(f"{len(mods)} footprints:")
        for name in mods:
            print(f"  {name}")
        print(f"\nsymbols in {SYMBOL_LIB.name}:")
        for root in symbol_roots(SYMBOL_LIB):
            print(f"  {root}")
        return 0

    if not args.footprint:
        parser.error("give a footprint name, or --list")

    mod = VENDOR / f"{args.footprint}.kicad_mod"
    if not mod.is_file():
        print(f"no footprint {args.footprint!r}. Try --list.", file=sys.stderr)
        return 2

    try:
        footprint = read_footprint(mod)
        pins = read_symbol_pins(SYMBOL_LIB, args.symbol or args.footprint)
        board, svg = build(footprint, pins, args.scale)
    except (KicadError, ImportError_) as exc:
        print(f"import_kicad_board: {exc}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / f"{footprint.name}.json"
    svg_path = args.out / f"{footprint.name}.svg"
    json_path.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    svg_path.write_text(svg, encoding="utf-8")

    print(f"{json_path.relative_to(REPO)}  ({len(board['pads'])} pads)")
    print(f"{svg_path.relative_to(REPO)}  ({board['image']['width']}x{board['image']['height']} px)")
    if board.get("unnamed_pads"):
        print(
            f"  note: {len(board['unnamed_pads'])} pad(s) had no symbol entry and kept "
            f"their pad number as the label: {board['unnamed_pads']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
