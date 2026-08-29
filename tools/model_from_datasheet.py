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
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import kicad  # noqa: E402

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
            "mouth_chamfer": (2.4, (
                "the two upper corners of a Series-B opening, cut off at 45 "
                "degrees. **Their PRESENCE is the standard's and it is not "
                "decoration: it is the KEY.** A Series-B plug's shell has the "
                "same two corners cut, which is what makes the pair mate one "
                "way up -- a socket drawn without them is a socket that would "
                "take the plug upside down. It is also the feature that tells "
                "a USB-B from an RJ45 at a glance, and a reader looking at "
                "this board called it an ethernet port, which is exactly what "
                "a plain rectangular metal socket is. "
                "The SIZE is a drawing quantity, the same standing as `wall` "
                "above: nothing measures it, nothing reaches it, and it is "
                "chosen so the bevel reads at the size this part renders at."
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


@dataclasses.dataclass(frozen=True)
class ModelledPack:
    """One flat surface-mount chip, from the vendor's own KiCad footprint.

    **Separate from `Modelled` rather than a mode of it**, because the two
    share a sentence and not a shape. `Modelled` reads EAGLE XML for a
    through-hole connector and asks it for signal pins, shell posts and a
    silkscreen; this reads a `.kicad_pcb` footprint and asks it for a body
    outline, a lead ring and an exposed pad. A single reader with a format
    flag would be one function doing two jobs badly, and its payload -- which
    is the part that actually differs -- would have to hold both vocabularies.

    What they DO share is the last step, and that is `run_blender`.
    """

    name: str
    #: The vendor's own footprint name, and the board file to read it out of.
    #: **Read, not copied**: a pad table retyped here would be a second source
    #: that can drift from the first.
    package: str
    pcb: pathlib.Path
    script: pathlib.Path
    #: Dimensions that are NOT geometry in that file, each with its source.
    cited: dict[str, tuple[float, str]]
    why_not_fetched: str


PACKS: tuple[ModelledPack, ...] = (
    ModelledPack(
        name="QFN_48_6x6_P0.4",
        package="QFN48-0.4-6X6X0.9MM_small",
        pcb=REPO / "third_party" / "seeed-pcb" / "ESP32-C5.kicad_pcb",
        script=REPO / "tools" / "blender" / "qfn_flatpack.py",
        cited={
            "height": (0.9, (
                "the last field of Seeed's own footprint name, "
                "`QFN48-0.4-6X6X0.9MM_small`, and the same reasoning as the "
                "QFN-60 below: a moulded slab's height is the one dimension a "
                "land pattern cannot express, so a footprint states it in the "
                "name or nowhere"
            )),
            "terminal": (0.23, (
                "how TALL a terminal is drawn and nothing else, exactly as "
                "for the QFN-60 below -- the leads' plan is the vendor's own "
                "pad clipped to the body. Under the chip, on a "
                "surface-mount part, changing no span `confirm` measures"
            )),
        },
        why_not_fetched=(
            "KiCad publishes `UQFN-48-1EP_6x6mm_P0.4mm_EP4.45x4.45mm`, which "
            "has the right lead count, body and pitch and is a DIFFERENT "
            "PART: `UQFN` is the ultra-thin height class, 0.6 mm or less, "
            "where Seeed's own name says 0.9, and its exposed pad is 4.45 mm "
            "against their 3.7. Its 6x6 neighbours are a Qorvo TQFN66 and a "
            "52-lead VQFN, so there is no closer one. The ESP32-C5 itself."
        ),
    ),
    ModelledPack(
        name="QFN_60_7x7_P0.4",
        package="QFN60-0.4-7X7X0.9MM",
        pcb=REPO / "third_party" / "seeed-pcb" / "RP2350.kicad_pcb",
        script=REPO / "tools" / "blender" / "qfn_flatpack.py",
        cited={
            "height": (0.9, (
                "the only number here that is not geometry, and it is still "
                "Seeed's own: their footprint is NAMED "
                "`QFN60-0.4-7X7X0.9MM`, and the 0.9 is the last field of it. "
                "A QFN is a moulded slab whose height is the one dimension "
                "its land pattern cannot carry, so a footprint states it in "
                "the name or nowhere"
            )),
            "terminal": (0.23, (
                "how TALL a terminal is drawn, and nothing else -- their "
                "plan is the vendor's own pad clipped to the body, with no "
                "number of ours in it. A drawing thickness rather than a "
                "measurement: a land pattern states where copper goes and "
                "never how far a terminal wraps up the side of the moulding. "
                "Nothing depends on it. The part is surface-mount so nothing "
                "hangs below the board, this is under the chip where a wire "
                "never goes, and it changes no span `confirm` measures"
            )),
        },
        why_not_fetched=(
            "KiCad's Package_DFN_QFN holds no QFN-60 at all -- 191 files "
            "listed on 2026-08-29 against the canonical library on GitLab, "
            "nothing matching a 60-lead name, and no Raspberry Pi or MCU "
            "library among its 115 top-level directories. Raspberry Pi "
            "publish KiCad reference designs for the RP2350A and RP2350B "
            "minimal viable boards and no STEP for the chip. Seeed ship a "
            "STEP inside the PCB archive for the MG24 and the nRF54LM20A and "
            "not for this board. If any of those three appears it is strictly "
            "better than this and should replace it. What must NOT replace it "
            "is `QFN-56-1EP_7x7mm_P0.4mm`: right body, right pitch, four "
            "leads short, and it would put a false part name in this model's "
            "own list."
        ),
    ),
)


@dataclasses.dataclass(frozen=True)
class ModelledSlab:
    """A moulded package whose whole body the vendor states, drawn as it is.

    **Separate from `ModelledPack` for the reason that one is separate from
    `Modelled`**: not a different format, a different SHAPE. A flat pack has a
    lead ring and an exposed pad to read; this has neither, and the two
    payloads share no field but the body. Merging them would mean one Blender
    script branching on which half of its input was present.

    A moulded chip package is a slab. Drawing its stated envelope is not an
    approximation of the part -- it is the part, minus a lens or a port hole.
    """

    #: Seeed's own footprint name, which states length x width x HEIGHT, and
    #: the board file to read its plan out of. Some boards draw `F.Fab` for a
    #: package and others do not, so this names one that does.
    package: str
    pcb: pathlib.Path
    #: `#rrggbb`, and one line saying what the material is.
    colour: str
    colour_source: str
    why_not_fetched: str

    @property
    def name(self) -> str:
        """A file name. The package's, with what a path cannot hold removed."""
        return re.sub(r"[^A-Za-z0-9_.-]", "_", self.package)


#: The three numbers a Seeed footprint name ends with: length, width, height.
#: `WLCSP20-0.4-2.4X1.9X0.5MM_SMALL` is why this searches rather than anchors.
_NAMED_BODY = re.compile(r"(\d+(?:\.\d+)?)[xX](\d+(?:\.\d+)?)[xX](\d+(?:\.\d+)?)MM")

#: How far the name's plan and `F.Fab`'s may disagree before the name is not
#: believed. **This is what proves the parse**, and it is the whole safety of
#: reading dimensions out of a string: `MIC6P-0.94-4X2X1.1MM` says 4 x 2 and
#: its assembly outline measures 4.27 x 2.26, so a name read wrongly -- taking
#: a pitch for a length, say -- misses by millimetres and not by a quarter.
NAMED_BODY_TOLERANCE_MM = 0.5

SLABS: tuple[ModelledSlab, ...] = (
    ModelledSlab(
        package="ANT2P-5.2x2x1.1MM",
        pcb=REPO / "third_party" / "seeed-pcb" / "nRF54L15.kicad_pcb",
        colour="#c6c4a0",
        colour_source=(
            "a chip antenna is a ceramic block, and this is the same "
            "off-white `tools/import_3d_model.py` already gives ceramic in "
            "FINISHES rather than a colour chosen here"
        ),
        why_not_fetched=(
            "KiCad's RF_Antenna library holds exactly four models -- two "
            "Johanson chip antennas, an AVX and a Pulse -- and none is 5.2 mm "
            "long, counted 2026-08-29. The nRF54L15 names Seeed's own "
            "`ANT_KH5220-A36`, under a path they do not publish."
        ),
    ),
    ModelledSlab(
        package="SW4-SMD-2.8-2.6X1.6X0.53MM",
        pcb=REPO / "third_party" / "seeed-pcb" / "RP2350.kicad_pcb",
        colour="#0f0f0f",
        colour_source="moulded black plastic, the switch body",
        why_not_fetched=(
            "the smallest surface-mount switch in KiCad's 159-file "
            "Button_Switch_SMD is the TS-1088 at 2.9 x 3.9 mm, against a "
            "2.6 x 1.6 mm part -- more than twice the footprint."
        ),
    ),
    ModelledSlab(
        package="MIC6P-0.94-4X2X1.1MM",
        pcb=REPO / "third_party" / "seeed-pcb" / "nRF54L15.kicad_pcb",
        colour="#4e4e4e",
        colour_source="a MEMS microphone's steel lid",
        why_not_fetched=(
            "the nRF54L15 names Seeed's own `312030722_MSM261DGT006`, which "
            "they do not publish, and KiCad has no microphone library."
        ),
    ),
    ModelledSlab(
        package="WLCSP47-0.3-2.451X2.245X0.42MM",
        pcb=REPO / "third_party" / "seeed-pcb" / "nRF54L15.kicad_pcb",
        colour="#272b27",
        colour_source=(
            "a wafer-level CSP is a bare silicon die, which is what the dark "
            "grey-green here is meant to read as rather than moulded epoxy"
        ),
        why_not_fetched=(
            "KiCad's Package_CSP holds 34 files and not one WLCSP-47; the "
            "closest by ball count is a WLCSP-49 at 3.44 x 3.44 mm, half "
            "again as large. The nRF54L15 itself."
        ),
    ),
    ModelledSlab(
        package="WLCSP20-0.4-2.4X1.9X0.5MM_SMALL",
        pcb=REPO / "third_party" / "seeed-pcb" / "nRF54L15.kicad_pcb",
        colour="#272b27",
        colour_source="a bare silicon die, as the WLCSP-47 above",
        why_not_fetched=(
            "KiCad has two WLCSP-20s, both 4x5 layouts at 1.7 x 2.1 and "
            "1.94 x 2.4 mm, and each names the maker of a different part. "
            "Seeed name their own `WLCSP20`, which they do not publish."
        ),
    ),
    ModelledSlab(
        package="IPEX-GEN4-SMD-1.7X1.7X1.0MM",
        pcb=REPO / "third_party" / "seeed-pcb" / "nRF54L15.kicad_pcb",
        colour="#a5a392",
        colour_source="the plated shell of a coaxial socket",
        why_not_fetched=(
            "KiCad's Connector_Coaxial holds fifteen models and its only "
            "sub-miniature one is the 2.6 mm U.FL, which would overhang a "
            "1.7 mm part by half a millimetre in each direction."
        ),
    ),
    ModelledSlab(
        package="LED4-0.8-1.6X1.5X0.55MM",
        pcb=REPO / "third_party" / "seeed-pcb" / "RP2350.kicad_pcb",
        colour="#ebebe5",
        colour_source="the diffuser over an RGB LED, unlit",
        why_not_fetched=(
            "KiCad's LED_SMD holds 39 files whose smallest RGB part is the "
            "1210 at 3.2 x 2.5 mm, twice this one."
        ),
    ),
    ModelledSlab(
        package="LED4-0.85-1.6X1.5X0.6MM",
        pcb=REPO / "third_party" / "seeed-pcb" / "RP2350.kicad_pcb",
        colour="#ebebe5",
        colour_source="the diffuser over an RGB LED, unlit",
        why_not_fetched=(
            "the same absence as the 0.8 mm pitch part above: no RGB LED in "
            "KiCad's library is under 3.2 mm."
        ),
    ),
)


@dataclasses.dataclass(frozen=True)
class ModelledSocket:
    """A USB Type-C receptacle, from the land pattern the vendor fitted it to.

    **A fourth shape, and separate for the reason the other three are**: a
    receptacle is a folded metal box with a hole in one end, a paddle inside
    it and two kinds of pad under it -- signal tails, shell feet and board
    locks. A `ModelledSlab` is one box and a `ModelledPack` is a box with a
    ring of terminals; neither has an opening, and an opening is the whole
    difference between a socket and a lump.

    What all four share is the last step, `run_blender`, and the rule: every
    number is either the vendor's or carries a citation beside it.
    """

    #: Seeed's own footprint name, and the board file to read it out of. Some
    #: boards draw `F.Fab` for a package and others do not -- the ESP32-C3
    #: draws none at all for its receptacle -- so this names one that does.
    package: str
    pcb: pathlib.Path
    #: Dimensions that are NOT in that file, each with its source.
    cited: dict[str, tuple[float, str]]
    why_not_fetched: str

    @property
    def name(self) -> str:
        """A file name. The package's, with what a path cannot hold removed."""
        return re.sub(r"[^A-Za-z0-9_.-]", "_", self.package)


#: `#rrggbb` per material, and where each was READ. Not one is chosen here:
#: every value is what a shipped vendor STEP gives that material, which is the
#: same standing `tools/import_3d_model.py` gives a colour it reads out of a
#: file rather than one it decides.
#:
#: The contact gold is in `compose_board_3d.CONTACT_COLOURS` on purpose and
#: not by luck: that set is what the composer reads to find a part's plated
#: contacts, so a receptacle whose tails were some other gold would be a part
#: with no measurable facing -- and the turn is the one thing about this part
#: that has been wrong three times.
SOCKET_COLOURS: dict[str, tuple[str, str]] = {
    "shell": ("#a5a392", (
        "the shell colour GCT's own STEP carries, which is also what the four "
        "boards that draw a steel-looking socket already show. Amphenol's "
        "model says #1d1d1d for the same steel, and drawing two of the five "
        "XIAOs with a black connector and three with a metal one made them "
        "look like different parts. They are not."
    )),
    "cavity": ("#050505", (
        "the insulator colour Amphenol's own STEP carries -- the darkest thing "
        "in either published model, which is what the inside of a socket is"
    )),
    "insulator": ("#0f0f0f", (
        "the insulator colour GCT's own STEP carries. A shade off the cavity "
        "above so that the tongue is visible against the hole it sits in, and "
        "both are readings rather than a pair chosen to contrast"
    )),
    "contact": ("#b58136", (
        "the gold BOTH published receptacles give their contacts, and one of "
        "the four values in `compose_board_3d.CONTACT_COLOURS`"
    )),
}

#: The envelope Seeed state in the footprint's own `Description` property:
#: `SMD USB TYPE C-W/P;12+4P-7.35*8.94*3.25mm`. Length, width, height, in
#: millimetres, and the height is the dimension no layer of a land pattern can
#: carry -- the same absence the QFN's footprint NAME fills.
_STATED_ENVELOPE = re.compile(
    r"(\d+(?:\.\d+)?)\*(\d+(?:\.\d+)?)\*(\d+(?:\.\d+)?)\s*mm", re.IGNORECASE)

#: A USB Type-C contact is named by the specification -- A1 to A12 along one
#: row and B1 to B12 along the other -- and a USB 2.0 receptacle joins four
#: pairs inside itself, which is why a 16-contact part arrives on 12 pads and
#: says so: `A1_B12`, `A4_B9`, `B4_A9`, `B1_A12`.
#:
#: **This is how a contact is told from a shell tab**, and it is the vendor
#: writing the standard's own vocabulary rather than a rule invented here. The
#: shell pads are `S1` upward and the mounting slots carry no number at all.
_SPEC_CONTACT = re.compile(r"^[AB]\d{1,2}(?:_[AB]\d{1,2})*$")

#: How far apart the contact pads' own axis may spread before they are not a
#: row. They share one coordinate exactly on both of these land patterns, so
#: this is a guard against reading a footprint this script does not draw --
#: one whose depth runs along y, say -- rather than a tolerance being spent.
CONTACT_ROW_MM = 0.05

#: The number of Type-C contacts a 16-pin receptacle has, which is what makes
#: `16P` in the vendor's own package name a fact about the part rather than a
#: string. Counted over the designations in the pad names: twelve pads, four
#: of which name two contacts each.
SPEC_CONTACTS = 16

SOCKETS: tuple[ModelledSocket, ...] = (
    ModelledSocket(
        package="USB2.0-TYPE-C",
        pcb=REPO / "third_party" / "seeed-pcb" / "ESP32-C6.kicad_pcb",
        cited={
            "opening_width": (8.34, (
                "the USB Type-C specification's plug interface, which is what "
                "the socket has to admit. Fixed by the standard rather than by "
                "a manufacturer, for the same reason the Uno's USB-B shell "
                "height is: a cable from any maker has to enter a socket from "
                "any other. It is also the ONLY number in this part that is "
                "not Seeed's, together with its height below"
            )),
            "opening_height": (2.56, (
                "the same interface's height. Together with the width this is "
                "the aperture the standard defines, and everything the shell "
                "measures follows from it by subtraction from the vendor's own "
                "body: 0.30 mm of folded sheet at the sides, 0.32 above and "
                "below"
            )),
            "terminal": (0.20, (
                "how THICK a solder tail is drawn and nothing else. The tails' "
                "plan is the vendor's own pad clipped to the metal outside the "
                "shell, with no number of ours in it; this is the one "
                "dimension a land pattern cannot state, it is under the "
                "connector against the board, and it changes no span `confirm` "
                "measures"
            )),
            "post_depth": (1.0, (
                "how far the shell tabs stand below the board. Not a datasheet "
                "figure and not one either: it is how far "
                "`compose_board_3d.leads_of` has to see them, and it is under "
                "the PCB where nothing looks"
            )),
            "tongue_width": (6.70, (
                "the paddle inside the opening, drawn so the socket reads as a "
                "socket rather than a hole. A drawing quantity like the "
                "USB-B's `mouth_width - 2.0`, not a measurement -- nothing "
                "reaches it, nothing measures it, and it is 1.64 mm inside an "
                "opening the standard fixes"
            )),
            "tongue_thickness": (0.70, (
                "the same paddle's thickness, and the same standing: a drawing "
                "quantity inside a cavity nothing enters"
            )),
            "tongue_setback": (1.00, (
                "how far behind the shell's lip the paddle's front edge sits. "
                "Drawn rather than measured, and it exists because a tongue "
                "flush with the cavity would share a face with it and the two "
                "would fight for the one surface anybody looks at"
            )),
        },
        why_not_fetched=(
            "**Seeed state the model for this one and it is still the wrong "
            "length.** Their ESP32-C6 names "
            "`Connector_USB.3dshapes/USB_C_Receptacle_GCT_USB4105-xx-A_16P_"
            "TopMnt_Horizontal.step`, which is 7.78 mm deep where the same "
            "footprint's own Description says 7.3 -- so the vendor's statement "
            "and the vendor's dimensions disagree, and the dimensions are the "
            "measurement. KiCad's `Connector_USB` holds thirteen files and "
            "exactly two 16-pin receptacles, the GCT above at 7.78 and "
            "Amphenol's 12401610E4-2A at 10.50, so there is no third to try."
        ),
    ),
    ModelledSocket(
        package="USB2.0-TYPE-C_USB-31C-F-16P",
        pcb=REPO / "third_party" / "seeed-pcb" / "RP2350.kicad_pcb",
        cited={
            "opening_width": (8.34, (
                "the USB Type-C specification's plug interface, as for the "
                "four-tab land above and for the same reason"
            )),
            "opening_height": (2.56, (
                "the same interface's height. On this part's 8.94 x 3.25 mm "
                "envelope it leaves 0.30 mm of folded sheet at the sides and "
                "0.345 above and below, which is what a stainless receptacle "
                "shell is made from -- the numbers cohere rather than merely "
                "fitting"
            )),
            "terminal": (0.20, (
                "how THICK a solder tail is drawn, as above: under the "
                "connector, against the board, measured by nothing"
            )),
            "post_depth": (1.0, (
                "how far the two board locks stand below the board, which is "
                "how far `compose_board_3d.leads_of` has to see them"
            )),
            "tongue_width": (6.70, (
                "the paddle inside the opening, as for the four-tab land "
                "above: a drawing quantity rather than a measurement, sitting "
                "1.64 mm inside an opening the standard fixes, reached by "
                "nothing and measured by nothing"
            )),
            "tongue_thickness": (0.70, (
                "the same paddle's thickness, and the same standing: a drawing "
                "quantity inside a cavity that nothing enters"
            )),
            "tongue_setback": (1.00, (
                "how far behind the shell's lip the paddle's front edge sits, "
                "as above -- drawn rather than measured, and it exists so that "
                "the paddle and the cavity do not share the one face anybody "
                "looks at"
            )),
        },
        why_not_fetched=(
            "the vendor names a part they do not publish -- "
            "`USB-31C-F-16P-L7.35.stp` on the RP2350 and "
            "`320011419_ST-USB-3316T.stp` on the nRF54L15 and the ESP32-C5, "
            "both under a `Y:/01_Cadence_Library` path that is a drive on "
            "somebody's desk. **`L7.35` is the body length and it is in the "
            "file name**, which is what makes the absence measurable: KiCad's "
            "two 16-pin receptacles are 7.78 and 10.50 mm deep, so the nearer "
            "of them is 0.43 mm too long and the one this land pattern needs "
            "-- it is the two-board-lock part, see OH-101 -- is 3.15 mm too "
            "long."
        ),
    ),
)


def socket_geometry(spec: ModelledSocket) -> dict[str, object]:
    """A receptacle's body, opening end, tails, feet and locks, from the vendor.

    **Two of Seeed's own sources, and each checks the other.** `F.Fab` is
    KiCad's assembly drawing and carries the plan to four decimals; the
    footprint's `Description` property states length, width AND height, which
    is the one dimension a land pattern cannot express. Comparing the two is
    what proves the string was read correctly rather than merely parsed -- the
    same argument `slab_geometry` rests on, against the same tolerance.

    **Y is negated**, exactly as `pack_geometry` negates it and for the same
    reason: KiCad measures down the page and the composer works in a frame
    whose y runs up. Both of these land patterns are symmetric about their own
    y, so this is currently unobservable and is done anyway -- a receptacle
    mounted off its own centre line would expose it at once.
    """
    tree = kicad.parse_sexp(spec.pcb.read_text(encoding="utf-8", errors="replace"))
    wanted = [n for n in kicad.children(tree, "footprint")
              if (n[1] if len(n) > 1 and isinstance(n[1], str) else ""
                  ).split(":", 1)[-1] == spec.package]
    if not wanted:
        raise SystemExit(f"{spec.pcb}: no footprint called {spec.package!r}")
    node = wanted[0]

    body = kicad._body_of(node)
    if body is None:
        raise SystemExit(
            f"{spec.package}: {spec.pcb.name} draws no *.Fab outline for it, "
            f"so there is no plan to read. Another board may; name that one."
        )

    described = ""
    for prop in kicad.children(node, "property"):
        if len(prop) > 2 and prop[1] == "Description" and isinstance(prop[2], str):
            described = prop[2]
    stated = _STATED_ENVELOPE.search(described)
    if stated is None:
        raise SystemExit(
            f"{spec.package}: its Description is {described!r}, which states "
            f"no length*width*height. The height is the one dimension no layer "
            f"of a land pattern carries, and a body of invented thickness is "
            f"what this whole file exists not to draw."
        )
    length, width, height = (float(g) for g in stated.groups())

    drawn = sorted((body[2] - body[0], body[3] - body[1]))
    claimed = sorted((length, width))
    apart = max(abs(a - b) for a, b in zip(drawn, claimed))
    if apart > NAMED_BODY_TOLERANCE_MM:
        raise SystemExit(
            f"{spec.package}: its Description says {length} x {width} mm and "
            f"its F.Fab measures {drawn[1]:.3f} x {drawn[0]:.3f}, which are "
            f"{apart:.3f} mm apart. Either the string was read wrongly or it "
            f"does not describe this footprint; do not draw either."
        )

    pads = kicad._pads_of(node)
    contacts = [p for p in pads
                if p.kind == "smd" and _SPEC_CONTACT.match(p.number)]
    feet = [p for p in pads
            if p.kind == "smd" and not _SPEC_CONTACT.match(p.number)]
    #: The mounting slots are neither: `np_thru_hole` is a hole with no copper
    #: in it, so nothing solders to it and nothing is drawn for it.
    posts = [p for p in pads if p.kind == "thru_hole"]

    designations = [name for pad in contacts for name in pad.number.split("_")]
    if len(set(designations)) != SPEC_CONTACTS:
        raise SystemExit(
            f"{spec.package}: its {len(contacts)} contact pads name "
            f"{len(set(designations))} of the specification's contacts and a "
            f"16-pin receptacle has {SPEC_CONTACTS}: "
            f"{sorted(set(designations))}"
        )
    if not posts:
        raise SystemExit(
            f"{spec.package}: no through-hole pads, so the model would have "
            f"no legs -- and `compose_board_3d.place` anchors a legged part on "
            f"them. A receptacle with none is a different mounting."
        )

    spread = max(p.x_mm for p in contacts) - min(p.x_mm for p in contacts)
    if spread > CONTACT_ROW_MM:
        raise SystemExit(
            f"{spec.package}: its contacts spread {spread:.3f} mm across x, so "
            f"they are not a row and this footprint's depth does not run along "
            f"x. `tools/blender/usb_c_receptacle.py` draws one that does."
        )

    bx0, bx1 = sorted((body[0], body[2]))
    by0, by1 = sorted((-body[1], -body[3]))
    #: **Which end the plug goes into, READ rather than assumed.** A
    #: receptacle's contacts leave at its back and solder to pads, so the end
    #: the tails are at is the back and the mouth is the other one -- the same
    #: physical fact `compose_board_3d.contact_miss` rests on, and the one
    #: OH-105 got backwards by measuring triangle area in each end plane.
    row = sum(p.x_mm for p in contacts) / len(contacts)
    back, front = (bx1, bx0) if row > (bx0 + bx1) / 2 else (bx0, bx1)

    tails = []
    for pad in contacts:
        near, far = pad.x_mm - pad.width_mm / 2, pad.x_mm + pad.width_mm / 2
        outside = (max(near, back), far) if back == bx1 else (near, min(far, back))
        if outside[1] <= outside[0]:
            raise SystemExit(
                f"{spec.package}: pad {pad.number} spans x {near:.3f}..{far:.3f} "
                f"and the shell's back face is at {back:.3f}, so none of it is "
                f"outside the body. A tail entirely under the shell is not a "
                f"tail, and the body or the row has been read wrongly."
            )
        tails.append({"x": list(outside),
                      "y": [-pad.y_mm - pad.height_mm / 2,
                            -pad.y_mm + pad.height_mm / 2]})

    #: A shell foot entirely inside the body's own plan is INVISIBLE -- it is
    #: under the folded metal that is drawn over it -- so it is not drawn.
    #: Skipped rather than drawn anyway, because a box sharing a face with the
    #: shell's own bottom plate is two surfaces fighting for one pixel.
    standing = [pad for pad in feet
                if not (bx0 <= pad.x_mm - pad.width_mm / 2
                        and pad.x_mm + pad.width_mm / 2 <= bx1
                        and by0 <= -pad.y_mm - pad.height_mm / 2
                        and -pad.y_mm + pad.height_mm / 2 <= by1)]

    def plan(pad) -> dict[str, list[float]]:
        return {"x": [pad.x_mm - pad.width_mm / 2, pad.x_mm + pad.width_mm / 2],
                "y": [-pad.y_mm - pad.height_mm / 2,
                      -pad.y_mm + pad.height_mm / 2]}

    return {
        "body": {"x": [bx0, bx1], "y": [by0, by1], "height": height},
        "front_face": front,
        "back_face": back,
        "contacts": tails,
        "feet": [plan(pad) for pad in standing],
        "posts": [plan(pad) for pad in posts],
        "designations": sorted(set(designations)),
        "hidden_feet": len(feet) - len(standing),
        "stated": [length, width, height],
        "apart": apart,
    }


def build_socket(spec: ModelledSocket, check: bool) -> int:
    print(f"{spec.name}:")
    if not spec.pcb.is_file():
        print(f"  SKIPPED: {spec.pcb} is not fetched. Run: "
              f"python tools/compose_board_3d.py")
        return 3
    plan = socket_geometry(spec)
    cited = {key: value for key, (value, _why) in spec.cited.items()}
    body = plan["body"]
    length, width, height = plan["stated"]
    print(f"  vendor  F.Fab {body['x'][1] - body['x'][0]:.3f} x "
          f"{body['y'][1] - body['y'][0]:.3f} mm; its own Description says "
          f"{length} x {width} x {height}, agreeing to {plan['apart']:.3f} mm")
    print(f"  vendor  {len(plan['contacts'])} contact pads naming "
          f"{len(plan['designations'])} of the standard's contacts, "
          f"{len(plan['feet'])} shell feet ({plan['hidden_feet']} under the "
          f"shell, not drawn), {len(plan['posts'])} board locks")
    print(f"  vendor  the plug enters at x {plan['front_face']:.3f} and the "
          f"tails leave at {plan['back_face']:.3f}")
    for key, (value, why) in spec.cited.items():
        print(f"  cited   {key} = {value} mm -- {why[:64]}...")
    if check:
        print("  build   skipped (--check)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{spec.name}.obj"
    run_blender(spec.name, REPO / "tools" / "blender" / "usb_c_receptacle.py", {
        "out": str(target).replace("\\", "/"),
        "body": body,
        "front_face": plan["front_face"],
        "back_face": plan["back_face"],
        "opening": {"width": cited["opening_width"],
                    "height": cited["opening_height"]},
        "tongue": {"width": cited["tongue_width"],
                   "thickness": cited["tongue_thickness"],
                   "setback": cited["tongue_setback"]},
        "terminal": cited["terminal"],
        "post_depth": cited["post_depth"],
        "contacts": plan["contacts"],
        "feet": plan["feet"],
        "posts": plan["posts"],
        "colours": {name: [int(rgb[at:at + 2], 16) / 255.0 for at in (1, 3, 5)]
                    for name, (rgb, _why) in SOCKET_COLOURS.items()},
    }, target)
    print(f"  build   {target.relative_to(REPO)}  "
          f"{target.stat().st_size:,} bytes")
    return 0


def slab_geometry(spec: ModelledSlab) -> dict[str, object]:
    """The body of `spec.package`: plan from `F.Fab`, height from its name.

    **Two vendor sources, and each checks the other.** `F.Fab` is KiCad's
    assembly drawing and carries the plan to three decimals; the height is the
    one dimension a land pattern cannot express, so it lives in the footprint
    name or nowhere -- the same argument OH-100's QFN-60 rests on.

    The name also states the plan, and that is not redundant: comparing the
    two is what proves the name was parsed correctly. A string read wrongly --
    a pitch mistaken for a length -- misses by millimetres, and
    `NAMED_BODY_TOLERANCE_MM` is a half.
    """
    tree = kicad.parse_sexp(spec.pcb.read_text(encoding="utf-8", errors="replace"))
    wanted = [n for n in kicad.children(tree, "footprint")
              if (n[1] if len(n) > 1 and isinstance(n[1], str) else ""
                  ).split(":", 1)[-1] == spec.package]
    if not wanted:
        raise SystemExit(f"{spec.pcb}: no footprint called {spec.package!r}")
    body = kicad._body_of(wanted[0])
    if body is None:
        raise SystemExit(
            f"{spec.package}: {spec.pcb.name} draws no *.Fab outline for it, "
            f"so there is no plan to read. Another board may; name that one."
        )

    named = _NAMED_BODY.search(spec.package)
    if named is None:
        raise SystemExit(
            f"{spec.package}: its name states no length x width x height, so "
            f"the one dimension no layer carries is unknown. A body of "
            f"invented thickness is what this whole file exists not to draw."
        )
    length, width, height = (float(g) for g in named.groups())

    drawn = sorted((body[2] - body[0], body[3] - body[1]))
    claimed = sorted((length, width))
    apart = max(abs(a - b) for a, b in zip(drawn, claimed))
    if apart > NAMED_BODY_TOLERANCE_MM:
        raise SystemExit(
            f"{spec.package}: its name says {length} x {width} mm and its "
            f"F.Fab measures {drawn[1]:.3f} x {drawn[0]:.3f}, which are "
            f"{apart:.3f} mm apart. Either the name was read wrongly or it "
            f"does not describe this footprint; do not draw either."
        )
    #: Y negated into the composer's frame, as `pack_geometry` does and for the
    #: same reason. A slab is symmetric so it cannot show, and the next one
    #: might not be.
    return {"x": sorted([body[0], body[2]]),
            "y": sorted([-body[1], -body[3]]),
            "height": height,
            "named": [length, width, height],
            "apart": apart}


def build_slab(spec: ModelledSlab, check: bool) -> int:
    print(f"{spec.name}:")
    if not spec.pcb.is_file():
        print(f"  SKIPPED: {spec.pcb} is not fetched. Run: "
              f"python tools/compose_board_3d.py")
        return 3
    plan = slab_geometry(spec)
    length, width, height = plan["named"]
    print(f"  vendor  F.Fab {plan['x'][1] - plan['x'][0]:.3f} x "
          f"{plan['y'][1] - plan['y'][0]:.3f} mm; its own name says "
          f"{length} x {width} x {height}, agreeing to {plan['apart']:.3f} mm")
    print(f"  colour  {spec.colour} -- {spec.colour_source}")
    if check:
        print("  build   skipped (--check)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{spec.name}.obj"
    run_blender(spec.name, REPO / "tools" / "blender" / "moulded_slab.py", {
        "out": str(target).replace("\\", "/"),
        "x": plan["x"],
        "y": plan["y"],
        "height": plan["height"],
        "colour": [int(spec.colour[at:at + 2], 16) / 255.0
                   for at in (1, 3, 5)],
    }, target)
    print(f"  build   {target.relative_to(REPO)}  "
          f"{target.stat().st_size:,} bytes")
    return 0


def pack_geometry(spec: ModelledPack) -> dict[str, object]:
    """Body, lead ring and exposed pad of `spec.package`, from the vendor.

    **Y is negated, exactly as `compose_board_3d.from_kicad` negates it for
    pads.** KiCad measures down the page and the composer works in a frame
    whose y runs up, so a model built in the file's own frame is MIRRORED
    against the placement that will position it. A QFN body is four-fold
    symmetric, so that draws perfectly and moves one thing: the pin-1 marker,
    which is the only feature on the part that says which way round it is.
    """
    tree = kicad.parse_sexp(spec.pcb.read_text(encoding="utf-8", errors="replace"))
    wanted = [n for n in kicad.children(tree, "footprint")
              if (n[1] if len(n) > 1 and isinstance(n[1], str) else ""
                  ).split(":", 1)[-1] == spec.package]
    if not wanted:
        raise SystemExit(f"{spec.pcb}: no footprint called {spec.package!r}")
    node = wanted[0]

    pads = kicad._pads_of(node)
    #: The exposed pad is the one that is not a lead, and it is told apart by
    #: AREA rather than by number: it is 3.45 mm square against a lead of
    #: 0.6 x 0.18, which is a factor of a hundred. Pad "61" would work on this
    #: part and is the vendor's numbering rather than a fact about QFNs.
    leads = [p for p in pads if p.width_mm * p.height_mm < 1.0]
    flags = [p for p in pads if p.width_mm * p.height_mm >= 1.0]
    if len(flags) != 1:
        raise SystemExit(
            f"{spec.package}: {len(flags)} pads are larger than a lead and "
            f"this expects exactly one exposed pad: "
            f"{[p.number for p in flags]}"
        )

    #: `*.Fab` is KiCad's own convention for the part's body outline, which is
    #: what makes the 7 x 7 mm a reading rather than a parse of the package
    #: name. `F.CrtYd` is the keep-out around it and is 0.01 mm larger there,
    #: so taking the wrong one would be invisible and wrong.
    #:
    #: **Read through `kicad._body_of` rather than here**, which this did
    #: until OH-108: it looked for an `fp_rect` and the ESP32-C5 draws its
    #: QFN's body as four lines, so a part whose outline was perfectly present
    #: was refused as absent. That function knows the difference between a
    #: closed outline and the loose lines a keep-out is drawn with, learned in
    #: OH-105, and having two readers of one layer meant only one of them did.
    corners = kicad._body_of(node)
    if corners is None:
        raise SystemExit(
            f"{spec.package}: nothing on *.Fab in {spec.pcb.name}, so there "
            f"is no body outline to read. Another board may draw one."
        )

    #: The pin-1 marker, and it is optional: a part without one is drawn
    #: without one rather than refused, because the alternative is inventing
    #: which corner is pin 1.
    mark = None
    for circle in kicad.children(node, "fp_circle"):
        layer = kicad.first(circle, "layer")
        if not (layer and len(layer) > 1 and layer[1] == "F.Fab"):
            continue
        centre = kicad._floats(kicad.first(circle, "center"))
        edge = kicad._floats(kicad.first(circle, "end"))
        if len(centre) >= 2 and len(edge) >= 2:
            mark = {"x": centre[0], "y": -centre[1],
                    "radius": max(abs(edge[0] - centre[0]),
                                  abs(edge[1] - centre[1]))}
    return {
        "body": {"x": sorted([corners[0], corners[2]]),
                 "y": sorted([-corners[1], -corners[3]])},
        "leads": [{"x": p.x_mm, "y": -p.y_mm,
                   "w": p.width_mm, "h": p.height_mm} for p in leads],
        # The negation here is CURRENTLY UNOBSERVABLE and is kept anyway: an
        # exposed pad is centred, so this one is at (0, 0) and -0.0 == 0.0.
        # A mutation removing it survives the suite, and that is a property of
        # the part rather than a gap in the tests -- recorded so nobody hunts
        # it twice. A flat pack with an off-centre flag would expose it.
        "flag": {"x": flags[0].x_mm, "y": -flags[0].y_mm,
                 "w": flags[0].width_mm, "h": flags[0].height_mm},
        "mark": mark,
    }


def run_blender(name: str, script: pathlib.Path, payload: dict[str, object],
                target: pathlib.Path) -> None:
    """Hand a payload to a Blender script and require it to write the mesh.

    The one step both kinds of modelled part share, and the one carrying every
    lesson that cost a session: the payload goes in a FILE, the pipe is
    decoded as UTF-8, and the script has to say `WROTE` before this believes
    it.
    """
    # **The payload goes in a file, not on argv.** Passed inline it is a
    # single argument full of quotes and braces, and Windows' command line is
    # rebuilt from a string by the runtime -- the JSON arrived mangled and
    # `subprocess` returned a `stdout` of None rather than an error anybody
    # could read.
    handover = OUT / f"{name}.json"
    handover.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    done = subprocess.run(
        [blender(), "--background", "--python", str(script), "--",
         str(handover)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600, check=False)
    # **`encoding` given explicitly**, because `text=True` alone decodes with
    # the locale codec -- cp1252 on this machine -- and Blender's banner is not
    # cp1252. The decode raised inside subprocess and `stdout` came back None,
    # which reads as "Blender printed nothing" and is a two-hour wrong turn.
    if done.stdout is None:
        raise SystemExit(f"{name}: Blender produced no output at all")
    if f"WROTE {str(target).replace(chr(92), '/')}" not in done.stdout:
        raise SystemExit(
            f"{name}: Blender did not write the mesh.\n"
            f"--- stdout ---\n{done.stdout[-2000:]}\n"
            f"--- stderr ---\n{done.stderr[-2000:]}"
        )


def build_pack(spec: ModelledPack, check: bool) -> int:
    print(f"{spec.name}:")
    if not spec.pcb.is_file():
        print(f"  SKIPPED: {spec.pcb} is not fetched. Run: "
              f"python tools/compose_board_3d.py --board XIAO-RP2350-DIP")
        return 3
    plan = pack_geometry(spec)
    cited = {key: value for key, (value, _why) in spec.cited.items()}
    body = plan["body"]
    print(f"  vendor  body {body['x'][1] - body['x'][0]:.3f} x "
          f"{body['y'][1] - body['y'][0]:.3f} mm from F.Fab, "
          f"{len(plan['leads'])} leads, exposed pad "
          f"{plan['flag']['w']:.2f} x {plan['flag']['h']:.2f} mm, "
          f"pin-1 mark {'yes' if plan['mark'] else 'none'}")
    for key, (value, why) in spec.cited.items():
        print(f"  cited   {key} = {value} mm -- {why[:64]}...")
    if check:
        print("  build   skipped (--check)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{spec.name}.obj"
    run_blender(spec.name, spec.script, {
        "out": str(target).replace("\\", "/"),
        "body": {**body, "height": cited["height"]},
        "leads": plan["leads"],
        "flag": plan["flag"],
        "mark": plan["mark"],
        "terminal": cited["terminal"],
        "colours": {"moulding": [0.06, 0.06, 0.07],
                    "lead": [0.72, 0.73, 0.76],
                    "mark": [0.30, 0.30, 0.32]},
    }, target)
    print(f"  build   {target.relative_to(REPO)}  "
          f"{target.stat().st_size:,} bytes")
    return 0


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
        # `insulator` is GCT's own value for the moulding inside their USB-C,
        # read out of the STEP `tools/compose_board_3d.py` fetches -- so the
        # two connectors on this project's boards state the same material with
        # the same number, and neither of them says the paddle is metal.
        "colours": {"shell": [0.62, 0.63, 0.66],
                    "cavity": [0.05, 0.05, 0.06],
                    "insulator": [0.06, 0.06, 0.06],
                    "pin": [0.72, 0.60, 0.30]},
        "body": {
            "x": plan["x"],
            "y": plan["y"],
            "height": cited["height"],
            "wall": cited["wall"],
            "lead_depth": cited["lead_depth"],
            "mouth": {"width": cited["mouth_width"],
                      "height": cited["mouth_height"],
                      "chamfer": cited["mouth_chamfer"]},
            # **The tongue is placed IN the opening rather than at a height of
            # its own**, which is one fewer number and cannot drift from the
            # aperture the way `z: wall + 0.6 + 1.6` could. Its own three
            # figures are drawing quantities, as the USB-C's are: inside a
            # cavity nothing reaches, measured by nothing.
            "tongue": {"width": cited["mouth_width"] - 2.0,
                       "thickness": 1.2,
                       "setback": 1.0},
        },
    }
    # **The payload goes in a file, not on argv.** Passed inline it is a
    # single argument full of quotes and braces, and Windows' command line is
    # rebuilt from a string by the runtime -- the JSON arrived mangled and
    # `subprocess` returned a `stdout` of None rather than an error anybody
    # could read.
    run_blender(spec.name, spec.script, payload, target)
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
        for spec in (*SPECS, *PACKS, *SLABS, *SOCKETS):
            source = ("EAGLE package" if isinstance(spec, Modelled)
                      else "KiCad footprint")
            print(f"{spec.name}  ({source} {spec.package})")
            print(f"    not fetched because: {spec.why_not_fetched}")
            # **A slab cites nothing and that is the point of it**: every
            # number it draws is in the vendor's own file, so it carries no
            # `cited` field at all. This printed one until OH-102 and the
            # command died on the first slab with an `AttributeError` -- which
            # is the command the handoff tells the next session to run first.
            for key, (value, why) in getattr(spec, "cited", {}).items():
                print(f"    {key} = {value} mm")
                print(f"        {why}")
        return 0

    every = (*SPECS, *PACKS, *SLABS, *SOCKETS)
    wanted = [s for s in every if args.part is None or s.name == args.part]
    if not wanted:
        print(f"no modelled part called {args.part!r}. Known: "
              f"{', '.join(s.name for s in every)}")
        return 2
    for spec in wanted:
        try:
            # Four kinds of part and four builders, dispatched by type
            # rather than by a flag on one: see `ModelledPack`.
            code = (build(spec, args.check) if isinstance(spec, Modelled)
                    else build_pack(spec, args.check)
                    if isinstance(spec, ModelledPack)
                    else build_socket(spec, args.check)
                    if isinstance(spec, ModelledSocket)
                    else build_slab(spec, args.check))
        except Unavailable as exc:
            print(f"SKIPPED: {exc}")
            return 3
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
