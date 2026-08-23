# OpenHardware — locate and parse the board art PICSimLab already ships.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
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

from webui import picsimlab

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
    """Find PICSimLab's `share/` directory.

    `start` names a PICSimLab root directly and is mostly for tests. With it
    omitted the location comes from `webui.picsimlab`, which is the only place
    that knows where upstream lives -- this repository does not contain it.
    """
    if start is not None:
        base = pathlib.Path(start) / "share"
    else:
        try:
            base = picsimlab.install_root() / "share"
        except picsimlab.PicsimlabNotFound as exc:
            raise AssetError(str(exc)) from exc
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


#: `share/parts/` is grouped into these. `Common` is shared IC body art (IC8,
#: IC16, ...) reused by several parts, not a part anyone can place, so it is
#: excluded from the catalogue.
PART_CATEGORIES = ("Input", "Output", "Other", "Virtual")


def resolve_part_art(directory: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path] | None:
    """Pick the SVG and image map for a part directory, or None if it has none.

    `src/lib/part.cc:447` gives the default -- `GetName() + "/part.svg"` -- but
    it is a **runtime method**, and parts override it. `output_7s_Display.cc:791`
    returns `part.svg` or `part1.svg` depending on the display type currently
    configured, and `output_LCD_hd44780.cc` composites four images through
    `GetPictureFileName` plus three underscore-suffixed variants.

    So no static rule can be exactly right, and an earlier version of this
    module assumed `part.svg` and therefore reported several parts as having no
    art at all -- `LCD hd44780` ships `LCD_hd44780.svg` beside a `part.map`, and
    `7 Segments Display (Decoder)` ships `7sdisplay_dec.{svg,map}`.

    The order here is: the documented default, then a same-stem pair, then the
    sole map with the first SVG. Choosing a variant wrongly shows a different
    picture of the same part, which is cosmetic; the regions still come from the
    map that is paired with it.
    """
    if not directory.is_dir():
        return None

    svgs = sorted(p for p in directory.glob("*.svg"))
    maps = sorted(p for p in directory.glob("*.map"))
    if not svgs or not maps:
        return None

    default_svg, default_map = directory / "part.svg", directory / "part.map"
    if default_svg.is_file() and default_map.is_file():
        return default_svg, default_map

    by_stem = {p.stem: p for p in svgs}
    for candidate in maps:
        if candidate.stem in by_stem:
            return by_stem[candidate.stem], candidate

    # A map whose stem names no SVG: the LCD case, where `part.map` describes
    # art that is composited from differently-named files.
    return svgs[0], maps[0]


def available_parts(root: pathlib.Path | None = None) -> dict[str, str]:
    """Map each drawable part's name to its category.

    The name is the directory name, which is also the name `splist` reports and
    `spadd` expects, so no translation is needed here -- unlike boards, where
    two spellings exist.
    """
    base = (root or share_root()) / "parts"
    found: dict[str, str] = {}
    for category in PART_CATEGORIES:
        directory = base / category
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if entry.is_dir() and resolve_part_art(entry) is not None:
                found[entry.name] = category
    if not found:
        raise AssetError(f"{base} holds no part with a drawable svg/map pair")
    return found


def load_part(name: str, root: pathlib.Path | None = None) -> BoardArt:
    """Load one part's art, using the same image-map parser boards use.

    Parts ship the identical format -- GIMP image maps with `O_`/`B_`/`I_`
    prefixed ids -- and the ids line up with the names the simulator reports
    for a placed part: `B_PB_1` in `share/parts/Input/Push Buttons/part.map`
    pairs with `part[00].in[00] PB_1` in an `info` dump.

    That correspondence is why placed peripherals can be drawn and clicked
    through exactly the same path as board regions.
    """
    base = (root or share_root()) / "parts"
    for category in PART_CATEGORIES:
        art = resolve_part_art(base / category / name)
        if art is None:
            continue
        svg_path, map_path = art
        width, height, regions = parse_map(
            map_path.read_text(encoding="utf-8", errors="replace")
        )
        return BoardArt(
            name=name,
            svg=svg_path.read_bytes(),
            width=width,
            height=height,
            regions=regions,
        )
    raise AssetError(f"no part art for {name!r} under {base}")


def sanitise(name: str) -> str:
    """Apply the simulator's own board-name sanitiser.

    `src/lib/board.cc:585-590` fills `board_desc.name_` from `name`:

        if ((name[i] != ' ') && (name[i] != '-')) { name_[i] = name[i]; }
        else                                      { name_[i] = '_'; }

    so a board carries two names. `info` reports `name` -- "ESP32-DevKitC" --
    and `blist` reports `name_` -- "ESP32_DevKitC". Art directories use the
    display form.

    The mapping is **lossy and must only be applied forwards.** Underscore has
    two possible origins, so "ESP32_C3_DevKitC_02" cannot be turned back into
    "ESP32-C3-DevKitC-02" without knowing the answer already. Ten of the
    twenty-one shipped boards contain a space or a hyphen, so guessing the
    inverse would silently fail on half the catalogue.
    """
    return re.sub(r"[ \-]", "_", name)


def resolve_board_name(name: str, root: pathlib.Path | None = None) -> str:
    """Return the art-directory name for either form of a board's name.

    Accepts the display name `info` reports or the sanitised name `blist`
    reports, and resolves both by sanitising the *candidates* rather than
    trying to un-sanitise the input.
    """
    base = (root or share_root()) / "boards"
    if (base / name / "board.svg").is_file():
        return name

    wanted = sanitise(name)
    matches = [
        candidate
        for candidate in available_boards(root)
        if sanitise(candidate) == wanted
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise AssetError(
            f"no board art matches {name!r}. Known boards: "
            f"{list(available_boards(root))}"
        )
    raise AssetError(
        f"{name!r} is ambiguous: {matches} all sanitise to {wanted!r}. "
        f"The simulator cannot distinguish them either."
    )


def load_board(name: str, root: pathlib.Path | None = None) -> BoardArt:
    """Load one board's SVG and parsed image map, by either name form."""
    name = resolve_board_name(name, root)
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
