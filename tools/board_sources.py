#!/usr/bin/env python3
# OpenHardware - where each vendor's hardware files are, and what they contain.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Answer, for one named hardware source: what is in it, and how to get it.

`tools/get_seeed_hardware.sh` was one vendor hard-coded into one shell script
-- repository URL, library directory name and the `--all` flag all Seeed's.
A second vendor written that way is a second script and fifteen is fifteen, so
the vendor-specific part is moved into a table and the fetching is done once,
generically, by `tools/get_board_sources.py`.

**This table is the only hand-written thing here**, in the shape
`webui/boards/catalogue.py` uses for `CHIPS`, and for the same reason: what a
vendor publishes cannot be computed from this repository. It is a fact about
somebody else's git server. Every row cites the survey row it came from, and
`tests/rules/test_board_sources.py` checks the rows against that survey
whenever the survey is present — and says SKIPPED, loudly, when it is not.

## A row records what a vendor does *not* publish

The most decision-relevant thing the survey produced is a negative. Seeed --
the vendor this project already imports 25 boards from — publishes no
schematic, in any format, and no PCB layout at all. Only footprints and
symbols. A schema that can only describe what a vendor *has* would render that
as five empty fields and read as "not looked into yet", which is the opposite
of the truth.

So every artefact class carries `Published` **and** `Evidence`: `no` with
`ABSENT` means a complete listing was searched and it is not there, while a
missing row means nobody looked. Those are different claims and the gap
between them is where a survey stops being useful.

## A licence may belong to one repository rather than to a vendor

`Licence.sampled` exists because of a specific finding, and it is the reason
this is not a `dict[vendor, str]`. Seeed ships one repository for its whole
range, so its MIT covers everything fetched from it. Adafruit and SparkFun
ship **one repository per board** — 634 and 1,413 of them — and the survey
found a SparkFun board repository whose README points at a `LICENSE.md` that
the repository does not contain, while three sibling repositories have one.
The failure mode is not a vendor changing its mind; it is a single repository
missing a file. A registry that stored one licence per vendor would state
terms for 1,412 repositories it never opened, which is precisely the licence
claim `rules/licence-hygiene.md` says we have no right to make.

So a licence read from one sampled repository says so, and a caller that needs
the licence of a *different* board from that vendor is told to go and read it.
"""

from __future__ import annotations

import enum
import pathlib
import typing

#: Downloads land here, and it is git-ignored. See
#: `tools/get_board_sources.py` for why fetching rather than vendoring is the
#: boundary that makes this table able to cover vendors at all.
THIRD_PARTY = pathlib.Path("third_party")
#: The survey these rows are drawn from, marked unadopted in the manner of
#: `docs/research/peripheral-layer/`. Read by the drift test, never at runtime:
#: adopting research is a decision, and this table is where the decision is
#: written down.
SURVEY = pathlib.Path("docs/research/board-sources/sources.json")
#: The artefact classes a row must answer for, in report order. Named once so
#: the renderer and the drift test cannot disagree about what "all of them"
#: means.
ARTEFACT_CLASSES = (
    "schematic_source",
    "schematic_pdf",
    "pcb_layout",
    "footprints_symbols",
    "model_3d",
    "board_support",
)


class SourceError(Exception):
    """A source is not in the registry, or cannot be fetched as described."""


class Published(enum.Enum):
    """Whether a source publishes an artefact class.

    Three values rather than a boolean because the survey found a real middle:
    Seeed ships 13 `.stl` meshes and no STEP or WRL, which is neither a 3D
    model you can use nor an absence.
    """

    YES = "yes"
    PARTIAL = "partial"
    NO = "no"


class Evidence(enum.Enum):
    """How a cell is known — OH-23's five classes, copied rather than reworded.

    Copied deliberately: the drift test compares these strings against the
    survey's own `evidence_classes`, so a synonym invented here would look
    like a disagreement about the world rather than about vocabulary. They are
    *not* `tools/inventory.py`'s classes, which grade files on this disk; these
    grade claims about somebody else's server.
    """

    OPENED = ("opened", "the artefact was fetched here and its contents read")
    LISTED = ("listed", "the host's own file listing was read; the files were not opened")
    STATED = ("stated", "a vendor page asserts it; nobody opened the artefact")
    ABSENT = ("absent", "a complete listing was searched and it is not there")
    UNREACHABLE = ("unreachable", "the source could not be reached; what was tried is recorded")

    def __init__(self, label: str, gloss: str) -> None:
        self.label = label
        self.gloss = gloss


class Transport(enum.Enum):
    """How a source is retrieved.

    `GIT_SPARSE` is the only one `tools/get_board_sources.py` performs.
    `HTTPS_ARCHIVE` is in the table because six of the surveyed vendors publish
    a per-board zip behind a product page and leaving them out would
    misrepresent the market as uniformly git-shaped. The fetcher refuses it by
    name and prints the URL, rather than the table pretending those vendors do
    not exist.
    """

    GIT_SPARSE = "git-sparse"
    HTTPS_ARCHIVE = "https-archive"


class Artefact(typing.NamedTuple):
    """One artefact class for one source: whether it is there, and how we know."""

    published: Published
    evidence: Evidence
    #: The value behind the claim — the filenames seen, or what was searched
    #: and not found. Never a bare yes or no.
    note: str


class Artefacts(typing.NamedTuple):
    """The six classes, all of them answered. There is no "not filled in yet"."""

    schematic_source: Artefact
    schematic_pdf: Artefact
    pcb_layout: Artefact
    footprints_symbols: Artefact
    model_3d: Artefact
    board_support: Artefact


class Licence(typing.NamedTuple):
    """The licence, and the extent of what it was actually read over."""

    name: str
    #: What the grant covers in its own words: design files, documentation
    #: only, or something the vendor left to inference.
    covers: str
    #: True when this was read from **one sampled repository** out of many that
    #: the vendor ships, so a sibling repository may say something else. See
    #: the module docstring: this is not hypothetical.
    sampled: bool
    evidence: Evidence
    cite: str


class Fetch(typing.NamedTuple):
    """What to retrieve, and what is deliberately left on the server."""

    transport: Transport
    url: str
    #: Directories worth fetching. Empty means the whole tree — there is
    #: nothing to narrow.
    wanted: tuple[str, ...]
    #: `(path, why it is not fetched)`. The reason is required, because the
    #: only thing that stops a skip list becoming folklore is the sentence
    #: next to each entry.
    skipped: tuple[tuple[str, str], ...]


class Source(typing.NamedTuple):
    """One fetchable hardware source."""

    #: The registry key and the directory under `third_party/`. Stable: other
    #: tools hold paths built from it.
    name: str
    vendor: str
    #: What the vendor's delivery looks like — one repository for a range, or
    #: one per board. It decides whether `licence.sampled` can ever be False.
    model: str
    size: str
    licence: Licence
    fetch: Fetch
    artefacts: Artefacts
    #: The survey row this came from.
    cite: str

    def dest(self, root: pathlib.Path) -> pathlib.Path:
        """Where this source lands, under a repository root."""
        return root / THIRD_PARTY / self.name

    def absent(self) -> tuple[str, ...]:
        """The artefact classes this source is known not to publish.

        Known, not merely unrecorded: only cells whose evidence is `ABSENT`
        count, so "we searched and it is not there" never blurs into "nobody
        looked". This is the answer OH-27 needed and could not get — that
        Seeed publishes no schematic at all is a fact about the vendor, and
        the reason `docs/tickets/OH-28` cannot be satisfied from this source.
        """
        return tuple(
            name
            for name in ARTEFACT_CLASSES
            if getattr(self.artefacts, name).evidence is Evidence.ABSENT
        )


#: The registry. **The only hand-written thing in this module**, and the only
#: place a vendor's name appears anywhere in the fetch path — see
#: `test_the_fetcher_names_no_vendor`, which reads the fetcher's source and
#: fails if it does.
#:
#: Keyed by `name`, not by vendor: the survey carries two separate Raspberry Pi
#: rows for two different download portals, so a vendor is not a unique key
#: and never was.
SOURCES: tuple[Source, ...] = (
    Source(
        name="seeed-xiao",
        vendor="Seeed Studio",
        model="one repository for the whole XIAO range",
        size="196,037 KiB",
        licence=Licence(
            name="MIT",
            covers="design files",
            sampled=False,
            evidence=Evidence.OPENED,
            cite="LICENSE at the repository root, read here in third_party/seeed-xiao",
        ),
        fetch=Fetch(
            transport=Transport.GIT_SPARSE,
            url="https://github.com/Seeed-Studio/OSHW-XIAO-Series.git",
            wanted=("Seeed Studio XIAO Series Library", "document"),
            skipped=(
                (
                    "pinout",
                    "two 2-5 MB marketing PNGs per board. Those are pictures of a "
                    "pinout, not a pinout, and they are nearly the whole 196 MB",
                ),
                (
                    "projects",
                    "community demo firmware and DIY enclosure STLs; no board CAD, "
                    "and the 13 .stl in here are cases for a clock project rather "
                    "than models of any board",
                ),
            ),
        ),
        artefacts=Artefacts(
            schematic_source=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "no .sch, .kicad_sch, .schdoc or .dsn anywhere in 675 blobs",
            ),
            schematic_pdf=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "exactly two PDFs and neither is a schematic: "
                "document/Seeed_Studio_XIAO_Slides.pdf and "
                "projects/community-diy-projects/XIAO_USE_CASE.pdf",
            ),
            pcb_layout=Artefact(
                Published.NO, Evidence.ABSENT, "no .kicad_pcb, .brd or .pcbdoc"
            ),
            footprints_symbols=Artefact(
                Published.YES,
                Evidence.OPENED,
                "37 .kicad_mod and 1 .kicad_sym; the pad coordinates in "
                "webui/boards/*.json were imported from them",
            ),
            model_3d=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "no STEP, WRL or board mesh of any kind. All 13 .stl sit under "
                "projects/community-diy-projects/XIAO_ESP32_NTP_Clock/3d_models/ "
                "and are printable clock-case parts contributed by a user -- not "
                "board geometry, and not Seeed's output. This cell said PARTIAL "
                "on the strength of the extension tally alone until the survey "
                "opened the paths",
            ),
            board_support=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "no pin-definition headers; Seeed's board support ships in the "
                "Arduino core, not here",
            ),
        ),
        cite="OH-23 survey, docs/research/board-sources/sources.json: "
        "Seeed Studio / Seeed-Studio-OSHW-XIAO-Series",
    ),
    Source(
        name="adafruit-huzzah32",
        vendor="Adafruit",
        model="one repository per board; 634 match 'PCB' in the name under org:adafruit",
        size="1,614 KiB",
        licence=Licence(
            name="CC BY-SA 3.0 Unported",
            covers="design files",
            sampled=True,
            evidence=Evidence.OPENED,
            cite="licence.txt at the repository root, read 2026-08-25. GitHub "
            "reports NOASSERTION because the file is the legal code rather than "
            "a recognised template",
        ),
        fetch=Fetch(
            transport=Transport.GIT_SPARSE,
            url="https://github.com/adafruit/Adafruit-HUZZAH32-ESP32-Feather-PCB.git",
            wanted=(),
            skipped=(),
        ),
        artefacts=Artefacts(
            schematic_source=Artefact(
                Published.YES,
                Evidence.OPENED,
                "'Adafruit HUZZAH32 ESP32 Feather.sch' — EagleCAD, proprietary binary. "
                "Fetched here, so the survey upgraded this cell from LISTED to OPENED",
            ),
            schematic_pdf=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "the only PDF is a pinout diagram, not a schematic",
            ),
            pcb_layout=Artefact(
                Published.YES,
                Evidence.LISTED,
                "'Adafruit HUZZAH32 ESP32 Feather.brd' — EagleCAD board",
            ),
            footprints_symbols=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "no .lbr here; Adafruit keeps its Eagle libraries in a separate "
                "repository, which this row does not cover",
            ),
            model_3d=Artefact(Published.NO, Evidence.ABSENT, "no STEP, WRL or STL"),
            board_support=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "software lives in separate repositories",
            ),
        ),
        cite="OH-23 survey, docs/research/board-sources/sources.json: "
        "Adafruit / one GitHub repository per board",
    ),
    Source(
        name="sparkfun-thing-plus-esp32-c6",
        vendor="SparkFun",
        model="one repository per board; 1,413 repositories under org:sparkfun",
        size="34,208 KiB",
        licence=Licence(
            name="CC BY-SA 4.0",
            covers="design files; the code in the same repository is under "
            "separate terms",
            sampled=True,
            evidence=Evidence.OPENED,
            cite="LICENSE.md in sparkfun/RP2040_Thing_Plus. **This repository's "
            "own README points at a LICENSE.md it does not contain**, while "
            "three sibling board repositories have one — so the licence here "
            "is inferred from a sibling and must be re-read per board",
        ),
        fetch=Fetch(
            transport=Transport.GIT_SPARSE,
            url="https://github.com/sparkfun/SparkFun_Thing_Plus_ESP32_C6.git",
            wanted=("Hardware",),
            skipped=(
                (
                    "Production",
                    "11 gerber layers, drill files, a panelised .brd and design "
                    "rules. Fabrication output, derived from the design source "
                    "in Hardware/ rather than a second copy of it",
                ),
                (
                    "docs",
                    "the product documentation site, images included. The "
                    "schematic PDF lives in here and is a rendering of the .sch "
                    "that Hardware/ already carries",
                ),
            ),
        ),
        artefacts=Artefacts(
            schematic_source=Artefact(
                Published.YES,
                Evidence.OPENED,
                "Hardware/Thing_Plus_ESP32_C6.sch — EagleCAD. Fetched here, so the "
                "survey upgraded this cell from LISTED to OPENED",
            ),
            schematic_pdf=Artefact(
                Published.YES,
                Evidence.LISTED,
                "docs/assets/board_files/Thing_Plus_ESP32_C6.pdf, which this "
                "row deliberately does not fetch",
            ),
            pcb_layout=Artefact(
                Published.YES,
                Evidence.LISTED,
                "Hardware/Thing_Plus_ESP32_C6.brd, plus a Production/ tree of "
                "gerbers",
            ),
            footprints_symbols=Artefact(
                Published.YES,
                Evidence.LISTED,
                "Hardware/ESP32-C6-WROOM-1.lbr — an Eagle library for the module",
            ),
            model_3d=Artefact(
                Published.NO, Evidence.ABSENT, "a dimensions PNG; no STEP or WRL"
            ),
            board_support=Artefact(
                Published.NO, Evidence.ABSENT, "not in the board repository"
            ),
        ),
        cite="OH-23 survey, docs/research/board-sources/sources.json: "
        "SparkFun / one GitHub repository per board",
    ),
    Source(
        name="raspberrypi-pico",
        vendor="Raspberry Pi",
        model="per-board zip linked from the product page",
        size="651,151 bytes",
        licence=Licence(
            name="bespoke permissive grant",
            covers="design files",
            sampled=True,
            evidence=Evidence.OPENED,
            cite="LICENSE.txt inside the zip: 'These design files are made "
            "available openly, with no limitations.' The adjacent Pico W zip "
            "ships no LICENSE.txt at all, which is why this is marked sampled",
        ),
        fetch=Fetch(
            transport=Transport.HTTPS_ARCHIVE,
            url="https://datasheets.raspberrypi.com/pico/RPi-Pico-R3-PUBLIC-20200119.zip",
            wanted=(),
            skipped=(),
        ),
        artefacts=Artefacts(
            schematic_source=Artefact(
                Published.YES,
                Evidence.OPENED,
                "RPI-PICO-R3-PUBLIC.DSN — OrCAD Capture, proprietary binary",
            ),
            schematic_pdf=Artefact(
                Published.YES,
                Evidence.OPENED,
                "RPI-PICO-R3-PUBLIC-SCHEMATIC.pdf, 260,692 bytes",
            ),
            pcb_layout=Artefact(
                Published.YES,
                Evidence.OPENED,
                "RPI-PICO-R3a-PUBLIC.brd — Cadence Allegro, proprietary binary",
            ),
            footprints_symbols=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "the zip has five entries and none is a library",
            ),
            model_3d=Artefact(
                Published.YES,
                Evidence.OPENED,
                "a separate download, Pico-R3-step.zip, holding Pico-R3.step",
            ),
            board_support=Artefact(
                Published.YES,
                Evidence.LISTED,
                "142 headers under src/boards/include/boards/ in "
                "raspberrypi/pico-sdk, BSD-3-Clause",
            ),
        ),
        cite="OH-23 survey, docs/research/board-sources/sources.json: "
        "Raspberry Pi / Pico design files (datasheets.raspberrypi.com)",
    ),
    Source(
        name="olimex-esp32-poe",
        vendor="Olimex",
        model="one repository per board; 144 under org:OLIMEX, HARDWARE/ per revision",
        size="36,801 KiB for the sampled board",
        licence=Licence(
            name="Apache-2.0",
            covers="design files",
            sampled=True,
            evidence=Evidence.OPENED,
            cite="LICENSE at repo root, read 2026-08-25. Sampled per repository "
            "and not per organisation, because the sibling OLIMEX/ESP32-POE-ISO "
            "has no LICENSE at all -- only a Licensee.pdf -- and GitHub reports "
            "no licence for it",
        ),
        fetch=Fetch(
            transport=Transport.GIT_SPARSE,
            url="https://github.com/OLIMEX/ESP32-POE.git",
            wanted=("HARDWARE",),
            skipped=(
                (
                    "SOFTWARE",
                    "85 .c, 41 .h and 34 .ino of example firmware. This project "
                    "models the board rather than compiling for it, and the "
                    "geometry OH-29 reads is entirely under HARDWARE/",
                ),
            ),
        ),
        artefacts=Artefacts(
            schematic_source=Artefact(
                Published.YES,
                Evidence.LISTED,
                "15 .sch and 3 .kicad_sch across revisions -- KiCad, text, "
                "parseable to a netlist; also 23 .lib and 3 .dcm",
            ),
            schematic_pdf=Artefact(
                Published.YES,
                Evidence.LISTED,
                "37 PDFs including per-revision colour and black-and-white "
                "schematics and a BOM PDF",
            ),
            pcb_layout=Artefact(
                Published.YES,
                Evidence.LISTED,
                "16 .kicad_pcb plus 142 .gbr gerbers, 28 .drl drill files and "
                "9 .net netlists. **This is the cell OH-29 turns on**: the board "
                "outline lives on the .kicad_pcb Edge.Cuts layer, in millimetres, "
                "beside the pads it has to agree with",
            ),
            footprints_symbols=Artefact(
                Published.YES, Evidence.LISTED, "23 .lib and 3 .dcm"
            ),
            model_3d=Artefact(
                Published.YES,
                Evidence.LISTED,
                "279 .step, 15 .stp and 151 .wrl -- the largest 3D holding in the "
                "survey by file count, and all of it component-level, under "
                "HARDWARE/<rev>/3d/: BAT54.step, C_0402_1005Metric.wrl, connector "
                "bodies. This is KiCad's per-footprint 3D library, not a model of "
                "the assembled board. Paired with the .kicad_pcb in the same "
                "directory it renders a board; on its own it does not",
            ),
            board_support=Artefact(
                Published.YES,
                Evidence.LISTED,
                "SOFTWARE/ in the same repository: 85 .c, 41 .h, 34 .ino",
            ),
        ),
        cite="OH-23 survey, docs/research/board-sources/sources.json: "
        "Olimex / OLIMEX/ESP32-POE (sampled)",
    ),
    Source(
        name="arduino-uno",
        vendor="Arduino",
        model="per-board CAD zip linked from the board's docs page",
        size="303,265 bytes",
        licence=Licence(
            name="CC BY-SA 4.0",
            covers="design files",
            sampled=False,
            evidence=Evidence.OPENED,
            cite="License.txt inside A000066-cad-files.zip, 211 bytes, says so "
            "explicitly and covers the hardware",
        ),
        fetch=Fetch(
            transport=Transport.HTTPS_ARCHIVE,
            # The hash in the path is the docs site's content-addressed asset
            # name and is not a version anybody publishes. It is the only URL
            # the board page links, so it is the one recorded; if it 404s, the
            # page at docs.arduino.cc/hardware/uno-rev3/ names the current one.
            url="https://docs.arduino.cc/static/"
            "6bb7a3ca51ebee82a252f60c0b418787/A000066-cad-files.zip",
            wanted=(),
            skipped=(),
        ),
        artefacts=Artefacts(
            schematic_source=Artefact(
                Published.YES,
                Evidence.OPENED,
                "UNO-TH_Rev3e.sch, 2,222,276 bytes. EAGLE 9.3.1, and the file "
                "is XML rather than a binary",
            ),
            schematic_pdf=Artefact(
                Published.YES,
                Evidence.STATED,
                "linked separately as A000066-schematics.pdf, not in this zip",
            ),
            pcb_layout=Artefact(
                Published.YES,
                Evidence.OPENED,
                "UNO-TH_Rev3e.brd, 707,996 bytes. EAGLE 9.3.1 XML: a 68.580 x "
                "53.340 mm outline in 12 segments on layer 20, 4 holes and 116 "
                "placed elements. tools/eagle.py reads it",
            ),
            footprints_symbols=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "no .lbr in the zip; it has five entries and two are __MACOSX "
                "resource forks",
            ),
            model_3d=Artefact(
                Published.NO,
                Evidence.ABSENT,
                "no STEP, WRL or mesh of any kind, in the zip or linked from "
                "the board page. Re-checked 2026-08-27 against KiCad's "
                "kicad-packages3D as well, whose Module.3dshapes holds two "
                "files and both are a Wemos D1 Mini. OH-75 composes a model "
                "from this .brd's placements instead of fetching one",
            ),
            board_support=Artefact(
                Published.YES,
                Evidence.LISTED,
                "arduino/ArduinoCore-avr, 19,021 KiB. GitHub reports no licence "
                "for it and there is no LICENSE file at the repository root",
            ),
        ),
        cite="OH-23 survey, docs/research/board-sources/sources.json: "
        "Arduino / per-board CAD zip on docs.arduino.cc. Fetched and opened "
        "again 2026-08-27 for OH-75",
    ),
)


def sources() -> tuple[Source, ...]:
    """Every source in the registry, in table order."""
    return SOURCES


def source(name: str) -> Source:
    """The source called `name`, or an error naming every source there is."""
    for candidate in SOURCES:
        if candidate.name == name:
            return candidate
    raise SourceError(
        f"no source called {name!r}. The registry holds: "
        f"{', '.join(candidate.name for candidate in SOURCES)}"
    )


def fetchable() -> tuple[Source, ...]:
    """The sources `tools/get_board_sources.py` can actually retrieve.

    Separated from `sources()` so that a vendor publishing behind a transport
    this project does not perform is *listed and excluded*, rather than
    quietly missing from the registry.
    """
    return tuple(
        candidate
        for candidate in SOURCES
        if candidate.fetch.transport is Transport.GIT_SPARSE
    )
