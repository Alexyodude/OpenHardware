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
import itertools
import math
import pathlib
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
#: two ESP32-C6 modules KiCad's library does not hold (OH-180). Its LICENSE.md:
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
        "CT/CN0603", "Capacitor_SMD", "C_0603_1608Metric",
        "Z1 and Z2, the USB line varistors. Two pads 2.00 mm apart on an "
        "0603-sized land, and a multilayer varistor IS a ceramic chip in an "
        "0603 body -- the model is the body, borrowed from the capacitor "
        "that shares it. The PART is a varistor; only the moulding is a "
        "capacitor's, and both are ceramic blocks.",
    ),
    Component(
        "0805", "Inductor_SMD", "L_0805_2012Metric",
        "L1 and L2, the ferrites. Two pads 2.20 mm apart, an 0805 land, and "
        "the 2.0 x 1.25 mm chip body.",
    ),
    Component(
        "MINIMELF", "Diode_SMD", "D_MiniMELF",
        "D2 and D3. Two pads 3.40 mm apart along y, and a MiniMELF is the "
        "3.5 x 1.4 mm glass cylinder the package name states. The KiCad "
        "model runs along x where EAGLE's runs along y, hence the turn.",
        turn=90.0,
    ),
    Component(
        "SMB", "Diode_SMD", "D_SMB",
        "D1, the reverse-protection diode. Two pads 4.40 mm apart and the "
        "SMB (DO-214AA) body is 4.3 x 3.6 mm -- the package name is the "
        "JEDEC name the model uses.",
    ),
    Component(
        "L1812", "Capacitor_SMD", "C_1812_4532Metric",
        "F1, the resettable polyfuse. Two pads 3.90 mm apart along y on an "
        "1812 land, and the model is the 4.5 x 3.2 mm 1812 BODY -- borrowed "
        "from the capacitor library because KiCad's Fuse library stops at "
        "1210 (checked against GitLab's own tree, 28 files, 2026-08-30). A "
        "polyfuse is a rectangular chip; the PART is a fuse, only the "
        "moulding is a capacitor's, the same argument as Z1/Z2 above. EAGLE "
        "runs it along y.",
        turn=90.0,
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
        "1.93 mm, and the package name is the model's own.",
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
    # or nothing. This table already makes that trade twice, for Z1/Z2's
    # varistor and F1's fuse: the PART is a diode and only the moulding is
    # borrowed, which is a statement about a 0.6 mm brick with no marking on
    # it. Seeed themselves reached the same conclusion first: all seven
    # ESD-0201 placements name `Resistor_SMD/R_0201_0603Metric` in the
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
    Component(
        "0603-NO", "Resistor_SMD", "R_0603_1608Metric",
        "the Feather's 0603s: two pads 1.70 mm apart. Adafruit place nine "
        "resistors and two capacitors (C4, C10) on this one package from "
        "one library, and a package is what this table is keyed by, so the "
        "capacitors are drawn in the resistor's moulding -- the borrow Z1/Z2 "
        "make above, a 1.6 x 0.8 mm ceramic chip either way.",
    ),
    Component(
        "0805-NO", "Capacitor_SMD", "C_0805_2012Metric",
        "the 10 and 22 uF capacitors on both Adafruit boards, every one a "
        "capacitor by its value: two pads 1.90 mm apart, an 0805 land, and "
        "the 2.0 x 1.25 mm chip.",
    ),
    Component(
        "_0805MP", "Capacitor_SMD", "C_0805_2012Metric",
        "C12 on the Feather, 10 uF: two pads 2.03 mm apart, Adafruit's other "
        "0805 land, and the same 2.0 x 1.25 mm chip.",
    ),
    Component(
        "_0402NO", "Capacitor_SMD", "C_0402_1005Metric",
        "the QT Py's 0402s: two pads 1.02 mm apart. Adafruit place twelve "
        "capacitors and six resistors on this one package from one library, "
        "so the resistors are drawn in the capacitor's moulding, as the "
        "Feather's two capacitors are in a resistor's -- a 1.0 x 0.5 mm "
        "ceramic chip either way.",
    ),
    Component(
        "_0402", "Inductor_SMD", "L_0402_1005Metric",
        "L1 and L2 on the QT Py, the antenna match -- 2 nH and a 0-ohm link "
        "by their values: two pads 1.02 mm apart, an 0402 land, and the "
        "1.0 x 0.5 mm chip.",
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
        "CHG and D3 on the Feather: two pads 1.50 mm apart, an 0603 land, "
        "and the 1.6 x 0.8 mm LED. TURNED 270: Adafruit put the cathode pad "
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
        "five pads spanning 1.90 x 2.60 mm on all three manifest boards -- "
        "SparkFun's regulator and charger, Adafruit's AP2112 and MCP73831 -- "
        "which is the Uno's SOT23-DBV land stood on end, so the same model "
        "turned a quarter.",
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
        "Q1 on the QT Py, BOOT0: four pads spanning 4.10 x 1.60 mm, the "
        "same land as SparkFun's, and the package name is C&K's KMR2.",
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
        "CONN1 on the QT Py, the STEMMA QT port: four 1 mm-pitch contacts "
        "and two mounting pads spanning 5.60 x 3.90 mm, and a body Adafruit "
        "draw 6.1 x 4.25 mm -- the SM04B-SRSS-TB SparkFun's Qwiic port is.",
    ),
    Component(
        "QFN32_5MM", "Package_DFN_QFN",
        "QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm",
        "U2 on the QT Py, the ESP32-C3FH4 itself: thirty-three pads spanning "
        "4.90 x 4.90 mm, thirty-two leads round a 5 x 5 mm body and the "
        "exposed pad. The same chip and the same model as Seeed's C3.",
    ),
    Component(
        "LED3535_FULLPADS", "LED_SMD", "LED_WS2812B-Mini_PLCC4_3.5x3.5mm",
        "LED1 on the Feather, value WS2812B_3535FULL: four pads spanning "
        "3.40 x 1.75 mm and a body Adafruit draw 3.5 x 3.5 mm -- the WS2812B "
        "in its 3535 package, which is what this model names.",
    ),
)

#: Packages that are on the board, are worth seeing, and are NOT drawn -- with
#: the reason, which travels to the page. An empty reason would be worse than
#: the omission: a person looking at a board with no USB socket should be told
#: why rather than left to wonder whether the importer broke.
#: Two reasons that each cover a part appearing under two vendor spellings.
#: Bound here rather than repeated in `ABSENT`, which is keyed by the vendor's
#: package name and so has to hold both spellings.
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
        "2.54 mm pitch in two rows 20.32 mm apart, 38.10 mm long. SparkFun "
        "give it no PROD_ID, where every part they fit carries one, so the "
        "file places the holes and no header; the holes are drawn as copper. "
        "No KiCad library was searched: there is no body to look for."
    ),
    "1X16_ROUND": (
        "JP1 on the Feather, sixteen plated holes on 2.54 mm, 38.10 mm long, "
        "which Adafruit give no value -- as they give none to its solder "
        "jumper, and a value to every part they fit. The holes are drawn as "
        "copper. No KiCad library was searched: there is no body to look for."
    ),
    "1X12_ROUND": (
        "JP3 on the Feather, twelve plated holes on 2.54 mm, 27.94 mm long, "
        "with no value, as JP1. The holes are drawn as copper. No KiCad "
        "library was searched: there is no body to look for."
    ),
    "1X07_CASTEL": (
        "JP1 and JP3 on the QT Py: **the module's own castellated edge**, "
        "seven pads each on 2.54 mm, 15.24 mm long, with a plated hole in "
        "each. Copper and the board's edge, drawn by the copper pass. No "
        "KiCad library was searched: there is no body to look for."
    ),
    "FIDUCIAL-MICRO": (
        "four fiducials on the Thing Plus, each a bare 0.635 mm copper "
        "pad. No KiCad library was searched: there is no body to look for."
    ),
    "FIDUCIAL_1MM": (
        "two fiducials on each Adafruit board, each a bare 1.0 mm copper "
        "pad. No KiCad library was searched: there is no body to look for."
    ),
    "SMT-JUMPER_2_NC_TRACE_SILK": (
        "five solder jumpers on the Thing Plus -- SHLD, CHG, PWR, SD_DET, "
        "ALRT -- two 0.66 x 1.27 mm pads each, closed by a trace a person "
        "may cut. Copper, drawn as copper. No KiCad library was searched: "
        "there is no body to look for."
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
        "I2C on the Thing Plus: three 0.66 x 1.27 mm pads, the pull-ups' "
        "jumper. No KiCad library was searched: there is no body to look for."
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
    "MOUNTINGHOLE_2.5_PLATED": (
        "two mounting holes on the Feather, 2.5 mm drilled in a 3.2 mm "
        "plated ring. Copper and a hole, and nothing fitted. No KiCad library "
        "was searched: there is no body to look for."
    ),
    # And the parts: each names what was listed and what the nearest thing
    # in it was, so the next reader re-runs the search rather than retakes it.
    "USB-C-16P_4LAYER-PADS": (
        "J2 on the Thing Plus, the USB-C socket: twelve contact pads and "
        "four shell tabs spanning 8.64 x 4.76 mm. SparkFun's file names no "
        "maker for it -- only their own PROD_ID, CONN-14122 -- and KiCad's "
        "Connector_USB, 12 models listed 2026-09-29, holds two 16-pin "
        "receptacles, GCT's USB4105 and Amphenol's 12401610E4-2A, each a "
        "named part of its own length. Drawing either would put a maker's "
        "name on a part nobody here can say was fitted, the mistake OH-102 "
        "undid on the XIAOs."
    ),
    "USB_C_CUSB31-CFM2AX-01-X": (
        "the USB-C socket on both Adafruit boards, whose package name is the "
        "part: CUI's CUSB31-CFM2AX-01-X, twelve contact pads and four shell "
        "tabs spanning 8.64 x 4.76 mm. KiCad's Connector_USB, 12 models "
        "listed 2026-09-29, holds nothing of CUI's; its two 16-pin "
        "receptacles are GCT's and Amphenol's, and one of them on this land "
        "would be a different maker's part under Adafruit's name for this one."
    ),
    "JST-2-SMD": (
        "J3 on the Thing Plus, the battery socket, SparkFun PRT-08612: two "
        "1.0 x 4.6 mm contact pads 2.0 mm apart and two mounting pads, a "
        "surface-mount JST PH. KiCad's Connector_JST holds 30 PH models, "
        "listed 2026-09-29, and every one is the through-hole -K; `confirm` "
        "refuses a legged model on these pads anyway."
    ),
    "JSTPH2_BATT": (
        "X1 on the Feather, the battery socket: the same two 1.0 x 4.6 mm "
        "contacts 2.0 mm apart and two mounting pads as SparkFun's J3, a "
        "surface-mount JST PH, and KiCad's 30 PH models are all through-hole."
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
        "LED1 on the QT Py: four pads under a 1.5 x 1.5 mm body, an SK6805 "
        "in its 1515 package. KiCad's LED_SMD, 38 models, has no addressable "
        "LED under the 3.5 x 3.5 mm WS2812B-Mini."
    ),
    "DFN-8": (
        "U4 on the Thing Plus, the MAX17048 fuel gauge: eight 0.5 mm-pitch "
        "pads round a 1.38 x 0.80 mm exposed pad, 2 x 2 mm by SparkFun's "
        "tDocu. KiCad's five 2 x 2 mm eight-lead models state exposed pads "
        "of 0.6 x 1.2, 0.9 x 1.6, 0.9 x 1.7 and 1.05 x 1.75 mm or none, and "
        "a model's name that states the wrong pad is the near miss "
        "QFN-56 is refused for. Listed 2026-09-29 in Package_DFN_QFN and "
        "Package_SON."
    ),
    "TDFN8_2X2MM": (
        "X2 on the Feather, the same MAX17048 on Adafruit's land for it: a "
        "0.80 x 1.38 mm exposed pad, 2 x 2 mm, and the same five KiCad "
        "models, none of them this pad."
    ),
    "LONGAN-IC_SNR6-1.0-3X3X1MM": (
        "U4 on the Feather, an AHT20 humidity sensor by value: six pads on a "
        "1.0 mm pitch and no exposed pad, 3 x 3 x 1 mm by its own name. "
        "KiCad's Sensor_Humidity holds one model, TI's HDC2080, and the "
        "3 x 3 mm DFN-6 in Package_DFN_QFN is a 0.95 mm pitch round a "
        "1.7 x 2.6 mm pad. Listed 2026-09-29. The name states a height, but "
        "tools/model_from_datasheet.py builds slabs out of KiCad footprints "
        "and this is an EAGLE package."
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
}


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
        "colour": "#e2180f",
        "colour_source": (
            "SparkFun's own board file, which states it twice: a note on its "
            "tDocu layer reading 'Soldermask: Red', and a manufacturing-"
            "preview solder mask of 0xC8FF0000 -- red at alpha 200/255, "
            "where the Arduino Uno's file carries 0xC8008000, the value left "
            "when nobody sets one. Drawn as that preview draws mask over bare "
            "laminate: 0xFF0000 at that alpha over the file's own substrate "
            "colour, 0x786E46"
        ),
    },
}


def manifest_composition(entry: board_manifest.Row) -> Composition:
    """A `tools/board_manifest.py` row, as the composition it describes."""
    source = board_sources.source(entry.source)
    stated = MANIFEST_STATED.get(entry.board, {})
    return Composition(
        board=entry.board,
        layout=board_manifest.cad_path(entry),
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
        colour=stated.get("colour", BOARD_MASK),
        colour_source=stated.get("colour_source", (
            "BOARD_MASK, A JUDGEMENT rather than a reading: the board file's "
            "manufacturing-preview solder mask is 0xC8008000, which the "
            "Arduino Uno's own file also carries under a board this table "
            "draws navy -- the value EAGLE leaves when nobody sets one, not a "
            "statement"
        )),
    )


COMPOSITIONS = COMPOSITIONS + tuple(
    manifest_composition(entry) for entry in board_manifest.ROWS)



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
            # Into the Y-up frame first, then rotated in it, then placed.
            local_x, local_y = pad.x_mm, -pad.y_mm
            if placed.back:
                # A part on the underside is mirrored across the board's own
                # x axis, which is what makes its pad 1 land where the copper
                # is rather than diagonally opposite it.
                local_x = -local_x
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
                # of the same sign, and a part on the underside is mirrored
                # in x, which reverses the sense.
                rotation_deg=(-pad.rotation_deg if placed.back
                              else pad.rotation_deg),
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

        elements.append(eagle.Element(
            name=placed.reference or placed.library,
            library=placed.library.split(":", 1)[0],
            package=placed.name,
            pads=tuple(pads),
            x_mm=placed.x_mm,
            y_mm=-placed.y_mm,
            rotation=placed.rotation_deg,
            mirrored=placed.back,
            silk=silk,
            mark=mark,
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
    step = CACHE / f"component-{component.slug}.step"
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


def correspondence_for(element: eagle.Element) -> Component | None:
    """The `CORRESPONDENCE` row for this placement, or None.

    A row naming the element's own vendor library wins over one that names
    none, because the library is the vendor saying which part a shared package
    name is -- see `Component.vendor_library`.
    """
    fallback = None
    for component in CORRESPONDENCE:
        if component.package != element.package:
            continue
        if component.vendor_library == element.library:
            return component
        if component.vendor_library is None:
            fallback = component
    return fallback


def pads_origin(component: Component) -> tuple[float, float] | None:
    """Where the middle of the model's own pads is, in the model's own frame.

    None for a model from KiCad's library, which `place` anchors as it always
    has. For a manufacturer's model, read out of the manufacturer's footprint:
    the centre of its pads, taken back through the `(offset ...)` its one
    `(model ...)` block places this STEP with. KiCad's footprint y runs down
    the page and a model's y runs up it, so `y` is negated on the way.

    Refuses a footprint whose block also turns or scales the model, or that
    names some other file: this reads an offset and nothing else, and a
    rotated model read as a translated one would be placed wrongly and still
    look like a module.
    """
    if component.footprint is None:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    local = CACHE / f"component-{component.slug}.kicad_mod"
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
        through = bool(element.pads_of("thru_hole"))
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
    every pin header on the Arduino Uno. Measured on all six composed boards,
    23 of the 43 packages placed come out at exactly 0.0000 -- so for those a
    half turn is not a claim that can be wrong, and nothing needs to check it.

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
    #: manifest boards no composed board drew one: EAGLE's `M` is the package
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
    for element in [*board.elements, *extra]:
        component = correspondence_for(element)
        if component is None:
            if element.package not in ABSENT:
                if element.pads:
                    unmodelled.append(f"{element.name} ({element.package})")
                else:
                    padless.append(element.name)
            continue
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
    refused = [e for e in board.elements if e.package in ABSENT]
    if refused:
        print(f"  refused {len(refused)} placement(s) of "
              f"{len({e.package for e in refused})} package(s), each with its "
              f"reason:")
    for package, why in sorted(ABSENT.items()):
        here = [e.name for e in board.elements if e.package == package]
        if here:
            print(f"  absent  {'/'.join(here)} ({package}): {why[:60]}...")

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
                 "elements": [e.name for e in board.elements
                              if e.package == package]}
                for package, why in sorted(ABSENT.items())
                if any(e.package == package for e in board.elements)
            ],
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

    wanted = [spec for spec in COMPOSITIONS
              if args.board is None or spec.board == args.board]
    if not wanted:
        print(f"no composed board called {args.board!r}. Known: "
              f"{', '.join(spec.board for spec in COMPOSITIONS)}")
        return 2

    total = 0
    for spec in wanted:
        try:
            written = compose(spec, args.deflection, args.check)
        except Unavailable as exc:
            print(f"SKIPPED: OpenCASCADE is not installed ({exc}). "
                  f"pip install cadquery-ocp")
            return 3
        if written == 3:
            return 3
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
