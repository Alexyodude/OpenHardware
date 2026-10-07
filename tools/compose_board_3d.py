#!/usr/bin/env python3
# OpenHardware - a board's 3D model, composed from CAD nobody published a mesh for.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Stand real component meshes on a real board outline, for a board with no model.

`tools/import_3d_model.py` fetches a vendor's own mechanical model and
tessellates it. That is the better answer and it is the one to reach for first.
This module is what to do when there is no such file, and the Arduino Uno is
the case it was written for: it is the only *buildable* board in this
repository still drawn as an extruded footprint, and it is the one most people
open first.

## Nobody publishes an Uno mesh, and here is where that was checked

Recorded in the same sentence as the conclusion, which
`docs/HANDOFF_2026-08-27_the-bench.md` section 3.1 cost a day by not doing:

  * Arduino's own docs page for the Uno Rev3 links `A000066-cad-files.zip`,
    303,265 bytes, CC BY-SA 4.0. Opened 2026-08-27: an EAGLE `.brd`, an EAGLE
    `.sch` and a licence. **No STEP, no WRL, no mesh.**
  * KiCad's `kicad-packages3D` has no Arduino board model. `Module.3dshapes`
    holds two files and both are a Wemos D1 Mini.
  * `docs/research/board-sources/sources.json` had already recorded
    `model_3d: no` for Arduino on 2026-08-25. This agrees with it.

## So it is composed, from three sources and no invented numbers

  * **Where everything is** -- Arduino's EAGLE `.brd`, read by `tools/eagle.py`.
    The outline is 12 segments on layer 20, which is the Uno's real silhouette
    including its 1 mm corner chamfers and the notch on the right edge. Every
    component's position, rotation and mirror is the file's own.
  * **What everything looks like** -- KiCad's `kicad-packages3D`, which
    `tools/import_3d_model.py` already fetches this project's LEDs and buzzer
    from. Real meshes of real parts, CC-BY-SA-4.0.
  * **The colour of the board** -- `#313d63`, read out of PICSimLab's
    `share/boards/Arduino Uno/board.svg`, where it fills the board-body path.
    That path's own data is the same silhouette, which is what makes it the
    board's colour rather than a colour that happens to be in the drawing.

**No height is typed in from a datasheet.** Not one of the 116 packages in the
`.brd` declares a height -- counted, not assumed -- so a component drawn as an
extruded box would need a thickness invented per package. That is section 3.6's
lead-tip defect in a new place: a plausible number, from a second source, that
disagrees with the geometry silently. Every height here comes off a mesh, and a
package with no mesh is not drawn.

## A correspondence proposed by name and confirmed by geometry

`CORRESPONDENCE` says which KiCad model *is* each EAGLE package. Every line of
it is a judgement, so none of them is trusted: `confirm` measures the element's
own pads against the mesh it was given and refuses a model that does not span
them. A `DIL28-3` mapped to a DIP-8 draws a plausible little chip in the right
place and is wrong, and nothing but the numbers would say so.

That check has teeth because the pads are the one thing both sources describe.
`ZU4`'s pads span 33.02 x 7.62 mm; `DIP-28_W7.62mm` is a 28-pin package on
7.62 mm rows, and 33.02 is 13 x 2.54. They agree because they are the same part.

## When even that runs out

The Uno's **USB-B socket** is in none of those libraries: KiCad's
`Connector_USB` holds three USB-A, seven USB-C, a Micro-B and a Mini-B and no
type B of any kind. It is also the most recognisable thing on the board after
the headers, so `tools/model_from_datasheet.py` builds it -- in Blender, out of
Arduino's own package geometry, with the one dimension that is not in any file
here cited to the USB standard. A component with `modelled=True` comes from
there, and the panel says which parts those are rather than letting them pass
as published.

## What is still deliberately not drawn

`ABSENT` is the honest end of the road: parts where no library has the right
model and the vendor's own drawing says the near miss is a miss. Both of the
Uno's remaining two are timing parts a few millimetres across, and each entry
carries the measurement that rules the obvious candidate out -- so the next
person reads the number rather than repeating the search.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import math
import pathlib
import re
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import board_manifest, board_sources, eagle, kicad  # noqa: E402
from tools.import_3d_model import (  # noqa: E402
    BOARD_MASK,
    CACHE,
    DEFLECTION,
    KICAD_3D,
    OUT,
    UNSTYLED,
    Extent,
    Frame,
    Mesh,
    Unavailable,
    box_of,
    handedness_of,
    read,
    report_finishes,
    tessellate,
    write_glb,
)
from webui.boards.catalogue import chip_for  # noqa: E402


@dataclasses.dataclass(frozen=True)
class Component:
    """One EAGLE package and the KiCad model that *is* that part.

    `why` is the evidence, not a restatement of the mapping. A line here is a
    claim about two libraries agreeing, and the next person to read it needs to
    know what was measured rather than that somebody was confident.
    """

    package: str
    library: str
    model: str
    why: str
    #: Degrees counter-clockwise taking the KiCad model's own axes onto the
    #: EAGLE package's, applied before the element's own rotation.
    #:
    #: **Not zero, and this is the bug that made it a field.** The two
    #: libraries lay a part out differently: EAGLE's `1X10` puts its ten pads
    #: along x, spanning 22.86 x 0.00 mm, and KiCad's `PinHeader_1x10` runs
    #: along y. Composed without this the headers stood across the board
    #: instead of along it, and the assembly measured 68.58 x 91.44 mm on a
    #: board 53.34 mm deep -- a picture that is obviously wrong once measured
    #: and looks like a rendering glitch on screen.
    turn: float = 0.0
    #: True when the mesh is one this project MADE, in Blender, because nobody
    #: publishes one -- `tools/model_from_datasheet.py` builds it and states
    #: where each of its numbers came from. A fourth kind of source and the
    #: worst, so it is a flag rather than a silent difference: the page says so.
    modelled: bool = False
    #: True for a part mounted UNDER the board, pins pointing down (OH-118).
    #:
    #: A XIAO DIP's headers hang below the PCB so the module can stand in a
    #: breadboard; KiCad's `PinHeader` models stand on top of it. `place`
    #: turns a flipped part half a turn about a horizontal axis -- a proper
    #: rotation, (x, z) -> (-x, -z), never a mirror -- and rests its body
    #: against the board's UNDERSIDE, which leaves the solder tails proud of
    #: the top face exactly where the pads are.
    flip: bool = False
    #: The vendor library the package has to come from, or None for any.
    #:
    #: **For one package name used for two different parts** (OH-180):
    #: SparkFun's board file places `0603` from SparkFun-Resistors for fourteen
    #: resistors and from SparkFun-Capacitors for nine capacitors. The library
    #: is the vendor saying which, so a row naming it wins over one that does
    #: not -- see `correspondence_for`.
    vendor_library: str | None = None
    #: The MANUFACTURER's own STEP, for a part KiCad's library does not hold,
    #: and the manufacturer's own footprint published beside it (OH-180).
    #:
    #: **The footprint is not optional, and it is what makes the model
    #: placeable.** A module's antenna overhangs its pads, so the body is not
    #: centred on them and `place`'s "centre the body on the pads" would put it
    #: millimetres off. The footprint places the model over its own pads with a
    #: stated `(offset ...)`, so `pads_origin` can say which point of the model
    #: sits over the middle of its pads -- and the anchor is pads on pads again,
    #: with `silk_miss` left free to check the body against the vendor's.
    step: str | None = None
    footprint: str | None = None
    #: The models a vendor's KiCad footprint places, by file stem, that this
    #: row's model stands for where it is not one of them by name (OH-195) --
    #: each a JUDGEMENT its `why` argues. A KiCad manifest row's footprint
    #: states the model it places, and `drawn_from` refuses a row that draws
    #: another without saying so here.
    stands_for: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        if self.step is not None:
            return self.step
        # `KICAD_3D` is GitLab, which is the library; the GitHub mirror this
        # fetched from until 2026-08-27 is a different and smaller tree. See
        # that constant for the counts.
        return f"{KICAD_3D}/{self.library}.3dshapes/{self.model}.step"

    @property
    def slug(self) -> str:
        return f"{self.library}-{self.model}".replace(".", "_")


#: Espressif's own KiCad library, at the commit read on 2026-09-29, for the
#: modules KiCad's library does not hold (OH-180). Its LICENSE.md:
#: CC-BY-SA 4.0 with the same exception as KiCad's own libraries. Pinned to a
#: commit rather than a branch, because `pads_origin` reads an offset out of
#: the footprint and a moved offset would move the module.
ESPRESSIF_KICAD = ("https://raw.githubusercontent.com/espressif/kicad-libraries/"
                   "dd76561812ab300351234ba6e0ec1295641796f0")

#: EAGLE package name -> the KiCad model of that part. Each span quoted below
#: was measured on 2026-08-27 with `eagle.Element.pad_extent`, and `confirm`
#: re-measures it on every run rather than trusting these comments.
CORRESPONDENCE: tuple[Component, ...] = (
    Component(
        "DIL28-3", "Package_DIP", "DIP-28_W7.62mm",
        "ZU4's pads span 33.02 x 7.62 mm. 7.62 mm is the row spacing in the "
        "model's own name and 33.02 is 13 x 2.54, which is 28 pins in two "
        "rows. The ATmega328P.",
        turn=90.0,
    ),
    Component(
        "1X10", "Connector_PinHeader_2.54mm", "PinHeader_1x10_P2.54mm_Vertical",
        "IOH's pads span 22.86 mm in one row, which is 9 x 2.54 -- ten pins.",
        turn=90.0,
    ),
    Component(
        "1X08", "Connector_PinHeader_2.54mm", "PinHeader_1x08_P2.54mm_Vertical",
        "IOL and POWER each span 17.78 mm in one row, which is 7 x 2.54.",
        turn=90.0,
    ),
    Component(
        "1X06", "Connector_PinHeader_2.54mm", "PinHeader_1x06_P2.54mm_Vertical",
        "AD spans 12.70 mm in one row, which is 5 x 2.54.",
        turn=90.0,
    ),
    Component(
        "2X03", "Connector_PinHeader_2.54mm", "PinHeader_2x03_P2.54mm_Vertical",
        "ICSP and ICSP1 each span 2.54 x 5.08 mm -- two rows of three. Which "
        "way round is the element's own rotation and not this table's problem.",
        turn=90.0,
    ),
    Component(
        "2X02", "Connector_PinHeader_2.54mm", "PinHeader_2x02_P2.54mm_Vertical",
        "JP2 spans 2.54 x 2.54 mm, which is two rows of two.",
        # Square, so the turn cannot be derived from the shape and cannot
        # matter either. Given for consistency with its neighbours.
        turn=90.0,
    ),
    Component(
        "XIAO-DIP-1X07", "Connector_PinHeader_2.54mm",
        "PinHeader_1x07_P2.54mm_Vertical",
        "A synthetic element `dip_header_elements` makes for a XIAO DIP's two "
        "header rows, seven through-hole pads spanning 15.24 mm -- 6 x 2.54, "
        "the vendor's own XIAO-*-DIP.kicad_mod rows. FLIPPED, because the "
        "headers hang below the board so the module can stand in a "
        "breadboard: the body rests against the underside and the solder "
        "tails come out proud of the top face, on the pads. OH-118.",
        turn=90.0,
        flip=True,
    ),
    # --- the Uno's small parts, unmapped until OH-119 -----------------------
    # The composer dropped 99 of the board's 116 elements with no model and
    # no stated reason -- among them the pin-13 LED every Blink drives, on a
    # project whose stated purpose is watching one. Each span below was
    # measured with eagle.Element.pad_extent on 2026-08-30, and `confirm`
    # re-measures on every run.
    Component(
        "CHIP-LED0805", "LED_SMD", "LED_0805_2012Metric",
        "ON, RX, TX and L -- the pin-13 LED. Two pads 2.10 mm apart, which "
        "is an 0805 land; the model is the 2.0 x 1.25 mm part the name "
        "states. The XIAOs already draw their LEDs from this library.",
    ),
    Component(
        "C0603-ROUND", "Capacitor_SMD", "C_0603_1608Metric",
        "C1-C11, eleven of them. Two pads 1.778 mm apart -- an 0603 land -- "
        "and the model is the 1.6 x 0.8 mm chip. The same model the XIAOs' "
        "C0402/C0201 siblings come from, one size up.",
    ),
    Component(
        "R0603-ROUND", "Resistor_SMD", "R_0603_1608Metric",
        "R1 and R2. The same 1.778 mm 0603 land as the capacitors, and the "
        "matching resistor body.",
    ),
    Component(
        "0805", "Inductor_SMD", "L_0805_2012Metric",
        "L1 and L2, the ferrites. Two pads 2.20 mm apart, an 0805 land, and "
        "the 2.0 x 1.25 mm chip body.",
    ),
    Component(
        "MINIMELF", "Diode_SMD", "D_MiniMELF",
        "D2 and D3. Two pads 3.40 mm apart along the package's own x, the "
        "cathode C at -x, and a MiniMELF is the 3.5 x 1.4 mm glass cylinder "
        "the package name states. KiCad's footprint puts pad 1, the cathode, "
        "at -x too, so no turn. Until OH-190 this row said 90, from pads "
        "measured on the board, where the element's own rotation had already "
        "turned them: both diodes lay across their land, the band as far "
        "from C as from A, and a test of the band now reads that.",
    ),
    Component(
        "SMB", "Diode_SMD", "D_SMB",
        "D1, the reverse-protection diode. Two pads 4.40 mm apart and the "
        "SMB (DO-214AA) body is 4.3 x 3.6 mm -- the package name is the "
        "JEDEC name the model uses.",
    ),
    Component(
        "CAY16", "Resistor_SMD", "R_Array_Convex_4x0603",
        "RN1-RN4, the resistor networks. Eight pads in two rows, 1.35 mm "
        "across the rows and 2.40 mm along them -- four 0603 elements at an "
        "0.8 mm pitch, which is what a CAY16 is and what this model draws.",
    ),
    Component(
        "SOT-23", "Package_TO_SOT_SMD", "SOT-23",
        "T1, the FDN340P power-switch FET. Three pads spanning 2.032 x "
        "1.93 mm, and the package name is the model's own. The Glyph C3's "
        "and C6's Q1, Si2301 by value, is on KiCad's own land of that name, "
        "which places this model (OH-195).",
    ),
    Component(
        "SOT23-DBV", "Package_TO_SOT_SMD", "SOT-23-5",
        "U2, the LMV358 that drives the ON LED. Five pads spanning 2.60 x "
        "1.90 mm; DBV is TI's name for SOT-23-5, and the model is the one "
        "the XIAO C3's SOT-25 already draws.",
    ),
    Component(
        "MSOP08", "Package_SO", "MSOP-8_3x3mm_P0.65mm",
        "U5, the other LMV358. Eight pads in two rows spanning 4.225 x "
        "1.95 mm -- three 0.65 mm pitches along each row -- and MSOP-8 is "
        "the 3 x 3 mm body those numbers describe.",
    ),
    Component(
        "POWERSUPPLY_DC-21MM", "Connector_BarrelJack", "BarrelJack_Horizontal",
        "X1's nine through-hole pads span 5.99 x 5.77 mm and the vendor draws "
        "its body from x -5.08 to 3.91 and y -6.35 to 7.14. The model is "
        "14.20 x 9.30 x 14.60 mm. It is anchored on its LEGS rather than its "
        "body, which is the whole reason `place` learned to do that: a barrel "
        "is entirely to one side of its pins. "
        "**270 and not 90, and every other check said 90 was fine.** Anchored "
        "on pins that are symmetric about their own centre, a jack turned "
        "180 degrees measures perfectly and points its barrel INTO the board. "
        "Against the vendor's silkscreen the four turns miss by 5.36, 7.50, "
        "5.35 and 0.01 mm, so the right one is not a matter of taste.",
        turn=270.0,
    ),
    Component(
        "MLF32", "Package_DFN_QFN", "QFN-32-1EP_5x5mm_P0.5mm_EP3.3x3.3mm",
        "U3's 33 surface-mount pads span 4.90 x 4.90 mm and the model is "
        "5.00 x 5.00 mm. MLF is Atmel's name for QFN and 32 pads on a 5 mm "
        "body is a 0.5 mm pitch. The ATmega16U2 that does the Uno's USB.",
    ),
    Component(
        "SOT223", "Package_TO_SOT_SMD", "SOT-223",
        "U1's four surface-mount pads span 6.20 x 4.62 mm against a model of "
        "7.00 x 6.50 mm. SOT-223 is the package in the EAGLE name and the "
        "model's, which is as direct as a correspondence gets.",
    ),
    Component(
        "PANASONIC_D", "Capacitor_SMD", "CP_Elec_6.3x5.4",
        "PC1 and PC2 have two surface-mount pads 4.80 mm apart. Panasonic's D "
        "case is a 6.3 mm diameter can 5.4 mm tall, which is this model's own "
        "name, and its land pattern measures 8.61 x 8.60 mm.",
    ),
    Component(
        "TS42", "Button_Switch_SMD", "SW_SPST_B3S-1000",
        "RESET's five surface-mount pads span 8.40 x 4.50 mm and the model is "
        "9.00 x 6.60 x 4.30 mm. Omron's B3S-1000 is the 6 mm surface-mount "
        "tactile switch this footprint is drawn for.",
    ),
    Component(
        "PN61729", "modelled", "USB_B_PN61729",
        "X2's four signal pins and two 2.2 mm shell posts, and a body of "
        "11.80 x 15.75 mm, are all Arduino's own package geometry -- this "
        "model is BUILT from that table rather than matched to it, so it "
        "cannot disagree. Only the 10.44 mm shell height comes from elsewhere, "
        "and it is the USB Series-B standard rather than a guess. See "
        "tools/model_from_datasheet.py, which cites every number it uses.",
        # No turn: the model is built in the vendor package's own frame, which
        # is the one thing a modelled part gets to choose and the reason it is
        # worth building rather than matching.
        modelled=True,
    ),
    # --- Seeed's XIAO ESP32-C3 v1.3, OH-93 ----------------------------------
    #
    # **Seeed's PCB names its footprints in its OWN library, not KiCad's**, and
    # it carries no `(model ...)` blocks at all -- so every line below is a
    # judgement of the same kind as the EAGLE ones above, and gets the same
    # treatment: `confirm` measures the placement's own pads against the mesh
    # and refuses one that does not span them. Each span quoted was measured
    # on 2026-08-29 with `from_kicad`.
    Component(
        "C0201", "Capacitor_SMD", "C_0201_0603Metric",
        "two pads 0.559 mm apart, which is the land pattern of an 0201 -- "
        "0.6 x 0.3 mm. Twenty-eight of them, the decoupling.",
    ),
    Component(
        "R0201", "Resistor_SMD", "R_0201_0603Metric",
        "two pads 0.559 mm apart, the same 0201 land as the capacitors and "
        "the same size of part. Fourteen of them.",
    ),
    Component(
        "L0201", "Inductor_SMD", "L_0201_0603Metric",
        "two pads 0.559 mm apart on the x axis -- an 0201 laid the other way "
        "round from the capacitors beside it.",
    ),
    Component(
        "LED-0402", "LED_SMD", "LED_0402_1005Metric",
        "two pads 0.766 mm apart, which is an 0402 land -- 1.0 x 0.5 mm. "
        "Reference CHG0, the charge indicator.",
    ),
    Component(
        "F0603", "Fuse", "Fuse_0603_1608Metric",
        "two pads 1.600 mm apart, an 0603 land -- 1.6 x 0.8 mm.",
    ),
    Component(
        "SOD-523", "Diode_SMD", "D_SOD-523",
        "two pads 1.600 mm apart on x, which is SOD-523's land: a 1.2 x 0.8 "
        "mm diode. The package name is the vendor's own and says so.",
    ),
    Component(
        "SOT-25", "Package_TO_SOT_SMD", "SOT-23-5",
        "five pads spanning 2.000 x 1.900 mm. SOT-25 is the JEDEC name for "
        "the five-lead SOT-23, which is what KiCad calls SOT-23-5.",
    ),
    Component(
        "QFN32G-0.5-5X5MM", "Package_DFN_QFN",
        "QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm",
        "thirty-three pads spanning 4.900 x 4.900 mm -- thirty-two leads on "
        "0.5 mm pitch around a 5 x 5 mm body, plus the exposed pad that makes "
        "thirty-three. The ESP32-C3 itself, and the name states all of it. "
        "TURNED 90, and the first thing OH-124's widened pin-1 reader did "
        "was catch this: the C3 draws the footprint with pad 1 entering on "
        "a different edge than the C6's one-letter sibling -- pad 1 local "
        "(-1.75, 2.45) against (-2.45, -1.75), axes swapped -- and "
        "compensates in the placement (-90 against 0), so THIS pairing "
        "needs the quarter turn the C6's does not. Measured: turn 0 put "
        "the model's own feature 4.621 mm from the vendor's dot, 90 puts "
        "it 1.540 -- a win past TURN_MARGIN_MM by a factor of ten. The "
        "composed C3 had shown its processor a quarter turn wrong since "
        "OH-93, invisible to a span, a centre, and a silk box alike.",
        turn=90.0,
    ),
    Component(
        "USB2.0-TYPE-C", "modelled", "USB2.0-TYPE-C",
        "MODELLED, not matched, and this is the one line in this table where "
        "**Seeed state a model and the model they state is the wrong part**. "
        "Their ESP32-C6 names KiCad's `USB_C_Receptacle_GCT_USB4105-xx-A_16P`, "
        "which is 7.78 mm deep; the same footprint's own `Description` property "
        "says `SMD USB Type-c;12P+4-8.9*7.3*3.2mm`. A vendor's statement is the "
        "best evidence there is here and it is not a proof -- their own "
        "dimensions win over their own hyperlink. "
        "Everything drawn is theirs: the body 7.341 x 8.992 mm from their "
        "F.Fab rectangle, agreeing with that Description to 0.092 mm; the "
        "3.2 mm height from it, which is the dimension no layer of a land "
        "pattern can carry; twelve contact pads naming sixteen of the "
        "standard's contacts, which is what `16P` means; four through-hole "
        "shell tabs. Only the 8.34 x 2.56 mm opening is not theirs and it is "
        "the USB Type-C specification's, for the reason the Uno's USB-B shell "
        "height is the standard's. "
        "**No turn: the model is built in the vendor footprint's own frame**, "
        "which is what a modelled part gets to choose and half the reason it "
        "is worth building. The GCT it replaces needed 270 and was given 0 and "
        "then 90 first -- see `contact_miss`, which now refuses all three.",
        modelled=True,
    ),
    Component(
        "X2-SMD-1.6X1.0X0.5MM", "Crystal",
        "Crystal_SMD_MicroCrystal_CM9V-T1A-2Pin_1.6x1.0mm",
        "two pads 1.100 mm apart in a 1.6 x 1.0 mm package, which the "
        "vendor's own footprint name states and the model's name repeats.",
    ),
    Component(
        "X4-SMD-2.0X1.6X0.5MM", "Crystal",
        "Crystal_SMD_2016-4Pin_2.0x1.6mm",
        "four pads spanning 1.000 x 1.200 mm in a 2.0 x 1.6 mm package -- "
        "the 2016 four-pad land, named in both files.",
    ),
    Component(
        "U-FL3P-SMD-2.6X2.6X1.0MM", "Connector_Coaxial",
        "U.FL_Hirose_U.FL-R-SMT-1_Vertical",
        "three pads spanning 1.397 x 2.540 mm in a 2.6 x 2.6 mm package. "
        "U.FL-R-SMT-1 is Hirose's own part number and the vendor's footprint "
        "name is U-FL. The antenna socket.",
    ),
    # --- OH-104: the parts nobody publishes, drawn as the slabs the vendor
    # --- already gave the size of. Each is `modelled`, so the page says it
    # --- was built here rather than fetched -- see
    # --- tools/model_from_datasheet.py, which refuses any package whose
    # --- name and F.Fab outline disagree about the plan by half a
    # --- millimetre, because that comparison is what proves the name was
    # --- read correctly rather than merely parsed.
    Component(
        "ANT2P-5.2x2x1.1MM", "modelled", "ANT2P-5.2x2x1.1MM",
        "MODELLED, not matched. Its body is 5.200 x 2.000 mm on Seeed's own "
        "F.Fab assembly layer, 1.1 mm tall by the last field of their "
        "footprint name, and those two sources agree about the plan to "
        "0.000 mm. KiCad's RF_Antenna library holds exactly four models -- "
        "two Johanson chip antennas, an AVX and a Pulse -- and none is 5.2 "
        "mm long, counted 2026-08-29. The nRF54L15 names Seeed's own "
        "`ANT_KH5220-A36`, under a path they do not publish.",
        modelled=True,
    ),
    Component(
        "SW4-SMD-2.8-2.6X1.6X0.53MM", "modelled", "SW4-SMD-2.8-2.6X1.6X0.53MM",
        "MODELLED, not matched. Its body is 2.600 x 1.600 mm on Seeed's own "
        "F.Fab assembly layer, 0.53 mm tall by the last field of their "
        "footprint name, and those two sources agree about the plan to "
        "0.000 mm. the smallest surface-mount switch in KiCad's 159-file "
        "Button_Switch_SMD is the TS-1088 at 2.9 x 3.9 mm, against a 2.6 x "
        "1.6 mm part -- more than twice the footprint.",
        modelled=True,
    ),
    Component(
        "MIC6P-0.94-4X2X1.1MM", "modelled", "MIC6P-0.94-4X2X1.1MM",
        "MODELLED, not matched. Its body is 2.257 x 4.267 mm on Seeed's own "
        "F.Fab assembly layer, 1.1 mm tall by the last field of their "
        "footprint name, and those two sources agree about the plan to "
        "0.267 mm. the nRF54L15 names Seeed's own `312030722_MSM261DGT006`, "
        "which they do not publish, and KiCad has no microphone library.",
        modelled=True,
    ),
    Component(
        "WLCSP47-0.3-2.451X2.245X0.42MM", "modelled", "WLCSP47-0.3-2.451X2.245X0.42MM",
        "MODELLED, not matched. Its body is 2.440 x 2.240 mm on Seeed's own "
        "F.Fab assembly layer, 0.42 mm tall by the last field of their "
        "footprint name, and those two sources agree about the plan to "
        "0.011 mm. KiCad's Package_CSP holds 34 files and not one WLCSP-47; "
        "the closest by ball count is a WLCSP-49 at 3.44 x 3.44 mm, half "
        "again as large. The nRF54L15 itself.",
        modelled=True,
    ),
    Component(
        "WLCSP20-0.4-2.4X1.9X0.5MM_SMALL", "modelled", "WLCSP20-0.4-2.4X1.9X0.5MM_SMALL",
        "MODELLED, not matched. Its body is 1.950 x 2.450 mm on Seeed's own "
        "F.Fab assembly layer, 0.5 mm tall by the last field of their "
        "footprint name, and those two sources agree about the plan to "
        "0.050 mm. KiCad has two WLCSP-20s, both 4x5 layouts at 1.7 x 2.1 "
        "and 1.94 x 2.4 mm, and each names the maker of a different part. "
        "Seeed name their own `WLCSP20`, which they do not publish.",
        modelled=True,
    ),
    Component(
        "IPEX-GEN4-SMD-1.7X1.7X1.0MM", "modelled", "IPEX-GEN4-SMD-1.7X1.7X1.0MM",
        "MODELLED, not matched. Its body is 1.700 x 1.700 mm on Seeed's own "
        "F.Fab assembly layer, 1.0 mm tall by the last field of their "
        "footprint name, and those two sources agree about the plan to "
        "0.000 mm. KiCad's Connector_Coaxial holds fifteen models and its "
        "only sub-miniature one is the 2.6 mm U.FL, which would overhang a "
        "1.7 mm part by half a millimetre in each direction.",
        modelled=True,
    ),
    Component(
        "LED4-0.8-1.6X1.5X0.55MM", "modelled", "LED4-0.8-1.6X1.5X0.55MM",
        "MODELLED, not matched. Its body is 1.500 x 1.600 mm on Seeed's own "
        "F.Fab assembly layer, 0.55 mm tall by the last field of their "
        "footprint name, and those two sources agree about the plan to "
        "0.000 mm. KiCad's LED_SMD holds 39 files whose smallest RGB part "
        "is the 1210 at 3.2 x 2.5 mm, twice this one.",
        modelled=True,
    ),
    Component(
        "LED4-0.85-1.6X1.5X0.6MM", "modelled", "LED4-0.85-1.6X1.5X0.6MM",
        "MODELLED, not matched. Its body is 1.600 x 1.530 mm on Seeed's own "
        "F.Fab assembly layer, 0.6 mm tall by the last field of their "
        "footprint name, and those two sources agree about the plan to "
        "0.030 mm. the same absence as the 0.8 mm pitch part above: no RGB "
        "LED in KiCad's library is under 3.2 mm.",
        modelled=True,
    ),
    # --- the C6, the RP2350 and the nRF54L15, OH-93 -------------------------
    #
    # **These three state some of their own models and the C3 states none**,
    # which is the difference between "SEEED STATES" and "MEASURED" below. A
    # stated line is a reading of `(model "${KICAD7_3DMODEL_DIR}/<lib>.3dshapes
    # /<name>.step")` in the vendor's own board file -- the correspondence, in
    # their hand. It is still put through `confirm`, for a reason two lines in
    # these same files make concrete: the RP2350 gives its ESD diode a
    # RESISTOR's model, and the crystal it names does not exist in KiCad's
    # library at all. A vendor statement is the best evidence there is here
    # and it is not a proof.
    Component(
        "C0402", "Capacitor_SMD", "C_0402_1005Metric",
        "SEEED STATES it, on all three boards: `Capacitor_SMD.3dshapes/"
        "C_0402_1005Metric.step`. Two pads 0.925 mm apart on the C6, which is "
        "an 0402 land -- 1.0 x 0.5 mm -- and agrees with what they wrote.",
    ),
    Component(
        "L0603", "Inductor_SMD", "L_0603_1608Metric",
        "SEEED STATES it on the ESP32-C6: `Inductor_SMD.3dshapes/"
        "L_0603_1608Metric.step`. Two pads 1.524 mm apart, an 0603 land. "
        "**The RP2350 states `R0603` for the same footprint** -- one of their "
        "own files, which they do not ship -- so the two disagree and the one "
        "naming a library anybody can fetch is the one that can be used.",
    ),
    Component(
        "X2-SMD-1.6X1.0MM", "Crystal",
        "Crystal_SMD_MicroCrystal_CM9V-T1A-2Pin_1.6x1.0mm",
        "SEEED STATES it on the nRF54L15, whose X2 is two pads 1.100 mm apart "
        "in the 1.6 x 1.0 mm package both names give. That is the same model "
        "and the same spacing the C3's `X2-SMD-1.6X1.0X0.5MM` was mapped to by "
        "measurement a day earlier -- a vendor confirming a judgement already "
        "made here, which is the only entry in this table with that standing.",
    ),
    Component(
        "LGA14-0.5-2.5X3X0.86MM", "Package_LGA",
        "LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y",
        "SEEED STATES it on the nRF54L15, and their own STEP assembly for the "
        "nRF54LM20A names the identical model for the identical part. "
        "Fourteen pads spanning 1.900 x 2.400 mm; 3 x 2.5 mm at 0.5 mm pitch "
        "in a 3-by-4 border is what both names say.",
    ),
    Component(
        "QFN32-0.5-5X5MM", "Package_DFN_QFN",
        "QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm",
        "MEASURED: thirty-three pads spanning 4.900 x 4.900 mm, identical to "
        "the C3's `QFN32G-0.5-5X5MM` in every figure -- the two vendor names "
        "differ by one letter. The ESP32-C6 itself.",
    ),
    Component(
        "USB2.0-TYPE-C_USB-31C-F-16P", "modelled",
        "USB2.0-TYPE-C_USB-31C-F-16P",
        "MODELLED, not matched. **The vendor names this part and does not ship "
        "it**: `USB-31C-F-16P-L7.35.stp` on the RP2350 and "
        "`320011419_ST-USB-3316T.stp` on the nRF54L15 and the ESP32-C5, both "
        "under a `Y:/01_Cadence_Library` path that is a drive on somebody's "
        "desk -- and `L7.35` in the first of those states the length. Their "
        "own `Description` says `SMD USB TYPE C-W/P;12+4P-7.35*8.94*3.25mm`, "
        "which agrees with the F.Fab rectangle they drew to 0.020 mm and adds "
        "the 3.25 mm height no land pattern can carry. "
        "So all of it is read: twelve contact pads naming sixteen of the "
        "standard's contacts, two smd shell feet, two through-hole board "
        "locks, and one 8.34 x 2.56 mm opening from the USB Type-C "
        "specification. "
        "**Both published 16-pin receptacles were tried here and both are the "
        "wrong length.** OH-93 used the GCT USB4105 that this land's four-tab "
        "sibling uses, and the GCT's four shell tabs against this land's two "
        "board locks left the contact row 0.42 mm past the board edge in "
        "mid-air (OH-101). Amphenol's 12401610E4-2A has the right two locks "
        "and is 10.50 mm deep against the 7.35 the vendor states -- 3.15 mm of "
        "connector that is not on the board, which is what `BODY_ALLOWANCE_MM` "
        "used to excuse and no longer has to. "
        "**No turn: the model is built in the vendor footprint's own frame.**",
        modelled=True,
    ),
    Component(
        "USON8-0.5-3X2MM", "Package_SON",
        "Winbond_USON-8-1EP_3x2mm_P0.5mm_EP0.2x1.6mm",
        "MEASURED: nine pads spanning 2.700 x 1.500 mm. USON-8, 3 x 2 mm, "
        "0.5 mm pitch is stated in the vendor's footprint name and repeated "
        "in the model's. The RP2350's flash.",
    ),
    Component(
        "X4-SMD-1.6X1.2MM", "Crystal",
        "Crystal_SMD_WE_IQXC-26-4Pin_1.6x1.2mm",
        "MEASURED: four pads spanning 0.800 x 1.050 mm in the 1.6 x 1.2 mm "
        "package both names state. Seeed name their own "
        "`CRYSTAL-SMD_4P-L1.6-W1.2-BL`, which they do not ship and which "
        "says the same size.",
    ),
    # --- OH-150: three chip diodes, in bodies their neighbours already
    # borrow -----------------------------------------------------------------
    #
    # **KiCad publishes no 0201 or 0402 chip diode at all** -- Diode_SMD
    # holds 39 files, listed 2026-08-31, and its smallest chip diode is an
    # 0603 -- so
    # the choice is a resistor's moulding of exactly the right land pattern
    # or nothing. The PART is a diode and only the moulding is borrowed,
    # which is a statement about a 0.6 mm brick with no marking on it -- and
    # one only a board with no schematic can make: on one that reads its
    # schematic, a part stated to be another kind is refused on a passive's
    # land (OH-187, OH-191). Seeed themselves reached the same conclusion
    # first: all seven ESD-0201 placements name `Resistor_SMD/R_0201_0603Metric` in the
    # vendor's own board file.
    Component(
        "ESD-0201", "Resistor_SMD", "R_0201_0603Metric",
        "seven ESD diodes across the RP2350, the ESP32-C5 and the "
        "nRF54L15, all one land pattern: two pads 0.2794 x 0.3175 mm with "
        "their centres 0.5094 mm apart. The vendor states this very model "
        "on every one of the seven.",
    ),
    Component(
        "ESD-0402", "Resistor_SMD", "R_0402_1005Metric",
        "the ESP32-C6's D2, the one ESD diode drawn a size up: two pads "
        "0.5 mm square, centres 0.925 mm apart. Seeed name no model for "
        "this one, so the body is the 0402 resistor whose land pattern it "
        "is -- the same borrow as its 0201 sibling above.",
    ),
    Component(
        "DFN1006-2L", "Diode_SMD", "D_SOD-882",
        "five placements over three boards -- D1 and D3 on the ESP32-C6 "
        "and the RP2350, D4 on the nRF54L15 -- of which FOUR share their "
        "drawing and the fifth does not (OH-152, correcting this row): the "
        "two D3s are both footprint uuid 74280228-6770-4ef7-a3f6-"
        "1b9b72be3acb and the two D1s both ca26a40d-c599-4020-9350-"
        "0c2ef85f72bb, while the nRF54L15's D4 is its own, and drawn to a "
        "different size -- F.Fab 1.321 x 0.711 mm against the others' "
        "0.749 x 0.508. Nothing here changes for that, because this row "
        "borrows a KiCad body at the body's own size rather than measuring "
        "the footprint; a row that DID measure would have to pick one. "
        "Two pads 0.70 mm between centres. "
        "**This is the one row where the vendor names the industry outline "
        "rather than their own**: the C6's Description reads `SMD Diode "
        "Schottky 40V-1A;SOD-882`, which is the KiCad body used here, "
        "while the nRF54L15's copy of the same footprint calls itself "
        "DFN1006-2L. Two names, one 1.0 x 0.6 mm two-lead package.",
    ),
    # --- OH-150: the small silicon OH-104 deferred, now drawn --------------
    Component(
        "CAF-50P160X80-6N", "modelled", "CAF-50P160X80-6N",
        "MODELLED, not matched: Murata's LFD182G45DCHD277 diplexer, the "
        "part that lets the ESP32-C5's two radios share one antenna. Its "
        "1.6 x 0.8 mm plan is stated three times over -- by the name, the "
        "F.Fab outline and the Description -- and the 0.7 mm height by the "
        "Description alone, which is why `slab_geometry` learned to read "
        "one.",
        modelled=True,
    ),
    Component(
        "PMOS_1.0X0.6X0.35MM", "modelled", "PMOS_1.0X0.6X0.35MM",
        "MODELLED, not matched: the load switch, a SOT-883 chip-scale "
        "MOSFET one millimetre long -- Q1 to Q3 on the ESP32-C6, Q1 and Q2 "
        "on the RP2350 and the nRF54L15. Plan and height both from the "
        "footprint's own name, 1.0 x 0.6 x 0.35 mm, which the C6's F.Fab "
        "matches to 0.000 mm. **Seeed drew the same footprint two sizes** "
        "-- the nRF54L15's copies and the RP2350's Q2 measure 0.508 x "
        "0.762 rather than 0.600 x 1.000 -- so this is one drawing at the "
        "size the vendor's own NAME states, which is the only one of the "
        "two that every board agrees to call the part.",
        modelled=True,
    ),
    Component(
        "PMOS_1.0_0.6_0.35MM", "modelled", "PMOS_1.0X0.6X0.35MM",
        "MODELLED, not matched: **the same part as the row above, under "
        "Seeed's other spelling of its name** -- Q1 on the ESP32-C3, which "
        "writes underscores where the other three boards write `x`. The "
        "model is the row above's, deliberately: one part is one drawing, "
        "and the C3's own F.Fab is 0.600 x 1.000 mm, the same rectangle the "
        "ESP32-C6 draws for it. `_NAMED_BODY` cannot read this spelling and "
        "must not learn to: measured 2026-08-31, allowing an "
        "underscore separator makes `SOT8_0d5_2_1x1_2x0_6mm` parse as "
        "**8 x 0.5 x 2.1 mm**, taking the `8` out of `SOT8` itself. So the "
        "indirection "
        "lives here, in the field that has always held a model name "
        "different from a footprint name, rather than in the parser.",
        modelled=True,
    ),
    Component(
        "BUTTON_TD1183SA", "modelled", "BUTTON_TD1183SA",
        "MODELLED, not matched: the boot and reset buttons, on the C3, the "
        "C5 and the nRF54L15. Plan from Seeed's own F.Fab, height from the "
        "footprint's `Description` -- `2P-L3.0*W2.5*H1.5mm`, whose L, W and "
        "H say which number is which -- and the two agree about the plan to "
        "0.110 mm. **The C3's own two copies carry an empty Description and "
        "are drawn from the C5's**, same vendor footprint name and same "
        "vendor part number, their F.Fab 0.010 mm apart. This is the "
        "refusal OH-104 deferred and OH-150 left standing, retired by "
        "reading all six placements rather than the two the note named.",
        modelled=True,
    ),
    Component(
        "WLCSP4-0.4-0.77X0.77X0.33MM", "modelled",
        "WLCSP4-0.4-0.77X0.77X0.33MM",
        "MODELLED, not matched: a 0.77 mm square die with four balls under "
        "it. Body from Seeed's own F.Fab, height from the last field of "
        "their footprint name, and the two agree about the plan to "
        "0.010 mm on all three boards that place one.",
        modelled=True,
    ),
    Component(
        "WLCSP-0.4-0.92X1.16X0.4MM", "modelled", "WLCSP-0.4-0.92X1.16X0.4MM",
        "MODELLED, not matched: SGMICRO's Li-Ion charger die, 0.900 x "
        "1.175 mm on Seeed's own F.Fab against the 0.92 x 1.16 mm its name "
        "claims -- 0.020 mm apart. The one name here that omits its ball "
        "count, which the six pads and their own Description both supply.",
        modelled=True,
    ),
    Component(
        "BGA6-0.35-0.85X1.2X0.4MM", "modelled", "BGA6-0.35-0.85X1.2X0.4MM",
        "MODELLED, not matched: the buck converter's bare die, which both "
        "boards' own Descriptions call a WLCSP-6B and a DSBGA. Its F.Fab "
        "measures 0.850 x 1.200 mm and its name says the same, agreeing to "
        "0.000 mm, which several rows here reach and none beats.",
        modelled=True,
    ),
    Component(
        "DFN6-0.4-1.1X0.7X0.45MM", "modelled", "DFN6-0.4-1.1X0.7X0.45MM",
        "MODELLED, not matched: a six-lead 0.4 mm-pitch flat pack, drawn as "
        "the moulded body it is. Name and F.Fab state the same rectangle "
        "the two ways round, which the sorted cross-check accepts.",
        modelled=True,
    ),
    Component(
        "DFN6-0.5-1.45X1X0.6", "modelled", "DFN6-0.5-1.45X1X0.6",
        "MODELLED, not matched: a six-lead 0.5 mm-pitch flat pack whose "
        "name states no unit -- the F.Fab's 1.460 x 1.000 mm is what says "
        "the numbers are millimetres.",
        modelled=True,
    ),
    Component(
        "SOT8_0d5_2_1x1_2x0_6mm", "modelled", "SOT8_0d5_2_1x1_2x0_6mm",
        "MODELLED, not matched: TI's TPS2116 power mux. Three of the "
        "board's own layers put the body at 2.1 x 1.2 mm and the name's "
        "last field gives the 0.6 mm height, in Seeed's underscore "
        "spelling.",
        modelled=True,
    ),
    Component(
        "X2SON4-0.625-1x1x0.6mm", "modelled", "X2SON4-0.625-1x1x0.6mm",
        "MODELLED, not matched: SGMICRO's SGM2040 LDO, a 1 mm square "
        "moulded body whose F.Fab and courtyard both measure exactly "
        "1.000 x 1.000 mm against the name's own 1x1.",
        modelled=True,
    ),
    Component(
        "QFN48-0.4-6X6X0.9MM_small", "modelled", "QFN_48_6x6_P0.4",
        "the ESP32-C5 itself, and MODELLED for the same reason as the "
        "QFN-60 below: forty-nine pads spanning 5.850 x 5.850 mm with a "
        "3.7 x 3.7 mm exposed pad, and the only published 48-lead 6 x 6 part "
        "on a 0.4 mm pitch is KiCad's `UQFN-48`, whose exposed pad is "
        "4.45 mm and whose `U` is the ultra-thin height class -- 0.6 mm or "
        "less, where Seeed's own name says 0.9. Body 6.000 x 6.000 mm from "
        "their F.Fab rectangle, leads from their own pads clipped to it, "
        "height from the last field of their footprint name.",
        modelled=True,
    ),
    Component(
        "QFN60-0.4-7X7X0.9MM", "modelled", "QFN_60_7x7_P0.4",
        "the RP2350 itself, and **the only part on any XIAO that is MODELLED "
        "rather than matched** -- so it is the one line in this table that is "
        "not a claim about two libraries agreeing. Nobody publishes a QFN-60: "
        "KiCad's `Package_DFN_QFN` has none among 191 files, Raspberry Pi "
        "publish reference designs and no STEP for the chip, and Seeed ship a "
        "STEP beside two of their board files and not this one. "
        "**`QFN-56-1EP_7x7mm_P0.4mm` is the near miss and is deliberately not "
        "used**: right body, right pitch, four leads short, and it would put "
        "a false part name in this model's own list. "
        "Every number is Seeed's, read at build time: the body is the "
        "`fp_rect` on F.Fab at 7.000 x 7.000 mm, the 60 leads are their own "
        "pads clipped to it, the exposed pad is 3.45 x 3.45 mm, and the "
        "pin-1 dot is their `fp_circle`. Only the 0.900 mm height is not "
        "geometry, and it is the last field of their own footprint NAME. See "
        "tools/model_from_datasheet.py, which cites both numbers it draws.",
        # No turn: like the USB-B, the model is built in the vendor package's
        # own frame, which is the one thing a modelled part gets to choose and
        # half the reason it is worth building rather than matching.
        modelled=True,
    ),
    Component(
        "X4-SMD-2.5X2.0MM", "Crystal", "Crystal_SMD_2520-4Pin_2.5x2.0mm",
        "MEASURED: four pads spanning 1.400 x 1.800 mm in a 2.5 x 2.0 mm "
        "package -- the 2520 land, named in the vendor's footprint and in the "
        "model. **Seeed state `Crystal_SMD_SeikoEpson_FA238-4Pin_2.5x2.0mm` "
        "and KiCad's library has no such file**; the FA238V it does have is a "
        "2.0 x 1.6 mm part. So the statement is unusable and the generic land "
        "of the size they drew is what is left.",
    ),
    # --- the three manifest boards, OH-180 ----------------------------------
    #
    # SparkFun's and Adafruit's EAGLE files, read the way the Uno's is. Every
    # span quoted was measured with `eagle.Element.pad_extent` on 2026-09-29
    # and `confirm` re-measures it on every run.
    Component(
        "ESP32-C6-WROOM-1-NARROW", "espressif", "ESP32-C6-WROOM-1",
        "U1 on the SparkFun Thing Plus, value ESP32-C6-WROOM-1-NARROW. "
        "SparkFun draw its body on tDocu as 18.0 x 25.5 mm, the WROOM-1's "
        "own outline, with 37 pads spanning 16.50 x 16.51 mm at the end away "
        "from the antenna. KiCad's RF_Module holds no ESP32-C6 module at all, "
        "listed 2026-09-29, so this is ESPRESSIF's own STEP and footprint -- "
        "the manufacturer's, under their LICENSE.md: CC-BY-SA 4.0 with the "
        "same exception as KiCad's libraries. Their footprint's pads span "
        "17.50 x 16.51 mm, SparkFun's NARROW land 1.0 mm narrower across its "
        "two side rows. Placed by `pads_origin`, "
        "so `silk_miss` is left to compare Espressif's body with SparkFun's "
        "drawing of it.",
        step=f"{ESPRESSIF_KICAD}/3dmodels/espressif.3dshapes/ESP32-C6-WROOM-1.STEP",
        footprint=(f"{ESPRESSIF_KICAD}/footprints/Espressif.pretty/"
                   f"ESP32-C6-WROOM-1.kicad_mod"),
    ),
    Component(
        "ESP32-PICO-MINI", "espressif", "ESP32-C6-MINI-1",
        "U1 on the Adafruit Feather ESP32-C6, value ESP32-C6-MINI_MINI on a "
        "land Adafruit named for the PICO-MINI, which is the same 13.2 x "
        "16.6 mm outline -- and that is what they draw on tDocu, the MINI-1 "
        "with its PCB antenna rather than the shorter -1U. 61 pads spanning "
        "11.90 x 9.90 mm in the package's own frame, the count and span of "
        "Espressif's own footprint. KiCad publishes no ESP32-C6 module; this "
        "is Espressif's STEP and footprint, as for the WROOM above.",
        step=f"{ESPRESSIF_KICAD}/3dmodels/espressif.3dshapes/ESP32-C6-MINI-1.STEP",
        footprint=(f"{ESPRESSIF_KICAD}/footprints/Espressif.pretty/"
                   f"ESP32-C6-MINI-1.kicad_mod"),
    ),
    Component(
        "0603", "Resistor_SMD", "R_0603_1608Metric",
        "the Thing Plus's fourteen resistors, R1-R14: two pads 1.70 mm "
        "apart, an 0603 land. SparkFun place this package name from TWO "
        "libraries, and this row is the one from SparkFun-Resistors.",
        vendor_library="SparkFun-Resistors",
    ),
    Component(
        "0603", "Capacitor_SMD", "C_0603_1608Metric",
        "the Thing Plus's nine capacitors, C1-C9: the same 1.70 mm 0603 land "
        "as the resistors, under the same package name, from "
        "SparkFun-Capacitors -- which is SparkFun saying which part it is.",
        vendor_library="SparkFun-Capacitors",
    ),
    # **Adafruit place resistors and capacitors on one package from one
    # library** (OH-187), so a package below may have a row per kind, and
    # which a placement takes is the kind its vendor's schematic states --
    # `stated_kinds` -- and never the package's.
    Component(
        "0603-NO", "Resistor_SMD", "R_0603_1608Metric",
        "a resistor on Adafruit's 0603 land: two pads 1.70 mm apart, and the "
        "1.6 x 0.8 mm resistor.",
    ),
    Component(
        "0603-NO", "Capacitor_SMD", "C_0603_1608Metric",
        "a capacitor on the same 1.70 mm 0603 land, and the 1.6 x 0.8 mm "
        "chip that stands on it.",
    ),
    Component(
        "0805-NO", "Capacitor_SMD", "C_0805_2012Metric",
        "a capacitor on Adafruit's 0805 land: two pads 1.90 mm apart, and the "
        "2.0 x 1.25 mm chip.",
    ),
    Component(
        "_0805MP", "Capacitor_SMD", "C_0805_2012Metric",
        "a capacitor on Adafruit's other 0805 land: two pads 2.03 mm apart, "
        "and the same 2.0 x 1.25 mm chip.",
    ),
    Component(
        "_0402NO", "Capacitor_SMD", "C_0402_1005Metric",
        "a capacitor on Adafruit's 0402 land: two pads 1.02 mm apart, and "
        "the 1.0 x 0.5 mm chip.",
    ),
    Component(
        "_0402NO", "Resistor_SMD", "R_0402_1005Metric",
        "a resistor on the same 1.02 mm 0402 land, placed from the same "
        "package and library as the capacitors -- which is why a table keyed "
        "by package drew them as capacitors until the schematic was read.",
    ),
    Component(
        "_0402", "Inductor_SMD", "L_0402_1005Metric",
        "an inductor on Adafruit's other 0402 land, the antenna match: two "
        "pads 1.02 mm apart, and the 1.0 x 0.5 mm chip. A part on it that "
        "its schematic values in ohms is refused rather than drawn as either.",
    ),
    Component(
        "_0603MP_TWO6MIL", "Resistor_SMD", "R_0603_1608Metric",
        "R7 on the QT Py, 10k: two pads 1.58 mm apart, Adafruit's tighter "
        "0603 land, and the 1.6 x 0.8 mm resistor.",
    ),
    Component(
        "RESPACK_4X0603", "Resistor_SMD", "R_Array_Convex_4x0603",
        "R3 on the Feather, 10k x 4: eight pads in two rows spanning "
        "1.70 x 2.60 mm, four 0603 elements side by side, and Adafruit draw "
        "the body 3.2 x 1.6 mm on tDocu -- the size of this model.",
        turn=90.0,
    ),
    Component(
        "LED-0603", "LED_SMD", "LED_0603_1608Metric",
        "D1 and D4 on the Thing Plus, the power and charge LEDs: two pads "
        "1.75 mm apart, an 0603 land, and the 1.6 x 0.8 mm LED. TURNED 180: "
        "SparkFun put the cathode pad C at +x, and KiCad's own footprint "
        "for this model puts pad 1, the cathode, at -x.",
        turn=180.0,
    ),
    Component(
        "CHIPLED_0603_NOOUTLINE", "LED_SMD", "LED_0603_1608Metric",
        "Adafruit's 0603 LED land: two pads 1.50 mm apart, and the "
        "1.6 x 0.8 mm LED. TURNED 270: Adafruit put the cathode pad "
        "C at +y, where KiCad's footprint puts pad 1, the cathode, at -x.",
        turn=270.0,
    ),
    Component(
        "SOD-323", "Diode_SMD", "D_SOD-323",
        "D3 on the Thing Plus: two pads 2.30 mm apart, and SOD-323 is the "
        "package the vendor's name and the model's both state. The cathode "
        "pad C is at -x, where KiCad's footprint puts pad 1, so no turn.",
    ),
    Component(
        "SOD-323_MINI", "Diode_SMD", "D_SOD-323",
        "D1 and D2 on the QT Py, NSR0320 by value: two pads 2.14 mm apart, "
        "Adafruit's smaller SOD-323 land and the same 1.7 x 1.25 mm body, "
        "cathode at -x like the model's.",
    ),
    Component(
        "SOD-123", "Diode_SMD", "D_SOD-123",
        "D4 on the Feather, MBR540 by value: two pads 3.70 mm apart, and "
        "SOD-123 is the package both names state; cathode at -x like the "
        "model's.",
    ),
    Component(
        "SOT23-5", "Package_TO_SOT_SMD", "SOT-23-5",
        "SparkFun's and Adafruit's five-lead SOT-23 land, under regulators "
        "and chargers alike: five pads spanning 1.90 x 2.60 mm, which is the "
        "Uno's SOT23-DBV land stood on end, so the same model turned a "
        "quarter.",
        turn=90.0,
    ),
    Component(
        "SOT23-3", "Package_TO_SOT_SMD", "SOT-23-3",
        "Q1 and Q2 on the Thing Plus: three pads spanning 1.90 x 2.10 mm, "
        "and SOT-23-3 is the name SparkFun give the package. TURNED 90: "
        "SparkFun lay pins 1 and 2 along x with pin 3 across from them, and "
        "KiCad's footprint lays them along y.",
        turn=90.0,
    ),
    Component(
        "SOT23-R", "Package_TO_SOT_SMD", "SOT-23",
        "Q3 on the Feather, DMG3415U by value: three pads spanning 1.90 x "
        "2.00 mm, the three-lead SOT-23 the Uno's T1 already draws, turned "
        "90 for the reason SparkFun's SOT23-3 is.",
        turn=90.0,
    ),
    Component(
        "CRYSTAL_2X1.6", "Crystal", "Crystal_SMD_2016-4Pin_2.0x1.6mm",
        "Y1 on the QT Py, 40 MHz: four pads spanning 1.35 x 1.00 mm, and "
        "Adafruit draw the body 2.0 x 1.6 mm on tDocu -- the 2016 part the "
        "model's name states, and the one Seeed's C3 crystal draws. Pad 1 "
        "is where KiCad's footprint puts it, so no turn.",
    ),
    Component(
        "ANT_2450AT18B100", "RF_Antenna", "Johanson_2450AT18x100",
        "X1 on the QT Py: two pads 2.80 mm apart. The package name is "
        "Johanson's own part number, 2450AT18B100, and this model is "
        "Johanson's 2450AT18x100 family -- the x is the letter B stands in.",
    ),
    Component(
        "TACTILE_SWITCH_SMD_4.6X2.8MM", "Button_Switch_SMD",
        "SW_Push_1P1T_NO_CK_KMR2",
        "RESET and BOOT on the Thing Plus: four pads spanning 4.10 x "
        "1.60 mm. SparkFun's own package description links C&K's KMR2 "
        "datasheet, and this is C&K's KMR2.",
    ),
    Component(
        "BTN_KMR2_4.6X2.8", "Button_Switch_SMD", "SW_Push_1P1T_NO_CK_KMR2",
        "Adafruit's KMR2 button land: four pads spanning 4.10 x 1.60 mm, "
        "the same land as SparkFun's, and the package name is C&K's KMR2.",
    ),
    Component(
        "BTN_KMR2_SLIM", "Button_Switch_SMD", "SW_Push_1P1T_NO_CK_KMR2",
        "Q2 on the QT Py, reset: four pads spanning 4.10 x 1.65 mm, a slimmer "
        "copy of the land above under a name that is still C&K's KMR2.",
    ),
    Component(
        "BTN_RKB2_4.6X2.8", "Button_Switch_SMD", "SW_Push_1P1T_NO_CK_KMR2",
        "SW1 and SW2 on the Feather: four pads spanning 3.95 x 2.15 mm. "
        "Adafruit name the land RKB2 and give both parts the value KMR2; the "
        "value is the part, and KiCad publishes no RKB2.",
    ),
    Component(
        "JST04_1MM_RA", "Connector_JST",
        "JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal",
        "J4 on the Thing Plus, the Qwiic port: four 1 mm-pitch contacts and "
        "two mounting pads, spanning 3.68 x 5.60 mm, and a body SparkFun "
        "draw 6.0 x 4.25 mm -- JST's SH right-angle SM04B-SRSS-TB.",
    ),
    Component(
        "JST_SH4_SKINNY", "Connector_JST",
        "JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal",
        "Adafruit's STEMMA QT port on its skinny land: four 1 mm-pitch "
        "contacts and two mounting pads spanning 5.60 x 3.90 mm, and a body "
        "Adafruit draw 6.1 x 4.25 mm -- the SM04B-SRSS-TB SparkFun's Qwiic "
        "port is.",
    ),
    # **One rule for an exposed pad, and it is that the pad decides nothing.**
    # It is under the body and drawn nowhere, and a land's pad is the vendor's
    # own paste choice rather than the part's: Adafruit and Seeed both land
    # the ESP32-C3 at 3.0 x 3.0 mm, and Seeed's C3 row above has drawn it with
    # the EP3.45 model since OH-93. So a model is matched on its leads, its
    # pitch and its body, the land's pad is stated where the model's name
    # differs, and among KiCad models that share a body the choice is (1) the
    # one this table already gives the same chip -- one part, one drawing --
    # else (2) the one whose pad is nearest the land's, a JUDGEMENT.
    Component(
        "QFN32_5MM", "Package_DFN_QFN",
        "QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm",
        "U2 on the QT Py, the ESP32-C3FH4 itself: thirty-three pads spanning "
        "4.90 x 4.90 mm, thirty-two leads round a 5 x 5 mm body. Adafruit "
        "land its exposed pad at 3.00 x 3.00 mm and the model's name says "
        "3.45: by the rule above the chip governs, and this is the model "
        "Seeed's C3 row gives the same chip on the same 3.00 mm land.",
    ),
    Component(
        "DFN-8", "Package_DFN_QFN", "DFN-8-1EP_2x2mm_P0.5mm_EP0.6x1.2mm",
        "U4 on the Thing Plus, the MAX17048 fuel gauge: eight pads on a "
        "0.5 mm pitch round a 1.38 x 0.80 mm exposed pad, 2 x 2 mm by "
        "SparkFun's tDocu. KiCad has six 2 x 2 mm eight-lead models on that "
        "pitch, listed 2026-09-29 in Package_DFN_QFN and Package_SON: one "
        "with no exposed pad, one named for Micrel, and four whose pads are "
        "0.6 x 1.2, 0.9 x 1.6, 0.9 x 1.7 and 1.05 x 1.75 mm. By the rule "
        "above this chip has no drawing yet, so the pad nearest the land "
        "chooses, and 0.6 x 1.2 is 0.20 mm off it at worst against 0.22 for "
        "the next -- a JUDGEMENT the land nearly ties. TURNED 90: SparkFun "
        "lay the leads along x and KiCad's footprint along y.",
        turn=90.0,
    ),
    Component(
        "TDFN8_2X2MM", "Package_DFN_QFN", "DFN-8-1EP_2x2mm_P0.5mm_EP0.6x1.2mm",
        "X2 on the Feather, the same MAX17048 on Adafruit's land for it, "
        "whose exposed pad is the same 0.80 x 1.38 mm as SparkFun's: one "
        "part, one drawing, the DFN-8 row's model. Adafruit lay the leads "
        "along y, as KiCad's footprint does, so no turn.",
    ),
    Component(
        "LED3535_FULLPADS", "LED_SMD", "LED_WS2812B-Mini_PLCC4_3.5x3.5mm",
        "LED1 on the Feather, value WS2812B_3535FULL: four pads spanning "
        "3.40 x 1.75 mm and a body Adafruit draw 3.5 x 3.5 mm -- the WS2812B "
        "in its 3535 package, which is what this model names.",
    ),
    # --- the Adafruit KB2040, OH-186 ----------------------------------------
    #
    # Its row in tools/board_manifest.py composed it by construction, and
    # these are the packages none of the rows above already drew. Each span
    # was measured with `eagle.Element.pad_extent` on 2026-09-30, and each
    # element's device is the one Adafruit's own schematic names.
    Component(
        "QFN56_7MM_REDUCEDEPAD", "Package_DFN_QFN",
        "QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm",
        "Adafruit's RP2040 land, its exposed pad reduced by its own name: "
        "fifty-seven pads spanning "
        "6.90 x 6.90 mm, fifty-six leads on a 0.4 mm pitch round a 7 x 7 mm "
        "body Adafruit draw on tDocu, and a 3.20 x 3.20 mm exposed pad. "
        "KiCad's Package_DFN_QFN, 191 models listed 2026-09-30, holds three "
        "56-lead 7 x 7 mm parts on that pitch, whose pads are 3.2, 4 and "
        "5.6 mm square. By the exposed-pad rule above this chip has no "
        "drawing yet, so the pad nearest the land chooses -- a JUDGEMENT, "
        "and not a close one: this model's is the land's own size. Pin 1 is "
        "where KiCad's footprint puts it, and the vendor's dot says so.",
    ),
    Component(
        "SOD-323F", "Diode_SMD", "D_SOD-323F",
        "Adafruit's SOD-323F land: two pads 2.00 mm apart, and SOD-323F, "
        "the flat-lead SOD-323, is the package Adafruit's name and the "
        "model's both state. Adafruit also place the same NSR0320 on a land "
        "they name SOD-323_MINI, drawn as D_SOD-323: each is drawn as its "
        "own land is named. TURNED 180: Adafruit put the cathode pad C at "
        "+x, and KiCad's footprint puts pad 1, the cathode, at -x; a test "
        "holds the model's band to pad C.",
        turn=180.0,
    ),
    Component(
        "CRYSTAL_2.5X2", "Crystal", "Crystal_SMD_2520-4Pin_2.5x2.0mm",
        "Adafruit's 2.5 x 2.0 mm crystal land: four pads spanning "
        "1.65 x 1.25 mm, and "
        "Adafruit draw the body 2.5 x 2.0 mm on tDocu -- the 2520 part the "
        "model's name states, and the one Seeed's RP2350 crystal draws. Pad "
        "1 is where KiCad's footprint puts it, so no turn.",
    ),
    Component(
        "_0603MP", "Capacitor_SMD", "C_0603_1608Metric",
        "a capacitor on the land Adafruit's own description calls 0603 "
        "MicroPitch: two pads 1.52 mm apart, and the 1.6 x 0.8 mm chip.",
    ),
    # --- the SparkFun Pro Micro ESP32-C3 and Qwiic Pocket ESP32-C6, OH-189 ----
    #
    # Their rows in tools/board_manifest.py composed both by construction,
    # and these are the packages no row above already drew. Each span was
    # measured with `eagle.Element.pad_extent` on 2026-09-30.
    Component(
        "0402-TIGHT", "Resistor_SMD", "R_0402_1005Metric",
        "a resistor on SparkFun's tight 0402 land: two pads 1.00 mm apart, "
        "and the 1.0 x 0.5 mm resistor.",
    ),
    Component(
        "0402-TIGHT", "Capacitor_SMD", "C_0402_1005Metric",
        "a capacitor on the same 1.00 mm 0402 land, and the 1.0 x 0.5 mm "
        "chip.",
    ),
    Component(
        "ESP32-C3-MINI-1", "espressif", "ESP32-C3-MINI-1",
        "SparkFun's ESP32-C3-MINI-1 land: 61 pads spanning 11.90 x 9.90 mm "
        "in the package's own frame, the count and span of Espressif's own "
        "footprint for the module. KiCad's RF_Module holds no ESP32-C3-MINI-1, "
        "listed 2026-09-30 -- its C3 is the WROOM-02 -- so this is "
        "Espressif's STEP and footprint, as for the C6 modules above. Placed "
        "by `pads_origin`; turned half round, SparkFun's drawing of the body "
        "misses Espressif's by more than 5 mm, which `silk_miss` refuses.",
        step=f"{ESPRESSIF_KICAD}/3dmodels/espressif.3dshapes/ESP32-C3-MINI-1.STEP",
        footprint=(f"{ESPRESSIF_KICAD}/footprints/Espressif.pretty/"
                   f"ESP32-C3-MINI-1.kicad_mod"),
    ),
    Component(
        "ESP32-C6-MINI-1", "espressif", "ESP32-C6-MINI-1",
        "SparkFun's own land for the ESP32-C6-MINI-1, under the module's "
        "name: 61 pads spanning 11.90 x 9.90 mm, the count and span of "
        "Espressif's footprint, and the model the Feather's PICO-MINI land "
        "draws -- one part, one drawing. Placed by `pads_origin`, on the "
        "underside where the board file mirrors it.",
        step=f"{ESPRESSIF_KICAD}/3dmodels/espressif.3dshapes/ESP32-C6-MINI-1.STEP",
        footprint=(f"{ESPRESSIF_KICAD}/footprints/Espressif.pretty/"
                   f"ESP32-C6-MINI-1.kicad_mod"),
    ),
    Component(
        "JST04_1MM_VERT", "Connector_JST",
        "JST_SH_BM04B-SRSS-TB_1x04-1MP_P1.00mm_Vertical",
        "SparkFun's vertical Qwiic port, by its own package description: "
        "four 1 mm-pitch contacts and two mounting pads 5.60 mm apart, the "
        "contacts 2.43 mm from the mounting pads' line where KiCad's vertical "
        "SH, BM04B-SRSS-TB, puts them 2.53 mm. Pin 1 is at -x, on the side "
        "away from the mounting pads, in both, so no turn -- a turn nothing "
        "here can check, and the composer counts it.",
    ),
    # --- the PCBCUPID Glyph Mini RP2040, OH-195 --------------------------------
    #
    # The first manifest row that is a `.kicad_pcb`. Its footprints are
    # KiCad's own by name, each from the library KiCad files it in or from a
    # PCBCUPID copy of one, and every one states the model it places -- so
    # each row below draws the model the vendor's own footprint names, and
    # says where it does not. Spans are the board-frame pad extents of
    # `eagle.Element.pad_extent`, measured 2026-09-30.
    Component(
        "R_0402_1005Metric", "Resistor_SMD", "R_0402_1005Metric",
        "KiCad's own 0402 resistor land, by name and from KiCad's own "
        "library: two pads 1.02 mm apart, and the model PCBCUPID's footprint "
        "places. Drawn only where the board file states a resistor -- see "
        "`kicad_statements`.",
    ),
    Component(
        "C_0402_1005Metric", "Capacitor_SMD", "C_0402_1005Metric",
        "KiCad's own 0402 capacitor land, by name and from KiCad's own "
        "library: two pads 0.96 mm apart, and the model PCBCUPID's footprint "
        "places. Drawn only where the board file states a capacitor.",
    ),
    Component(
        "LED_0603_1608Metric", "LED_SMD", "LED_0603_1608Metric",
        "D1, RED_LED by value, on KiCad's own 0603 LED land: two pads "
        "1.575 mm apart, and the model PCBCUPID's footprint places -- on "
        "the Glyph Mini, and D2 and D3 on the Glyph C3 and C6.",
    ),
    Component(
        "SW_Push_SPST_NO_Alps_SKRK", "Button_Switch_SMD",
        "SW_Push_SPST_NO_Alps_SKRK",
        "SW1 and SW2, SKRKAGE020 by value, an Alps SKRK, on a land PCBCUPID "
        "keep in their own `Button` library under KiCad's name for it: two "
        "pads 4.20 mm apart. Their footprint names `SKRKAHE020.STEP` from "
        "their own machine's user directory, which nobody publishes, so this "
        "is the model KiCad publishes for the land of that name -- a "
        "JUDGEMENT that one SKRK body stands for another.",
        stands_for=("SKRKAHE020",),
    ),
    Component(
        "SOIC-8_5.3x5.3mm_P1.27mm", "Package_SO", "SOIC-8_5.3x5.3mm_P1.27mm",
        "U1, the W25Q32JVSS flash by value, on KiCad's own 208 mil SOIC-8 "
        "land: eight pads spanning 3.81 x 7.18 mm turned as placed, and the "
        "model PCBCUPID's footprint places.",
    ),
    Component(
        "SOT-23-5", "Package_TO_SOT_SMD", "SOT-23-5",
        "KiCad's own SOT-23-5 land, by name: five pads spanning 2.28 x "
        "1.90 mm, and the model each footprint placing it states -- the "
        "Glyph Mini's U2 regulator, on the underside where the board file "
        "flips it, and the Glyph C3's and C6's charger and regulator. "
        "Olimex keep KiCad's name for a land of their own laid out half "
        "round, which has rows of its own below.",
    ),
    Component(
        "Crystal_SMD_Abracon_ABM8AIG-4Pin_3.2x2.5mm", "Crystal",
        "Crystal_SMD_SeikoEpson_FA238-4Pin_3.2x2.5mm",
        "Y1, on KiCad's own land for Abracon's ABM8AIG: four pads spanning "
        "2.20 x 1.60 mm under a 3.2 x 2.5 mm body. PCBCUPID's footprint "
        "places KiCad's Seiko Epson FA-238 model on it, a four-pad crystal "
        "of the same 3.2 x 2.5 mm, and that is the model drawn. On the "
        "underside, where the board file flips it.",
    ),
    Component(
        "QFN-56-1EP_7x7mm_P0.4mm_EP5.6x5.6mm", "Package_DFN_QFN",
        "QFN-56-1EP_7x7mm_P0.4mm_EP5.6x5.6mm",
        "IC1, the RP2040 by value, on PCBCUPID's own copy of KiCad's 7 x 7 mm "
        "QFN-56 land with the 5.6 x 5.6 mm exposed pad its name states: 56 "
        "leads and that pad spanning 6.88 x 6.88 mm, with paste apertures "
        "over the pad on no copper layer, and the model their footprint "
        "places. "
        "On the underside, where the board file flips it; pin 1 is where "
        "their own marker says, which `mark_turns` reads there too.",
    ),
    Component(
        "USB_C_Receptacle_Palconn_UTC16-G", "Connector_USB",
        "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
        "J2, on a land PCBCUPID name for Palconn's UTC16-G: sixteen contact "
        "pads and four shell tabs spanning 8.64 x 4.84 mm. Its value says "
        "USB4105 and its part number GCT's USB4105-15-A-120, and their "
        "footprint places KiCad's GCT USB4105 model -- three statements of "
        "one part, so that is the model drawn. Their footprint moves the "
        "model 1.25 mm off its origin, and anchored on its shell tabs this "
        "one lands where that offset puts it: "
        "`test_the_glyph_usb_socket_lands_where_its_own_footprint_puts_it` "
        "measures the two. The Glyph C3 and C6 place the same land with "
        "HRO's model on it, and `drawn_from` refuses this row there.",
    ),
    # --- the PCBCUPID Glyph C3 and C6, OH-195 -----------------------------------
    #
    # One board twice, with its module changed: KiCad 8 files whose
    # footprints are KiCad's own, from KiCad's own libraries, each placing
    # the model KiCad files with it -- except three, which place models from
    # PCBCUPID's own disk and are refused or argued below. Spans are the
    # footprints' own pad extents, read 2026-10-08.
    Component(
        "R_0603_1608Metric", "Resistor_SMD", "R_0603_1608Metric",
        "KiCad's own 0603 resistor land, by name: two pads 1.65 mm apart, "
        "and the model the footprint places -- the Glyph C3's and C6's, from "
        "KiCad's Resistor_SMD, and the Thing Plus C5's, from SparkFun's own "
        "copy of the land under KiCad's name. Drawn only where the board "
        "file states a resistor.",
    ),
    Component(
        "C_0603_1608Metric", "Capacitor_SMD", "C_0603_1608Metric",
        "KiCad's own 0603 capacitor land, by name: two pads 1.55 mm apart, "
        "and the model the footprint places -- the Glyph C3's and C6's, and "
        "SparkFun's on the Thing Plus C5. Drawn only where the board file "
        "states a capacitor.",
    ),
    Component(
        "D_SMA", "Diode_SMD", "D_SMA",
        "D1 on the Glyph C3 and C6, SS34 by value, a Schottky rectifier in "
        "DO-214AC: KiCad's own SMA land, two pads 4.00 mm apart with pad 1, "
        "the cathode, at -x, and the model the footprint places.",
    ),
    Component(
        "SW_SPDT_PCM12", "Button_Switch_SMD", "SW_SPDT_PCM12",
        "SW3 on the Glyph C3 and C6, the slide switch: KiCad's own land for "
        "C&K's PCM12, three contacts and four shell tabs spanning 7.30 x "
        "2.86 mm round two locating holes, and the model the footprint "
        "places.",
    ),
    Component(
        "JST_SH_BM04B-SRSS-TB_1x04-1MP_P1.00mm_Vertical", "Connector_JST",
        "JST_SH_BM04B-SRSS-TB_1x04-1MP_P1.00mm_Vertical",
        "J5 on the Glyph C3 and C6, the Qwiic port: KiCad's own land for "
        "JST's vertical SH, BM04B-SRSS-TB -- four 1 mm-pitch contacts and "
        "two mounting pads spanning 5.60 x 2.53 mm. PCBCUPID's footprint "
        "places a BM4B-SRSS-TB.step from their own disk, which nobody "
        "publishes; that this is the same part as the land's BM04B, the "
        "contact count written without its zero, is a JUDGEMENT, and this "
        "is KiCad's model of it.",
        stands_for=("BM4B-SRSS-TB",),
    ),
    Component(
        "ESP32-H2-MINI-1_EXP", "espressif", "ESP32-C3-MINI-1",
        "U4 on the Glyph C3, valued ESP32-C3-MINI-1-N4, from PCBCUPID's own "
        "library named ESP32C3, on a land they named for the ESP32-H2-MINI-1. "
        "Espressif's own footprints for the H2-, C3- and C6-MINI-1 put down "
        "the same 61 pads at the same places -- compared 2026-10-08 at the "
        "pinned commit -- so the land's name says nothing of the chip, and "
        "the value and the library say C3. 61 pads spanning 11.90 x "
        "9.90 mm, within 0.01 mm of Espressif's. The footprint places no "
        "model; this is Espressif's STEP and footprint, as for SparkFun's "
        "C3-MINI-1 above.",
        step=f"{ESPRESSIF_KICAD}/3dmodels/espressif.3dshapes/ESP32-C3-MINI-1.STEP",
        footprint=(f"{ESPRESSIF_KICAD}/footprints/Espressif.pretty/"
                   f"ESP32-C3-MINI-1.kicad_mod"),
    ),
    Component(
        "ESP32-C6-MINI-1_EXP", "espressif", "ESP32-C6-MINI-1",
        "U4 on the Glyph C6, valued ESP32-C6-MINI-1-N4, on PCBCUPID's land "
        "named for it: 61 pads spanning 11.90 x 9.90 mm, Espressif's own. "
        "The footprint places no model; this is Espressif's STEP and "
        "footprint, the one the Feather's and the Pocket's C6-MINI-1 draw.",
        step=f"{ESPRESSIF_KICAD}/3dmodels/espressif.3dshapes/ESP32-C6-MINI-1.STEP",
        footprint=(f"{ESPRESSIF_KICAD}/footprints/Espressif.pretty/"
                   f"ESP32-C6-MINI-1.kicad_mod"),
    ),
    # --- the Olimex ESP32-C3-DevKit-Lipo, revision D, OH-195 ---------------------
    #
    # Olimex's own footprint libraries, each footprint placing a model from
    # the project's own packages3D/ directory. Where that file carries
    # KiCad's model's name the row draws KiCad's; where it does not, the row
    # says what it stands for. Turns are read off pad numbers against KiCad's
    # own footprint for the model, in each land's library frame -- for a part
    # on the underside, its stored pads with y negated -- 2026-10-08.
    Component(
        "R_0402_5MIL_DWS", "Resistor_SMD", "R_0402_1005Metric",
        "Olimex's 0402 resistor land: two pads 1.02 mm apart, and the model "
        "it places is named for KiCad's 0402 resistor.",
    ),
    Component(
        "C_0402_5MIL_DWS", "Capacitor_SMD", "C_0402_1005Metric",
        "Olimex's 0402 capacitor land: two pads 1.02 mm apart, and the model "
        "it places is named for KiCad's 0402 capacitor.",
    ),
    Component(
        "C_0603_5MIL_DWS", "Capacitor_SMD", "C_0603_1608Metric",
        "Olimex's 0603 capacitor land: two pads 1.78 mm apart, and the model "
        "it places is named for KiCad's 0603 capacitor.",
    ),
    Component(
        "LED_0603_KA", "LED_SMD", "LED_0603_1608Metric",
        "LED1 and CHARGING1, green and yellow by value: Olimex's 0603 LED "
        "land, two pads 1.52 mm apart, named K then A and drawn with its body "
        "reaching past pad 1 -- the cathode at -x, as KiCad's footprint puts "
        "pad 1. Olimex place their own LED_0603_G and LED_0603_Y from the "
        "project's packages3D/, which nothing here fetches; KiCad's 0603 LED "
        "standing for both is a JUDGEMENT, and it is not coloured.",
        stands_for=("LED_0603_G", "LED_0603_Y"),
    ),
    Component(
        "SOD-123_1C-2A_KA", "Diode_SMD", "D_SOD-123",
        "D1 and D2, 1N5819S4/SOD123 by value: Olimex's SOD-123 land, two "
        "pads 3.80 mm apart, whose own name puts the cathode on pad 1 at -x, "
        "as KiCad's footprint does. Olimex place their own SOD123.step; "
        "KiCad's SOD-123, the package both names state, stands for it.",
        stands_for=("SOD123",),
    ),
    Component(
        "SOT23", "Package_TO_SOT_SMD", "SOT-23",
        "FET1, IRLML6402 by value, on the underside: Olimex's SOT-23 land, "
        "three pads spanning 2.21 x 1.90 mm, and the model named SOT-23 it "
        "places. TURNED 180: Olimex put pins 1 and 2 at +x and pin 3 at -x, "
        "where KiCad's footprint puts 1 and 2 at -x.",
        turn=180.0,
        vendor_library="OLIMEX_Transistors-FP",
    ),
    Component(
        "SOT-23-5", "Package_TO_SOT_SMD", "SOT-23-5",
        "U1, the TP4054 charger by value: Olimex's own SOT-23-5 land under "
        "KiCad's name, five pads spanning 2.60 x 1.90 mm, and the model named "
        "SOT-23-5 it places. TURNED 180: Olimex put pins 1 to 3 at +x, "
        "where KiCad's footprint puts them at -x.",
        turn=180.0,
        vendor_library="OLIMEX_IC-FP",
    ),
    Component(
        "SOT-23-5", "Package_TO_SOT_SMD", "SOT-23-5",
        "U2, the SY8089 regulator by value, on the underside: the same land "
        "from Olimex's regulator library, five pads spanning 2.60 x 1.90 mm "
        "with pins 1 to 3 at +x, so TURNED 180 for the reason the charger's "
        "is.",
        turn=180.0,
        vendor_library="OLIMEX_Regulators-FP",
    ),
    Component(
        "HN1x9", "Connector_PinHeader_2.54mm", "PinHeader_1x09_P2.54mm_Vertical",
        "EXT1 and EXT2, the two header rows, on the underside: Olimex's land "
        "of nine plated holes on 2.54 mm, 20.32 mm long, pin 1 at -x. Olimex "
        "place their own HN1x9-PinHeader_1x09_P2.54mm_Vertical.step, named "
        "for this KiCad model, which stands for it. TURNED 90: KiCad's "
        "footprint runs its pins down the page from pin 1.",
        turn=90.0,
        stands_for=("HN1x9-PinHeader_1x09_P2.54mm_Vertical",),
    ),
    Component(
        "ESP32-­C3-­MINI­-1", "espressif", "ESP32-C3-MINI-1",
        "U3, valued ESP32-C3-MINI-1-N4, on Olimex's land for it, whose name "
        "carries three soft hyphens: 61 pads spanning 11.90 x 9.90 mm, "
        "Espressif's own count and span, with a plated 1.1 mm hole in the "
        "middle of its ground pad. Olimex place their own "
        "ESP32-C3-MINI-1-N4.STEP; Espressif's STEP and footprint, as for the "
        "other C3-MINI-1 lands above, stand for it.",
        step=f"{ESPRESSIF_KICAD}/3dmodels/espressif.3dshapes/ESP32-C3-MINI-1.STEP",
        footprint=(f"{ESPRESSIF_KICAD}/footprints/Espressif.pretty/"
                   f"ESP32-C3-MINI-1.kicad_mod"),
        stands_for=("ESP32-C3-MINI-1-N4",),
    ),
    # --- the SparkFun Thing Plus ESP32-C5, OH-195 --------------------------------
    #
    # SparkFun's own KiCad libraries, each footprint placing a model from
    # their own 3dmodels tree. Their lands here are laid out as KiCad's own
    # footprints for each model are -- pad for pad, compared 2026-10-08 --
    # so no row turns, where the same names in SparkFun's EAGLE libraries
    # are turned (`SOT23-5`, `DFN-8`).
    Component(
        "SOT23-5", "Package_TO_SOT_SMD", "SOT-23-5",
        "U2, U4 and U5, two RT9080-3.3 regulators and an MCP73831 charger: "
        "SparkFun's KiCad SOT-23-5 land, five pads spanning 2.60 x 1.90 mm "
        "laid out as KiCad's own, pin 1 at -x, so not turned as their EAGLE "
        "land of the same name is.",
        vendor_library="SparkFun-Semiconductor-Standard",
    ),
    Component(
        "SOT23-6", "Package_TO_SOT_SMD", "SOT-23-6",
        "D1, the DT1042-04SO ESD array by value: SparkFun's SOT-23-6 land, "
        "six pads spanning 2.60 x 1.90 mm laid out as KiCad's own, and the "
        "model named SOT-23-6 it places.",
        vendor_library="SparkFun-Semiconductor-Standard",
    ),
    Component(
        "SOT-583-8", "Package_TO_SOT_SMD", "SOT-583-8",
        "U7, the LM66200 by value: SparkFun's SOT-583-8 land, eight pads "
        "spanning 1.48 x 1.50 mm and pad for pad KiCad's own. SparkFun's "
        "footprint places a file named SOT-583-3; its name says three leads "
        "where the land is named for eight and puts down eight, so KiCad's "
        "eight-lead SOT-583 standing for it is a JUDGEMENT the vendor's own "
        "copper makes.",
        stands_for=("SOT-583-3",),
        vendor_library="SparkFun-Semiconductor-Standard",
    ),
    Component(
        "DFN-8_2x2mm_P0.5mm_EP1.2x0.8mm", "Package_DFN_QFN",
        "DFN-8-1EP_2x2mm_P0.5mm_EP1.05x1.75mm",
        "U6, the MAX17048 by value: SparkFun's 2 x 2 mm DFN-8 land, eight "
        "leads on 0.5 mm laid out as KiCad's footprint for this model lays "
        "them, and the model it places. Their EAGLE DFN-8 row draws the same "
        "chip with the EP0.6x1.2 model, chosen by the land's exposed pad "
        "where nothing stated one; here the footprint states this one.",
        vendor_library="SparkFun-Semiconductor-Standard",
    ),
    Component(
        "LED_0603_1608Metric_Red", "LED_SMD", "LED_0603_1608Metric",
        "D4 and D5, red by value: SparkFun's 0603 LED land, two pads "
        "1.57 mm apart, pad for pad KiCad's own, and their own "
        "LED_0603_1608Metric_Red.step on it. KiCad's 0603 LED standing for "
        "it is a JUDGEMENT, and is not red.",
        stands_for=("LED_0603_1608Metric_Red",),
    ),
    Component(
        "LED_0603_1608Metric_Yellow", "LED_SMD", "LED_0603_1608Metric",
        "D6, yellow by value: the same land, two pads 1.57 mm apart, and the "
        "same JUDGEMENT as the red pair, for SparkFun's "
        "LED_0603_1608Metric_Yellow.step.",
        stands_for=("LED_0603_1608Metric_Yellow",),
    ),
    Component(
        "JST_1x04_P1.0mm_Horizontal_SMD", "Connector_JST",
        "JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal",
        "J1, the Qwiic port, valued Qwiic_RA: SparkFun's land, four 1 "
        "mm-pitch contacts 3.68 mm from two mounting pads, numbered from -x "
        "with the mounting pads down the page, as KiCad's SM04B-SRSS-TB "
        "footprint has them 3.88 mm apart -- the land their EAGLE Thing Plus "
        "places as JST04_1MM_RA, drawn from this model. The file never names "
        "SM04B-SRSS-TB: the footprint's Description reads '4 pin JST 1mm "
        "polarized connector for I2C', its Datasheet is JST's eSH.pdf, the "
        "SH series, and it places SparkFun's own Qwiic-Horizontal.step. That "
        "KiCad's SM04B-SRSS-TB, the four-pin right-angle SH, stands for it "
        "is A JUDGEMENT from those.",
        stands_for=("Qwiic-Horizontal",),
    ),
    Component(
        "ESP32-C5-WROOM-1-NARROW", "espressif", "esp32-c5-wroom-1",
        "U1, valued ESP32-C5-WROOM-1: SparkFun's narrow land for the module, "
        "the 28 pads Espressif's own footprint numbers with its two side "
        "rows 16.50 mm apart where Espressif's are 17.50, and the exposed pad "
        "split into nine. KiCad publishes no ESP32-C5 module; this is "
        "Espressif's STEP and footprint, placed by `pads_origin` on the "
        "middle of the pads and held by `silk_miss` to the body SparkFun "
        "draw, standing for the ESP32-C5-WROOM-1.step their footprint "
        "places.",
        step=f"{ESPRESSIF_KICAD}/3dmodels/espressif.3dshapes/esp32-c5-wroom-1.step",
        footprint=(f"{ESPRESSIF_KICAD}/footprints/Espressif.pretty/"
                   f"ESP32-C5-WROOM-1.kicad_mod"),
        stands_for=("ESP32-C5-WROOM-1",),
    ),
)

#: Packages that are on the board, are worth seeing, and are NOT drawn -- with
#: the reason, which travels to the page. An empty reason would be worse than
#: the omission: a person looking at a board with no USB socket should be told
#: why rather than left to wonder whether the importer broke.
#: Two reasons that each cover a part appearing under two vendor spellings.
#: Bound here rather than repeated in `ABSENT`, which is keyed by the vendor's
#: package name and so has to hold both spellings.
#: The words every `ABSENT` reason for copper, ink or a hole ends on -- a
#: package that has no body, as against a part nobody publishes a model of.
#: `compose` counts the two apart by this phrase (OH-180).
NO_BODY = "there is no body to look for"

#: The Glyph Mini's three header rows (OH-195), which are two package names
#: and one reason. Not a `NO_BODY` reason: the vendor's own footprint places a
#: body there, and a reader looking at the board would look for it.
GLYPH_HEADER = (
    "J3, J4 and J5 on the Glyph Mini, PCBCUPID's own castellated rows from "
    "their library `Conn_Castellated_Holes_2.54mm`: each pin is two plated "
    "holes 1.5 mm apart, the outer one cut by the board's edge, and that "
    "copper is drawn by the copper pass. Their footprint also hangs KiCad's "
    "own PinHeader model under the row, turned half round and dropped "
    "1.5 mm, which is the header a person may solder in. It is refused "
    "rather than drawn: `place` anchors a legged model on the middle of the "
    "through-hole pads, which here is the middle of each pair, and that "
    "would stand every pin half a pair outboard of the hole the vendor's "
    "model puts it in. Nothing in the file says whether a header is "
    "fitted -- no DNP, nothing left off the BOM -- and the footprint names "
    "no maker and no part."
)

ABSENT: dict[str, str] = {
    # --- pads with no body, stated rather than silent (OH-119) --------------
    "TP-SP": (
        "61 test points, each a bare 0.8 x 0.8 mm pad. A test point is the "
        "copper itself, which OH-110 already draws, and any body stood on "
        "one would be an invention. No KiCad library was searched: there is no body to look for."
    ),
    "FIDUCIA-MOUNT": (
        "three fiducials, each a bare 1.016 mm copper disc the pick-and-place "
        "camera sights on. Nothing is fitted to them, so nothing is drawn. No KiCad library was searched: there is no body to look for."
    ),
    "SJ": (
        "two solder jumpers, GROUND and RESET-EN: two 1.168 x 1.600 mm "
        "half-moon pads each, which a person may bridge with solder. "
        "Unbridged from the factory there is no component to draw, and the "
        "pads themselves are drawn as copper. No KiCad library was searched: there is no body to look for."
    ),
    "FRAME": (
        "the schematic frame: zero pads and 0.0 mm of copper, a drawing "
        "artefact in the board file rather than a part. No KiCad library was searched: there is no body to look for."
    ),
    "QS": (
        "the 16 MHz crystal. Arduino's own silkscreen makes its body "
        "6.86 x 4.57 mm, and every through-hole crystal in KiCad's Crystal "
        "library is an HC49 at 10.90 or 11.05 mm across -- near enough to pass "
        "a footprint check and half as long again as the real can. The size "
        "check would have accepted it; the vendor's own drawing is what says "
        "no."
    ),
    "RESONATOR": (
        "the ceramic resonator. Its pads are surface-mount and its body is "
        "3.20 x 1.60 mm by the vendor's silkscreen; KiCad's only three-pin "
        "resonators are 7 mm through-hole cans standing 12.5 mm tall. "
        "`confirm` refuses it on mounting, which is the check that exists "
        "because the size tolerance let this one through."
    ),
    # --- OH-93: the XIAOs' undrawn parts ------------------------------------
    #
    # **Every one of these is a part KiCad's library does not hold**, checked
    # by listing the library folder rather than by a 404 -- so each says which
    # folder was listed and what the nearest thing in it was. A model of
    # nearly the right part is what `confirm`'s tolerances exist to refuse,
    # and a 7 x 7 mm chip is not the place to spend that tolerance.
    # **Nothing here is a part any more.** This block held two pairs of
    # keys -- the load switch under Seeed's two spellings and the buttons
    # under theirs -- and both pairs turned out to be false absences that a
    # sweep found rather than a reader: OH-153 drew the buttons from a
    # height four of their six placements state, and OH-154 drew the load
    # switch, whose name states all three dimensions and whose refusal was
    # only ever that KiCad publishes no SOT-883. What is left below is
    # copper, ink and holes, which is the only kind of thing that belongs.
    #
    # Both notes were also wrong about which boards place what -- the
    # buttons were said to be on "the C3 and the nRF54L15" when the C5
    # carries two as well -- and both errors came of trusting the note
    # beside a part instead of listing every placement of it.
    # --- OH-150: the XIAOs' copper and ink, which have no body either -----
    #
    # **The same class the Uno's TP-SP and FIDUCIA-MOUNT are in**, found on
    # the KiCad boards when OH-125 closed the silent `continue` that had
    # been hiding every unmodelled placement. A test point is its pad, a
    # logo is its ink, and a castellation is the board's own edge: none is
    # a part that a library could hold, so each says so rather than being
    # counted as a gap somebody might one day fill.
    "H7-HALF-HOLE-2.54": (
        "J1 and J2 on the ESP32-C3: **the module's own castellated edge**, "
        "drawn as two seven-pin references where the C6, C5 and nRF54L15 "
        "draw all fourteen on one MOUDLE14P footprint. Seeed mark both "
        "`DNP` -- nothing is fitted. Seven pads of each row sit exactly on "
        "Edge.Cuts, which the copper pass already halves into castellations, "
        "and the other seven are a plain through-hole row 1.27 mm inboard on "
        "the same nets. No KiCad library was searched: there is no body to "
        "look for."
    ),
    "BGA6-0.35-0.745X10.95X0.4MM": (
        "the ESP32-C6's U1, a DCDC buck converter by its own Description, "
        "and **the one package here whose own name is wrong**: it states "
        "0.745 x 10.95 mm where the drawing says about 0.85 x 1.2 -- "
        "**and the two boards say it on different layers**: the RP2350's "
        "F.Fab rectangle gives 0.850 x 1.200, while the ESP32-C6 draws no "
        "F.Fab for this footprint at all, so its 0.840 x 1.200 is the "
        "silkscreen fallback OH-124 added and is worth not calling F.Fab. "
        "Either way the name is 9.750 mm out -- a six-ball chip-scale "
        "part is not eleven millimetres long. **Every fact needed to draw "
        "it exists, and saying otherwise would be the easy refusal rather "
        "than the true one**: the ESP32-C5 places the same chip -- a "
        "byte-identical Description, `DCDC Buck-ADJ-1A ... WLCSP-6B` -- "
        "under the sound name `BGA6-0.35-0.85X1.2X0.4MM`, whose plan "
        "agrees with THIS board's F.Fab to 0.010 mm, and both names end "
        "`X0.4MM`, so even the height is stated twice. What is missing is "
        "a MECHANISM rather than a number: `ModelledSlab` gives one "
        "string two jobs -- the key that finds the footprint and the text "
        "`_NAMED_BODY` reads dimensions out of -- and drawing this part "
        "needs them separated, a believed name beside the literal one, "
        "which would have exactly one caller here. This repository's own "
        "rules say not to build that. So the refusal is a judgement about "
        "scope and it lasts only until a second such part arrives or "
        "Seeed correct the string. No KiCad library was searched: the "
        "model was never the problem."
    ),
    "TP-D45MIL": (
        "36 test points across all five KiCad XIAOs, each a bare "
        "1.143 x 1.143 mm pad -- 45 mil, which is what the package name "
        "says -- on B.Cu and B.Mask only. Every other graphic on all 36 "
        "sits on B.Fab or B.CrtYd, documentation and keepout layers that "
        "plot to nothing, and each is sized to the pad's own bounding box "
        "rather than to a body. A test point is the copper itself, which "
        "OH-110 already draws. No KiCad library was searched: there is no "
        "body to look for."
    ),
    "TP-1.6MM-ROUND": (
        "16 test points on the nRF54L15 and the RP2350, each a bare 1.6 mm "
        "round pad -- the name's own figure -- on B.Cu and B.Mask only. "
        "The RP2350's eight carry a stray 0.01 mm B.Mask line the "
        "nRF54L15's do not: ten microns is below any fabricator's minimum "
        "feature, so it is a CAD artefact rather than a stated feature. A "
        "test point is the copper itself, which OH-110 already draws. No "
        "KiCad library was searched: there is no body to look for."
    ),
    "TP-80X40MIL": (
        "12 test points across all five KiCad XIAOs, some named TPn and "
        "some named for the net they sit on -- GND0, BAT0, BAT+1, BAT-1 -- "
        "each a bare 2.032 x 1.016 mm pad, which is 80 x 40 mil as the "
        "name says. A test point is the copper itself, which OH-110 "
        "already draws. No KiCad library was searched: there is no body to "
        "look for."
    ),
    "LOGO-SEEED-NEW-1X9.6MM": (
        "Seeed's own logo -- U$2 on the ESP32-C3, REF** on the ESP32-C6, "
        "G*** on the RP2350 -- with zero pads and no `(model ...)` on any "
        "of the three. Ink and nothing else: 9.571 x 1.070 mm of it on the "
        "C3 and C6, drawn as 1,505 `fp_line`, and 8.916 x 1.005 mm on the "
        "RP2350, drawn as 12 `fp_poly` under the same package name. Both "
        "readings are already accounted for -- `kicad._silk_of` takes every "
        "footprint's silk whether or not this entry exists, so the lines "
        "are drawn as board silk and the polygons are in that board's own "
        "`not ink` count. No KiCad library was searched: there is no body "
        "to look for."
    ),
    "LOGO-SEEED-NEW-0.83X7.5MM": (
        "The smaller Seeed logo, G*** on the ESP32-C5: zero pads, no "
        "`(model ...)`, and 7.498 x 0.846 mm of silkscreen -- the name's "
        "own 0.83 x 7.5 to two thousandths -- drawn as the 12 `fp_poly` "
        "that are the whole of that board's `not ink` polygon count. No "
        "KiCad library was searched: there is no body to look for."
    ),
    "LOGO-CE_4.0x3.0mm_SilkScreen": (
        "The CE mark on the nRF54L15, which Seeed's own `(descr \"CE "
        "marking\")` names and their `exclude_from_pos_files "
        "exclude_from_bom` says is never fitted. Zero pads, no "
        "`(model ...)`, and 4.046 x 2.947 mm of silkscreen -- the name's "
        "own 4.0 x 3.0 -- drawn as 942 `fp_line` and the 7 `fp_arc` that "
        "are the whole of that board's `not ink` arc count. No KiCad "
        "library was searched: there is no body to look for."
    ),
    "MOUDLE14P-XIAO-HALF-HOLE": (
        "U2 on the ESP32-C6 and the RP2350: **the module's own edge**, not "
        "a part standing on it. `tools/kicad.py` says the same thing from "
        "the other side -- this footprint IS the XIAO outline -- and the "
        "geometry agrees: its 14 pins carry 56 pad records spanning "
        "15.240 x 17.780 mm on a 2.54 mm pitch, its castellation holes sit "
        "exactly on the y-extent of the Edge.Cuts it draws itself, and "
        "that outline measures 20.955 x 17.780 mm, which is the board. "
        "Nothing inside the footprint reaches F.Fab except hidden empty "
        "properties, so there is no body outline to read. The copper is "
        "drawn as copper and the half-holes are cut with the edge. No "
        "KiCad library was searched: there is no body to look for."
    ),
    # --- OH-180: the manifest boards' copper, and the parts nobody publishes
    #
    # Copper first: a pad with no body is its own drawing, which OH-110's
    # artwork pass already makes.
    "THING_PLUS": (
        "J1 on the Thing Plus, the pad map itself: 28 plated holes on the "
        "2.54 mm pitch in two rows 20.32 mm apart, 38.10 mm long. Its device "
        "says nothing of whether a header is fitted; SparkFun give it no "
        "PROD_ID, where every part they fit carries one, so that no header "
        "is fitted is A JUDGEMENT from that, and the holes are drawn as "
        "copper. No KiCad library was searched: there is no body to look for."
    ),
    "1X16_ROUND": (
        "JP1 on the Feather, sixteen plated holes on 2.54 mm, 38.10 mm long. "
        "Its device says nothing of whether a header is fitted; Adafruit give "
        "it no value -- as they give none to its solder jumper, and a value "
        "to every part they fit -- so that none is fitted is A JUDGEMENT from "
        "that. The holes are drawn as copper. No KiCad library was searched: "
        "there is no body to look for."
    ),
    "1X12_ROUND": (
        "JP3 on the Feather, twelve plated holes on 2.54 mm, 27.94 mm long, "
        "with no value, as the sixteen-hole row has none: that no header is "
        "fitted is the same JUDGEMENT. The holes are drawn as copper. No "
        "KiCad library was searched: there is no body to look for."
    ),
    "1X07_CASTEL": (
        "JP1 and JP3 on the QT Py: **the module's own castellated edge**, "
        "seven pads each on 2.54 mm, 15.24 mm long, with a plated hole in "
        "each. Copper and the board's edge, drawn by the copper pass. No "
        "KiCad library was searched: there is no body to look for."
    ),
    "FIDUCIAL-MICRO": (
        "SparkFun's fiducial, a bare 0.635 mm copper pad the pick-and-place "
        "camera sights on. No KiCad library was searched: there is no body "
        "to look for."
    ),
    "FIDUCIAL_1MM": (
        "Adafruit's fiducial, a bare 1.0 mm copper pad the pick-and-place "
        "camera sights on. No KiCad library was searched: there is no body "
        "to look for."
    ),
    "SMT-JUMPER_2_NC_TRACE_SILK": (
        "a solder jumper of SparkFun's: two 0.66 x 1.27 mm pads, closed by a "
        "trace a person may cut. Copper, drawn as copper. No KiCad library "
        "was searched: there is no body to look for."
    ),
    "SMT-JUMPER_2_NO_SILK": (
        "RGB on the Thing Plus: two 0.635 x 1.27 mm pads a person may bridge "
        "with solder, open from the factory. No KiCad library was searched: "
        "there is no body to look for."
    ),
    "SMT-JUMPER_3_1-NC_TRACE_SILK": (
        "LP on the Thing Plus: three 0.66 x 1.27 mm pads, two joined by a "
        "trace a person may cut. No KiCad library was searched: there is no "
        "body to look for."
    ),
    "SMT-JUMPER_3_2-NC_TRACE_SILK": (
        "a three-pad solder jumper of SparkFun's: three 0.66 x 1.27 mm pads, "
        "each outer pad joined to the middle one by a trace a person may "
        "cut. No KiCad library was searched: there is no body to look for."
    ),
    "COMBO-JUMPER_2_NC_TRACE": (
        "MEAS on the Thing Plus: two 0.635 x 1.27 mm pads joined by a trace "
        "and two 1.88 mm plated holes beside them, for a meter's leads once "
        "the trace is cut. No KiCad library was searched: there is no body "
        "to look for."
    ),
    "SOLDERJUMPER_CLOSEDWIRE": (
        "SJ1 on the Feather: two 1.168 x 1.600 mm pads closed by a "
        "0.2 mm wire of copper. No KiCad library was searched: there is no "
        "body to look for."
    ),
    "B1,27": (
        "SWC1 and SWC2 on the QT Py, test pads: a bare 1.27 mm copper pad "
        "each. No KiCad library was searched: there is no body to look for."
    ),
    "TESTPOINT_PLUS_1X3MM": (
        "VBAT on the QT Py, a bare 0.5 mm pad on the underside for a "
        "battery's lead. No KiCad library was searched: there is no body to "
        "look for."
    ),
    "TESTPOINT_MINUS_1X3MM": (
        "GND on the QT Py, the other bare 0.5 mm battery pad. No KiCad "
        "library was searched: there is no body to look for."
    ),
    # --- OH-189: the Pro Micro's and the Pocket's copper ----------------------
    "1X09_CASTELLATED": (
        "**a board's own castellated edge**: nine plated half-holes on "
        "2.54 mm, 20.32 mm long, cut by the edge, with a smaller plated hole "
        "1.57 mm inboard of each. Copper and the board's edge, drawn by the "
        "copper pass. No KiCad library was searched: there is no body to "
        "look for."
    ),
    "USB-SOLDER-PADS": (
        "four 3.0 x 0.9 mm pads, VBUS, D+, D- and GND, for a USB cable's "
        "wires soldered straight to the board. Copper, drawn as copper. No "
        "KiCad library was searched: there is no body to look for."
    ),
    "PAD.03X.05": (
        "a test point, a bare 1.27 mm round pad by SparkFun's own "
        "description of it. No KiCad library was searched: there is no body "
        "to look for."
    ),
    "PAD.03X.03": (
        "a test point, a bare 0.76 mm round pad by SparkFun's own "
        "description of it. No KiCad library was searched: there is no body "
        "to look for."
    ),
    "MOUNTINGHOLE_2.5_PLATED": (
        "two mounting holes on the Feather, 2.5 mm drilled in a 3.2 mm "
        "plated ring. Copper and a hole, and nothing fitted. No KiCad library "
        "was searched: there is no body to look for."
    ),
    # --- OH-186: the KB2040's copper ----------------------------------------
    "1X13_CASTEL": (
        "**a board's own castellated edge**, "
        "thirteen half-holes on 2.54 mm, 30.48 mm long, with a plated "
        "hole 1.524 mm inboard of each. Copper and the board's edge, drawn "
        "by the copper pass. No KiCad library was searched: there is no body "
        "to look for."
    ),
    "SOLDERJUMPER_ARROW_NOPASTE": (
        "a solder jumper: two 0.762 x 1.524 mm pads and the copper between "
        "them that a person bridges with solder. No KiCad "
        "library was searched: there is no body to look for."
    ),
    "TESTPOINT_ROUND_1.5MM_NO": (
        "a test point, a bare 1.5 mm round pad. No KiCad "
        "library was searched: there is no body to look for."
    ),
    # And the parts: each names what was listed and what the nearest thing
    # in it was, so the next reader re-runs the search rather than retakes it.
    "USB-C-16P_4LAYER-PADS": (
        "SparkFun's USB-C socket: twelve contact pads and four shell tabs "
        "spanning 8.64 x 4.76 mm. SparkFun's files name no maker for it -- "
        "only their own PROD_ID, CONN-14122 -- and KiCad's "
        "Connector_USB, 12 models listed 2026-09-29, holds two 16-pin "
        "receptacles, GCT's USB4105 and Amphenol's 12401610E4-2A, each a "
        "named part of its own length. Drawing either would put a maker's "
        "name on a part nobody here can say was fitted, the mistake OH-102 "
        "undid on the XIAOs."
    ),
    "USB_C_CUSB31-CFM2AX-01-X": (
        "Adafruit's USB-C socket, whose package name is the "
        "part: CUI's CUSB31-CFM2AX-01-X, twelve contact pads and four shell "
        "tabs spanning 8.64 x 4.76 mm. KiCad's Connector_USB, 12 models "
        "listed 2026-09-29, holds nothing of CUI's; its two 16-pin "
        "receptacles are GCT's and Amphenol's, and one of them on this land "
        "would be a different maker's part under Adafruit's name for this one."
    ),
    "JST-2-SMD": (
        "SparkFun's battery socket, a surface-mount JST PH: two "
        "1.0 x 4.6 mm contact pads 2.0 mm apart and two mounting pads. "
        "KiCad's Connector_JST holds 30 PH models, "
        "listed 2026-09-29, and every one is the through-hole -K; `confirm` "
        "refuses a legged model on these pads anyway."
    ),
    "JSTPH2_BATT": (
        "X1 on the Feather, the battery socket: the same two 1.0 x 4.6 mm "
        "contacts 2.0 mm apart and two mounting pads as SparkFun's JST-2-SMD "
        "land, a surface-mount JST PH, and KiCad's 30 PH models are all "
        "through-hole."
    ),
    "JST_SH4_RA": (
        "CONN1 on the Feather, the STEMMA QT port, **whose name and land "
        "disagree**. Adafruit name it a right-angle SH, and its four 1 mm "
        "contacts sit 2.548 mm from its two mounting pads and are numbered "
        "from +x -- where KiCad's own right-angle SM04B-SRSS-TB footprint "
        "puts them 3.875 mm apart numbered from -x. The land matches KiCad's "
        "VERTICAL BM04B-SRSS-TB to 0.023 mm instead, turned half round. "
        "Drawing either model would be choosing between two statements of "
        "the vendor's; the QT Py's STEMMA QT port, on the SM04B land, is "
        "drawn."
    ),
    "MICROSD_TINY": (
        "J5 on the Thing Plus, the microSD socket, value MICRO-SDFRICTION: "
        "fifteen pads spanning 10.68 x 7.24 mm. SparkFun's file names no "
        "maker -- only PROD_ID CONN-13500 -- and KiCad's Connector_Card holds "
        "three models, listed 2026-09-29: two Hirose microSD sockets, each "
        "a named part, and a nano-SIM."
    ),
    "WS2812-2020": (
        "D5 on the Thing Plus, the STAT LED: four pads under a body SparkFun "
        "draw 2.2 x 2.0 mm, a WS2812 in its 2020 package. KiCad's LED_SMD "
        "holds 38 models, listed 2026-09-29, and its smallest WS2812 is the "
        "3.5 x 3.5 mm WS2812B-Mini -- the Feather's, which is drawn."
    ),
    "SK6805_1515": (
        "Adafruit's addressable LED: four pads under a 1.5 x 1.5 mm "
        "body, an SK6805 "
        "in its 1515 package. The smallest addressable LED in KiCad's "
        "LED_SMD, 38 models listed 2026-09-29, is the reverse-mount "
        "SK6812MINI-E at 3.2 x 2.8 mm, about twice this one's side."
    ),
    "LONGAN-IC_SNR6-1.0-3X3X1MM": (
        "U4 on the Feather, an AHT20 humidity sensor by value: six pads on a "
        "1.0 mm pitch and no exposed pad, 3 x 3 x 1 mm by its own name. "
        "KiCad's Sensor_Humidity holds one model, TI's HDC2080, and the "
        "3 x 3 mm DFN-6 in Package_DFN_QFN is a 0.95 mm pitch round a "
        "1.7 x 2.6 mm pad. Listed 2026-09-29. **Every dimension is stated, "
        "so this is the OH-153 kind of absence and not an honest one**: "
        "tools/model_from_datasheet.py builds a slab from a name like this "
        "one, but reads it out of a KiCad footprint and this is an EAGLE "
        "package. The gap is that reader, filed in OH-180's note."
    ),
    "USON8_4X4": (
        "a QSPI flash on Adafruit's USON land, valued by its size and naming "
        "no maker: eight leads on a 0.8 mm pitch round a 2.0 x 3.0 mm "
        "exposed pad, under a 4 x 4 mm body. KiCad's only eight-lead "
        "4 x 4 mm parts on that pitch, listed 2026-09-30 in Package_DFN_QFN "
        "and Package_SON, are DFN-8-1EP_4x4mm_P0.8mm_EP2.5x3.6mm, 0.92 mm "
        "tall over a 2.5 x 3.6 mm pad, and WSON-8_4x4mm_P0.8mm, 0.82 mm "
        "tall over none. U names the ultra-thin height class and neither "
        "is in it, so either would draw a thicker part than the land is "
        "named for; and the name states no height to build one from."
    ),
    "MOUDLE14P-XIAO-HALF-HOLE-PRO": (
        "U9 on the ESP32-C5 and the nRF54L15, and the same edge as the "
        "entry above: identical 15.240 x 17.780 mm pad span, identical "
        "2.54 mm pitch, identical 20.955 x 17.780 mm Edge.Cuts. What the "
        "`-PRO` names is a finer land pattern -- a uniform "
        "1.626 x 1.725 mm flare pulled 0.862 mm off the edge on all 14 "
        "pins, against the plain variant's mixed flares at 0.55 to "
        "0.61 mm -- and a land pattern is not a body. No KiCad library was "
        "searched: there is no body to look for."
    ),
    # --- OH-195: the Glyph Mini's header rows -----------------------------------
    "PinHeader_1x05_P2.54mm_Vertical": GLYPH_HEADER,
    "PinHeader_1x09_P2.54mm_Vertical": GLYPH_HEADER,
    # --- OH-195: the Glyph C3 and C6 ---------------------------------------------
    "SW_SPST_PTS810": (
        "SW1 and SW2 on the Glyph C3 and C6, the BOOT and RESET buttons, "
        "**whose land and model name two parts**. The land, four pads "
        "spanning 4.15 x 2.15 mm, is KiCad's own "
        "for C&K's PTS 810, by its own description, and KiCad publishes that "
        "model; but PCBCUPID's footprint places a file named KMR621NG LFS, "
        "another C&K part number, from their own disk, which nobody "
        "publishes. Nothing else in the file -- the value is SW_Push -- says "
        "which they fit, and drawing the PTS 810 would take the land's word "
        "over the model's."
    ),
    # --- OH-195: the Olimex ESP32-C3-DevKit-Lipo's copper and holes ---------------
    "Fiducial1x3": (
        "four of Olimex's fiducials, two a side: a bare 1.0 mm copper disc "
        "the pick-and-place camera sights on, with no paste. No KiCad "
        "library was searched: there is no body to look for."
    ),
    "Fiducial1x3_Paste": (
        "two of Olimex's fiducials, one a side: the same bare 1.0 mm disc, "
        "pasted. No KiCad library was searched: there is no body to look for."
    ),
    "Mounting_Hole_Drill-3.3mm_Clerance-7mm": (
        "MH1 to MH4 on the Olimex, four unplated 3.3 mm mounting holes, "
        "nothing fitted. No KiCad library was searched: there is no body to "
        "look for."
    ),
    "SJ_1_SMALLER": (
        "three solder jumpers on the Olimex's underside, valued Opened: two "
        "0.51 x 0.76 mm pads each that a person may bridge with solder. "
        "Copper, drawn as copper. No KiCad library was searched: there is "
        "no body to look for."
    ),
    # And the Olimex's parts, each named by what its own file says it is.
    # Olimex publish a model of every one in the project's packages3D/,
    # which `tools/board_sources.py` does not fetch, and each footprint
    # places it with a turn its block states -- `pads_origin` reads an
    # offset only. Drawing them is that fetch and that reader.
    "CD32": (
        "L1 on the Olimex's underside, valued 2.2uH/NRS3015T2R2MNGH/1.5A/"
        "3.00x3.00x1.50mm -- Taiyo Yuden's NRS3015, its body stated in the "
        "value -- on a land Olimex name for Sumida's CD32, two pads 2.40 mm "
        "apart, placing their own L-CD32_shielded.step. KiCad's Inductor_SMD, "
        "518 models listed 2026-10-08, holds no Taiyo Yuden NR and no Sumida "
        "CD32. **Every dimension is stated, so this is the OH-153 kind of "
        "absence and not an honest one**: tools/model_from_datasheet.py "
        "builds a slab from a footprint's NAME, and this states its body in "
        "a value."
    ),
    "YTS-A016-X": (
        "BUT1 on the Olimex, the button: Olimex's own land, four pads "
        "spanning 4.15 x 2.15 mm, placing their own "
        "YTS-A016-X(SKRPABE010).stp -- Alps' SKRP, by the file's name. "
        "KiCad's Button_Switch_SMD, 157 models listed 2026-10-08, holds Alps' "
        "SKRK and no SKRP."
    ),
    "GBH-254-SMT-10": (
        "UEXT1 on the Olimex, the UEXT socket, valued P-B-V-10-LF: a "
        "surface-mount 2 x 5 box header on 2.54 mm, ten pads spanning 10.16 "
        "x 6.25 mm, placing their own model of CviLux's CH8710xM100 by its "
        "file's name. KiCad's Connector_IDC, 51 models listed 2026-10-08, "
        "holds IDC box headers that name no maker; one of them would stand "
        "a part on this land that nothing in the file names."
    ),
    "LIPO_BAT_VERTICAL_DW02S": (
        "BAT1 on the Olimex, the battery socket, **whose land and model name "
        "two parts**: valued DW02S on a land named for it, two plated holes "
        "2.03 mm apart, placing Molex's PicoBlade 53047-0210 by the model's "
        "file name. KiCad's Connector_Molex, 89 models listed 2026-10-08, "
        "holds no 53047 either."
    ),
    "USB2.0_TYPE-C(A40-00119-A52-12)": (
        "USB-C1 on the Olimex, the USB socket, **whose land and model name "
        "two parts**: valued USB-C-16P-F(A40-00119-A52-12) on a land named "
        "for that part number, sixteen contact pads and four plated shell "
        "tabs spanning 5.08 x 9.86 mm, placing GCT's USB4105-GF-A by the "
        "model's file name. KiCad publishes GCT's USB4105, and drawing it "
        "would put "
        "GCT's name on a part the value says is another -- the mistake "
        "OH-102 undid on the XIAOs."
    ),
    # --- OH-195: the SparkFun Thing Plus ESP32-C5's copper and holes --------------
    "ThingPlus_With_Connectors": (
        "U3 on the Thing Plus C5, the pad map itself: 28 plated holes on the "
        "2.54 mm pitch in two rows 20.32 mm apart. Its footprint places no "
        "model and SparkFun give it no PROD_ID, where every part they fit "
        "carries one, so that no header is fitted is A JUDGEMENT from that, "
        "as for the C6's THING_PLUS. The holes are drawn as copper. No KiCad "
        "library was searched: there is no body to look for."
    ),
    "Fiducial_0.5mm_Mask1mm": (
        "SparkFun's fiducial, by its own description a bare 0.5 mm copper "
        "disc in a 1 mm mask opening. No KiCad library was searched: there "
        "is no body to look for."
    ),
    "Standoff": (
        "ST1 to ST4 on the Thing Plus C5, unplated 3.1 mm holes for "
        "standoffs. The footprint carries a screw and a nut of two sizes, "
        "every one hidden: nothing is fitted. No KiCad library was "
        "searched: there is no body to look for."
    ),
    "Jumper_2_NC_Trace": (
        "a solder jumper of SparkFun's: two 0.66 x 1.27 mm pads, closed by a "
        "trace a person may cut. Copper, drawn as copper. No KiCad library "
        "was searched: there is no body to look for."
    ),
    "Jumper_2_NO": (
        "a solder jumper of SparkFun's: two 0.64 x 1.27 mm pads a person "
        "may bridge with solder, open from the factory. No KiCad library was "
        "searched: there is no body to look for."
    ),
    "Jumper_3_NC-1_Trace": (
        "a three-pad solder jumper of SparkFun's: three 0.66 x 1.27 mm pads, "
        "two joined by a trace a person may cut. No KiCad library was "
        "searched: there is no body to look for."
    ),
    "Jumper_3_NC-2_Trace": (
        "a three-pad solder jumper of SparkFun's: three 0.66 x 1.27 mm pads, "
        "all joined by traces a person may cut. No KiCad library was "
        "searched: there is no body to look for."
    ),
    "Jumper_2_PTH_SMD_Combo-NC": (
        "MEAS on the Thing Plus C5: two 0.64 x 1.27 mm pads joined by a "
        "trace and two 1.88 mm plated holes beside them, for a meter's leads "
        "once the trace is cut. No KiCad library was searched: there is no "
        "body to look for."
    ),
    # And its parts. SparkFun publish a model of each in their KiCad
    # library's 3dmodels/, which nothing here fetches; these are the ones
    # whose own maker's model KiCad does not publish either.
    "JST_1x02_P2.0mm_Horizontal_SMD": (
        "J3 on the Thing Plus C5, the battery socket, a surface-mount 2 mm "
        "JST by its description, 'to match SparkFun LiPo batteries': two "
        "1.0 x 4.6 mm contact pads 2.0 mm apart and two mounting pads, the "
        "C6's JST-2-SMD land. Every PH model in KiCad's Connector_JST, 158 "
        "listed 2026-10-08, is the through-hole -K."
    ),
    "USB-C_16": (
        "J2 on the Thing Plus C5, the USB-C socket: twelve contact pads and "
        "four shell tabs spanning 8.64 x 4.76 mm, PROD_ID CONN-14122, the "
        "part SparkFun's EAGLE boards place as USB-C-16P_4LAYER-PADS, and "
        "naming no maker. KiCad's Connector_USB, 12 models listed "
        "2026-10-08, holds two 16-pin receptacles, GCT's and Amphenol's, "
        "each a named part of its own."
    ),
    "microSD_Friction_Fit_Common": (
        "J4 on the Thing Plus C5's underside, the microSD socket, PROD_ID "
        "CONN-20948: thirteen pads spanning 10.20 x 6.20 mm, whose footprint's "
        "Datasheet property is Molex's document 1050270001_sd.pdf -- Molex's "
        "105027-0001. KiCad's Connector_Card holds three models, listed "
        "2026-10-08: two Hirose microSD sockets and a nano-SIM, and no Molex "
        "105027."
    ),
    "WS2812_2020": (
        "D2 on the Thing Plus C5, valued WS2812B on a land named for the "
        "2020 package: four 0.7 mm pads spanning 1.83 x 1.10 mm. The "
        "smallest WS2812 in KiCad's LED_SMD is the 3.5 x 3.5 mm "
        "WS2812B-Mini, as for the C6's WS2812-2020."
    ),
    "Push_SMD_4.6x2.8mm_h2.5mm": (
        "SW1 and SW2 on the Thing Plus C5, four pads spanning 4.10 x 1.60 mm "
        "-- the land the C6's EAGLE file names for C&K's KMR2 -- under a name "
        "that states the body, 4.6 x 2.8 mm and 2.5 mm high. KiCad's KMR2 is "
        "4.60 x 2.80 x 1.90 mm, measured 2026-10-08, and this land's own "
        "file links no datasheet: drawing it would be 0.6 mm short of what "
        "the name says. **Every dimension is stated, so this is the OH-153 "
        "kind of absence and not an honest one**: "
        "tools/model_from_datasheet.py reads a body written L x W x H, and "
        "this writes its height as h2.5mm."
    ),
}

#: `ABSENT` entries that hold only for a land from the named vendor library
#: (OH-195). Their package names are KiCad's own, so a board placing KiCad's
#: footprint of that name places another part, and is not refused for this
#: one's reason: PCBCUPID keep their castellated rows in their own library
#: under the names of KiCad's plain headers.
ABSENT_ONLY_FROM: dict[str, str] = {
    "PinHeader_1x05_P2.54mm_Vertical": "Conn_Castellated_Holes_2.54mm",
    "PinHeader_1x09_P2.54mm_Vertical": "Conn_Castellated_Holes_2.54mm",
}


def absent_why(element: eagle.Element) -> str | None:
    """The `ABSENT` reason this placement is not drawn for, or None."""
    only = ABSENT_ONLY_FROM.get(element.package)
    if only is not None and element.library != only:
        return None
    return ABSENT.get(element.package)


@dataclasses.dataclass(frozen=True)
class Composition:
    """A board that is composed rather than fetched, and what it is made of."""

    board: str
    #: The vendor's own layout, under `third_party/`, which is gitignored:
    #: this is a fetched input. An EAGLE `.brd` or a KiCad `.kicad_pcb`, and
    #: `read_layout` picks the reader by suffix -- the only place below this
    #: line that knows which vendor's CAD it came from.
    layout: pathlib.Path
    #: How to fetch it, said in words, because the two are fetched differently
    #: and a missing file should print the command that gets it rather than
    #: the one that gets somebody else's.
    fetch_with: str
    #: The `PCB_SOURCES` key that downloads `layout`, when this tool can do it
    #: itself. `None` for the Arduino Uno, whose board file is an
    #: `https-archive` a person has to accept terms for -- the same reason
    #: `tools/get_board_sources.py` prints its URL rather than fetching it.
    #:
    #: **This is what makes `fetch_with` true rather than circular.** Until it
    #: existed `fetch_pcb` had no caller at all: a missing XIAO layout printed
    #: "Run: python tools/compose_board_3d.py --board XIAO-ESP32-C3-DIP",
    #: which is the command that had just printed it. The C3's file happened
    #: to be on this disk, unzipped by hand, so nothing noticed.
    pcb_chip: str | None
    #: What the model's `geometry` extra says, which the page shows a reader.
    geometry: str
    #: The elements whose pads are the board's pad map. The model is centred on
    #: these, because `webui/static/board3d.js` centres it on the same pads --
    #: and unlike a XIAO, whose castellations are symmetric, an Uno's headers
    #: sit well off the middle of its board.
    headers: tuple[str, ...]
    #: The PCB, in millimetres. EAGLE carries no board thickness, and 1.6 mm is
    #: what `board3d.js` already assumes for every extruded footprint -- so
    #: this is the existing assumption reused, not a new one.
    thickness_mm: float
    #: `#rrggbb`, and where it was read from.
    colour: str
    colour_source: str
    #: The boards this one model serves, when it is more than the one named
    #: above. **Only variants that share the SAME FITTED PARTS may share a
    #: model** (OH-118): a DIP variant hangs two header rows below the board
    #: and an SMD variant does not, so the file that used to serve both was
    #: right for neither -- the SMD boards each compose their own now.
    serves: tuple[str, ...] = ()
    #: True for a DIP variant, whose two seven-pin header rows the published
    #: SMD `.kicad_pcb` does not place -- see `dip_header_elements`, and
    #: OH-118 for the measurement: without them every D-pad on a XIAO DIP
    #: page sat 3.25 to 3.95 mm from the nearest metal, and the pad map is
    #: the vendor's own DIP footprint and is right.
    dip_headers: bool = False
    #: The vendor's file that says which kind of passive each placement is
    #: (OH-187): an EAGLE board's schematic, or a KiCad manifest row's own
    #: board file, whose footprints carry their library, reference, value and
    #: attributes (OH-195). None for the XIAOs, which compose from their
    #: board file alone and read nothing of the kind.
    schematic: pathlib.Path | None = None


#: Where a vendor KiCad project lands. Gitignored with the rest of
#: `third_party/`, and for the sharper of the two reasons: these archives are
#: on Seeed's wiki file server and state no licence at all, exactly as the
#: meshes in `tools/import_3d_model.py` do.
PCB_CACHE = REPO / "third_party" / "seeed-pcb"

#: chip -> (url, bytes). OH-93's survey; every size is a `Content-Length`
#: measured on 2026-08-28 and re-checked on every fetch, because a vendor may
#: replace a file and a board composed from a different revision than these
#: numbers were measured on would be wrong in a way nothing else here catches.
PCB_SOURCES: dict[str, tuple[str, int]] = {
    "ESP32-C3": (
        ("https://files.seeedstudio.com/wiki/XIAO_WiFi/Resources/"
         "XIAO_ESP32C3_v1.3_KiCad_260116.zip"),
        339_671,
    ),
    "ESP32-C6": (
        ("https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32C6/"
         "XIAO_ESP32_C6_v1.0_SCH&PCB_260114.zip"),
        1_126_886,
    ),
    "RP2350": (
        ("https://files.seeedstudio.com/wiki/XIAO-RP2350/res/"
         "XIAO_RP2350_v1.0_SCH&PCB_240626.zip"),
        1_145_969,
    ),
    "nRF54L15": (
        ("https://files.seeedstudio.com/wiki/XIAO_nRF54L15/Getting_Start/"
         "nRF54L15_KICAD.zip"),
        1_305_099,
    ),
    # **Named after the board rather than after its contents**, which is how
    # a survey that classified link text walked past it. OH-108.
    "ESP32-C5": (
        ("https://files.seeedstudio.com/wiki/XIAO_ESP32C5/res/"
         "Seeed_Studio_XIAO_ESP32C5.zip"),
        865_127,
    ),
}


def fetch_pcb(chip: str) -> pathlib.Path:
    """The vendor's `.kicad_pcb` for this chip, downloading it if need be.

    Mirrors `import_3d_model.fetch` deliberately, including the size check: two
    ways of fetching a vendor archive would be two things to keep true.
    """
    import zipfile

    out = PCB_CACHE / f"{chip}.kicad_pcb"
    if out.is_file():
        return out
    url, size = PCB_SOURCES[chip]
    PCB_CACHE.mkdir(parents=True, exist_ok=True)
    archive = PCB_CACHE / f"{chip}.zip"
    if not archive.is_file():
        print(f"  fetch  {url}")
        with urllib.request.urlopen(url) as response:  # noqa: S310 - https, fixed
            archive.write_bytes(response.read())
    actual = archive.stat().st_size
    if actual != size:
        raise SystemExit(
            f"{archive} is {actual:,} bytes and this file records {size:,}. "
            f"The vendor's archive changed; re-measure before trusting a "
            f"board composed from it."
        )
    with zipfile.ZipFile(archive) as zipped:
        inside = [n for n in zipped.namelist() if n.endswith(".kicad_pcb")]
        if len(inside) != 1:
            raise SystemExit(
                f"{archive} holds {len(inside)} .kicad_pcb files and this "
                f"expects exactly one: {inside}"
            )
        out.write_bytes(zipped.read(inside[0]))
    return out


COMPOSITIONS: tuple[Composition, ...] = (
    Composition(
        board="Arduino Uno",
        layout=REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd",
        fetch_with="python tools/get_board_sources.py arduino-uno",
        pcb_chip=None,
        geometry=(
            "Arduino's own EAGLE board file, CC BY-SA 4.0: the outline "
            "from layer 20 and every component's position, rotation and "
            "mirror as the file states them"
        ),
        headers=("IOH", "IOL", "POWER", "AD"),
        thickness_mm=1.6,
        colour="#313d63",
        colour_source=(
            "PICSimLab's share/boards/Arduino Uno/board.svg, where it fills "
            "the board-body path -- whose own path data is this same "
            "silhouette, which is what makes it the board's colour rather "
            "than one that happens to be in the drawing"
        ),
        # Arduino's schematic, from the same CAD zip as the board file: what
        # says which kind of passive each placement is (OH-191).
        schematic=REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.sch",
    ),
    Composition(
        board="XIAO-ESP32-C3-DIP",
        layout=PCB_CACHE / "ESP32-C3.kicad_pcb",
        fetch_with="python tools/compose_board_3d.py --board XIAO-ESP32-C3-DIP",
        pcb_chip="ESP32-C3",
        geometry=(
            "Seeed's own KiCad project for the XIAO ESP32-C3 v1.3: the "
            "outline from Edge.Cuts and every component's position, rotation "
            "and side as the board file states them. Seeed publishes no mesh "
            "for this board -- see docs/research/board-models/"
        ),
        headers=("J1", "J2"),
        # Seeed's own board file says 1.0 mm nowhere this reads, and the XIAO
        # is a 1.2 mm board by the RP2040 model's own PCB solid (0.00..1.20 in
        # its extras). Reused rather than invented: the sibling the vendor DID
        # publish a mesh of is the best evidence for a board of this family.
        thickness_mm=1.2,
        colour=BOARD_MASK,
        colour_source=(
            "BOARD_MASK, and it is A JUDGEMENT rather than a reading -- see "
            "that constant, which records the four places searched for a "
            "stated colour and found none: Seeed's STEP files (the PCB is "
            "UNSTYLED), their .kicad_pro (pcb_color has alpha 0, which is "
            "KiCad's unset), the .kicad_pcb (no stackup), and their wiki (no "
            "mention of a colour at all). The nine XIAOs with published "
            "meshes take the same constant on their own PCB solid, so all ten "
            "agree"
        ),
        serves=("XIAO-ESP32-C3-DIP-SMD",),
        dip_headers=True,
    ),
    # --- OH-93 5.1: the three XIAOs Seeed publish a PCB and no mesh for -----
    #
    # **Everything below the board name is the same on all three**, and that
    # is a measurement rather than a copy: their `MOUDLE14P-XIAO-HALF-HOLE`
    # footprint puts 56 pads on the identical 15.240 x 17.780 mm lattice the
    # C3 builds its two headers on, and all four outlines measure
    # 20.955 x 17.780 mm. A XIAO is a XIAO.
    Composition(
        board="XIAO-ESP32-C6-DIP",
        layout=PCB_CACHE / "ESP32-C6.kicad_pcb",
        fetch_with="python tools/compose_board_3d.py --board XIAO-ESP32-C6-DIP",
        pcb_chip="ESP32-C6",
        geometry=(
            "Seeed's own KiCad project for the XIAO ESP32-C6 v1.0: the "
            "outline from Edge.Cuts and every component's position, rotation "
            "and side as the board file states them. Seeed publishes no mesh "
            "for this board -- see docs/research/board-models/"
        ),
        # One footprint, not two: where the C3 draws its castellations as
        # J1 and J2, these three draw all fourteen as the single module
        # footprint the board outline is also inside.
        headers=("U2",),
        thickness_mm=1.2,
        colour=BOARD_MASK,
        colour_source=(
            "BOARD_MASK, A JUDGEMENT rather than a reading -- see that "
            "constant. This board's own .kicad_pcb has no (stackup ...) "
            "either, so it adds nothing to the four searches recorded there"
        ),
        dip_headers=True,
    ),
    Composition(
        board="XIAO-RP2350-DIP",
        layout=PCB_CACHE / "RP2350.kicad_pcb",
        fetch_with="python tools/compose_board_3d.py --board XIAO-RP2350-DIP",
        pcb_chip="RP2350",
        geometry=(
            "Seeed's own KiCad project for the XIAO RP2350 v1.0: the outline "
            "from Edge.Cuts and every component's position, rotation and side "
            "as the board file states them. Seeed publishes no mesh for this "
            "board -- see docs/research/board-models/"
        ),
        headers=("U2",),
        thickness_mm=1.2,
        colour=BOARD_MASK,
        colour_source=(
            "BOARD_MASK, A JUDGEMENT rather than a reading -- see that "
            "constant. This board's own .kicad_pcb has no (stackup ...) "
            "either, so it adds nothing to the four searches recorded there"
        ),
        dip_headers=True,
    ),
    Composition(
        board="XIAO-ESP32-C5-DIP",
        layout=PCB_CACHE / "ESP32-C5.kicad_pcb",
        fetch_with="python tools/compose_board_3d.py --board XIAO-ESP32-C5-DIP",
        pcb_chip="ESP32-C5",
        geometry=(
            "Seeed's own KiCad project for the XIAO ESP32-C5 v1.1: the "
            "outline from Edge.Cuts and every component's position, rotation "
            "and side as the board file states them. Seeed publishes no mesh "
            "for this board -- see docs/research/board-models/"
        ),
        headers=("U9",),
        thickness_mm=1.2,
        colour=BOARD_MASK,
        colour_source=(
            "BOARD_MASK, A JUDGEMENT rather than a reading -- see that "
            "constant. This board's own .kicad_pcb has no (stackup ...) "
            "either, so it adds nothing to the four searches recorded there"
        ),
        dip_headers=True,
    ),
    Composition(
        board="XIAO-nRF54l15-DIP",
        layout=PCB_CACHE / "nRF54L15.kicad_pcb",
        fetch_with="python tools/compose_board_3d.py --board XIAO-nRF54l15-DIP",
        pcb_chip="nRF54L15",
        geometry=(
            "Seeed's own KiCad project for the XIAO nRF54L15 v1.0: the "
            "outline from Edge.Cuts and every component's position, rotation "
            "and side as the board file states them. Seeed publishes no mesh "
            "for this board -- see docs/research/board-models/"
        ),
        # `MOUDLE14P-XIAO-HALF-HOLE-PRO`, and the reference moved with it.
        headers=("U9",),
        thickness_mm=1.2,
        colour=BOARD_MASK,
        colour_source=(
            "BOARD_MASK, A JUDGEMENT rather than a reading -- see that "
            "constant. This board's own .kicad_pcb has no (stackup ...) "
            "either, so it adds nothing to the four searches recorded there"
        ),
        dip_headers=True,
    ),
)

#: **The SMD variants, derived rather than written out** (OH-118). Each is
#: its DIP sibling's PCB composed WITHOUT the two header rows the DIP hangs
#: below the board -- which is the whole difference between the variants, and
#: is why they stopped sharing one file: a model that served both was right
#: for neither. `dataclasses.replace` keeps every other field identical by
#: construction, so the two cannot drift apart.
COMPOSITIONS = COMPOSITIONS + tuple(
    dataclasses.replace(
        spec,
        board=spec.board.replace("-DIP", "-SMD"),
        fetch_with=spec.fetch_with.replace("-DIP", "-SMD"),
        serves=(),
        dip_headers=False,
    )
    for spec in COMPOSITIONS if spec.dip_headers
)


# --- the manifest boards, composed from their rows (OH-180) -------------------
#
# **A row in tools/board_manifest.py already names everything a composition
# needs except two numbers**: the vendor's board file; the elements whose pads
# are the pad map, which the model is centred on, so the two agree by
# construction; and the registry source, which says who the vendor is, under
# what licence, and how the file is fetched. So a row is composed without a
# second hand-written entry, and only what a row does not carry is below.

#: The thickness of a manifest board whose files state none, and it is the
#: Arduino Uno's reasoning reused: 1.6 mm is what `board3d.js` assumes for
#: every extruded footprint. An EAGLE file's design rules carry a layer stack,
#: and where it is the one the Uno's own file carries it states nothing -- see
#: `test_a_manifest_boards_thickness_is_its_own_note_or_the_unos_stack`.
MANIFEST_THICKNESS_MM = 1.6

#: A `MANIFEST_STATED` colour that is not typed in: `manifest_composition`
#: reads it out of the board file with `preview_mask`. Left as this string
#: -- which is not a colour and cannot be drawn -- only while the board file
#: is not fetched, when `compose` refuses the board before any colour is used.
FROM_PREVIEW = "the board file's own manufacturing preview, not yet read"

#: What a manifest board's own files DO state that its row does not carry.
#: A board with no entry takes `MANIFEST_THICKNESS_MM` and `BOARD_MASK`, and
#: says on the page that the colour is a judgement. Every number in these
#: entries is read back out of the board file by
#: `test_a_manifest_boards_colour_is_read_where_its_file_states_one`.
MANIFEST_STATED: dict[str, dict[str, object]] = {
    "SparkFun Thing Plus ESP32-C6": {
        # The note on layer 51 in the board file's own <plain> section reads
        # "Board thickness: 1.6mm" as well as "Soldermask: Red".
        "thickness_mm": 1.6,
        "colour": FROM_PREVIEW,
        "colour_source": (
            "SparkFun's own board file, which states it twice: a note on its "
            "tDocu layer reading 'Soldermask: Red', and a manufacturing-"
            "preview solder mask of 0xC8FF0000 -- red at alpha 200/255. "
            "Drawn, A JUDGEMENT, the way that preview draws mask over bare "
            "laminate: 0xFF0000 at that alpha over the file's own substrate "
            "colour, 0x786E46, which `preview_mask` computes from those "
            "numbers. That 0xC8FF0000 is a choice rather than a default is "
            "a judgement too: the Arduino Uno's file carries 0xC8008000 under "
            "a board this table draws navy, and that is taken for the value "
            "EAGLE leaves when nobody sets one"
        ),
    },
    "SparkFun Pro Micro ESP32-C3": {
        # Its layer-51 note reads "Board thickness: 0.8mm" and "Soldermask:
        # Red": half the Thing Plus's board, the same red named.
        "thickness_mm": 0.8,
        "colour": FROM_PREVIEW,
        "colour_source": (
            "SparkFun's own board file, which states it twice: a note on its "
            "tDocu layer reading 'Soldermask: Red', and a manufacturing-"
            "preview solder mask of 0xC8AA0000 -- a darker red, 0xAA0000, at "
            "alpha 200/255. Drawn, A JUDGEMENT, the way that preview draws "
            "mask over bare laminate: 0xAA0000 at that alpha over the file's "
            "own substrate colour, 0x786E46, which `preview_mask` computes "
            "from those numbers. That 0xC8AA0000 is a choice rather than a "
            "default is a judgement too: the Arduino Uno's file carries "
            "0xC8008000 under a board this table draws navy, and that is "
            "taken for the value EAGLE leaves when nobody sets one"
        ),
    },
    "SparkFun Qwiic Pocket ESP32-C6": {
        # Its layer-51 note reads "Board thickness: 1.6mm" and "Soldermask:
        # Red".
        "thickness_mm": 1.6,
        "colour": FROM_PREVIEW,
        "colour_source": (
            "SparkFun's own board file, which states it twice: a note on its "
            "tDocu layer reading 'Soldermask: Red', and a manufacturing-"
            "preview solder mask of 0xC8FF0000 -- 0xFF0000 at alpha 200/255. "
            "Drawn, A JUDGEMENT, the way that preview draws mask over bare "
            "laminate: 0xFF0000 at that alpha over the file's own substrate "
            "colour, 0x786E46, which `preview_mask` computes from those "
            "numbers. That 0xC8FF0000 is a choice rather than a default is "
            "a judgement too: the Arduino Uno's file carries 0xC8008000 under "
            "a board this table draws navy, and that is taken for the value "
            "EAGLE leaves when nobody sets one"
        ),
    },
}


def preview_mask(layout: pathlib.Path) -> str:
    """The solder mask an EAGLE file's manufacturing preview draws over bare
    laminate, as `#rrggbb`.

    EAGLE writes each preview colour as ARGB. The mask is drawn at its own
    alpha over the file's `substratecolor`, and this is that blend, done on
    the file's own numbers -- the reading is the file's, the idea that the
    preview is what the board looks like is a judgement (`MANIFEST_STATED`).
    """
    colours = {node.get("name"): node.get("color")
               for node in eagle._open(layout, "board").iter("mfgpreviewcolor")}
    mask, laminate = colours["soldermaskcolor"], colours["substratecolor"]
    alpha = int(mask[2:4], 16) / 255
    return "#" + "".join(
        f"{round(int(mask[at:at + 2], 16) * alpha + int(laminate[at:at + 2], 16) * (1 - alpha)):02x}"
        for at in (4, 6, 8))


#: The solder-mask colours KiCad's own 3D view draws a stackup's mask name
#: in, and the alpha it lays each at: `g_MaskColors` in
#: 3d-viewer/3d_canvas/board_adapter.cpp, lines 169-184 at commit
#: 3ff0b3cc57dd043ac6b159611d85a01374df7a88 (OH-195), red, green and blue
#: out of 255 copied as written there. The view looks the name up in exactly
#: this list (lines 655-694 of that file). **Not `gbrjobColors`** in
#: pcbnew/board_stackup_manager/stackup_predefined_prms.cpp, which this table
#: held until OH-195's review: a Gerber job file writes the colour's name,
#: not those numbers, and that list's "Green" is 60, 150, 80 where the 3D
#: view's is 20, 51, 36 at 0.83. A board file stating its mask as `#rrggbb`
#: or `#rrggbbaa` is drawn from that instead.
KICAD_MASK_COLOURS: dict[str, tuple[tuple[int, int, int], float]] = {
    "Green": ((20, 51, 36), 0.83),
    "Light Green": ((91, 168, 12), 0.83),
    "Saturated Green": ((13, 104, 11), 0.83),
    "Red": ((181, 19, 21), 0.83),
    "Light Red": ((210, 40, 14), 0.83),
    "Red/Orange": ((239, 53, 41), 0.83),
    "Blue": ((2, 59, 162), 0.83),
    "Light Blue 1": ((54, 79, 116), 0.83),
    "Light Blue 2": ((61, 85, 130), 0.83),
    "Green/Blue": ((21, 70, 80), 0.83),
    "Black": ((11, 11, 11), 0.83),
    "White": ((245, 245, 245), 0.83),
    "Purple": ((32, 2, 53), 0.83),
    "Light Purple": ((119, 31, 91), 0.83),
    "Yellow": ((194, 195, 0), 0.83),
}

#: The board-body colours the same view draws a stackup's dielectric name
#: in: `g_BoardColors`, lines 195-203 of the same file at the same commit,
#: red, green and blue copied as written there. What a KiCad row's mask is
#: laid over, as an EAGLE row's is laid over its file's `substratecolor`
#: (`preview_mask`); the substrate is drawn opaque, as EAGLE's is, so the
#: alpha the view gives each is not carried.
KICAD_BOARD_COLOURS: dict[str, tuple[int, int, int]] = {
    "FR4 natural, dark": (51, 43, 22),
    "FR4 natural": (109, 116, 75),
    "PTFE natural": (252, 252, 250),
    "Polyimide": (205, 130, 0),
    "Phenolic natural": (92, 17, 6),
    "Brown 1": (146, 99, 47),
    "Brown 2": (160, 123, 54),
    "Brown 3": (146, 99, 47),
    "Aluminum": (213, 213, 213),
}


def kicad_stackup(layout: pathlib.Path) -> tuple[
        str | None, float | None, float | None, tuple[str, ...]]:
    """What a `.kicad_pcb` states of its board: the top solder mask's colour,
    the sum of its stackup's layer thicknesses, and its `(general
    (thickness))` -- each None where the file does not state it -- and the
    colour each dielectric layer names, in order, where it names one."""
    tree = kicad.parse_sexp(layout.read_text(encoding="utf-8"))

    def millimetres(node: list, where: str) -> float:
        try:
            return float(node[1])
        except ValueError as exc:
            raise ValueError(
                f"{layout}: {where} states its thickness as {node[1]!r}, "
                f"which is not a number of millimetres") from exc

    general = kicad.first(tree, "general")
    thickness = kicad.first(general, "thickness") if general else None
    setup = kicad.first(tree, "setup")
    stack = kicad.first(setup, "stackup") if setup else None
    mask, total, core = None, None, []
    for layer in (kicad.children(stack, "layer") if stack else ()):
        colour, height = kicad.first(layer, "color"), kicad.first(layer, "thickness")
        if layer[1] == "F.Mask" and colour:
            mask = colour[1]
        if layer[1].startswith("dielectric") and colour:
            core.append(colour[1])
        if height:
            total = (total or 0.0) + millimetres(
                height, f"its stackup's layer {layer[1]!r}")
    return (mask, total,
            millimetres(thickness, "(general)") if thickness else None,
            tuple(core))


def _kicad_manifest_composition(entry: board_manifest.Row, source,
                                layout: pathlib.Path) -> Composition:
    """A KiCad manifest row (OH-195): the stackup's own mask and thickness,
    and the board file itself for what each footprint is."""
    mask, stack, general, core = (kicad_stackup(layout) if layout.is_file()
                                  else (None, None, None, ()))
    if stack is not None and general is not None and abs(stack - general) < 5e-4:
        # Two statements that agree decide, and the one written as a number
        # is taken, since the stackup's is a sum of floats.
        thickness = general
    else:
        # KiCad writes `(general (thickness))` for every board, 1.6 unless
        # somebody changed it, so without a stackup that adds up to it the
        # number is a default as often as a statement: the Uno's reused.
        thickness = MANIFEST_THICKNESS_MM
    # **What the mask is laid over**: the dielectric's own colour where the
    # stackup names one KiCad's view knows, and KiCad's FR4 otherwise.
    if len(set(core)) == 1 and core[0] in KICAD_BOARD_COLOURS:
        substrate = KICAD_BOARD_COLOURS[core[0]]
        beneath = (f"the {core[0]!r} its stackup names for its dielectric, "
                   f"which that view draws as rgb {', '.join(map(str, substrate))}")
    else:
        substrate = KICAD_BOARD_COLOURS["FR4 natural"]
        beneath = (f"KiCad's own 'FR4 natural', rgb "
                   f"{', '.join(map(str, substrate))} -- A JUDGEMENT too: its "
                   f"stackup names "
                   + (f"{', '.join(map(repr, core))} for its dielectric "
                      f"layers, which is not one colour that view names"
                      if core else "no colour for its dielectric"))
    if mask in KICAD_MASK_COLOURS:
        rgb, alpha = KICAD_MASK_COLOURS[mask]
        said = (f"as {mask!r}, which KiCad's own 3D view draws as rgb "
                f"{', '.join(map(str, rgb))} at alpha {alpha} "
                f"(KICAD_MASK_COLOURS, its g_MaskColors)")
    elif mask is not None and re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", mask):
        # KiCad reads `#rrggbbaa` as red, green, blue and alpha, and a
        # `#rrggbb` as opaque (COLOR4D::SetFromHexString).
        rgb = tuple(int(mask[at:at + 2], 16) for at in (1, 3, 5))
        alpha = int(mask[7:9], 16) / 255 if len(mask) == 9 else 1.0
        said = (f"as {mask}: rgb {', '.join(map(str, rgb))} at alpha "
                + (f"{int(mask[7:9], 16)}/255" if len(mask) == 9 else "1, opaque"))
    else:
        rgb = None
    if rgb is not None:
        # The EAGLE rows' blend (`preview_mask`), on KiCad's numbers.
        colour = "#" + "".join(
            f"{round(over * alpha + under * (1 - alpha)):02x}"
            for over, under in zip(rgb, substrate))
        colour_source = (
            f"{source.vendor}'s own board file, whose stackup states its top "
            f"solder mask {said}. Drawn, A JUDGEMENT, as KiCad's own 3D view "
            f"lays a mask over the board: at that alpha over {beneath}. "
            f"That is {colour}")
    elif mask is None:
        colour = BOARD_MASK
        colour_source = (
            "BOARD_MASK, A JUDGEMENT rather than a reading: the board file's "
            "stackup names no colour for its top solder mask")
    else:
        colour = BOARD_MASK
        colour_source = (
            f"BOARD_MASK, A JUDGEMENT rather than a reading: the board file's "
            f"stackup names its top solder mask {mask!r}, which is neither a "
            f"name KiCad's own 3D view draws (KICAD_MASK_COLOURS) nor "
            f"#rrggbb or #rrggbbaa")
    return Composition(
        board=entry.board,
        layout=layout,
        fetch_with=f"python tools/get_board_sources.py {entry.source}",
        pcb_chip=None,
        geometry=(
            f"{source.vendor}'s own board file, "
            f"{pathlib.PurePosixPath(entry.cad).name}, {source.licence.name}: "
            f"the outline and every component's position, rotation and "
            f"side as the file states them"
        ),
        headers=entry.select,
        thickness_mm=thickness,
        colour=colour,
        colour_source=colour_source,
        schematic=layout,
    )


def manifest_composition(entry: board_manifest.Row) -> Composition:
    """A `tools/board_manifest.py` row, as the composition it describes.

    **An EAGLE or a KiCad row**, and refused by name otherwise. Each states
    its colour, its thickness and its parts its own way: an EAGLE file in
    its manufacturing preview, its notes and its schematic, a KiCad file in
    its `(stackup ...)` and its footprints (OH-195). Composing one with the
    other's readings would put an EAGLE sentence on a KiCad board.
    """
    suffix = pathlib.PurePosixPath(entry.cad).suffix.lower()
    if suffix not in (".brd", ".kicad_pcb"):
        raise ValueError(
            f"{entry.board}: composition from a {suffix} manifest row is not "
            f"supported -- its colour, thickness and parts are read from "
            f"EAGLE's or KiCad's own fields, which a {suffix} does not have"
        )
    source = board_sources.source(entry.source)
    if suffix == ".kicad_pcb":
        return _kicad_manifest_composition(entry, source,
                                           board_manifest.cad_path(entry))
    stated = MANIFEST_STATED.get(entry.board, {})
    layout = board_manifest.cad_path(entry)
    colour = stated.get("colour", BOARD_MASK)
    if colour == FROM_PREVIEW and layout.is_file():
        colour = preview_mask(layout)
    return Composition(
        board=entry.board,
        layout=layout,
        fetch_with=f"python tools/get_board_sources.py {entry.source}",
        pcb_chip=None,
        geometry=(
            f"{source.vendor}'s own board file, "
            f"{pathlib.PurePosixPath(entry.cad).name}, {source.licence.name}: "
            f"the outline and every component's position, rotation and "
            f"mirror as the file states them"
        ),
        headers=entry.select,
        thickness_mm=stated.get("thickness_mm", MANIFEST_THICKNESS_MM),
        colour=colour,
        colour_source=stated.get("colour_source", (
            "BOARD_MASK, A JUDGEMENT rather than a reading: the board file's "
            "manufacturing-preview solder mask is 0xC8008000, which the "
            "Arduino Uno's own file also carries under a board this table "
            "draws navy -- taken, a judgement too, for the value EAGLE "
            "leaves when nobody sets one rather than a statement"
        )),
        schematic=source.dest(REPO) / entry.schematic,
    )


def manifest_compositions(rows) -> tuple[tuple[Composition, ...], dict[str, str]]:
    """Every row's composition, and each row refused with its reason."""
    made: list[Composition] = []
    refused: dict[str, str] = {}
    for entry in rows:
        try:
            made.append(manifest_composition(entry))
        except ValueError as exc:
            refused[entry.board] = str(exc)
    return tuple(made), refused


#: Manifest rows that are NOT composed, and why -- printed by `main`, so a
#: row that draws its footprint says so rather than going quiet.
_MANIFEST, MANIFEST_REFUSED = manifest_compositions(board_manifest.ROWS)
COMPOSITIONS = COMPOSITIONS + _MANIFEST



#: How far a mesh's footprint may sit from the pads it is supposed to stand on
#: before the mapping is refused. Generous, because a package's pads and its
#: body are legitimately different sizes -- a DIP's body is narrower than its
#: rows and a header's shroud is wider than its pins. What this catches is a
#: model of the wrong SIZE of the right kind of part, which is the mistake a
#: name-based table actually makes.
SPAN_TOLERANCE_MM = 3.0

#: KiCad's own convention, and the frame every component mesh arrives in.
PART_UP = 2

#: Where `tools/model_from_datasheet.py` leaves the parts it builds.
MODELLED = REPO / "third_party" / "modelled"


# --- a KiCad board, presented as the one this already composes -----------------
#
# **An adapter, and deliberately not a mode.** `compose` needs a board with an
# outline and placed elements; `tools/eagle.py` produces one from a `.brd` and
# this produces the same one from a `.kicad_pcb`. Nothing below the reader
# learns which vendor's CAD it came from, so there is no `if kicad:` anywhere
# in the composing, the confirming or the placing -- which is what
# `.claude/CLAUDE.md` rule 7 asks for when a second caller wants the same
# behaviour from a different source.
#
# OH-93's survey is why this exists: Seeed publishes no mesh for six of the
# eight unmodelled chips but does publish the vendor KiCad project, which is
# the same class of source as the Arduino EAGLE file the Uno is built from.

#: How finely an outline arc is chopped, in millimetres of chord.
#:
#: A XIAO's corner radius is about 1.5 mm, so 0.2 mm of chord puts roughly
#: eleven segments on a quarter turn -- under a tenth of a degree of visible
#: faceting at the size a 21 mm board is drawn, and far below the 0.05 mm
#: `DEFLECTION` every component mesh is tessellated to. The outline is
#: extruded once into a slab, so this costs almost nothing.
ARC_CHORD_MM = 0.2


def arc_points(arc: kicad.Arc, chord: float = ARC_CHORD_MM
               ) -> list[tuple[float, float]]:
    """The points of one KiCad arc, start to end, through its middle.

    **KiCad stores three points on the curve and not a centre**, so the centre
    is solved for: it is where the perpendicular bisectors of the two chords
    meet. Three collinear points have no centre, and that is a straight line
    rather than an error -- a board outline may legitimately carry a
    zero-bulge arc, and refusing it would refuse the board.
    """
    (x1, y1), (xm, ym), (x2, y2) = ((arc.x1_mm, arc.y1_mm),
                                    (arc.xm_mm, arc.ym_mm),
                                    (arc.x2_mm, arc.y2_mm))
    # Twice the signed area of the triangle; zero when the three are collinear.
    twice_area = 2 * ((xm - x1) * (y2 - y1) - (ym - y1) * (x2 - x1))
    if abs(twice_area) < 1e-12:
        return [(x1, y1), (x2, y2)]

    first = x1 * x1 + y1 * y1
    middle = xm * xm + ym * ym
    last = x2 * x2 + y2 * y2
    cx = (first * (ym - y2) + middle * (y2 - y1) + last * (y1 - ym)) / twice_area
    cy = (first * (x2 - xm) + middle * (x1 - x2) + last * (xm - x1)) / twice_area
    radius = math.hypot(x1 - cx, y1 - cy)

    # **The centre is equidistant from all three points or it is not the
    # centre**, and this is the check that names the failure instead of
    # letting it draw. Both numerators above were sign-flipped in the first
    # version: the centre came out NEGATED, which for a board at x = 140 mm
    # put it 360 mm away, turned a 90-degree corner into a 359.99-degree
    # sweep, and produced an outline of 67,569 segments spanning 746 mm. The
    # only local symptom was that the three radii disagreed in the fourth
    # decimal place -- so that disagreement is what is tested for.
    spread = max(abs(math.hypot(px - cx, py - cy) - radius)
                 for px, py in ((xm, ym), (x2, y2)))
    if spread > 1e-6 * max(radius, 1.0):
        raise ValueError(
            f"arc ({x1}, {y1}) -> ({x2}, {y2}) via ({xm}, {ym}): the solved "
            f"centre ({cx:.4f}, {cy:.4f}) is {spread:.6f} mm from being "
            f"equidistant, so it is not the centre of any circle through them"
        )

    start = math.atan2(y1 - cy, x1 - cx)
    through = math.atan2(ym - cy, xm - cx)
    end = math.atan2(y2 - cy, x2 - cx)

    # Go the way that passes through the middle point. Taking the short way
    # round without checking draws the complement of a reflex arc, which on a
    # rounded corner is a three-quarter circle bitten out of the board.
    def forward(a: float, b: float) -> float:
        return (b - a) % (2 * math.pi)

    sweep = forward(start, end)
    if forward(start, through) > sweep:
        sweep -= 2 * math.pi

    steps = max(2, math.ceil(abs(sweep) * radius / chord))
    return [(cx + radius * math.cos(start + sweep * step / steps),
             cy + radius * math.sin(start + sweep * step / steps))
            for step in range(steps + 1)]


def from_kicad(path: pathlib.Path) -> eagle.Board:
    """One `.kicad_pcb`, as the `eagle.Board` the composer already consumes.

    **The one thing that is not bookkeeping is the sign of Y.** KiCad measures
    down the page and `eagle.Pad` is documented as the board's space with Y
    UPWARD, so every coordinate is negated on the way through. Getting this
    wrong mirrors the whole board -- which draws perfectly, has the right
    outline and the right parts, and puts pin 1 at the opposite corner.

    Rotation survives unchanged, and that is the same fact rather than an
    inconsistency: KiCad's positive rotation is counter-clockwise *as drawn*,
    and flipping Y turns its down-the-page frame into the up-the-page one the
    composer uses, where counter-clockwise means the same thing.
    """
    board = kicad.read_board(path)

    outline: list[eagle.Segment] = []
    for seg in board.outline:
        outline.append(eagle.Segment("Dimension", seg.x1_mm, -seg.y1_mm,
                                     seg.x2_mm, -seg.y2_mm))
    for arc in board.arcs:
        points = arc_points(arc)
        for (ax, ay), (bx, by) in itertools.pairwise(points):
            outline.append(eagle.Segment("Dimension", ax, -ay, bx, -by))

    elements: list[eagle.Element] = []
    for placed in board.placements:
        turn = math.radians(placed.rotation_deg)
        cos, sin = math.cos(turn), math.sin(turn)
        pads: list[eagle.Pad] = []
        for pad in placed.pads:
            # Into the Y-up frame first, then rotated in it, then placed --
            # and **never mirrored, on either side of the board** (OH-195,
            # after OH-182): KiCad stores a flipped footprint's pads already
            # flipped, so `kicad.pad_on_board` places them turned and moved
            # only. Mirroring an underside pad again put it on the far side
            # of its footprint's centre line, which no XIAO showed only
            # because every underside pad on one sits on that line.
            local_x, local_y = pad.x_mm, -pad.y_mm
            pads.append(eagle.Pad(
                number=pad.number,
                # `eagle.Pad.kind` uses this module's vocabulary, which IS
                # KiCad's, so nothing is translated here -- except that a
                # `np_thru_hole` is a mounting slot and not a contact.
                kind="thru_hole" if pad.kind == "thru_hole" else "smd",
                x_mm=placed.x_mm + local_x * cos - local_y * sin,
                y_mm=-placed.y_mm + local_x * sin + local_y * cos,
                width_mm=pad.width_mm,
                height_mm=pad.height_mm,
                net=None,
                shape=pad.shape,
                # **The stored angle is already the board's**, not the
                # footprint's -- measured on the RP2350, where every pad of
                # every footprint placed at 90 degrees says 90. So the
                # placement's own rotation is NOT added here; it is already
                # in. What the frames do to it: flipping y turns KiCad's
                # down-the-page rotation into this one's up-the-page rotation
                # of the same sign -- on the underside too, whose pads are
                # stored flipped already.
                rotation_deg=pad.rotation_deg,
                front=pad.front,
                back=pad.back,
            ))
        # **The body outline, which is what makes `silk_miss` able to run.**
        # KiCad names its assembly layer, so this is `F.Fab` rather than the
        # silkscreen EAGLE mixes it in with -- and it arrives in the local
        # frame `silk_miss` expects, y negated like every pad above it and the
        # mirror left to `eagle.place`, which applies it from the spelling.
        #
        # Until this existed the field defaulted to `None` on every KiCad
        # element, so the one check that can see a part turned 180 degrees
        # returned `None` for all nine composed XIAO boards and said nothing.
        body = placed.body
        silk = None if body is None else (body[0], -body[3], body[2], -body[1])
        # The pin-1 marker crosses the same way and for the same reason: it is
        # a coordinate in the footprint's own frame, so only its y is negated.
        mark = None if placed.mark is None else (placed.mark[0], -placed.mark[1])
        rotation = placed.rotation_deg
        if placed.back:
            # **An underside footprint, in the frame `place` and `mark_of`
            # expect** (OH-195). KiCad flips a footprint onto the back top to
            # bottom -- its stored pads are the library's with y negated, as
            # QFN-56 pad 1 at (-3.4375, 2.6) against the library's
            # (-3.4375, -2.6) shows -- and stores them flipped. So what the
            # file holds, read in this module's y-up frame, is the library's
            # own geometry with no negation at all; and a flip top to bottom
            # is `eagle.place`'s mirror in x turned half round. Hence the
            # outline and the marker cross unnegated, and the element turns
            # 180 degrees further, which is what puts a model the way the
            # file's own pads and marker already lie.
            silk = None if body is None else body
            mark = placed.mark
            rotation = (placed.rotation_deg + 180.0) % 360.0

        elements.append(eagle.Element(
            name=placed.reference or placed.library,
            library=placed.library.split(":", 1)[0],
            package=placed.name,
            pads=tuple(pads),
            x_mm=placed.x_mm,
            y_mm=-placed.y_mm,
            rotation=rotation,
            mirrored=placed.back,
            silk=silk,
            mark=mark,
            # The vendor's words for the part, beside its land's name, which
            # `contradiction` holds a row to as it does an EAGLE element's
            # (OH-195): PCBCUPID place the Glyph C3's ESP32-C3-MINI-1 on a
            # land named for the H2's, and only the value says C3.
            value=placed.value or None,
        ))

    # The ink, y negated like every coordinate above it and for the same
    # reason. A stroke's WIDTH is a length rather than a coordinate, so it
    # crosses unchanged -- getting that wrong would be invisible, since the
    # boards' widths are all positive.
    silk = tuple(eagle.Stroke(s.layer, s.x1_mm, -s.y1_mm, s.x2_mm, -s.y2_mm,
                              s.width_mm)
                 for s in board.silk)
    # The routed copper crosses the same way, and its curves are flattened
    # here rather than in the reader: solving an arc's centre from three
    # points is `arc_points`, which the outline already needs.
    traces = [eagle.Stroke(t.layer, t.x1_mm, -t.y1_mm, t.x2_mm, -t.y2_mm,
                           t.width_mm)
              for t in board.traces]
    for curve in board.trace_arcs:
        points = arc_points(curve)
        for (ax, ay), (bx, by) in itertools.pairwise(points):
            traces.append(eagle.Stroke(curve.layer, ax, -ay, bx, -by,
                                       curve.width_mm))
    vias = tuple(eagle.Via(v.x_mm, -v.y_mm, v.diameter_mm) for v in board.vias)
    return eagle.Board(name=path.stem, version="kicad_pcb",
                       elements=tuple(elements), outline=tuple(outline),
                       silk=silk, silk_unread=board.silk_unread,
                       traces=tuple(traces), vias=vias,
                       traces_unread=board.traces_unread)


def read_layout(path: pathlib.Path) -> eagle.Board:
    """Whichever vendor CAD this is, as one board. Chosen by suffix."""
    if path.suffix == ".kicad_pcb":
        return from_kicad(path)
    return eagle.read_board(path)


def contours(segments: tuple[eagle.Segment, ...]) -> list[list[tuple[float, float]]]:
    """Chain drawn segments into every closed ring they form.

    EAGLE and KiCad both write an outline in no particular order and no
    particular direction, so this walks from an end to whichever segment
    shares it. It **refuses a ring that does not close** rather than joining
    the ends, because a board outline with a gap is a board this cannot
    describe and a silently-closed polygon is a plausible wrong shape.

    **More than one ring is normal and was not, until OH-93.** The Arduino Uno
    draws a single silhouette. Seeed's XIAO ESP32-C3 draws its outer edge and
    two 0.76 x 0.51 mm rounded slots inside it, and `loop`'s single-ring
    assumption reported that as "the outline does not chain: 74 segments left"
    -- which reads like a parse failure and is a correct parse of a shape it
    could not hold.
    """
    if not segments:
        raise ValueError("no outline segments")
    remaining = [((s.x1_mm, s.y1_mm), (s.x2_mm, s.y2_mm)) for s in segments]
    rings: list[list[tuple[float, float]]] = []
    while remaining:
        start, here = remaining.pop(0)
        ring = [start, here]
        while not _near(ring[0], here):
            for index, (a, b) in enumerate(remaining):
                if _near(a, here):
                    here = b
                elif _near(b, here):
                    here = a
                else:
                    continue
                remaining.pop(index)
                ring.append(here)
                break
            else:
                # **Two different failures, and they are kept apart.** A
                # segment that touches nothing is a gap in the drawing; a
                # chain that simply runs out is a shape that encloses nothing.
                # One message for both passes with either guard deleted, which
                # a mutation found once already -- see the two tests above.
                if remaining:
                    raise ValueError(
                        f"the outline does not chain: {len(remaining)} "
                        f"segment(s) left and none touches {here}. A board "
                        f"outline with a gap in it is not a shape this can "
                        f"extrude."
                    )
                raise ValueError(
                    f"the outline chains but does not close: it ends at "
                    f"{here} having started at {ring[0]}"
                )
        rings.append(ring[:-1])
    return rings


def loop(segments: tuple[eagle.Segment, ...]) -> list[tuple[float, float]]:
    """The one closed ring these segments form, refusing anything else.

    Kept as the strict form so a board that was a single silhouette does not
    quietly become several: `outer` is what a caller uses when it knows the
    shape may have cutouts, and this is what it uses when it does not.
    """
    rings = contours(segments)
    if len(rings) != 1:
        raise ValueError(
            f"these segments form {len(rings)} closed rings, not one; use "
            f"`outer` if cutouts are expected"
        )
    return rings[0]


def outer(segments: tuple[eagle.Segment, ...]
          ) -> tuple[list[tuple[float, float]], list[list[tuple[float, float]]]]:
    """`(the board's silhouette, everything else)`, largest ring first.

    The cutouts are RETURNED rather than dropped, so the caller reports what
    it is not drawing. Extruding the outer ring alone is a board with its
    slots filled in; saying nothing about them is the part that would be
    wrong.
    """
    rings = sorted(contours(segments), key=lambda ring: abs(_area(ring)),
                   reverse=True)
    return rings[0], rings[1:]


#: How far apart two outline endpoints may be and still be the same corner.
#:
#: **A vendor's own drawing has gaps in it, and the board is still made.** This
#: was a tenth of a micron -- EAGLE writes 3 decimals, so an EAGLE outline
#: either meets exactly or does not meet -- until Seeed's XIAO RP2350 and
#: nRF54L15, whose routed slots miss by 0.005 mm where an arc meets its line:
#: `66.6404` against `66.6354`, four times per board. Five microns is a tenth
#: of what any fab holds, so those are the same point in every sense except
#: the file's.
#:
#: **The bounds are measured, not chosen, and they are two orders apart.**
#: Across all five boards this composes:
#:
#:     largest gap that MUST close      0.00559 mm   nRF54L15
#:     closest endpoints that must NOT  0.19079 mm   nRF54L15
#:                                      1.41421 mm   Arduino Uno
#:
#: 0.02 mm is 3.6x the first and 9.5x below the second. The ceiling is this
#: file's own `ARC_CHORD_MM`, not the vendors': those near-misses are
#: consecutive points along an arc some OTHER entity was expanded into, so
#: **anything approaching the chord length would weld a curve to its
#: neighbour**. Any tolerance here must stay far under it.
CHAIN_TOLERANCE_MM = 0.02


def _near(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Are these two endpoints the same corner? See `CHAIN_TOLERANCE_MM`."""
    return (abs(a[0] - b[0]) < CHAIN_TOLERANCE_MM
            and abs(a[1] - b[1]) < CHAIN_TOLERANCE_MM)


def _area(ring: list[tuple[float, float]]) -> float:
    """Twice the signed area. Positive when the ring runs counter-clockwise."""
    total = 0.0
    for index, (x, y) in enumerate(ring):
        nx, ny = ring[(index + 1) % len(ring)]
        total += x * ny - nx * y
    return total


def ear_clip(ring: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    """Triangulate a simple polygon by clipping ears.

    The Uno's outline is not convex -- the notch on its right edge is the
    point -- so a fan from one vertex would put triangles outside the board.
    Ear clipping handles any simple polygon and needs no library, which is the
    same reasoning `tools/import_3d_model.py` gives for hand-writing its glTF.
    """
    order = list(range(len(ring)))
    if _area(ring) < 0:
        order.reverse()
    triangles: list[tuple[int, int, int]] = []
    guard = 0
    while len(order) > 3:
        guard += 1
        if guard > len(ring) * len(ring):
            raise ValueError(
                f"no ear found in a {len(order)}-vertex remainder; the outline "
                f"is not a simple polygon"
            )
        for at in range(len(order)):
            prev = order[at - 1]
            here = order[at]
            nxt = order[(at + 1) % len(order)]
            if not _is_ear(ring, prev, here, nxt, order):
                continue
            triangles.append((prev, here, nxt))
            order.pop(at)
            break
    triangles.append((order[0], order[1], order[2]))
    return triangles


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _is_ear(ring, prev: int, here: int, nxt: int, order: list[int]) -> bool:
    """Convex at `here`, and no other vertex inside the triangle it cuts off."""
    if _cross(ring[prev], ring[here], ring[nxt]) <= 0:
        return False
    for other in order:
        if other in (prev, here, nxt):
            continue
        point = ring[other]
        if (_cross(ring[prev], ring[here], point) >= 0
                and _cross(ring[here], ring[nxt], point) >= 0
                and _cross(ring[nxt], ring[prev], point) >= 0):
            return False
    return True


def slab(ring: list[tuple[float, float]], thickness: float, colour: str,
         centre: tuple[float, float]) -> Mesh:
    """The PCB: the outline extruded, in glTF axes and millimetres.

    glTF y is up and z runs the short way, so an EAGLE (x, y) becomes
    (x, height, -y) -- the same negation `board3d.js` applies to a pad, and for
    the same reason: EAGLE's y grows upward and the scene's z grows toward the
    camera, so getting it wrong mirrors the board end for end.
    """
    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []

    def put(x: float, y: float, up: float, normal: tuple[float, float, float]) -> int:
        positions.extend((x - centre[0], up, -(y - centre[1])))
        normals.extend(normal)
        return len(positions) // 3 - 1

    faces = ear_clip(ring)
    for a, b, c in faces:
        top = [put(*ring[i], thickness, (0.0, 1.0, 0.0)) for i in (a, b, c)]
        indices.extend(top)
        bottom = [put(*ring[i], 0.0, (0.0, -1.0, 0.0)) for i in (a, c, b)]
        indices.extend(bottom)

    for index, point in enumerate(ring):
        nxt = ring[(index + 1) % len(ring)]
        along = (nxt[0] - point[0], nxt[1] - point[1])
        length = math.hypot(*along) or 1.0
        # The outward normal of a counter-clockwise ring is the edge turned a
        # quarter to the right, and z is negated with y.
        normal = (along[1] / length, 0.0, along[0] / length)
        corners = [put(*point, 0.0, normal), put(*nxt, 0.0, normal),
                   put(*nxt, thickness, normal), put(*point, thickness, normal)]
        indices.extend((corners[0], corners[1], corners[2]))
        indices.extend((corners[0], corners[2], corners[3]))

    return Mesh({colour: (positions, normals, indices)})


#: The finish on a XIAO's exposed copper. **A JUDGEMENT, like `BOARD_MASK`**,
#: and made the same way: nothing in a `.kicad_pcb` states a surface finish --
#: it is a fabrication order, not a design file -- so this is the pale gold of
#: immersion gold rather than a reading of anything. Seeed's own assembly
#: export for the nRF54LM20A colours its pads a light tin grey, which is the
#: other common finish; the boards in the photographs on their own wiki are
#: gold, and that is as far as the evidence goes.
#:
#: **It must not be one of `CONTACT_COLOURS`**, and that is not aesthetics: the
#: overhang test finds a receptacle's tails by colour, and a castellated
#: half-hole is copper that is SUPPOSED to reach the board's edge. Sharing a
#: value would make every XIAO fail a check about its USB socket.
COPPER = "#c8a253"

#: The white a board is screen-printed with. Also a judgement, and a shallow
#: one: silkscreen is white on all five of these boards in the vendor's own
#: photographs, and KiCad stores no colour for the layer either.
SILKSCREEN = "#e9e9e4"

#: How much brighter a board's own mask is where there is copper under it.
#:
#: **A trace is not exposed metal, it is the mask with something brighter
#: behind it** -- soldermask is a translucent film, so light goes through it,
#: reflects off whatever is underneath, and comes back through. Copper returns
#: far more than bare laminate does, and the film has filtered the light both
#: ways, so what changes is the LIGHTNESS and not the hue.
#:
#: **The first version of this blended the mask toward `COPPER` by 0.30 and
#: that was wrong in a way the picture showed.** Copper's blue channel is 83
#: and the Arduino Uno's navy mask's is 99, so blending pulled blue down while
#: pushing red and green up: rgb(49,61,99) came out rgb(94,91,94), a NEUTRAL
#: GREY, and the Uno rendered with silver tracery on a blue board. Scaling
#: keeps the hue by construction, and the same navy becomes rgb(76,95,153) --
#: a lighter navy, which is what an Arduino's routing actually looks like.
#:
#: The factor is a drawing quantity, not a measurement, and it is low on
#: purpose: the routing has to read as relief in the mask rather than as bare
#: metal, and none of these boards is unmasked.
TRACE_LIFT = 1.55


def mask_over_copper(mask: str) -> str:
    """This board's own mask colour, over copper instead of over laminate.

    **Per board rather than one value written down.** Given a colour, the
    Arduino Uno's blue board would have got whatever a black XIAO needed; this
    way each board's routing is its own mask, and the boards stay as different
    from each other as their vendors made them.
    """
    def channel(at: int) -> int:
        # Clamped, which on a pale mask would flatten the hue -- none of the
        # six boards here is pale, and the brightest channel any of them has
        # is the Uno's 99 of 255.
        return min(255, round(int(mask[at:at + 2], 16) * TRACE_LIFT))
    return "#" + "".join(f"{channel(at):02x}" for at in (1, 3, 5))

#: How far above the board's own top face the copper is drawn. One ounce of
#: copper is 35 um, which is what this is -- so it is a real thickness rather
#: than a nudge to beat depth fighting, and it does both jobs. A component
#: body sits at the board's top face and therefore 35 um INSIDE its own pads,
#: which is invisible and is also what solder does.
COPPER_THICKNESS_MM = 0.035

#: And the ink over it. Screen-printed epoxy is 10 to 20 um; 15 keeps it above
#: the copper it is never printed on top of anyway.
SILK_THICKNESS_MM = 0.015

#: Where a routed trace is drawn, and it is BELOW the pads on purpose.
#:
#: Physically the mask over a trace stands a little proud of a bare pad -- 35
#: um of copper plus the ink over it, against 35 um of copper with the ink
#: opened away. Drawn that way a trace would occlude the edge of every pad it
#: runs into, and a pad is the thing a reader is looking for. So the routing
#: goes under, by 15 um, and the pads win every overlap.
TRACE_PROUD_MM = 0.020

#: How many sides a via is drawn with. A via on these boards is 0.3 to 0.6 mm
#: across and there are 82 to 307 of them, so this is where a sensible number
#: of sides pays for itself: eight is a fifth of a pixel of chord error at the
#: zoom the page opens at, and 307 x 6 triangles rather than 307 x 10.
VIA_SIDES = 8

#: Pad shapes this draws, and what it draws them as. `custom` is not here:
#: KiCad states it as a list of primitives rather than a size, and the 60 on
#: these five boards are all the surface tab beside a castellated half-hole
#: whose drilled barrel is drawn anyway. Counted and reported, not dropped
#: quietly.
ROUND_PADS = frozenset({"circle", "oval"})
SQUARE_PADS = frozenset({"rect", "roundrect"})

#: How many sides a round pad is drawn with. A castellated half-hole is
#: 1.27 mm across on a board 21 mm long, so twelve sides is a quarter of a
#: pixel of chord error at any zoom the page offers.
ROUND_PAD_SIDES = 12


def pad_outline(pad: eagle.Pad) -> list[tuple[float, float]] | None:
    """One pad as a closed ring in board millimetres, or None if not drawn.

    The pad's own size and its own angle, both the vendor's. A rectangle is
    four corners and a round pad is `ROUND_PAD_SIDES` points on its ellipse --
    an oval pad's two axes differ, which is why this is an ellipse and not a
    circle with one radius.
    """
    if pad.shape in SQUARE_PADS:
        local = [(-pad.width_mm / 2, -pad.height_mm / 2),
                 (pad.width_mm / 2, -pad.height_mm / 2),
                 (pad.width_mm / 2, pad.height_mm / 2),
                 (-pad.width_mm / 2, pad.height_mm / 2)]
    elif pad.shape in ROUND_PADS:
        local = [(pad.width_mm / 2 * math.cos(step),
                  pad.height_mm / 2 * math.sin(step))
                 for step in (2 * math.pi * i / ROUND_PAD_SIDES
                              for i in range(ROUND_PAD_SIDES))]
    else:
        return None
    turn = math.radians(pad.rotation_deg)
    cos, sin = math.cos(turn), math.sin(turn)
    return [(pad.x_mm + x * cos - y * sin, pad.y_mm + x * sin + y * cos)
            for x, y in local]


def convex(ring: list[tuple[float, float]]) -> bool:
    """Does this ring turn the same way at every vertex?

    **Which decides whether copper can be clipped to it exactly.** Clipping a
    pad against a convex region -- one half-plane per edge, Sutherland and
    Hodgman's algorithm -- is exact; against a concave one the same procedure
    quietly removes area that is inside the board. Every XIAO's silhouette is
    a rounded rectangle and convex; the Arduino Uno's has a notch and is not.
    """
    signs = []
    for index, point in enumerate(ring):
        nxt = ring[(index + 1) % len(ring)]
        after = ring[(index + 2) % len(ring)]
        cross = ((nxt[0] - point[0]) * (after[1] - nxt[1])
                 - (nxt[1] - point[1]) * (after[0] - nxt[0]))
        if abs(cross) > 1e-9:
            signs.append(cross > 0)
    return len(set(signs)) <= 1


def clipped_to(ring: list[tuple[float, float]],
               shape: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """`shape` with everything outside the convex `ring` cut away.

    Sutherland-Hodgman, one half-plane at a time. **The caller must have
    checked `convex(ring)`** -- this is where copper stops at the board's edge,
    and a castellated half-hole is exactly that: 42 of the RP2350's 316 pads
    cross the outline, and drawn whole they would hang in the air beside the
    board.
    """
    # **Which side is "inside" is measured off the ring, not assumed.** The
    # sign of a ring's own area says which way it winds, and nothing upstream
    # promises a direction -- `contours` chains segments in whatever order the
    # vendor wrote them. Guessing would clip every pad away on half the boards,
    # which is a failure that looks exactly like "the vendor drew no copper".
    inward = 1.0 if signed_area(ring) > 0 else -1.0
    out = list(shape)
    for index, edge_a in enumerate(ring):
        if not out:
            return []
        edge_b = ring[(index + 1) % len(ring)]
        along = (edge_b[0] - edge_a[0], edge_b[1] - edge_a[1])

        def side(point, a=edge_a, d=along) -> float:
            return (d[0] * (point[1] - a[1]) - d[1] * (point[0] - a[0])) * inward

        nxt: list[tuple[float, float]] = []
        for at, point in enumerate(out):
            before = out[at - 1]
            here, prior = side(point), side(before)
            if here >= 0:
                if prior < 0:
                    nxt.append(_crossing(before, point, prior, here))
                nxt.append(point)
            elif prior >= 0:
                nxt.append(_crossing(before, point, prior, here))
        out = nxt
    return out


def signed_area(ring: list[tuple[float, float]]) -> float:
    """Twice the ring's area, positive when it winds counter-clockwise."""
    return sum(a[0] * b[1] - b[0] * a[1]
               for a, b in zip(ring, ring[1:] + ring[:1]))


def _crossing(a: tuple[float, float], b: tuple[float, float],
              da: float, db: float) -> tuple[float, float]:
    """Where the segment a-b crosses the edge, from the two signed distances."""
    span = da - db
    t = 0.0 if abs(span) < 1e-12 else da / span
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def flat(rings: list[list[tuple[float, float]]], up: float, colour: str,
         centre: tuple[float, float], upward: bool) -> Mesh:
    """Closed rings as flat faces at height `up`, in the scene's own axes.

    Copper and ink are 15 to 35 um of a board 1.2 mm thick, so they are drawn
    as single faces rather than as slabs with sides: at that thickness a side
    is a fraction of a pixel at any zoom, and every one of them would be two
    more triangles across the two thousand shapes on a board.
    """
    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []
    normal = (0.0, 1.0, 0.0) if upward else (0.0, -1.0, 0.0)

    for ring in rings:
        if len(ring) < 3:
            continue
        # **Every ring is wound the same way before it is emitted**, and this
        # is not tidiness: `pad_outline` builds counter-clockwise and
        # `stroke_outline` built clockwise, because the offset that makes a
        # line into a rectangle naturally goes left-then-right. Two windings
        # in one mesh means half of it is back-facing, which shows up as
        # artwork that is there from one side of the board and gone from the
        # other -- and only on whichever half the author did not look at.
        if signed_area(ring) < 0:
            ring = ring[::-1]
        base = len(positions) // 3
        for x, y in ring:
            positions.extend((x - centre[0], up, -(y - centre[1])))
            normals.extend(normal)
        # A fan, which is correct for the convex shapes this is given: a pad
        # is a rectangle or an ellipse, and a clipped one stays convex because
        # `clipped_to` intersects it with half-planes. A stroke is a rectangle.
        for corner in range(1, len(ring) - 1):
            fan = (base, base + corner, base + corner + 1)
            indices.extend(fan if upward else (fan[0], fan[2], fan[1]))
    return Mesh({colour: (positions, normals, indices)})


def stroke_outline(stroke: eagle.Stroke) -> list[tuple[float, float]] | None:
    """One silkscreen stroke as the rectangle its width sweeps out.

    None for a stroke of no length, which a vendor writes as a dot and which
    would give a zero-area quad and a normal of nothing.
    """
    along = (stroke.x2_mm - stroke.x1_mm, stroke.y2_mm - stroke.y1_mm)
    length = math.hypot(*along)
    if length < 1e-9 or stroke.width_mm <= 0.0:
        return None
    half = stroke.width_mm / 2
    across = (-along[1] / length * half, along[0] / length * half)
    return [(stroke.x1_mm + across[0], stroke.y1_mm + across[1]),
            (stroke.x2_mm + across[0], stroke.y2_mm + across[1]),
            (stroke.x2_mm - across[0], stroke.y2_mm - across[1]),
            (stroke.x1_mm - across[0], stroke.y1_mm - across[1])]


def box_around(name: str, put: Mesh) -> dict[str, object]:
    """An axis-aligned box around a placed component, in the scene's frame.

    What a wire may not pass through. A box and not the mesh: `wires.js`
    resolves contact against boxes and spheres because a rope is stepped up to
    eight times a frame, and a triangle test against seventeen thousand of them
    is not a thing to do sixty times a second. A header is a box to within its
    own gaps, and a wire resting on the top of one is the picture that matters.
    """
    points = [(p[at], p[at + 1], p[at + 2])
              for _colour, (p, _n, _i) in put.groups.items()
              for at in range(0, len(p), 3)]
    return {
        "name": name,
        "min": [round(min(v[axis] for v in points), 4) for axis in range(3)],
        "max": [round(max(v[axis] for v in points), 4) for axis in range(3)],
    }


def component_mesh(component: Component, deflection: float) -> tuple[Mesh, object]:
    """Fetch and tessellate one KiCad model, in its own z-up millimetres.

    Left in KiCad's frame rather than glTF's, because `place` has to rotate it
    about the board's vertical and that is KiCad's z -- permuting first would
    mean rotating about a different axis and remembering which.
    """
    if component.modelled:
        made = MODELLED / f"{component.model}.obj"
        if not made.is_file():
            raise Unavailable(
                f"{made} has not been built. Run: "
                f"python tools/model_from_datasheet.py --part {component.model}"
            )
        return read_obj(made)

    CACHE.mkdir(parents=True, exist_ok=True)
    step = cached(component, component.url, ".step")
    if not step.is_file():
        print(f"  fetch  {component.url}")
        with urllib.request.urlopen(component.url) as response:  # noqa: S310
            step.write_bytes(response.read())
    shape, styles, _document = read(step)
    box = box_of(shape)
    #: Identity: x stays x, z stays up, y stays y. `place` does the moving.
    frame = Frame(long_axis=0, up=1, short_axis=2,
                  handedness=handedness_of((0, 1, 2)),
                  origin=(0.0, 0.0, 0.0))
    mesh = tessellate(shape, styles, deflection, frame)
    origin = pads_origin(component)
    if origin is not None:
        mesh = OverPads(mesh.groups, origin)
    return mesh, box


@dataclasses.dataclass
class OverPads(Mesh):
    """A model that is not centred over its own pads, and where they are.

    `origin` is the middle of the model's pads in its own frame, read by
    `pads_origin` out of the manufacturer's footprint; `place` anchors that
    point on the element's pads instead of the middle of the body.
    """

    origin: tuple[float, float] = (0.0, 0.0)


# --- which kind of passive a placement is (OH-187) -----------------------------
#
# **Adafruit place a resistor and a capacitor on one package from one
# library**, so neither the package nor `vendor_library` can say which a
# placement is, and a table keyed by them drew the QT Py's resistors as
# capacitors. The vendor's schematic says, twice over, and nothing else here
# is read for it.

#: The KiCad library folders that each hold one kind of passive, which is
#: the kind a row drawing from one of them draws.
PASSIVE_KINDS = {"Resistor_SMD": "resistor", "Capacitor_SMD": "capacitor",
                 "Inductor_SMD": "inductor", "Fuse": "fuse"}

#: EAGLE's `prefix`, which a deviceset states once for every part placed from
#: it: the letters a reference designator is numbered after. Only an EMPTY
#: prefix is silence. Any other names a kind, and one not in this table names
#: a kind that is none of these -- `D`, `U`, `FB`, `LED`, `CONN`. `F` is here
#: so that a fuse's prefix agrees with a value reading FUSE and no other does;
#: `RN` is a resistor network's, which the Uno's `4R-N` states (OH-191).
PREFIX_KINDS = {"R": "resistor", "C": "capacitor", "L": "inductor",
                "F": "fuse", "RN": "resistor"}

#: The kind a prefix outside `PREFIX_KINDS` states.
OTHER = "other"

#: A value that can only be a resistance: a unit (`0 ohm`, `10Ω`, `4R7`), or a
#: multiplier and nothing else (`10K`, `5.1K`, `4K7`). A bare number states no
#: unit -- `27` -- and a lowercase `m` is milli, so neither is one.
_OHMS = re.compile(r"\s*\d+(?:\.\d+)?\s*(?:[kKM]?\s*(?:ohms?|Ohms?|OHMS?|Ω)|[kKMR]\d*)\s*")
#: A value that can only be a capacitance: a number, a multiplier, farads.
_FARADS = re.compile(r"\s*\d+(?:\.\d+)?\s*[pnuµμ]?[Ff]\s*")
#: Values that name a kind in a word. Closed: a word is read only once it is
#: in this table, because a value is free text.
KIND_WORDS = {"FUSE": "fuse"}
#: Words in a DEVICESET's name that state a kind, as a whole token of it: a
#: third statement beside the prefix and the value, agreeing or disagreeing
#: as they do (OH-191). Arduino places its varistors from `VARISTOR` with
#: prefix R. FERRITE is an inductor's because that is how KiCad draws one --
#: its own ferrite-bead symbol takes the `L_` footprints -- and PTC a fuse's,
#: the resettable fuse these boards carry: both JUDGEMENTS. Closed.
DEVICESET_WORDS = {"VARISTOR": "varistor", "FUSE": "fuse", "PTC": "fuse",
                   "THERMISTOR": "thermistor", "FERRITE": "inductor"}
#: The letter stems of a part's NAME that agree with a passive's deviceset
#: prefix (OH-191). EAGLE names a part after its prefix; a designer who
#: renames it to a stem not listed here -- the Uno's fuse F1 on an inductor's
#: prefix L, a varistor RV1 or a thermistor RT1 on an R, a diode CR1 -- has
#: said the library's kind is not the part's, and the part is refused with
#: both statements. Only a passive's prefix is checked: an LED's or a
#: header's names (ON, TX, POWER) state nothing. Closed: IEEE 315's class
#: letters, and the stems these boards and common practice pair with them --
#: PC for a polarised C (the Uno's PC1), FB for a ferrite on an L, PTC for a
#: resettable fuse on an F, RN and R for a network.
DESIGNATOR_STEMS = {"R": frozenset({"R", "RN"}), "C": frozenset({"C", "PC"}),
                    "L": frozenset({"L", "FB"}), "F": frozenset({"F", "PTC"}),
                    "RN": frozenset({"RN", "R"})}
#: Values that say a part is NOT fitted, and the one that says nobody has
#: decided. Either way drawing the part would assert it is there. Read only
#: of a part stated to be a passive: a jumper or a switch valued NC is
#: normally closed, not missing.
NOT_FITTED = frozenset({"DNP", "NC", "NF", "DNF", "DNI"})
UNDECIDED = frozenset({"TBD"})
#: What a DEVICE's name says when the vendor places a part that is not
#: fitted: SparkFun's CONN_06 carries a NO_SILK_NO_POP beside the
#: NO_SILK_FEMALE_PTH they fit, on one land. Closed, and read as a whole
#: `_`-separated run of the device's name, of any part: unlike NC, it names
#: nothing else.
NOT_FITTED_DEVICE = ("NO", "POP")


def value_kind(value: str) -> str | None:
    """The kind of part a value states -- by its unit, or by a word in
    `KIND_WORDS` -- or None where it states none."""
    if _OHMS.fullmatch(value):
        return "resistor"
    if _FARADS.fullmatch(value):
        return "capacitor"
    return KIND_WORDS.get(value.strip().upper())


@dataclasses.dataclass(frozen=True)
class Statement:
    """What a vendor's schematic says about one part (OH-187)."""

    #: A kind in `PREFIX_KINDS`, `KIND_WORDS` or `OTHER`; None where neither
    #: the prefix nor the value speaks, or where they disagree.
    kind: str | None
    #: The deviceset's prefix where it spoke, and the value where it spoke.
    prefix: str | None
    value: str | None
    #: Why the part is not drawn at all, or None.
    refused: str | None = None
    #: The word of the deviceset's name that spoke (`DEVICESET_WORDS`).
    word: str | None = None
    #: The models a KiCad footprint itself places, by file stem, hidden
    #: alternates left out (OH-195). Empty for an EAGLE part, which places
    #: none, and for a footprint that names none.
    models: tuple[str, ...] = ()


def _current_variant(root) -> str | None:
    """The name of the variant an EAGLE drawing is set to, or None: the
    `<variantdef current="yes">` under its `<variantdefs>`."""
    return next((variant.get("name") for variant in root.iter("variantdef")
                 if variant.get("current") == "yes"), None)


def _unpopulated(placed, variant: str | None) -> bool:
    """Whether a `<part>` or an `<element>` is not fitted in `variant`.

    **Where EAGLE writes it, and nowhere else**: `populate` is an attribute
    of `<variant>`, one per variant a part or an element is placed in, and
    of `<element>` itself on a board. A `<part populate="no">` is not a shape
    EAGLE writes, so it is not read.
    """
    if placed.tag == "element" and placed.get("populate") == "no":
        return True
    return any(each.get("name") == variant and each.get("populate") == "no"
               for each in placed.findall("variant"))


def stated_kinds(schematic: pathlib.Path) -> dict[str, Statement]:
    """Each part as the vendor's schematic states it.

    Two statements of kind and nothing else: the `prefix` of the deviceset
    the part is placed from, and its value where that is ohms, farads or a
    word in `KIND_WORDS`. Where both speak and disagree the part is refused,
    as a connector whose name and land disagree is (`JST_SH4_RA`): drawing
    either would be choosing between two statements of the vendor's. A part
    not fitted in the schematic's current variant is refused whatever its
    kind; a passive valued as not fitted, or still `TBD`, is refused too.

    Devicesets are keyed by library AND urn, because one schematic can carry
    two libraries under one name; the Feather's carries two `supply1`s.
    """
    root = eagle._open(schematic, "schematic").find("drawing/schematic")
    prefixes = {(library.get("name"), library.get("urn", ""), deviceset.get("name")):
                deviceset.get("prefix", "")
                for library in root.iter("library")
                for deviceset in library.iter("deviceset")}
    variant = _current_variant(root)
    stated: dict[str, Statement] = {}
    for part in root.iter("part"):
        name, value = part.get("name"), part.get("value", "")
        where = f"{part.get('library')}/{part.get('deviceset')}"
        prefix = prefixes.get((part.get("library"), part.get("library_urn", ""),
                               part.get("deviceset")), "")
        by_prefix = (PREFIX_KINDS.get(prefix, OTHER) if prefix else None)
        by_value = value_kind(value)
        said_word = next((token for token in re.split(
            r"[^A-Z0-9]+", part.get("deviceset", "").upper())
            if token in DEVICESET_WORDS), None)
        by_word = DEVICESET_WORDS.get(said_word)
        spoke = {"prefix": prefix if by_prefix else None,
                 "value": value if by_value else None,
                 "word": said_word}
        spoken = {kind for kind in (by_prefix, by_word, by_value) if kind}
        disagree = len(spoken) > 1
        kind = None if disagree else next(iter(spoken), None)
        # **A designer who renames a part away from its deviceset's prefix
        # has said something the library did not** (OH-191): see
        # `DESIGNATOR_STEMS`, which is the whole of what is read of a name.
        stem = re.match(r"[A-Za-z]*", name).group(0).upper()
        renamed = (by_prefix in PASSIVE_KINDS.values()
                   and stem not in DESIGNATOR_STEMS.get(prefix.upper(), ()))
        word = value.strip().upper()
        passive = kind in PASSIVE_KINDS.values()
        device = part.get("device", "")
        runs = device.upper().split("_")
        if _unpopulated(part, variant):
            refused = (f'{schematic.name} places {name} with populate="no" in '
                       f"its current variant, {variant!r}: not fitted")
        elif any(tuple(runs[at:at + len(NOT_FITTED_DEVICE)]) == NOT_FITTED_DEVICE
                 for at in range(len(runs))):
            refused = (f"{schematic.name} places {name} from {where}'s device "
                       f"{device!r}, whose name says NO_POP: not fitted")
        elif disagree:
            said = ([f"whose prefix {prefix} says "
                     + ("a kind none of R, C, L and F" if by_prefix == OTHER
                        else by_prefix)] if by_prefix else []) \
                + ([f"the deviceset's own name, {said_word}, saying {by_word}"]
                   if by_word else []) \
                + ([f"valued {value!r}, which says {by_value}"] if by_value else [])
            refused = (f"{schematic.name} places {name} from {where}, "
                       f"{', '.join(said)}: statements of its kind that "
                       f"disagree, and drawing it as any one would be choosing "
                       f"between them")
        elif renamed:
            refused = (f"{schematic.name} places {name} from {where}, whose prefix "
                       f"{prefix} says {by_prefix} and would number it "
                       f"{prefix}<n>, and its designer named it {name}, a stem "
                       f"{stem} not one of {sorted(DESIGNATOR_STEMS[prefix.upper()])}: "
                       f"the library and the designer disagree about what it "
                       f"is, and drawing the library's kind would take its word "
                       f"over theirs")
        elif passive and word in NOT_FITTED:
            refused = f"{schematic.name} values {name} {value!r}: not fitted"
        elif passive and word in UNDECIDED:
            refused = (f"{schematic.name} values {name} {value!r}: whether it is "
                       f"fitted is not stated, and drawing it would say it is")
        else:
            refused = None
        stated[name] = Statement(None if refused else kind, refused=refused, **spoke)
    return stated


#: What a reference's letter stem says a part is: a passive prefix's own
#: letters and the stems `DESIGNATOR_STEMS` pairs with it. A KiCad
#: footprint carries no deviceset, and its reference is the prefix its
#: symbol numbered it by (OH-195).
STEM_KINDS = {stem: PREFIX_KINDS[prefix]
              for prefix, stems in DESIGNATOR_STEMS.items() for stem in stems}


def kicad_statements(layout: pathlib.Path) -> dict[str, Statement]:
    """Each footprint of a KiCad board as its own file states it (OH-195).

    Three statements of kind, under OH-187's rule -- those that speak must
    agree, or the part is refused: its footprint library where that is one
    of KiCad's own passive libraries (`PASSIVE_KINDS`), the letter stem of
    its reference (`STEM_KINDS`, any other stem naming another kind), and
    its value where that is ohms, farads or a word in `KIND_WORDS`. A
    footprint with pads that KiCad marks `dnp` or `exclude_from_bom` is not
    fitted; a passive valued as not fitted, or still TBD, is refused too.
    And the models the footprint places, which `drawn_from` holds a row to.

    Keyed as `from_kicad` names an element: by reference, or by the
    footprint's library name where the file gives no reference. **A
    reference two footprints with pads share is refused**, naming both,
    since which of them a part's statements are about cannot be told. A
    footprint with no pad under a reference already read is ink and is
    passed over -- PCBCUPID's `G***` logos and `kibuzzard-*` lettering,
    Olimex's two `REF*` signs.
    """
    tree = kicad.parse_sexp(layout.read_text(encoding="utf-8"))
    stated: dict[str, Statement] = {}
    #: Each reference with pads, and the footprint that placed it.
    padded: dict[str, str] = {}
    for footprint in kicad.children(tree, "footprint"):
        name = kicad._reference_of(footprint) or footprint[1]
        has_pads = bool(kicad.children(footprint, "pad"))
        if name in stated and not has_pads:
            continue
        at = kicad.first(footprint, "at")
        here = f"{footprint[1]} at ({' '.join(map(str, at[1:])) if at else 'nowhere stated'})"
        if has_pads and name in padded:
            raise ValueError(
                f"{layout.name} places two footprints with pads under the "
                f"reference {name!r}: {padded[name]} and {here}. Which one "
                f"its statements are about cannot be told")
        if has_pads:
            padded[name] = here
        value = kicad._value_of(footprint)
        models = tuple(pathlib.PurePosixPath(model.path).stem
                       for model in kicad._models_of(footprint) if not model.hidden)
        library = footprint[1].split(":", 1)[0] if ":" in footprint[1] else ""
        attr = kicad.first(footprint, "attr")
        flags = [flag for flag in (attr[1:] if attr else []) if isinstance(flag, str)]
        stem = re.match(r"[A-Za-z]*", name).group(0).upper()
        by_prefix = STEM_KINDS.get(stem, OTHER) if stem else None
        by_value = value_kind(value)
        by_library = PASSIVE_KINDS.get(library)
        spoken = {kind for kind in (by_prefix, by_library, by_value) if kind}
        disagree = len(spoken) > 1
        kind = None if disagree else next(iter(spoken), None)
        word = value.strip().upper()
        passive = kind in PASSIVE_KINDS.values()
        fitted_not = [flag for flag in flags if flag in ("dnp", "exclude_from_bom")]
        if fitted_not and has_pads:
            refused = (f"{layout.name} marks {name} "
                       f"{' and '.join(fitted_not)}: not fitted")
        elif disagree:
            said = ([f"its reference's letters {stem} saying "
                     + ("a kind none of R, C, L and F" if by_prefix == OTHER
                        else by_prefix)] if by_prefix else []) \
                + ([f"its library {library} saying {by_library}"]
                   if by_library else []) \
                + ([f"valued {value!r}, which says {by_value}"] if by_value else [])
            refused = (f"{layout.name} places {name} from {footprint[1]}, "
                       f"{', '.join(said)}: statements of its kind that "
                       f"disagree, and drawing it as any one would be choosing "
                       f"between them")
        elif passive and word in NOT_FITTED:
            refused = f"{layout.name} values {name} {value!r}: not fitted"
        elif passive and word in UNDECIDED:
            refused = (f"{layout.name} values {name} {value!r}: whether it is "
                       f"fitted is not stated, and drawing it would say it is")
        else:
            refused = None
        stated[name] = Statement(
            None if refused else kind, stem if by_prefix else None,
            value if by_value else None, refused=refused,
            word=library if by_library else None, models=models)
    return stated


def statements_for(spec: "Composition") -> dict[str, Statement] | None:
    """What a board's own files say of each part it places, or None for a
    board composed without a schematic -- the XIAOs.

    The schematic's statements (`stated_kinds`), and the board file's own
    word on what is not fitted: an `<element>` with `populate="no"`, or not
    fitted in the board's current variant.
    """
    if spec.schematic is None:
        return None
    if spec.schematic.suffix == ".kicad_pcb":
        return kicad_statements(spec.schematic)
    statements = stated_kinds(spec.schematic)
    board = eagle._open(spec.layout, "board").find("drawing/board")
    variant = _current_variant(board)
    for element in board.iter("element"):
        if _unpopulated(element, variant):
            name = element.get("name")
            statements[name] = dataclasses.replace(
                statements.get(name, Statement(None, None, None)), kind=None,
                refused=(f'{spec.layout.name} places {name} with '
                         f'populate="no": not fitted'))
    return statements


def correspondence_for(element: eagle.Element,
                       kind: str | None = None) -> Component | None:
    """The `CORRESPONDENCE` row for this placement, or None.

    A row naming the element's own vendor library wins over one that names
    none, because the library is the vendor saying which part a shared package
    name is -- see `Component.vendor_library`. Given a `kind` the vendor's
    schematic states (`stated_kinds`), only a row drawing that kind is
    returned. Without one, a package with two rows naming no library is
    answered with None: which of them is not this function's to guess.
    """
    fallbacks = []
    for component in CORRESPONDENCE:
        if component.package != element.package:
            continue
        if kind is not None and PASSIVE_KINDS.get(component.library) != kind:
            continue
        if component.vendor_library == element.library:
            return component
        if component.vendor_library is None:
            fallbacks.append(component)
    return fallbacks[0] if len(fallbacks) == 1 else None


def drawn_from(element: eagle.Element, statements: dict[str, Statement] | None,
               schematic: str = "the schematic") -> tuple[Component | None, str | None]:
    """The row a placement is drawn from, or why it is not drawn at all.

    `statements` is None for a board with no schematic -- the XIAOs --
    which compose from the table alone, as they always have, ESD diodes in
    a resistor's moulding included. Otherwise a part its files refuse is
    refused; a resistor, capacitor, inductor or fuse is drawn only from a row
    of the kind stated; and on a land every row of which draws one of those,
    a part stated to be some other kind is refused, as is a part nothing
    states -- a row does not get to decide what a part is. A borrowed body
    for another kind on a board with a schematic would have to be marked so
    on its row, and no row is.

    **A KiCad footprint states the model it places** (OH-195), so on a KiCad
    manifest row a row draws only that model, or one it says stands for it
    (`Component.stands_for`); any other is refused, with both names. One
    land can carry two parts on two boards -- PCBCUPID put GCT's USB4105 on
    the Glyph Mini's Palconn land and HRO's TYPE-C-31-M-12 on the Glyph
    C3's -- and the package name cannot tell them apart.
    """
    if statements is None:
        return correspondence_for(element), None
    said = statements.get(element.name)
    if said is not None and said.refused:
        return None, said.refused
    if said is not None and said.kind in PASSIVE_KINDS.values():
        row = correspondence_for(element, said.kind)
    else:
        rows = [row for row in CORRESPONDENCE if row.package == element.package]
        if rows and all(row.library in PASSIVE_KINDS for row in rows):
            if said is None or said.kind is None:
                return None, (f"nothing in {schematic} states what kind of part "
                              f"{element.name} is, and every row for its land, "
                              f"{element.package}, draws a passive")
            return None, (f"{schematic} places {element.name} under the prefix "
                          f"{said.prefix}, which names a kind none of R, C, L "
                          f"and F, and every row for its land, "
                          f"{element.package}, draws a resistor, capacitor, "
                          f"inductor or fuse")
        row = correspondence_for(element)
    if (row is not None and said is not None and said.models
            and not {row.model, *row.stands_for} & set(said.models)):
        return None, (f"{schematic}'s footprint for {element.name} places "
                      f"{' and '.join(said.models)}, and the row for its land, "
                      f"{element.package}, draws {row.model}, which is not that "
                      f"and does not say it stands for it: drawing it would "
                      f"put a part on the board that its own file does not")
    return row, None


# --- a row held to the vendor's own words (OH-193) ------------------------------
#
# **A row is a claim that one library's model IS another's package**, and the
# pads, the body and the pin-1 marker are what check it. They cannot see a
# word: KiCad's vertical and horizontal SH sockets share a land, and so do
# the C3 and C6 MINI modules. Where the vendor's own package name or value
# states something a model's name also states, the two must agree. Each
# vocabulary is closed: a word is read only once it is here.

#: Orientation, as a vendor spells it in a token of its package or value,
#: against the word KiCad's model names carry.
ORIENTATION_WORDS = {"VERT": "Vertical", "VERTICAL": "Vertical",
                     "RA": "Horizontal", "HORIZONTAL": "Horizontal"}

#: Chips a module or a package can be named for, on either side.
CHIP_NAMES = ("ESP32-C3", "ESP32-C5", "ESP32-C6", "ESP32-H2", "ESP32-S2",
              "ESP32-S3", "RP2040", "RP2350")

#: A lead count, as a vendor's package name states it and as a model's name
#: does. Two-digit header counts only, so a `2X2MM` body is not a header;
#: and a count is at most three digits and not followed by a digit, an X or
#: a point, so a DFN1006's 1006 and a QFN-3X3's 3 are body sizes, not leads.
_VENDOR_LEADS = (re.compile(r"(?:QFN|MLF|DFN|SON)-?(\d{1,3})(?![\dX.])"),
                 re.compile(r"SOT23-(\d)(?!\d)"), re.compile(r"MSOP0?(\d+)"),
                 re.compile(r"DIL(\d+)"),
                 re.compile(r"(?:^|[_-])([12])X(\d\d)(?:$|[_-])"))
_MODEL_LEADS = (re.compile(r"(?:QFN|DFN|SON)[-_](\d{1,3})(?![\dXx.])"),
                re.compile(r"SOT-23-(\d)(?!\d)"), re.compile(r"MSOP-(\d+)"),
                re.compile(r"DIP-(\d+)"), re.compile(r"PinHeader_(\d)x(\d+)"))


def _leads(text: str, patterns) -> int | None:
    """The lead count the first pattern that matches states, or None."""
    for pattern in patterns:
        found = pattern.search(text)
        if found:
            numbers = [int(group) for group in found.groups()]
            return numbers[0] * numbers[1] if len(numbers) == 2 else numbers[0]
    return None


def _chips(text: str) -> set[str]:
    return {name for name in CHIP_NAMES
            if re.search(rf"(?<![A-Z0-9]){re.escape(name)}(?![A-Z0-9])", text)}


def contradiction(element: eagle.Element, component: Component) -> str | None:
    """What the vendor's own words for this placement state that its row's
    model contradicts, or None."""
    vendor = f"{element.package} {element.value or ''}".upper()
    names = [component.model] + [pathlib.PurePosixPath(url).name
                                 for url in (component.step, component.footprint)
                                 if url is not None]
    model = " ".join(names)
    for token in re.split(r"[^A-Z0-9]+", vendor):
        said = ORIENTATION_WORDS.get(token)
        other = {"Vertical": "Horizontal", "Horizontal": "Vertical"}.get(said)
        if said and other.lower() in model.lower():
            return (f"the vendor's {token!r} says {said.lower()}, and "
                    f"{component.model} is {other.lower()}")
    stated, drawn = _chips(vendor), _chips(model.upper())
    if stated and drawn - stated:
        return (f"the vendor's words name {sorted(stated)} and the row's model "
                f"and files name {sorted(drawn)}")
    leads, modelled = _leads(element.package.upper(), _VENDOR_LEADS), \
        _leads(component.model, _MODEL_LEADS)
    if leads is not None and modelled is not None and leads != modelled:
        return (f"{element.package} states {leads} leads and {component.model} "
                f"{modelled}")
    return None


def cached(component: Component, url: str, suffix: str) -> pathlib.Path:
    """Where a fetched model file is kept.

    A KiCad model keeps the name it always had. A manufacturer's file is keyed
    by its URL too, which carries the pinned commit, so re-pinning
    `ESPRESSIF_KICAD` fetches afresh instead of reading the old commit's file
    under the new commit's name.
    """
    name = f"component-{component.slug}"
    if component.step is not None:
        name += "-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return CACHE / f"{name}{suffix}"


def pads_origin(component: Component) -> tuple[float, float] | None:
    """Where the middle of the model's own pads is, in the model's own frame.

    None for a model from KiCad's library, which `place` anchors as it always
    has. For a manufacturer's model, read out of the manufacturer's footprint:
    the centre of its pads, taken back through the x and y of the `(offset
    ...)` its one `(model ...)` block places this STEP with. KiCad's footprint
    y runs down the page and a model's y runs up it, so `y` is negated on the
    way.

    **The offset's z is ignored, and that is a JUDGEMENT.** `place` rests a
    model's own z = 0 on the board, and Espressif's MINI-1 footprint lifts its
    model 0.5 mm while the STEP's lowest point is already at z = -0.02 mm:
    honoured, the module would float half a millimetre over the board it is
    soldered to. `test_a_manufacturers_model_sits_on_the_board_whatever_its_z`
    reads both numbers.

    Refuses a footprint whose block also turns or scales the model, or that
    names some other file: a rotated model read as a translated one would be
    placed wrongly and still look like a module.
    """
    if component.footprint is None:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    local = cached(component, component.footprint, ".kicad_mod")
    if not local.is_file():
        print(f"  fetch  {component.footprint}")
        with urllib.request.urlopen(component.footprint) as response:  # noqa: S310
            local.write_bytes(response.read())
    tree = kicad.parse_sexp(local.read_text(encoding="utf-8"))
    stated = [m for m in kicad._models_of(tree)
              if pathlib.PurePosixPath(m.path).stem == component.model]
    if len(stated) != 1:
        raise SystemExit(
            f"{component.footprint} places {len(stated)} models named "
            f"{component.model}, not one, so where its pads sit under the "
            f"model is not stated once"
        )
    model = stated[0]
    if model.rotate != (0.0, 0.0, 0.0) or model.scale != (1.0, 1.0, 1.0):
        raise SystemExit(
            f"{component.footprint} turns or scales {component.model} "
            f"(rotate {model.rotate}, scale {model.scale}); only an offset is "
            f"read here"
        )
    pads = kicad._pads_of(tree)
    xs = [pad.x_mm for pad in pads]
    ys = [pad.y_mm for pad in pads]
    middle = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    return (middle[0] - model.offset[0], -middle[1] - model.offset[1])


def read_obj(path: pathlib.Path) -> tuple[Mesh, Extent]:
    """A Wavefront OBJ and its `.mtl`, as the same `Mesh` a STEP tessellates to.

    **Narrow on purpose**, like `write_glb` at the other end of the pipeline:
    triangles, vertex normals and one colour per material group. Blender writes
    exactly that and nothing here needs more. Anything it cannot read it
    refuses by line, rather than skipping a face and drawing most of a part.

    Quads are triangulated by fanning, which is correct for the convex faces a
    box export produces and is not a general polygon triangulation -- `slab`
    has the real one, and needs it because a board outline is concave.
    """
    colours: dict[str, str] = {}
    material = path.with_suffix(".mtl")
    if material.is_file():
        name = ""
        for line in material.read_text(encoding="utf-8").splitlines():
            if line.startswith("newmtl "):
                name = line.split(None, 1)[1].strip()
            elif line.startswith("Kd ") and name:
                red, green, blue = (float(v) for v in line.split()[1:4])
                colours[name] = (f"#{round(red * 255):02x}"
                                 f"{round(green * 255):02x}"
                                 f"{round(blue * 255):02x}")

    vertices: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    groups: dict[str, tuple[list[float], list[float], list[int]]] = {}
    current = UNSTYLED

    def emit(corner: str) -> int:
        """One `v/vt/vn` reference, appended to the current group."""
        parts = corner.split("/")
        vertex = vertices[int(parts[0]) - 1]
        normal = (normals[int(parts[2]) - 1]
                  if len(parts) > 2 and parts[2] else (0.0, 0.0, 1.0))
        positions, into_normals, _indices = groups.setdefault(
            current, ([], [], []))
        positions.extend(vertex)
        into_normals.extend(normal)
        return len(positions) // 3 - 1

    for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.startswith("v "):
            vertices.append(tuple(float(v) for v in line.split()[1:4]))
        elif line.startswith("vn "):
            normals.append(tuple(float(v) for v in line.split()[1:4]))
        elif line.startswith("usemtl "):
            current = colours.get(line.split(None, 1)[1].strip(), UNSTYLED)
        elif line.startswith("f "):
            corners = line.split()[1:]
            if len(corners) < 3:
                raise ValueError(f"{path}:{number}: a face with "
                                 f"{len(corners)} corners is not a polygon")
            made = [emit(corner) for corner in corners]
            indices = groups[current][2]
            for at in range(1, len(made) - 1):
                indices.extend((made[0], made[at], made[at + 1]))

    if not groups:
        raise ValueError(f"{path}: no faces, so there is nothing to draw")
    every = [v for v in vertices]
    return Mesh(groups), Extent(
        min(v[0] for v in every), max(v[0] for v in every),
        min(v[1] for v in every), max(v[1] for v in every),
        min(v[2] for v in every), max(v[2] for v in every),
    )


def footprint(box, turn: float, element: eagle.Element) -> tuple[float, float]:
    """The mesh's span along the board's own x and y, once fully turned.

    Both the component's `turn` and the element's own rotation, because that is
    what decides which way the part actually lies on this board. A quarter turn
    swaps the two numbers, which is exactly the difference `confirm` has to be
    able to see.
    """
    angle = math.radians(turn + element.rotation)
    cos, sin = abs(math.cos(angle)), abs(math.sin(angle))
    return (box.width * cos + box.height * sin,
            box.width * sin + box.height * cos)


#: How far below the board plane a vertex has to be before it counts as a
#: LEAD. KiCad models sit on z = 0 with through-hole legs hanging under it, so
#: anything materially negative is a leg. Loose enough that a surface-mount
#: pad's own plating, which is a few hundredths under, is not mistaken for one.
LEAD_DEPTH_MM = 0.5


def leads_of(mesh: Mesh) -> list[tuple[float, float]]:
    """The xy of every vertex below the board plane: a through-hole part's legs.

    Empty for a surface-mount model, which is the whole reason this is useful
    twice -- it says which KIND of part a mesh is, and for a through-hole one
    it says where the pins are without needing pad data a STEP does not carry.
    """
    return [(positions[at], positions[at + 1])
            for _colour, (positions, _n, _i) in mesh.groups.items()
            for at in range(0, len(positions), 3)
            if positions[at + 2] < -LEAD_DEPTH_MM]


def via_in_pad(hole: eagle.Pad, element: eagle.Element) -> bool:
    """Is this plated hole a via in a pad, rather than a hole for a leg?

    **Yes where surface-mount copper under its own number lies on all four
    sides of its centre** (OH-195): a half-line from the centre along +x,
    -x, +y and -y each meets one of those pads, each taken as its own width
    by height turned by its own rotation -- a round or oval pad as the
    rectangle round it, and an EAGLE pad unturned, since `eagle.Pad` carries
    no angle for one. A centre inside one such pad is the case where all
    four start in it, as on a XIAO's castellations. A centre in the middle
    of a pad laid as a field of squares is the other, as on Olimex's
    ESP32-C3-MINI-1: its plated hole is the middle square of nine and lies
    in none of the eight surface-mount squares round it. A slot beside a pad
    of its number meets that copper on one or two sides, as each of the
    Olimex USB-C's four shell slots does, and is a leg's hole.
    """
    same = [pad for pad in element.pads_of("smd") if pad.number == hole.number]

    def meets(pad: eagle.Pad, dx: float, dy: float) -> bool:
        # Into the pad's own frame, where its copper is an upright rectangle,
        # and the half-line clipped against it one axis at a time.
        turn = math.radians(pad.rotation_deg)
        cos, sin = math.cos(turn), math.sin(turn)
        ox, oy = hole.x_mm - pad.x_mm, hole.y_mm - pad.y_mm
        near, far = 0.0, math.inf
        for origin, step, half in (
                (ox * cos + oy * sin, dx * cos + dy * sin, pad.width_mm / 2),
                (-ox * sin + oy * cos, -dx * sin + dy * cos, pad.height_mm / 2)):
            if abs(step) < 1e-12:
                if abs(origin) > half:
                    return False
                continue
            low, high = sorted(((-half - origin) / step, (half - origin) / step))
            near, far = max(near, low), min(far, high)
        return near <= far

    return all(any(meets(pad, dx, dy) for pad in same)
               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def confirm(element: eagle.Element, box, turn: float,
            mesh: Mesh | None = None) -> str | None:
    """Does this mesh fit the pads it is supposed to stand on, the way round
    it is about to be placed?

    Returns a complaint, or `None` when they agree. Three things are checked
    and the last two were each added after they were needed:

    * **Size.** The mesh's footprint must contain the pad span within a
      tolerance -- a body is generally at least as big as its pads and never
      much smaller. A `DIL28-3` mapped to a DIP-8 fails by 20 mm.
    * **Orientation, in order and NOT sorted.** The first version of this
      compared `sorted` spans so that it would not care which way round a part
      was. That made it blind to the one mistake it most needed to catch:
      EAGLE lays a `1X10` along x and KiCad lays a `PinHeader_1x10` along y, so
      every header on the Uno was placed across the board and the check said
      nothing, because 22.86 x 2.54 sorts the same as 2.54 x 22.86.
    * **Mounting.** A through-hole model on surface-mount pads is a different
      part in the right place, whatever its footprint measures. `Y2` on the Uno
      is a 3.20 x 1.60 mm surface-mount resonator -- read off the vendor's own
      silkscreen -- and KiCad's only three-pin resonators are 7 mm
      through-hole cans 12.5 mm tall. The size check passed it, because 7 mm
      against 2 mm of pads is inside a tolerance that has to allow a body wider
      than its pins. Mounting is what tells them apart, and a mesh says which
      it is by whether it has anything below the board.
    """
    x0, y0, x1, y1 = element.pad_extent()
    pads = (x1 - x0, y1 - y0)
    span = footprint(box, turn, element)

    if mesh is not None:
        # **A plated hole in a pad's own copper is a via in that pad** and
        # not a hole for a leg (OH-195): Olimex drill one through the middle
        # of the ESP32-C3-MINI-1's ground pad.
        through = any(not via_in_pad(pad, element)
                      for pad in element.pads_of("thru_hole"))
        legged = bool(leads_of(mesh))
        if through and not legged:
            return ("the element has through-hole pads and the model has "
                    "nothing below the board, so it is a surface-mount part")
        if not through and legged:
            return ("the element has only surface-mount pads and the model "
                    "has legs below the board, so it is a through-hole part")
    for axis, (mesh_side, pad_side) in enumerate(zip(span, pads)):
        which = "x" if axis == 0 else "y"
        if mesh_side < pad_side - SPAN_TOLERANCE_MM:
            return (f"turned as the table says, the model spans "
                    f"{span[0]:.2f} x {span[1]:.2f} mm and the pads it must "
                    f"cover span {pads[0]:.2f} x {pads[1]:.2f} -- it is "
                    f"{pad_side - mesh_side:.2f} mm too short in {which}")
        if mesh_side > pad_side + SPAN_TOLERANCE_MM * 4:
            return (f"turned as the table says, the model spans "
                    f"{span[0]:.2f} x {span[1]:.2f} mm against pads spanning "
                    f"{pads[0]:.2f} x {pads[1]:.2f} -- it is "
                    f"{mesh_side - pad_side:.2f} mm too long in {which}")
    return None


#: The gold and brass a KiCad model gives a plated contact.
#:
#: **Colour is the vendor's statement about a material here**, which is the
#: whole basis of `tools/import_3d_model.py`, so reading "these triangles are
#: the plated contacts" off it is the same kind of reading as "this face is
#: solder mask". Every value was taken from a shipped mesh rather than chosen.
CONTACT_COLOURS = frozenset({"#b58136", "#ebbc51", "#edbe51", "#e7c863"})

#: A part needs this many surface-mount pads before its turn is decided by
#: where its contacts land.
#:
#: Two pads cannot say which way round a part is -- a chip capacitor is the
#: same part rotated -- and neither can four in a square. Eight in a row is a
#: pin field, and a pin field has an orientation. The USB-C has sixteen.
TURN_FROM_CONTACTS_PADS = 8


def contact_miss(element: eagle.Element, put: Mesh,
                 centre: tuple[float, float]) -> float | None:
    """How far the model's plated contacts land from the pads they solder to.

    `None` when the part has too few surface-mount pads to have a facing, or
    when its model states no contact colour.

    **This is what decides which way a part faces, and until OH-107 nothing
    did.** `confirm` measures a model against the pads and `silk_miss`
    measures its body against the vendor's drawing; neither can see a half
    turn, because a span and a centre both survive one. So `Component.turn`
    was the only claim in `CORRESPONDENCE` that was taken on trust -- and the
    USB-C was turned wrongly three times running, by three people looking at
    pictures.

    A receptacle's contacts leave at its back and solder to pads. The
    footprint says where those pads are and the model says where its contacts
    are, so putting one on the other is two vendor sources agreeing, with no
    judgement in between. On the four composed boards the right turn wins by a
    factor of two to five.
    """
    pads = [pad for pad in element.pads if pad.kind == "smd"]
    if len(pads) < TURN_FROM_CONTACTS_PADS:
        return None
    plated = [(positions[at], positions[at + 2])
              for colour, (positions, _n, _i) in put.groups.items()
              if colour in CONTACT_COLOURS
              for at in range(0, len(positions), 3)]
    if not plated:
        return None
    #: Into the scene's frame, where `place` has already put the mesh: x is
    #: unchanged and z is the board's y negated.
    #:
    #: **That negation is currently unobservable** and is kept anyway: every
    #: part this runs on has a contact field centred on the board's own y, so
    #: the centroid's z is within 0.044 mm of zero on all four boards and a
    #: sign flip moves it less than the margin. A mutation removing it
    #: survives, which is a property of these parts rather than a gap in the
    #: tests -- recorded so nobody hunts it twice. A connector mounted off the
    #: centre line would expose it immediately.
    want = (sum(p.x_mm for p in pads) / len(pads) - centre[0],
            -(sum(p.y_mm for p in pads) / len(pads) - centre[1]))
    got = (sum(p[0] for p in plated) / len(plated),
           sum(p[1] for p in plated) / len(plated))
    return math.dist(got, want)


#: How much better the stated turn has to be than the next one before it is
#: believed to be a choice rather than a coin toss.
#:
#: On the four composed USB-C sockets the right turn beats the runner-up by
#: 0.94 to 2.64 mm, so 0.3 is loose against every case that exists and still
#: refuses the three wrong answers this part has been given.
TURN_MARGIN_MM = 0.3

#: How far a placed body may sit from where the vendor drew it before the
#: placement is refused. A body and a silkscreen are different outlines -- one
#: is the part and one is a drawing of where it goes -- so they do not agree
#: exactly. 1.5 mm is loose against the 0.40 mm worst case among the fourteen
#: parts that were right, and tight against the 7.50 mm of the one that was not.
#:
#: **This is the only tolerance now, and there was a second one until OH-102.**
#: `BODY_ALLOWANCE_MM` was a per-package admission that the model was A
#: DIFFERENT PART from the one the vendor fitted -- 2.3 mm for the USB-C's
#: four-tab land and 1.6 for its two-lock one, because KiCad's only two 16-pin
#: receptacles are 0.43 and 3.15 mm longer than the 7.35 Seeed state. Modelling
#: the part they name emptied it, so it is gone rather than left standing at
#: zero entries: the misses are 0.275 and 0.350 mm now, against a bare 1.5.
#:
#: **If one is ever needed again, key it by PACKAGE and not by board**, and
#: measure it against the body the vendor drew rather than the one this tool
#: reads -- the first version of that table was calibrated against an `F.Fab`
#: outline with a cable keep-out unioned into it, and was therefore excusing
#: the very connector that was a quarter turn out. It landed on its first
#: outing, and its C6 entry was still quoting the pre-OH-105 figure of 2.215
#: when the real miss had been 0.500 for a day.
SILK_TOLERANCE_MM = 1.5


def silk_miss(element: eagle.Element, put: Mesh,
              centre: tuple[float, float]) -> float | None:
    """How far the placed mesh sits from the body the vendor drew, in mm.

    `None` where the package has no silkscreen and there is nothing to compare.

    **This is the check that knows which way a part faces**, and it exists
    because nothing else did. `confirm` measures a model against the pads, and
    `place` anchors it on them -- both of which are blind to a part turned
    180 degrees, because a pin field is very often symmetric about its own
    centre. The Arduino Uno's barrel jack was exactly that: every earlier check
    passed while its barrel pointed into the board instead of out over the
    edge, 7.50 mm from where Arduino's own silkscreen puts it.

    The silkscreen is the vendor saying where the body goes, in the same file
    as the pads and transformed the same way, so this compares two things that
    both came from the vendor and neither from a table written here.
    """
    if element.silk is None:
        return None
    x0, y0, x1, y1 = element.silk
    spelling = ("MR" if element.mirrored else "R") + str(int(element.rotation))
    corners = [eagle.place(cx, cy, (element.x_mm, element.y_mm), spelling)
               for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    drawn_x = [c[0] for c in corners]
    drawn_y = [c[1] for c in corners]

    # Back out of the scene's frame into the board's, undoing only the centring
    # and the z flip -- so a sign error in `place` shows up here rather than
    # cancelling.
    mesh_x = [p[at] + centre[0]
              for _c, (p, _n, _i) in put.groups.items()
              for at in range(0, len(p), 3)]
    mesh_y = [-p[at + 2] + centre[1]
              for _c, (p, _n, _i) in put.groups.items()
              for at in range(0, len(p), 3)]
    return max(
        abs((min(drawn_x) + max(drawn_x)) / 2 - (min(mesh_x) + max(mesh_x)) / 2),
        abs((min(drawn_y) + max(drawn_y)) / 2 - (min(mesh_y) + max(mesh_y)) / 2),
    )


#: How far off the centre of its own body a curved silkscreen feature has to
#: sit before it is read as a pin-1 marker, as a fraction of that body's size.
#:
#: **Curvature alone does not mean pin 1**, and the two cases that prove it are
#: on the same board. Arduino's `DIL28-3` draws the DIP notch at 0.500 of the
#: package's size from its centre and their `MLF32` draws the corner dot at
#: 0.453; their `PANASONIC_D` draws a can as two arcs whose centroid is the
#: origin to 0.000, and their `TS42` draws a button as two concentric circles
#: at 0.021. The KiCad footprints agree: five of them carry an `fp_circle` on
#: `F.Fab`, at 0.441 to 0.641. So the gap this number sits in is 0.021 to
#: 0.441, and 0.15 is loose against both sides of it.
MARK_OFFSET_FRACTION = 0.15

#: The cell a placed vertex is counted in when a mesh is compared with itself
#: half-turned. A tenth of a millimetre is finer than any feature this is
#: looking for and coarser than the tessellation, so two placements of the
#: same vertex land in the same cell.
TURN_CELL_MM = 0.10


def _turn_cells(put: Mesh) -> set[tuple[int, int, int]]:
    """A placed mesh's vertices, rounded onto a grid, as a set."""
    return {(round(positions[at] / TURN_CELL_MM),
             round(positions[at + 1] / TURN_CELL_MM),
             round(positions[at + 2] / TURN_CELL_MM))
            for _colour, (positions, _n, _i) in put.groups.items()
            for at in range(0, len(positions), 3)}


def half_turn_moves(mesh: Mesh, element: eagle.Element, turn: float,
                    thickness: float, centre: tuple[float, float]) -> float:
    """What fraction of a placed mesh a half turn moves.

    **Zero means the turn cannot matter**, and that is the common case rather
    than a failure: a 0201 capacitor IS the same part turned round, and so is
    every pin header on the Arduino Uno. A package that comes out at exactly
    0.0000 is one whose half turn is not a claim that can be wrong, and
    nothing needs to check it; `compose` counts the rest.

    `place` is called rather than a separate model of what a turn does, so
    this measures the half turn the composer would actually apply.
    """
    here = _turn_cells(place(mesh, element, turn, thickness, centre))
    half = _turn_cells(place(mesh, element, (turn + 180.0) % 360.0,
                             thickness, centre))
    span = max(len(here), len(half))
    return len(here ^ half) / span if span else 0.0


def mark_of(element: eagle.Element) -> tuple[float, float] | None:
    """Where the vendor's own pin-1 marker lands on the board, or None.

    `None` where they draw none, where there is no body to measure it
    against, or where what they drew is not off-centre enough to be a marker
    at all -- see `MARK_OFFSET_FRACTION` for that last one and the two
    packages on the Arduino Uno that make it necessary.

    Transformed by `eagle.place` with the element's own spelling, which is
    what `silk_miss` does to the body: the marker and the body come out of the
    same file and have to be moved the same way as the pads.
    """
    if element.mark is None or element.silk is None:
        return None
    x0, y0, x1, y1 = element.silk
    size = max(x1 - x0, y1 - y0)
    if size <= 0:
        return None
    middle = ((x0 + x1) / 2, (y0 + y1) / 2)
    if math.dist(element.mark, middle) / size < MARK_OFFSET_FRACTION:
        return None
    spelling = ("MR" if element.mirrored else "R") + str(int(element.rotation))
    return eagle.place(element.mark[0], element.mark[1],
                       (element.x_mm, element.y_mm), spelling)


def mark_turns(element: eagle.Element, mesh: Mesh, thickness: float,
               centre: tuple[float, float]) -> dict[float, float] | None:
    """How far the model's own asymmetric feature lands from the vendor's
    pin-1 marker, at each of the four turns. `None` when nothing to compare.

    **This is what sees a half turn on a part the contacts cannot speak
    for.** `contact_miss` needs a pin field of plated metal and decides the
    USB-C; a DIP, a QFN and a land-grid array have no such field, and until
    this existed `silk_miss` was all they had -- and `silk_miss` compares
    CENTRES, which a half turn preserves. Twenty placements moved under a half
    turn with nothing able to see it.

    **Neither side of the comparison is a table written here.** The marker is
    the vendor's, read off their own footprint; the feature is the model's
    own, found by asking which of its vertices a half turn moves and where
    they are. The feature is not named and does not need to be: on the DIP it
    is the notch in the top of the body, 1.5 x 0.8 mm of `#050505` at the end
    Arduino draw their notch at, and the rule would hold just as well if it
    were a bevel or a dimple.

    All four turns at once, because they cost four placements rather than
    eight: the answer for a turn needs the placement half a turn away, which
    is another of the four.

    Measured on the six packages this can run on, the stated turn against its
    nearest rival: DIL28-3 1.542 against 25.15, MLF32 0.158 against 3.27,
    USON8 0.142 against 1.79, QFN60 0.014 against 6.34, QFN48 0.015 against
    4.87, LGA14 0.231 against 1.95. Every one wins by more than a millimetre
    and a half, against a `TURN_MARGIN_MM` of 0.3.
    """
    want = mark_of(element)
    if want is None:
        return None
    placed = {turn: _turn_cells(place(mesh, element, turn, thickness, centre))
              for turn in (0.0, 90.0, 180.0, 270.0)}
    misses: dict[float, float] = {}
    for turn, here in placed.items():
        moved = here - placed[(turn + 180.0) % 360.0]
        if not moved:
            continue
        count = len(moved)
        # Out of the scene's frame and back into the board's -- x unchanged
        # and z the board's y negated, the same undoing `silk_miss` does.
        at = (sum(c[0] for c in moved) / count * TURN_CELL_MM + centre[0],
              -sum(c[2] for c in moved) / count * TURN_CELL_MM + centre[1])
        misses[turn] = math.dist(at, want)
    return misses or None


def turn_unseen(element: eagle.Element, mesh: Mesh, put: Mesh, turn: float,
                thickness: float, centre: tuple[float, float]) -> bool:
    """Whether a half turn would move this part and no check here would tell.

    **The four questions in the order they cost, cheapest first.** Do the
    contacts decide it; does a half turn move the mesh at all; does the vendor
    draw a pin-1 marker; and would `silk_miss` actually REFUSE the half turn.

    That last one is asked against `SILK_TOLERANCE_MM` rather than against
    some new tolerance of its own, because the question is not "does the
    number change" but "would the existing check reject it" -- and the
    tolerance is that check. The Arduino Uno's barrel jack moves its silk miss
    from 0.013 to 7.496 mm and its USB-B from 0.400 to 8.860, so both are
    caught by a check that was already there and neither belongs in this
    count.
    """
    if contact_miss(element, put, centre) is not None:
        return False
    if half_turn_moves(mesh, element, turn, thickness, centre) == 0.0:
        return False
    if mark_turns(element, mesh, thickness, centre) is not None:
        return False
    other = place(mesh, element, (turn + 180.0) % 360.0, thickness, centre)
    half = silk_miss(element, other, centre)
    return half is None or half <= SILK_TOLERANCE_MM


# --- the DIP variant's headers (OH-118) --------------------------------------

#: How far each header row sits from the module's centre, and it is the
#: vendor's own number: every one of Seeed's twelve `XIAO-*-DIP.kicad_mod`
#: footprints puts its two seven-pin through-hole rows at y = +/-7.62 --
#: measured across all twelve on 2026-08-30 -- which is the breadboard 0.6"
#: DIP convention, INBOARD of the castellations at +/-8.08. The published
#: `.kicad_pcb` is the SMD board and places no hole there, which is why these
#: rows have to be synthesized rather than read out of it.
DIP_ROW_OFFSET_MM = 7.62

#: Seven pins a row at the 0.1" pitch, from the same footprints.
DIP_ROW_PINS = 7
DIP_PITCH_MM = 2.54

#: The drill's finished pad, for the synthetic pads' own size. A judgement in
#: the same register as `BOARD_MASK`: the vendor's DIP footprint states 1.7 mm
#: pads on a 1.0 mm drill, and nothing here draws these pads anyway -- the
#: size only feeds `confirm`'s span arithmetic.
DIP_PAD_MM = 1.7


def dip_header_elements(header_pads) -> list[eagle.Element]:
    """The two header rows a XIAO DIP hangs below its board, as elements.

    **Placed relative to the castellation field the composer already has**,
    not read out of a file: the DIP footprint and the module footprint share
    an origin -- both are symmetric about the module's centre -- so the rows
    sit `DIP_ROW_OFFSET_MM` either side of that centre, along the field's
    SHORTER axis, which is the 15.24 mm the seven castellations per side span
    against the 17.78 mm between the two sides. Measured on all five composed
    boards: the field is axis-aligned on every one, so the shorter axis is a
    coordinate axis and no rotation has to be solved for.
    """
    xs = [pad.x_mm for pad in header_pads]
    ys = [pad.y_mm for pad in header_pads]
    centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    rows_along_x = (max(xs) - min(xs)) < (max(ys) - min(ys))
    made = []
    for side in (-1.0, 1.0):
        pads = []
        for step in range(DIP_ROW_PINS):
            along = (step - (DIP_ROW_PINS - 1) / 2) * DIP_PITCH_MM
            if rows_along_x:
                at = (centre[0] + along, centre[1] + side * DIP_ROW_OFFSET_MM)
            else:
                at = (centre[0] + side * DIP_ROW_OFFSET_MM, centre[1] + along)
            pads.append(eagle.Pad(
                number=str(step + 1), kind="thru_hole", x_mm=at[0], y_mm=at[1],
                width_mm=DIP_PAD_MM, height_mm=DIP_PAD_MM, net=None))
        made.append(eagle.Element(
            name=f"DIP{1 if side < 0 else 2}",
            library="composed",
            package="XIAO-DIP-1X07",
            pads=tuple(pads),
            x_mm=(centre[0] if rows_along_x
                  else centre[0] + side * DIP_ROW_OFFSET_MM),
            y_mm=(centre[1] + side * DIP_ROW_OFFSET_MM if rows_along_x
                  else centre[1]),
            # The synthetic package is DEFINED to run along x, like EAGLE's
            # own `1X07`; a board whose rows run along y says so here, the
            # same way a real element would.
            rotation=0.0 if rows_along_x else 90.0,
        ))
    return made


def anchor_of(element: eagle.Element, legged: bool) -> tuple[float, float]:
    """Where a mesh's own anchor has to land: the centre of the pads it IS.

    **Like against like, and that is the whole of it.** `place` anchors a
    through-hole model on its legs, because a barrel jack's body is entirely to
    one side of its pins; so the pads those legs go into are the through-hole
    ones, and comparing them against every pad on the footprint is comparing
    two different features. A surface-mount model has no legs, is anchored on
    its body, and its body sits over all of them.

    On a part whose pads are all of one kind -- every DIP, every header, the
    Uno's barrel jack and its USB-B -- the two answers are identical, which is
    why this was invisible until a part had both.

    **The USB-C is that part.** OH-101 found half of it: the RP2350's land has
    two board locks against the GCT model's four shell tabs, so `place` matched
    two different features and the connector slid 0.42 mm off the board edge.
    Giving it the two-lock Amphenol fixed the model and left the rule, and the
    rule is still wrong -- those two locks sit 4.75 mm from the contact row, so
    a model anchored on them lands 2.26 to 2.43 mm inboard of where it belongs
    on the three boards that use that land, and 0.31 to 0.34 on the other two.

    Extracted rather than left as an expression inside `place` for the reason
    OH-103's `body_allowance` was: a decision buried there is invisible to
    every test that has not got OpenCASCADE and a whole board, and a mutation
    to it survives the suite.
    """
    pads = element.pads_of("thru_hole") if legged else element.pads
    if not pads:
        raise SystemExit(
            f"{element.name} ({element.package}): its model has legs below the "
            f"board and the footprint places no through-hole pad for them to "
            f"go into, so there is nothing to anchor on. `confirm` refuses "
            f"this pairing before it gets here."
        )
    xs = [pad.x_mm for pad in pads]
    ys = [pad.y_mm for pad in pads]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def place(mesh: Mesh, element: eagle.Element, turn: float, thickness: float,
          centre: tuple[float, float], flip: bool = False) -> Mesh:
    """Move a component's mesh onto the board, the way its pads were moved.

    `tools/eagle.py`'s `place` mirrors in x, then rotates counter-clockwise,
    then translates -- an order checked there against routed copper. This does
    the same thing to a mesh, so a component lands exactly where the pads this
    repository already trusts put it.

    **`turn` happens first, before the mirror**, and the order is not
    arbitrary: it takes the KiCad model into the frame EAGLE's own package is
    drawn in, and everything after it is what EAGLE says to do to *that*. Turn
    after mirroring and a mirrored part comes out reflected in the wrong axis.

    **Anchored on the pads, not on either library's origin.** The two do not
    agree about where a package begins: KiCad puts a header's origin on pin 1,
    EAGLE puts it in the middle of the pin field, and `AD` -- a 1x06 whose pin
    1 is 6.35 mm from its element origin -- landed a full 2.54 mm off the end
    of the board because of it. Rather than a table of per-package offsets,
    which would be one more hand-kept thing to get wrong, the mesh's own
    footprint centre is put on the element's own pad centre. The pads are the
    one thing both libraries describe, which is what makes them the anchor.

    **The legs are the anchor when there are legs**, which removes the
    assumption this used to carry. Centring a body on its pads is right for a
    DIP and a header, whose shrouds are symmetric about their pins, and wrong
    for a barrel jack, whose barrel is entirely to one side: centred on its
    body, the jack sits a few millimetres too far into the board and its barrel
    stops short of the edge it is supposed to overhang.

    A through-hole model says where its own pins are -- they are the geometry
    below the board plane -- and that is exactly what the pads describe. So the
    anchor is the centre of the legs, and only a surface-mount model, which has
    none, falls back to the centre of the body.

    **And the pads it is put onto are the ones of that same kind**, which
    `anchor_of` is where it says so. A legged model against every pad on the
    footprint is the OH-101 mistake in general form.

    **An `OverPads` mesh is the third case: a model whose pads are not under
    the middle of its body** (OH-180). An ESP32 module's antenna overhangs its
    pad field by three millimetres, so centring its body on its pads draws it
    that far off. Its manufacturer's footprint says where its pads sit under
    it -- `pads_origin` -- and that point goes on the centre of every pad the
    element places, which is still pads on pads. It rides on the mesh rather
    than as an argument, so every check that places a model places this one
    the same way without being told.
    """
    origin = mesh.origin if isinstance(mesh, OverPads) else None
    spin = math.radians(turn)
    turn_cos, turn_sin = math.cos(spin), math.sin(spin)
    rot = math.radians(element.rotation)
    rot_cos, rot_sin = math.cos(rot), math.sin(rot)

    def turned(x: float, y: float) -> tuple[float, float]:
        # **`flip` is half a turn about the horizontal y axis** (OH-118): x is
        # negated here and z in the emission below, which together are a
        # PROPER rotation -- one negated axis alone would mirror the mesh, the
        # exact defect class OH-115 was. Applied before `turn` so that a
        # flipped part's stated turn means the same thing an unflipped one's
        # does.
        if flip:
            x = -x
        return (x * turn_cos - y * turn_sin, x * turn_sin + y * turn_cos)

    # The legs if it has any, the whole body if it has not. Measured off the
    # vertices rather than off the bounding box, so it is the same number the
    # placement below uses.
    legs = [] if origin is not None else leads_of(mesh)
    if origin is not None:
        mid_x, mid_y = turned(*origin)
    else:
        anchor_points = legs or [
            (positions[at], positions[at + 1])
            for _colour, (positions, _n, _i) in mesh.groups.items()
            for at in range(0, len(positions), 3)
        ]
        every = [turned(x, y) for x, y in anchor_points]
        mid_x = (min(p[0] for p in every) + max(p[0] for p in every)) / 2
        mid_y = (min(p[1] for p in every) + max(p[1] for p in every)) / 2

    anchor = anchor_of(element, bool(legs))

    def onto_board(x: float, y: float, direction: bool = False) -> tuple[float, float]:
        tx, ty = turned(x, y)
        if not direction:
            tx, ty = tx - mid_x, ty - mid_y
        if element.mirrored:
            tx = -tx
        return (tx * rot_cos - ty * rot_sin, tx * rot_sin + ty * rot_cos)

    #: **A MIRRORED element is on the underside too** (OH-180), and until the
    #: manifest boards no composed board stood a MODEL on one -- the Uno's one
    #: mirrored element, its GROUND jumper, is copper: EAGLE's `M` is the package
    #: turned over onto the bottom face, so its model hangs there exactly as a
    #: flipped one does. `onto_board` negates x for it; negating z as well is
    #: what makes the pair a turn rather than a reflection -- a reflection
    #: alone stood the QT Py's ESP32-C3 on the TOP of the board, inside out.
    #: Both at once is a part turned over twice, which is the right way up.
    under = flip != element.mirrored
    moved: dict[str, tuple[list[float], list[float], list[int]]] = {}
    for colour, (positions, normals, indices) in mesh.groups.items():
        out_positions: list[float] = []
        out_normals: list[float] = []
        for at in range(0, len(positions), 3):
            dx, dy = onto_board(positions[at], positions[at + 1])
            bx, by = anchor[0] + dx, anchor[1] + dy
            # KiCad z is up and rises from the board plane; glTF y is up and
            # the PCB's top face is at `thickness`.
            #
            # **A flipped part hangs from the board's UNDERSIDE**: its z is
            # negated -- the other half of the rotation `turned` starts -- and
            # its former bottom face, z = 0, comes to rest against glTF y = 0,
            # which is where the board's bottom face is. The solder tails,
            # which the raw mesh keeps below its own zero, end up proud of the
            # top face, which is what lets `carvePins` find them on the pads.
            lift = -positions[at + 2] if under else thickness + positions[at + 2]
            out_positions.extend((bx - centre[0], lift, -(by - centre[1])))
            # A normal is a direction, so it is turned but never translated.
            tnx, tny = onto_board(normals[at], normals[at + 1], direction=True)
            up = -normals[at + 2] if under else normals[at + 2]
            out_normals.extend((tnx, up, -tny))
        moved[colour] = (out_positions, out_normals, list(indices))
    return Mesh(moved)


def merge(*meshes: Mesh) -> Mesh:
    """One mesh from several, keeping the colour groups and reindexing."""
    groups: dict[str, tuple[list[float], list[float], list[int]]] = {}
    for mesh in meshes:
        for colour, (positions, normals, indices) in mesh.groups.items():
            into = groups.setdefault(colour, ([], [], []))
            base = len(into[0]) // 3
            into[0].extend(positions)
            into[1].extend(normals)
            into[2].extend(index + base for index in indices)
    return Mesh(groups)


def artwork(board: eagle.Board, ring: list[tuple[float, float]],
            thickness: float, centre: tuple[float, float], mask: str
            ) -> tuple[list[Mesh], dict[str, int]]:
    """The copper and the ink the vendor drew, and a tally of what was left.

    **Every composed board was a slab with boxes standing on it until this**,
    and the reason was not that the data was missing: Seeed's own board files
    carry 211 to 362 pads and 47 to 232 board-level silkscreen strokes each,
    all of which this project already parsed and none of which it drew. Put
    beside their own KiCad assembly export for the nRF54LM20A -- castellated
    barrels down both edges, copper under every part, outlines and letters --
    a composed XIAO looked like a different and much worse thing.

    Nothing here is invented. A pad is the vendor's own size at the vendor's
    own angle; a stroke is their line at their width. The two colours are
    judgements and say so, because a `.kicad_pcb` states neither -- a surface
    finish is a fabrication order and not a design file.
    """
    left: dict[str, int] = {}
    can_clip = convex(ring)

    def inside(shape: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """`shape` cut to the board, or emptied if it cannot be cut exactly."""
        if can_clip:
            return clipped_to(ring, shape)
        # A concave silhouette -- the Arduino Uno -- cannot be clipped by
        # half-planes without eating area that is inside the board. So a shape
        # that is wholly inside is kept and one that is not is dropped and
        # counted, rather than approximated. No Uno pad is affected: its
        # copper is all well within its outline.
        if all(point_in(ring, point) for point in shape):
            return shape
        left["outside a concave outline"] = (
            left.get("outside a concave outline", 0) + 1)
        return []

    front: list[list[tuple[float, float]]] = []
    back: list[list[tuple[float, float]]] = []
    for element in board.elements:
        for pad in element.pads:
            if pad.kind == "np_thru_hole":
                # A hole with no copper in it. Nothing solders to it and
                # nothing is drawn for it.
                left["np_thru_hole"] = left.get("np_thru_hole", 0) + 1
                continue
            shape = pad_outline(pad)
            if shape is None:
                left[pad.shape or "no shape"] = (
                    left.get(pad.shape or "no shape", 0) + 1)
                continue
            cut = inside(shape)
            if len(cut) < 3:
                continue
            if pad.front:
                front.append(cut)
            if pad.back:
                back.append(cut)

    ink: list[list[tuple[float, float]]] = []
    ink_back: list[list[tuple[float, float]]] = []
    for stroke in board.silk:
        shape = stroke_outline(stroke)
        if shape is None:
            left["zero-length stroke"] = left.get("zero-length stroke", 0) + 1
            continue
        cut = inside(shape)
        if len(cut) < 3:
            continue
        (ink_back if stroke.layer.startswith("B.") else ink).append(cut)

    #: The routing, and it is drawn in the board's OWN mask warmed toward the
    #: metal rather than in bare copper: a trace is under the soldermask and a
    #: pad is not, and drawing both gold is a picture of a board with no mask
    #: on it. Clipped like everything else, because a trace may run to a
    #: castellation on the edge.
    track: list[list[tuple[float, float]]] = []
    track_back: list[list[tuple[float, float]]] = []
    for stroke in board.traces:
        shape = stroke_outline(stroke)
        if shape is None:
            left["zero-length trace"] = left.get("zero-length trace", 0) + 1
            continue
        cut = inside(shape)
        if len(cut) < 3:
            continue
        (track_back if stroke.layer.startswith("B.") else track).append(cut)

    #: A via joins the two faces, so it is drawn on both. Tented -- covered by
    #: mask -- which is why it takes the same colour as a trace and not the
    #: copper of an exposed pad.
    holes = []
    for via in board.vias:
        ellipse = [(via.x_mm + via.diameter_mm / 2 * math.cos(step),
                    via.y_mm + via.diameter_mm / 2 * math.sin(step))
                   for step in (2 * math.pi * i / VIA_SIDES
                                for i in range(VIA_SIDES))]
        cut = inside(ellipse)
        if len(cut) >= 3:
            holes.append(cut)

    routed = mask_over_copper(mask)
    return ([flat(track + holes, thickness + TRACE_PROUD_MM, routed, centre, True),
             flat(front, thickness + COPPER_THICKNESS_MM, COPPER, centre, True),
             flat(ink, thickness + COPPER_THICKNESS_MM + SILK_THICKNESS_MM,
                  SILKSCREEN, centre, True),
             flat(track_back + holes, -TRACE_PROUD_MM, routed, centre, False),
             flat(back, -COPPER_THICKNESS_MM, COPPER, centre, False),
             flat(ink_back, -COPPER_THICKNESS_MM - SILK_THICKNESS_MM,
                  SILKSCREEN, centre, False)],
            {"pads front": len(front), "pads back": len(back),
             "ink front": len(ink), "ink back": len(ink_back),
             "track front": len(track), "track back": len(track_back),
             "vias": len(holes),
             "clipped to the outline": int(can_clip), **left})


def point_in(ring: list[tuple[float, float]], point: tuple[float, float]) -> bool:
    """Is this point inside the ring? Even-odd, by a ray along +x."""
    hit = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a[1] > point[1]) != (b[1] > point[1]):
            span = b[1] - a[1]
            if span and point[0] < (b[0] - a[0]) * (point[1] - a[1]) / span + a[0]:
                hit = not hit
    return hit


def compose(spec: Composition, deflection: float, check: bool) -> int:
    """Read, confirm, compose and write one board. Returns the byte count."""
    print(f"{spec.board}:")
    if not spec.layout.is_file() and spec.pcb_chip is not None:
        fetch_pcb(spec.pcb_chip)
    if not spec.layout.is_file():
        print(f"  SKIPPED: {spec.layout} is not fetched. Run: {spec.fetch_with}")
        return 3
    if spec.schematic is not None and not spec.schematic.is_file():
        print(f"  SKIPPED: {spec.schematic} is not fetched, and it is what says "
              f"which kind each passive is. Run: {spec.fetch_with}")
        return 3

    board = read_layout(spec.layout)
    # **The silhouette, and the cutouts said out loud.** The Uno is one closed
    # ring; a XIAO ESP32-C3 is its edge plus two 1.270 x 0.508 mm routed slots,
    # which `loop` alone reported as "the outline does not chain".
    ring, cutouts = outer(board.outline)
    if cutouts:
        print(f"  cutouts {len(cutouts)} not drawn: "
              + ", ".join(f"{max(p[0] for p in c) - min(p[0] for p in c):.3f} x "
                          f"{max(p[1] for p in c) - min(p[1] for p in c):.3f} mm"
                          for c in cutouts))
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    print(f"  outline {len(ring)} points, "
          f"{max(xs) - min(xs):.3f} x {max(ys) - min(ys):.3f} mm, "
          f"{len(ear_clip(ring))} triangles")

    # **Centred on the pads, not on the PCB.** `board3d.js` puts the model's
    # origin at the centre of the pad map's own extent; on a XIAO those agree
    # because the castellations are symmetric, and on an Uno they are 7.7 mm
    # apart. Centring on the PCB here would draw the whole board off to one
    # side of its own pad markers.
    header_pads = [pad for name in spec.headers
                   for pad in board.element(name).pads]
    hx = [pad.x_mm for pad in header_pads]
    hy = [pad.y_mm for pad in header_pads]
    centre = ((min(hx) + max(hx)) / 2, (min(hy) + max(hy)) / 2)
    print(f"  centre  on {len(header_pads)} header pads at "
          f"({centre[0]:.3f}, {centre[1]:.3f}) mm; the PCB's own centre is "
          f"({(min(xs) + max(xs)) / 2:.3f}, {(min(ys) + max(ys)) / 2:.3f})")

    pieces = [slab(ring, spec.thickness_mm, spec.colour, centre)]
    # **The copper and the ink, before any component stands on them**, so a
    # part's own body hides the pads under it exactly as solder does.
    drawn_art, tally = artwork(board, ring, spec.thickness_mm, centre,
                               spec.colour)
    pieces.extend(drawn_art)
    print("  artwork " + ", ".join(f"{k} {v}" for k, v in tally.items()))
    if board.silk_unread:
        print("  not ink " + ", ".join(f"{k} {v}" for k, v in board.silk_unread)
              + " -- text needs a font; the rest is a handful per board")
    if board.traces_unread:
        print("  not cu  "
              + ", ".join(f"{k} {v}" for k, v in board.traces_unread)
              + " -- inner layers are inside the laminate; a zone's fill is a "
                "keyhole polygon, see kicad._routing_of")
    drawn: list[str] = []
    #: A box around each placed component, for the renderer's wire physics.
    #: **Measured here because it is measured here already** -- the same
    #: vertices `silk_miss` and the overhang checks walk. A renderer that had
    #: to work these out itself would be re-deriving, from a mesh, numbers this
    #: tool had in its hand.
    solids: list[dict[str, object]] = []
    #: The subset of `drawn` whose mesh this project made rather than fetched.
    #: Carried separately all the way to the caption, because "KiCad's
    #: published meshes" stops being the whole truth the moment one is not.
    modelled: list[str] = []
    #: Placements whose turn IS observable -- a half turn moves the mesh -- and
    #: which nothing here can check, because the model has no plated pin field
    #: and the vendor drew no pin-1 marker. Counted and printed for the reason
    #: `Board.silk_unread` is: a gap that is measured is a gap somebody can
    #: close, and a gap that is silent is one nobody knows about. OH-106.
    unpinned: list[str] = []
    pad_top = spec.thickness_mm
    cache: dict[str, tuple[Mesh, object]] = {}
    # **The DIP variant's headers, which the published PCB does not place**
    # (OH-118). Synthesized here and composed exactly as a real element is --
    # `confirm` measures them, `place` anchors them on their own pads -- so
    # everything downstream treats them as the placements they stand for.
    extra = dip_header_elements(header_pads) if spec.dip_headers else []
    #: Placements with no model and no ABSENT entry -- until OH-125 these
    #: fell through a bare `continue`, which is the mechanism that let
    #: OH-119 and OH-122 sit unnoticed: the gap was not even a number.
    unmodelled: list[str] = []
    #: Placements that put down no pad at all (OH-180). Nothing is soldered to
    #: them, so no part stands there: every one on the manifest boards is ink
    #: -- a logo, a pin label, an ordering note -- or a bare hole. Counted
    #: rather than given an ABSENT entry apiece, because SparkFun's file alone
    #: places 63 pin labels, each its own package.
    padless: list[str] = []
    #: Each passive drawn, and which of its schematic's statements said what
    #: kind it is; and each part that schematic refuses (OH-187). Only for a
    #: board with a schematic to read -- the XIAOs compose as they always
    #: have.
    statements = statements_for(spec)
    kinds: dict[str, dict[str, str]] = {}
    kind_refused: list[tuple[eagle.Element, str]] = []
    for element in [*board.elements, *extra]:
        component, refused = drawn_from(
            element, statements,
            spec.schematic.name if spec.schematic is not None else "")
        if refused is not None:
            kind_refused.append((element, refused))
            continue
        said = statements.get(element.name) if statements is not None else None
        if (component is not None and said is not None
                and said.kind in PASSIVE_KINDS.values()):
            kinds[element.name] = {
                key: text for key, text in (("kind", said.kind),
                                            ("prefix", said.prefix),
                                            ("value", said.value),
                                            ("word", said.word))
                if text is not None}
        if component is None:
            if absent_why(element) is None:
                if element.pads:
                    unmodelled.append(f"{element.name} ({element.package})")
                else:
                    padless.append(element.name)
            continue
        said = contradiction(element, component)
        if said is not None:
            raise SystemExit(
                f"{spec.board}: {element.name} is a {element.package} and "
                f"CORRESPONDENCE gives it {component.library}/{component.model}, "
                f"but {said}. Fix the table rather than the words."
            )
        if component.slug not in cache:
            cache[component.slug] = component_mesh(component, deflection)
        mesh, box = cache[component.slug]
        complaint = confirm(element, box, component.turn, mesh)
        if complaint is not None:
            raise SystemExit(
                f"{spec.board}: {element.name} is a {element.package} and "
                f"CORRESPONDENCE gives it {component.library}/{component.model}, "
                f"but {complaint}. Fix the table rather than the tolerance."
            )
        put = place(mesh, element, component.turn, spec.thickness_mm,
                    centre, component.flip)
        # **A flip may not undo the vendor's mirror** (OH-193). `place` puts
        # a part under the board for a mirrored element -- the vendor's
        # statement of its side -- and for a row that flips it, which is for
        # the XIAO DIP headers the vendor's board file does not place. Each
        # is a half turn, so the two together are an XOR and a flipped row
        # on a mirrored element lands on top. This guard is that case: the
        # part is measured on the placed mesh's own height against the
        # board's mid-plane, and refused where it is not under the board
        # that a mirror or a flip put it under.
        heights = [value for positions, _n, _i in put.groups.values()
                   for value in positions[1::3]]
        below = (min(heights) + max(heights)) / 2 < spec.thickness_mm / 2
        if below != (element.mirrored or component.flip):
            raise SystemExit(
                f"{spec.board}: {element.name} ({element.package}) is "
                f"{'mirrored onto the underside by its board file' if element.mirrored else 'on top'}"
                f"{' and its row flips it' if component.flip else ''}, and it "
                f"is drawn on the {'underside' if below else 'top'}: a flip "
                f"on a mirrored element turns it back over. Fix the row's "
                f"flip rather than the side."
            )
        solids.append(box_around(element.name, put))
        # **The turn, checked the way the model and the place already are.**
        # Both other checks survive a half turn -- a span does and a centre
        # does -- so without this one `turn` is the only line in
        # `CORRESPONDENCE` taken on trust, and the USB-C was turned wrongly
        # three times running because of it.
        facing = contact_miss(element, put, centre)
        if facing is not None:
            rivals = []
            for other in (0.0, 90.0, 180.0, 270.0):
                if other == component.turn:
                    continue
                rival = contact_miss(
                    element, place(mesh, element, other, spec.thickness_mm,
                                   centre, component.flip), centre)
                if rival is not None:
                    rivals.append((rival, other))
            best = min(rivals, default=None)
            if best is not None and facing > best[0] - TURN_MARGIN_MM:
                raise SystemExit(
                    f"{spec.board}: {element.name} ({element.package}) is "
                    f"turned {component.turn:.0f}, which puts its contacts "
                    f"{facing:.3f} mm from the pads they solder to -- and "
                    f"{best[1]:.0f} puts them {best[0]:.3f}. The model says "
                    f"where its contacts are and the footprint says where "
                    f"their pads are; believe those rather than a picture."
                )

        # **And the turn again, for the parts the contacts cannot speak
        # for.** `contact_miss` needs a pin field of plated metal, so it
        # decides the USB-C and returns `None` for everything else on these
        # six boards. This reads the vendor's own pin-1 marker instead and
        # asks where the model's own asymmetric feature lands -- see
        # `mark_turns`, which is where the argument and the margins are.
        pointing = mark_turns(element, mesh, spec.thickness_mm, centre)
        if pointing is not None and component.turn in pointing:
            rivals = [(miss, turn) for turn, miss in pointing.items()
                      if turn != component.turn]
            best = min(rivals, default=None)
            stated = pointing[component.turn]
            if best is not None and best[0] <= stated - TURN_MARGIN_MM:
                # A rival turn wins by the margin: the turn is WRONG.
                raise SystemExit(
                    f"{spec.board}: {element.name} ({element.package}) is "
                    f"turned {component.turn:.0f}, which puts the model's own "
                    f"asymmetric feature {stated:.3f} mm "
                    f"from the pin-1 marker the vendor drew -- and "
                    f"{best[1]:.0f} puts it {best[0]:.3f}. Both of those come "
                    f"out of vendor files and neither out of CORRESPONDENCE, "
                    f"so believe them rather than a picture."
                )
            if best is not None and stated > best[0] - TURN_MARGIN_MM:
                # **Nobody wins by the margin, and that is a THIRD case**
                # (OH-124). OH-106's six packages all decided by 1.6 mm or
                # more, so "not a decisive win" and "a rival won" were the
                # same condition -- until the widened marker reader gave the
                # C3's U.FL a mark and its nearly four-fold-symmetric mesh
                # put every turn within 0.006 mm of every other. A margin
                # test on a symmetric mesh carries no information: the turn
                # IS observable and nothing here can check it, which is
                # exactly what the unseen count is for.
                unpinned.append(f"{element.name} ({element.package})")
        elif turn_unseen(element, mesh, put, component.turn,
                         spec.thickness_mm, centre):
            # Counted and printed rather than passed over: this part's turn IS
            # observable and nothing here can check it.
            unpinned.append(f"{element.name} ({element.package})")

        miss = silk_miss(element, put, centre)
        if miss is not None and miss > SILK_TOLERANCE_MM:
            raise SystemExit(
                f"{spec.board}: {element.name} ({element.package}) lands "
                f"{miss:.2f} mm from the body the vendor's own drawing puts "
                f"there, which is more than {SILK_TOLERANCE_MM} mm. Almost "
                f"always a `turn` that is 180 degrees out: the pins are "
                f"symmetric so every other check passes. Try the other three. "
                f"If the model is simply a different SIZE from the part they "
                f"fitted, the answer is to model the one they name -- see "
                f"tools/model_from_datasheet.py -- and not a wider tolerance "
                f"for every part on every board."
            )
        pieces.append(put)
        drawn.append(f"{element.name} ({component.model})")
        if component.modelled:
            modelled.append(f"{element.name} ({component.model})")
        # **How high a pad marker has to ride on THIS board.** A XIAO's pads
        # are castellations on the edge and a marker sits on the PCB. An Uno's
        # are inside a header shroud, so a marker left on the board is buried
        # by the very component that proves it is a header -- and a wire would
        # be dropped on a pin it cannot see. A person clips a lead to the PIN,
        # so the marker goes on the pin tip, and the tip is measured off the
        # header that is actually there rather than looked up.
        if element.name in spec.headers:
            pad_top = max(pad_top, max(
                value for _colour, (positions, _n, _i) in put.groups.items()
                for value in positions[1::3]))

    print(f"  drawn   {len(drawn)}: {', '.join(drawn)}")
    if modelled:
        print(f"  modelled {len(modelled)}: {', '.join(modelled)} "
              f"-- built here, not fetched; see tools/model_from_datasheet.py")
    if kinds:
        both = sum("prefix" in said and "value" in said for said in kinds.values())
        prefix = sum("prefix" in said and "value" not in said for said in kinds.values())
        value = sum("value" in said and "prefix" not in said for said in kinds.values())
        word = sum("word" in said for said in kinds.values())
        # What spoke, in each format's own terms: an EAGLE deviceset's prefix
        # and name, or a KiCad reference's letters and footprint library.
        kicad_file = spec.schematic.suffix == ".kicad_pcb"
        letters = "the reference's letters" if kicad_file else "the deviceset's prefix"
        named = "the footprint's library" if kicad_file else "the deviceset's name"
        print(f"  kinds   {len(kinds)} passive(s) drawn as the kind "
              f"{spec.schematic.name} states: {both} by {letters} and the "
              f"value, {prefix} by the {letters.split()[-1]} alone, {value} by "
              f"the value alone"
              + (f", {word} with {named} agreeing" if word else ""))
    if unmodelled:
        print(f"  no model {len(unmodelled)} placement(s) drawn as nothing, "
              f"with no ABSENT entry saying why: "
              + ", ".join(unmodelled[:8])
              + (" ..." if len(unmodelled) > 8 else ""))
    if padless:
        print(f"  no pads {len(padless)} placement(s) put down no pad, so no "
              f"part stands on them -- ink or a bare hole")
    if unpinned:
        print(f"  turn    {len(unpinned)} placement(s) a half turn would move "
              f"and nothing here can see: {', '.join(unpinned)}")
    print(f"  markers ride at {pad_top:.3f} mm, the top of the header pins; "
          f"the PCB's own top face is at {spec.thickness_mm:.3f}")
    # **A part refused and a pad with no part are two different gaps**, and
    # they are counted apart: the first is something a reader will look for
    # and not find, the second is drawn already as copper, ink or a hole.
    #: A part its schematic refuses is counted there and nowhere else, whatever
    #: its package: a not-fitted part is not absent for want of a model.
    stated_off = {element.name for element, _why in kind_refused}
    absent = [e for e in board.elements
              if absent_why(e) is not None and e.name not in stated_off]
    parts = [e for e in absent if NO_BODY not in ABSENT[e.package]]
    if parts or kind_refused:
        stated = ("" if spec.schematic is None else
                  f", and {len(kind_refused)} by what their own schematic states")
        print(f"  refused {len(parts) + len(kind_refused)} placement(s): "
              f"{len(parts)} of {len({e.package for e in parts})} package(s) "
              f"with no published model{stated} -- each with its reason")
    for label, group in (("absent ", parts), ("bodyless", [
            e for e in absent if NO_BODY in ABSENT[e.package]])):
        packages = sorted({e.package for e in group})
        if packages and label == "bodyless":
            print(f"  bodyless {len(group)} placement(s) of {len(packages)} "
                  f"package(s): copper, ink or a hole, with no body to draw")
        for package in packages:
            here = [e.name for e in group if e.package == package]
            print(f"  absent  {'/'.join(here)} ({package}): "
                  f"{ABSENT[package][:60]}...")
        if label == "absent ":
            for element, why in kind_refused:
                print(f"  refused {element.name} ({element.package}): {why}")

    whole = merge(*pieces)
    print(f"  mesh    {whole.triangles():,} triangles, "
          f"{len(whole.groups)} colours")
    # **The audit the importer already runs, on the files the composer makes**
    # (OH-120). The composer writes six of the twelve .glb files and every
    # copper, silkscreen and trace surface -- and its copper shipped at
    # DEFAULT_FINISH for a session because nothing printed the assignment
    # where somebody would see it.
    report_finishes(whole)
    if check:
        print("  write   skipped (--check)")
        return 0

    out = OUT / f"{_slug(spec.board)}.glb"
    size = write_glb(
        whole, out, spec.board, str(spec.layout.name),
        (max(xs) - min(xs), max(ys) - min(ys), spec.thickness_mm),
        extras={
            "composed": True,
            "board": spec.board,
            # **Where the PCB is, relative to this model's origin.** The origin
            # is the pad centre, because that is what `board3d.js` positions a
            # model by; on this board the PCB's own centre is 6.86 mm away from
            # it. Without this the wire collider -- which is a box around the
            # PCB -- would sit that far off the board it is meant to be.
            # Absent on every fetched model, where the two centres coincide,
            # and the renderer defaults it to zero for exactly that reason.
            "pcb_offset": [
                round((min(xs) + max(xs)) / 2 - centre[0], 4),
                round(-((min(ys) + max(ys)) / 2 - centre[1]), 4),
            ],
            # **How big the pad field is, in millimetres.** The page scales a
            # model by a constant 8 px/mm, which is what
            # `tools/import_board.py` generates a board JSON at -- and is not
            # what PICSimLab's Arduino Uno artwork is. That is about
            # 5.66 px/mm, so the model came out 41% too large and its headers
            # stood well outside their own pad markers. Handing over the span
            # lets the renderer divide one by the other and get the scale from
            # the two things that describe the same pads, rather than from a
            # constant that happens to be true of nine boards.
            # **For a DIP board, the span of the DIP FIELD and not the
            # castellations** (OH-118): the page's pad map is the vendor's DIP
            # footprint, and a span measured off a different pad field gave
            # `scaleFromPads` 121.9 px over 17.78 mm where the pixels were the
            # 15.24 mm axis -- every XIAO DIP model drawn 14% too small.
            # Along the row and across the rows -- (7-1) x 2.54 and
            # 2 x 7.62, and that both come to 15.24 is the vendor's own
            # coincidence, not an assumption.
            "pad_span": (
                [round((DIP_ROW_PINS - 1) * DIP_PITCH_MM, 4),
                 round(2 * DIP_ROW_OFFSET_MM, 4)]
                if spec.dip_headers else
                [round(max(hx) - min(hx), 4), round(max(hy) - min(hy), 4)]
            ),
            "pad_top": round(pad_top, 4),
            "pcb_colour": spec.colour,
            "pcb_colour_source": spec.colour_source,
            "geometry": spec.geometry,
            "components": (
                "KiCad kicad-packages3D, CC-BY-SA-4.0 with the library "
                "exception; fetched, not vendored"
                + "".join(sorted({
                    f"; and the manufacturer's own STEP, {component.url}"
                    for component in CORRESPONDENCE
                    if component.step is not None
                    and component.slug in cache}))
            ),
            "drawn": drawn,
            "modelled": modelled,
            "solids": solids,
            # **What was measured and NOT drawn, riding to the page**
            # (OH-125). The panel could only say "Not drawn: Y1, Y2" about
            # a board also missing its silkscreen text and dozens of
            # unmodelled placements -- the composer measured all of it and
            # the measurement stopped at stdout. A gap that is measured is
            # a gap somebody can close, and now a reader can see it too.
            "artwork": dict(tally),
            "not_drawn": {
                "ink": dict(board.silk_unread),
                "copper": dict(board.traces_unread),
                "cutouts": len(cutouts),
                "turn_unseen": unpinned,
                "unmodelled": unmodelled,
                "no_pads": padless,
            },
            "absent": [
                {"package": package, "why": why,
                 "elements": [e.name for e in absent if e.package == package]}
                for package, why in sorted(ABSENT.items())
                if any(e.package == package for e in absent)
            ] + [
                # A passive refused for its kind is refused alone, not its
                # package: the same land carries parts that are drawn.
                {"package": element.package, "why": why,
                 "elements": [element.name]}
                for element, why in kind_refused
            ],
            # Which kind each passive is drawn as, and what said so (OH-187).
            "kinds": kinds,
        })
    print(f"  write   {out.relative_to(REPO)}  {size:,} bytes")
    return size


def _slug(board: str) -> str:
    return board.replace(" ", "-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--board", help="one board; every composed one without it")
    parser.add_argument("--check", action="store_true",
                        help="report and write nothing")
    parser.add_argument("--deflection", type=float, default=DEFLECTION)
    args = parser.parse_args(argv)

    # A manifest row that is not composed says so, by name, every run.
    for board, why in MANIFEST_REFUSED.items():
        if args.board is None or args.board == board:
            print(f"{board}:\n  REFUSED {why}")
    if args.board in MANIFEST_REFUSED:
        return 2
    wanted = [spec for spec in COMPOSITIONS
              if args.board is None or spec.board == args.board]
    if not wanted:
        print(f"no composed board called {args.board!r}. Known: "
              f"{', '.join(spec.board for spec in COMPOSITIONS)}")
        return 2

    total = 0
    #: Boards whose files are not fetched. Each says so as it is reached and
    #: the rest compose; the run then ends 3, as a checker that could not
    #: find its source does, rather than passing quietly or stopping at the
    #: first (OH-191: a checkout holding the Uno's board file and not its
    #: schematic composed nothing at all).
    skipped: list[str] = []
    for spec in wanted:
        try:
            written = compose(spec, args.deflection, args.check)
        except Unavailable as exc:
            print(f"SKIPPED: OpenCASCADE is not installed ({exc}). "
                  f"pip install cadquery-ocp")
            return 3
        if written == 3:
            skipped.append(spec.board)
            continue
        total += written
    if not args.check and total:
        from tools.import_3d_model import write_index
        # **The composer's own list, not the importer's copy of it.** Every
        # board a `Composition` serves gets the same file, exactly as a XIAO's
        # DIP and SMD variants share one fetched mesh.
        index = write_index(tuple(
            (name, chip_for(spec.board), _slug(spec.board))
            for spec in COMPOSITIONS
            for name in (spec.board, *spec.serves)
        ))
        print(f"{total:,} bytes of glTF; index at {index.relative_to(REPO)}")
    if skipped:
        print(f"SKIPPED {len(skipped)} board(s), their files not fetched: "
              f"{', '.join(skipped)}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
