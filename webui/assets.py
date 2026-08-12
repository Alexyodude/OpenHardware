# OpenHardware — locate and parse the board art PICSimLab already ships.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Read `share/boards/<name>/board.{svg,map}` into something a browser can use.

No new artwork is needed for a web UI. Every board already ships an SVG and a
`.map` file, and the map is **already an HTML image map** — GIMP's Image Map
plug-in emitted it, so it is literally the format a browser was going to need:

    <area shape="rect" coords="158,53,169,63" href="O_LD_L" />

The `href` is a region id whose first letter gives its role and whose remainder
matches the name the simulator reports for that element, so `O_LD_L` pairs with
``board.out[01] LD_L`` from an `info` dump. That correspondence is what lets a
browser draw live state onto shipped art without any new geometry.

Surveyed across all 28 shipped board maps on 2026-08-12: exactly three prefixes
(`O_` 296, `B_` 138, `I_` 46) and exactly two shapes (`rect` 396,
`circle` 84). Both are handled; anything else raises rather than being skipped,
because a silently dropped region is an element the UI will never draw and
nobody will be told about.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re

#: `href` prefix -> role. Surveyed, not guessed; see the module docstring.
ROLES = {"O": "output", "B": "button", "I": "input"}

_AREA = re.compile(
    r'<area\s+shape="(?P<shape>[a-z]+)"\s+coords="(?P<coords>[\d,\s]+)"\s+'
    r'href="(?P<href>[^"]+)"',
    re.IGNORECASE,
)
_SIZE = re.compile(r'width="(?P<width>\d+)"\s+height="(?P<height>\d+)"')


class AssetError(Exception):
    """The art is missing, unreadable, or not shaped the way the parser expects."""


@dataclasses.dataclass(frozen=True)
class Region:
    """One clickable or drawable area of a board image."""

    id: str
    role: str
    name: str
    #: Bounding box in image coordinates, inclusive. A circle is stored as its
    #: bounding box plus `radius`, so a caller that only needs a hit area or a
    #: place to put a dot never has to branch on shape.
    left: int
    top: int
    right: int
    bottom: int
    shape: str
    radius: int | None = None

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)


@dataclasses.dataclass(frozen=True)
class BoardArt:
    name: str
    svg: bytes
    width: int
    height: int
    regions: tuple[Region, ...]

    def by_role(self, role: str) -> tuple[Region, ...]:
        return tuple(r for r in self.regions if r.role == role)


def _coords(shape: str, raw: str, href: str) -> tuple[int, int, int, int, int | None]:
    parts = [int(value) for value in raw.replace(" ", "").split(",") if value != ""]
    if shape == "rect":
        if len(parts) != 4:
            raise AssetError(f"{href}: rect needs 4 coords, got {len(parts)}")
        left, top, right, bottom = parts
        return left, top, right, bottom, None
    if shape == "circle":
        if len(parts) != 3:
            raise AssetError(f"{href}: circle needs 3 coords, got {len(parts)}")
        cx, cy, radius = parts
        return cx - radius, cy - radius, cx + radius, cy + radius, radius
    raise AssetError(
        f"{href}: unsupported shape {shape!r}. Only rect and circle appear in the "
        f"shipped maps; a new one must be handled rather than skipped, or the UI "
        f"silently loses an element."
    )


def parse_map(text: str) -> tuple[int, int, tuple[Region, ...]]:
    """Parse an image map into its image size and its regions.

    Raises on a map with no regions. An empty result is indistinguishable from
    a board whose art failed to load, and this repository's rule is that a
    parser which returns nothing must say so rather than report success.
    """
    size = _SIZE.search(text)
    if size is None:
        raise AssetError("no width/height on the <img> line; not an image map")

    regions: list[Region] = []
    for match in _AREA.finditer(text):
        href = match.group("href")
        shape = match.group("shape").lower()
        prefix, _, name = href.partition("_")
        role = ROLES.get(prefix)
        if role is None:
            raise AssetError(
                f"{href}: unknown role prefix {prefix!r}; known: {sorted(ROLES)}"
            )
        left, top, right, bottom, radius = _coords(shape, match.group("coords"), href)
        regions.append(
            Region(
                id=href,
                role=role,
                name=name,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                shape=shape,
                radius=radius,
            )
        )

    if not regions:
        raise AssetError("image map declares no <area> regions")
    return int(size.group("width")), int(size.group("height")), tuple(regions)


def share_root(start: pathlib.Path | None = None) -> pathlib.Path:
    """Find the repository's `share/` directory."""
    base = (start or pathlib.Path(__file__).resolve().parent.parent) / "share"
    if not (base / "boards").is_dir():
        raise AssetError(f"no board art under {base}; expected {base / 'boards'}")
    return base


def available_boards(root: pathlib.Path | None = None) -> tuple[str, ...]:
    base = (root or share_root()) / "boards"
    names = sorted(
        entry.name for entry in base.iterdir() if (entry / "board.svg").is_file()
    )
    if not names:
        raise AssetError(f"{base} holds no board with a board.svg")
    return tuple(names)


def load_board(name: str, root: pathlib.Path | None = None) -> BoardArt:
    """Load one board's SVG and parsed image map."""
    base = (root or share_root()) / "boards" / name
    svg_path, map_path = base / "board.svg", base / "board.map"
    for path in (svg_path, map_path):
        if not path.is_file():
            raise AssetError(f"{name}: missing {path.name} at {path}")

    width, height, regions = parse_map(map_path.read_text(encoding="utf-8", errors="replace"))
    return BoardArt(
        name=name,
        svg=svg_path.read_bytes(),
        width=width,
        height=height,
        regions=regions,
    )
