# OpenHardware - a USB Type-C receptacle, modelled because both published
# ones are a different length from the part the vendor fitted.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Run by `tools/model_from_datasheet.py`, which reads every dimension out of
# Seeed's own footprint and passes them in as JSON, so that each number lives
# in one place with its source beside it. Nothing is typed here.
#
#   blender --background --python tools/blender/usb_c_receptacle.py -- <spec.json>
#
# A path rather than the JSON itself, because Windows rebuilds a command line
# from a single string and a brace-and-quote argument does not survive.
#
# ## Why this file exists at all
#
# KiCad's `Connector_USB` holds exactly two 16-pin receptacles and **both are
# longer than the one Seeed fit**, which shows on every composed XIAO as a
# connector reaching further inboard than the vendor's own assembly drawing
# puts it:
#
#     Seeed's own part          7.35 mm deep
#     GCT USB4105-xx-A_16P      7.78      (+0.43)
#     Amphenol 12401610E4-2A   10.50      (+3.15)
#
# There is no third to try, and the vendor names a part they do not publish --
# `USB-31C-F-16P-L7.35.stp` on the RP2350, `320011419_ST-USB-3316T.stp` on the
# nRF54L15 and the ESP32-C5.
#
# ## The geometry is the vendor's, except the opening
#
# **Seeed state the whole envelope in the footprint's own `Description`
# property**, which is the same kind of statement as the QFN's height in its
# footprint NAME and is more explicit:
#
#     SMD USB TYPE C-W/P;12+4P-7.35*8.94*3.25mm      the 16P land
#     SMD USB Type-c;12P+4-8.9*7.3*3.2mm             the four-tab land
#
# So the depth, the width AND the height are all read out of their file, and
# the plan is then checked against the `F.Fab` rectangle they drew -- two of
# their own sources, agreeing to 0.020 and 0.092 mm. The contacts, the shell
# feet and the board locks are their own pads, unaltered.
#
# The ONE thing that is not theirs is the opening a plug goes into, and it is
# the USB Type-C specification's: 8.34 x 2.56 mm, fixed by the standard rather
# than by a manufacturer for the same reason the Uno's USB-B shell height is --
# a cable from any maker has to enter a socket from any other. Everything the
# opening implies is then arithmetic on the vendor's own body, and not a
# number: the shell is (8.94 - 8.34) / 2 = 0.30 mm thick at the sides and
# (3.25 - 2.56) / 2 = 0.345 top and bottom, which is what a folded stainless
# receptacle shell measures.

import json
import sys

import bpy


def clear() -> None:
    """An empty scene. `--background` still opens the startup file."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.objects):
        for item in list(block):
            block.remove(item)


def material(name: str, colour: tuple) -> bpy.types.Material:
    made = bpy.data.materials.new(name=name)
    made.use_nodes = True
    made.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        *colour, 1.0
    )
    return made


def box(name, x0, x1, y0, y1, z0, z1, made) -> bpy.types.Object:
    """An axis-aligned box from two corners, in millimetres.

    `size=2.0`, so the primitive spans -1..+1 and a scale of the HALF extent
    gives the whole one. With `size=1.0` -- which reads like the obvious
    choice -- every box comes out at half the dimensions asked for; the USB-B
    script records the run where that produced a tidy, symmetrical, wrong
    connector.
    """
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    cube = bpy.context.active_object
    cube.name = name
    cube.scale = ((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2)
    cube.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    cube.data.materials.append(made)
    return cube


def main() -> None:
    handover = sys.argv[sys.argv.index("--") + 1:][0]
    with open(handover, encoding="utf-8") as source:
        spec = json.load(source)
    clear()

    shell = material("shell", tuple(spec["colours"]["shell"]))
    cavity = material("cavity", tuple(spec["colours"]["cavity"]))
    insulator = material("insulator", tuple(spec["colours"]["insulator"]))
    contact = material("contact", tuple(spec["colours"]["contact"]))

    body = spec["body"]
    bx0, bx1 = body["x"]
    by0, by1 = body["y"]
    height = body["height"]
    front = spec["front_face"]
    back = spec["back_face"]
    #: Which way "into the connector" points, so that one script draws a
    #: receptacle whose tails leave at either end. It is READ rather than
    #: assumed: the solder tails leave at the back, so the end the contacts
    #: are at is the back and the mouth is the other one. That is the same
    #: physical fact `compose_board_3d.contact_miss` rests on.
    inward = 1.0 if front < back else -1.0

    #: **The shell thickness is arithmetic, not a number.** The body is the
    #: vendor's and the opening is the standard's, so what is left over is the
    #: folded sheet between them -- 0.30 mm at the sides and 0.345 above and
    #: below on Seeed's own 8.94 x 3.25 mm envelope.
    opening = spec["opening"]
    side = ((by1 - by0) - opening["width"]) / 2
    lid = (height - opening["height"]) / 2

    # The shell, as five plates rather than one solid: a receptacle is a
    # folded metal box and the opening has to go somewhere. Plates also keep
    # the normals outward without a boolean, which is the operation most
    # likely to behave differently between Blender versions.
    box("shell_top", bx0, bx1, by0, by1, height - lid, height, shell)
    box("shell_bottom", bx0, bx1, by0, by1, 0.0, lid, shell)
    box("shell_left", bx0, bx1, by0, by0 + side, 0.0, height, shell)
    box("shell_right", bx0, bx1, by1 - side, by1, 0.0, height, shell)
    box("shell_back", back - inward * side, back, by0, by1, 0.0, height, shell)

    # The mouth: the dark recess a plug goes into, inset from the front face
    # so the shell reads as a shell rather than as a painted rectangle. Its
    # cross-section is the standard's opening and its depth is a drawing
    # quantity -- what is behind it is never seen through a 2.56 mm slot.
    depth = spec["mouth_depth"]
    box("cavity", front, front + inward * depth,
        by0 + side, by1 - side, lid, height - lid, cavity)

    # The tongue the contacts sit on, which is what makes the opening read as
    # a USB socket rather than an empty box. It runs from `setback` behind the
    # shell's lip to the back of the cavity, and it is given the insulator's
    # own colour rather than the cavity's: a paddle flush with the hole would
    # share the one face anybody looks at, and two coplanar surfaces fight for
    # it. Centred on the BODY rather than on the origin, because a vendor's
    # own outline is not obliged to straddle its footprint's zero.
    tongue = spec["tongue"]
    mid = (by0 + by1) / 2
    box("tongue", front + inward * tongue["setback"], front + inward * depth,
        mid - tongue["width"] / 2, mid + tongue["width"] / 2,
        (height - tongue["thickness"]) / 2,
        (height + tongue["thickness"]) / 2, insulator)

    # **The contacts, and they are the load-bearing part of the file.** Each
    # is the vendor's own pad rectangle clipped to the part of it the shell
    # does not cover -- the mirror of the rule `qfn_flatpack.py` uses, where
    # a QFN's terminal is its pad clipped TO the body because that is the
    # metal the moulding exposes. Here the metal outside the body is the
    # visible tail, so the clip is the other way round.
    #
    # `compose_board_3d.contact_miss` reads exactly these to decide which way
    # round the part goes, and the overhang test reads them to check that
    # nothing soldered hangs off the board, so their colour has to be one the
    # composer knows as a plated contact.
    thick = spec["terminal"]
    for index, tail in enumerate(spec["contacts"]):
        box(f"contact{index + 1}", tail["x"][0], tail["x"][1],
            tail["y"][0], tail["y"][1], 0.0, thick, contact)

    # The shell's own feet: surface-mount pads that are the shell folded down
    # onto the board rather than a signal. Steel, not gold, because that is
    # what they are -- and because giving them the contact colour would put
    # them into the turn measurement as if they were contacts.
    for index, foot in enumerate(spec["feet"]):
        box(f"foot{index + 1}", foot["x"][0], foot["x"][1],
            foot["y"][0], foot["y"][1], 0.0, thick, shell)

    # The board locks. **Everything below the board plane is what
    # `compose_board_3d.leads_of` reads to decide where the part's legs are,
    # and therefore where the whole part goes**, so their xy is the vendor's
    # own through-hole pad table, unaltered.
    for index, post in enumerate(spec["posts"]):
        box(f"post{index + 1}", post["x"][0], post["x"][1],
            post["y"][0], post["y"][1], -spec["post_depth"], lid, shell)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.wm.obj_export(filepath=spec["out"], export_materials=True,
                          export_selected_objects=True, forward_axis="Y",
                          up_axis="Z", global_scale=1.0)
    print(f"WROTE {spec['out']}")


main()
