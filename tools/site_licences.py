#!/usr/bin/env python3
# OpenHardware - what the static site may publish, and whose it is.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Which 3D models the static site ships, and the notices beside them (OH-241).

    python tools/site_licences.py      # every model on this machine: ships, or not and why

`tools/build_site.py` writes a folder anyone may download, so everything in
it is redistributed, and only a licence allows that. This module holds the
decisions and writes the notices; the build does the copying.

## The 3D models

`webui/static/models/` is built on the machine that runs the build, from
vendors' files fetched there, and is gitignored -- so a build carries
whichever models were built where it ran, and a CI build none. **Every `.glb`
has a row in `BOARD_MODELS`**, and one without a row stops the build by name:
a new model's licence is a decision, never a default.

A model that ships is published under CC BY-SA 4.0, whatever it is drawn from:

* a board file under CC BY-SA 4.0; or 3.0, whose section 4(b) lets an
  adaptation be licensed under a later version with the same licence
  elements; or MIT, which puts no terms on a combined work but its notice;
* KiCad's component meshes, CC BY-SA 4.0 with the KiCad library exception,
  and Espressif's, under the same by its LICENSE.md;
* parts out of Adafruit_CAD_Parts, MIT. PROVENANCE.md section 4 says that
  licence's notice must travel with any published `.glb` drawn from it, so it
  is written out whole beside the models, as is PCBCUPID's for the one board
  file of theirs under MIT.

`models/parts/` is KiCad's own meshes, and ships as they are licensed.

## Withheld, and why each is reversible

Each `Withheld` row is a question somebody has to answer, not a finding that
the file may not be published; answering it is one changed row.

## The runtime

Pyodide's runtime is redistributed whole. `RUNTIME_TEXTS` are its licence
texts and CPython's, fetched pinned by size and sha256. `EMSCRIPTEN_TEXTS`
are read from the Emscripten that `tools/build_site.py` already requires --
the version Pyodide's main module was linked by -- for Emscripten's runtime,
musl, and LLVM's libc++, libc++abi, libunwind and compiler-rt.
"""

from __future__ import annotations

import json
import pathlib
import sys
import typing

try:
    from tools import board_sources
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import board_sources

REPO = pathlib.Path(__file__).resolve().parents[1]
MODELS = REPO / "webui" / "static" / "models"

#: What every shipped model is published under.
SHIPPED_AS = "CC BY-SA 4.0"
CC_BY_SA_4 = "https://creativecommons.org/licenses/by-sa/4.0/"

#: Where `models/parts/` comes from: a part from anywhere else is refused.
KICAD_PACKAGES3D = "https://gitlab.com/kicad/libraries/kicad-packages3D/"


#: The licences, as `tools/board_sources.py` names them, a board file may be
#: under for a model drawn from it to ship as CC BY-SA 4.0 -- the module
#: docstring says why each -- provided the licence was read from a licence
#: file (`Evidence.OPENED`) and not only stated.
SHIPPABLE = frozenset({"CC BY-SA 4.0", "CC BY-SA 3.0 Unported", "MIT"})


class UnlistedModel(Exception):
    """A model with no row, or a part from a library with no licence here."""


class NotShippable(Exception):
    """A row says a model ships, and its board file's licence does not allow it."""


class Ships(typing.NamedTuple):
    #: The `tools/board_sources.py` source the model's board file is from,
    #: by name: its licence is read there, not restated here.
    source: str
    #: Keys of `NOTICE_TEXTS` this model must carry whole: an MIT work in it.
    notices: tuple[str, ...] = ()


class Withheld(typing.NamedTuple):
    why: str


#: Every component mesh a composed board draws, KiCad's or Espressif's.
COMPONENTS = ("KiCad's kicad-packages3D and, where a board names one, Espressif's "
              "kicad-libraries: CC BY-SA 4.0 with the KiCad library exception")

_SEEED_PCB = Withheld(
    "composed from Seeed's XIAO KiCad archive, which carries no licence file; "
    "whether its CC BY-SA logo is a grant is OH-234, the owner's open question")
_SEEED_MESH = Withheld(
    "Seeed's own mesh, from the wiki's file server, which states no licence for "
    "it (tools/import_3d_model.py); the owner's open question in OH-234")
_STATED = Withheld(
    "the board file's licence is in a README that links CC BY-SA 4.0's deed and "
    "names no file it covers: tools/board_sources.py grades it `stated`, not "
    "`opened` (PROVENANCE.md 2g)")
_CERN = Withheld(
    "CERN-OHL, stated in Olimex's README; whether a model drawn from the board "
    "file is modified Documentation under it is left to the owner before "
    "anything built from it is published (PROVENANCE.md 2g)")

#: One row per `.glb` in `webui/static/models/`, keyed by file name.
BOARD_MODELS: dict[str, Ships | Withheld] = {
    "Arduino-Uno.glb": Ships("arduino-uno"),
    "SparkFun-Thing-Plus-ESP32-C6.glb": Ships("sparkfun-thing-plus-esp32-c6"),
    "SparkFun-Pro-Micro-ESP32-C3.glb": Ships("sparkfun-pro-micro-esp32-c3"),
    "SparkFun-Qwiic-Pocket-ESP32-C6.glb": Ships("sparkfun-qwiic-pocket-esp32-c6"),
    "SparkFun-Thing-Plus-ESP32-C5.glb": Ships("sparkfun-thing-plus-esp32-c5"),
    "Adafruit-QT-Py-ESP32-C3.glb": Ships("adafruit-qt-py-esp32-c3", ("Adafruit_CAD_Parts",)),
    "Adafruit-Feather-ESP32-C6.glb": Ships("adafruit-feather-esp32-c6", ("Adafruit_CAD_Parts",)),
    "Adafruit-KB2040.glb": Ships("adafruit-kb2040", ("Adafruit_CAD_Parts",)),
    "PCBCUPID-Glyph-Mini-RP2040.glb": Ships("pcbcupid-glyph-mini-2040",
                                           ("PCBCUPID glyph-mini-2040",)),
    "PCBCUPID-Glyph-C3.glb": _STATED,
    "PCBCUPID-Glyph-C6.glb": _STATED,
    "Olimex-ESP32-C3-DevKit-Lipo.glb": _CERN,
    "Olimex-ESP32-C6-EVB.glb": _CERN,
    "XIAO-ESP32-C3-DIP.glb": _SEEED_PCB,
    "XIAO-ESP32-C3-SMD.glb": _SEEED_PCB,
    "XIAO-ESP32-C5-DIP.glb": _SEEED_PCB,
    "XIAO-ESP32-C5-SMD.glb": _SEEED_PCB,
    "XIAO-ESP32-C6-DIP.glb": _SEEED_PCB,
    "XIAO-ESP32-C6-SMD.glb": _SEEED_PCB,
    "XIAO-RP2350-DIP.glb": _SEEED_PCB,
    "XIAO-RP2350-SMD.glb": _SEEED_PCB,
    "XIAO-STM32C5-SMD.glb": _SEEED_PCB,
    "XIAO-nRF54l15-DIP.glb": _SEEED_PCB,
    "XIAO-nRF54l15-SMD.glb": _SEEED_PCB,
    "SAMD21.glb": _SEEED_MESH,
    "RP2040.glb": _SEEED_MESH,
    "ESP32-S3.glb": _SEEED_MESH,
    "nRF52840.glb": _SEEED_MESH,
    "MG24.glb": _SEEED_MESH,
    "nRF54LM20A.glb": _SEEED_MESH,
}


class Pinned(typing.NamedTuple):
    url: str
    sha256: str
    size: int


#: Licence texts a shipped model must carry whole, keyed as `Ships.notices`
#: names them. Each at the commit its work was read at.
NOTICE_TEXTS: dict[str, Pinned] = {
    "Adafruit_CAD_Parts": Pinned(
        "https://raw.githubusercontent.com/adafruit/Adafruit_CAD_Parts/"
        "c128bceb1f96b6ea8b68f250bda986ba85da24ea/LICENSE",
        "f60436644e066301d4c2e8f1f0674a157b1f60e4fd5586717b99dde255cc18cd", 1076),
    "PCBCUPID glyph-mini-2040": Pinned(
        "https://raw.githubusercontent.com/pcbcupid/glyph-mini-2040/"
        "5d78c06193aeb61b7ce8f4cb0f90ef9573c6c01e/LICENSE",
        "f0eac866f27e961cfc9a720828d9fd016dbf36488a3d355c656e0d8d338e8654", 1066),
}

#: The runtime's licence texts, at the releases `tools/build_site.py` pins.
RUNTIME_TEXTS: dict[str, Pinned] = {
    "Pyodide 314.0.7 (MPL-2.0)": Pinned(
        "https://raw.githubusercontent.com/pyodide/pyodide/314.0.7/LICENSE",
        "1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5", 16725),
    "CPython 3.14.2 (PSF-2.0)": Pinned(
        "https://raw.githubusercontent.com/python/cpython/v3.14.2/LICENSE",
        "b0e25a78cffb43f4d92de8b61ccfa1f1f98ecbc22330b54b5251e7b6ba010231", 13804),
    "CPython 3.14.2: the licences of what it incorporates": Pinned(
        "https://raw.githubusercontent.com/python/cpython/v3.14.2/Doc/license.rst",
        "c695d550b135e53e38807e76496d1db17d22c40e461d1f3f354c86188d3305dd", 57595),
}

#: Read from the Emscripten tree, relative to its `upstream/emscripten/`.
EMSCRIPTEN_TEXTS: dict[str, str] = {
    "Emscripten (MIT or NCSA)": "LICENSE",
    "musl libc (MIT)": "system/lib/libc/musl/COPYRIGHT",
    "libc++ (Apache-2.0 WITH LLVM-exception)": "system/lib/libcxx/LICENSE.TXT",
    "libc++abi (Apache-2.0 WITH LLVM-exception)": "system/lib/libcxxabi/LICENSE.TXT",
    "libunwind (Apache-2.0 WITH LLVM-exception)": "system/lib/libunwind/LICENSE.TXT",
    "compiler-rt (Apache-2.0 WITH LLVM-exception)": "system/lib/compiler-rt/LICENSE.TXT",
}


def board_licence(row: Ships) -> board_sources.Licence:
    """The licence of a shipped row's board file, refused unless it allows
    shipping: one of `SHIPPABLE`, read from a licence file."""
    sources = {source.name: source for source in board_sources.SOURCES}
    if row.source not in sources:
        raise NotShippable(f"{row.source!r} is no source in tools/board_sources.py")
    licence = sources[row.source].licence
    if licence.evidence is not board_sources.Evidence.OPENED:
        raise NotShippable(f"{row.source}'s licence, {licence.name}, is "
                           f"{licence.evidence.name.lower()}, not read from a "
                           f"licence file: {licence.cite}")
    if licence.name not in SHIPPABLE:
        raise NotShippable(f"{row.source} is under {licence.name}, which is not "
                           f"one of {sorted(SHIPPABLE)}")
    return licence


def decide(name: str) -> Ships | Withheld:
    """The row for one model file, by its name in `webui/static/models/`;
    a shipped row only if its board file's licence allows it."""
    try:
        row = BOARD_MODELS[name]
    except KeyError:
        raise UnlistedModel(
            f"webui/static/models/{name} has no row in tools/site_licences.py's "
            f"BOARD_MODELS: say whether it ships, and under what, before a "
            f"build publishes it") from None
    if isinstance(row, Ships):
        board_licence(row)
    return row


class Selection(typing.NamedTuple):
    #: `index.json` as the site carries it: only what ships.
    index: dict[str, object]
    #: Model files to copy, relative to `webui/static/models/`.
    files: list[str]
    #: Each shipped board model's row, by file name.
    shipped: dict[str, Ships]
    #: Each withheld one's, by file name.
    withheld: dict[str, Withheld]


def _file(entry: dict[str, object]) -> str:
    """`/models/parts/X.glb` -> `parts/X.glb`."""
    path = str(entry["file"])
    if not path.startswith("/models/"):
        raise UnlistedModel(f"index.json names {path!r}, outside /models/")
    return path.removeprefix("/models/")


def select(index: dict[str, object], on_disk: list[str]) -> Selection:
    """What of `index` (models/index.json) and `on_disk` (every `.glb` under
    models/, relative to it) the site may carry."""
    for name in on_disk:
        if "/" not in name:
            decide(name)

    boards: dict[str, object] = {}
    shipped: dict[str, Ships] = {}
    withheld: dict[str, Withheld] = {}
    for board, entry in index.get("boards", {}).items():
        name = _file(entry)
        row = decide(name)
        if isinstance(row, Ships):
            boards[board] = entry
            shipped[name] = row
        else:
            withheld[name] = row

    libraries: dict[str, list[dict[str, object]]] = {}
    parts = index.get("parts", {"libraries": {}})
    for library, entries in parts["libraries"].items():
        for entry in entries:
            if not str(entry["source"]).startswith(KICAD_PACKAGES3D):
                raise UnlistedModel(
                    f"models/{_file(entry)} is from {entry['source']}, not "
                    f"{KICAD_PACKAGES3D}: no licence for it is recorded here")
        libraries[library] = entries

    selected = {**index, "boards": boards, "parts": {**parts, "libraries": libraries}}
    files = sorted({*shipped, *(_file(entry) for entries in libraries.values()
                                for entry in entries)})
    missing = [name for name in files if name not in on_disk]
    if missing:
        raise UnlistedModel(f"index.json names {missing}, which are not on disk")
    return Selection(selected, files, shipped, withheld)


def model_notice(selection: Selection, texts: dict[str, str]) -> str:
    """`models/NOTICE.txt`: what each shipped model is, whose, and under what.

    `texts` holds each `NOTICE_TEXTS` entry a shipped row names, read.
    """
    lines = [
        "# The 3D models on this site",
        "",
        f"Each model here is published under [{SHIPPED_AS}]({CC_BY_SA_4}). "
        "It was composed by OpenHardware's tools/compose_board_3d.py from the "
        "board file named below, which gives its outline and where each "
        f"component sits, and from {COMPONENTS}. Changes were made: the board "
        "file's geometry is tessellated into a glTF mesh with component "
        "meshes placed on it.",
        "",
    ]
    sources = {source.name: source for source in board_sources.SOURCES}
    for name, row in sorted(selection.shipped.items()):
        source = sources[row.source]
        lines.append(f"* `{name}`: from {source.vendor}'s board file, "
                     f"{source.fetch.url}, {source.licence.name}.")
        lines.extend(f"  It also draws parts out of {key}, under the MIT licence "
                     f"below." for key in row.notices)
    if any(selection.index["parts"]["libraries"].values()):
        lines += ["", f"`parts/` holds component meshes from {KICAD_PACKAGES3D}, "
                      f"{COMPONENTS.split(': ')[1]}."]
    named = sorted({key for row in selection.shipped.values() for key in row.notices})
    for key in named:
        lines += ["", f"## {key}", "", "```text", texts[key].rstrip("\n"), "```"]
    return "\n".join(lines) + "\n"


def runtime_notice(texts: dict[str, str]) -> str:
    """`NOTICE.txt` at the site's root: the runtime's licences, whole.

    `texts` holds every `RUNTIME_TEXTS` and `EMSCRIPTEN_TEXTS` entry, read.
    """
    lines = [
        "# Notices",
        "",
        "OpenHardware is MIT; its LICENSE is in the repository it is built "
        "from. This site also carries, unmodified, the Pyodide runtime -- "
        "CPython compiled to WebAssembly by Emscripten -- whose licences "
        "follow, and three.js, whose licence is vendor/LICENSE.",
    ]
    for title in [*RUNTIME_TEXTS, *EMSCRIPTEN_TEXTS]:
        lines += ["", f"## {title}", "", "```text", texts[title].rstrip("\n"), "```"]
    return "\n".join(lines) + "\n"


def on_disk(models: pathlib.Path = MODELS) -> list[str]:
    """Every `.glb` under `models`, relative to it."""
    return sorted(path.relative_to(models).as_posix()
                  for path in models.rglob("*.glb"))


def main() -> int:
    present = on_disk()
    index_file = MODELS / "index.json"
    if not index_file.is_file():
        print(f"no {index_file.relative_to(REPO)}: nothing built here, nothing ships")
        return 0
    selection = select(json.loads(index_file.read_text(encoding="utf-8")), present)
    for name, row in sorted(selection.shipped.items()):
        print(f"ships     {name}: {row.source}, {board_licence(row).name}")
    for name, row in sorted(selection.withheld.items()):
        print(f"withheld  {name}: {row.why}")
    parts = [name for name in selection.files if name.startswith("parts/")]
    print(f"ships     {len(parts)} parts from {KICAD_PACKAGES3D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
