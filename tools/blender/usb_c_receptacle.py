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
import math
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


def obround(mid_y: float, mid_z: float, width: float, height: float,
            steps: int) -> list:
    """A stadium: a rectangle with a SEMICIRCLE at each end, counter-clockwise.

    **This is the shape of a USB Type-C connector and the whole of OH-114.**
    A reader called this part blocky, which a square-cornered box is: the
    Type-C interface is an obround whose ends are half-circles of radius half
    its height, and that pill is the single most recognisable thing about the
    connector -- it is why the plug is reversible and why nobody mistakes one
    for anything else.

    Nothing new is cited for it. The radius IS half the height, so the shape
    follows from dimensions this part already had: the shell's from Seeed's
    own 8.94 x 3.25 mm envelope, the opening's from the standard's 8.34 x
    2.56.
    """
    radius = height / 2
    flat = max(0.0, width / 2 - radius)
    points = []
    for end, centre in ((0, mid_y + flat), (1, mid_y - flat)):
        for step in range(steps + 1):
            angle = (-math.pi / 2 + math.pi * end) + math.pi * step / steps
            points.append((centre + radius * math.cos(angle),
                           mid_z + radius * math.sin(angle)))
    return points


#: How many segments each half-circle is drawn with. A Type-C shell is 3.25 mm
#: tall, so its end radius is 1.625 and eight segments put the chord within
#: 12 um of the arc -- a third of the copper on the board it stands on.
CAP_STEPS = 8


def ring(name, outer, inner, x_at, made) -> None:
    """The flat face between two closed profiles, at `x_at`. A frame."""
    verts = ([(x_at, y, z) for y, z in outer]
             + [(x_at, y, z) for y, z in inner])
    count = len(outer)
    faces = [[i, (i + 1) % count, count + (i + 1) % count, count + i]
             for i in range(count)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    made_object = bpy.data.objects.new(name, mesh)
    made_object.data.materials.append(made)
    bpy.context.collection.objects.link(made_object)


def skin(name, profile, x0: float, x1: float, made) -> None:
    """One closed profile swept from `x0` to `x1`: the wall of a tube."""
    verts = ([(x0, y, z) for y, z in profile] + [(x1, y, z) for y, z in profile])
    count = len(profile)
    faces = [[i, (i + 1) % count, count + (i + 1) % count, count + i]
             for i in range(count)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    made_object = bpy.data.objects.new(name, mesh)
    made_object.data.materials.append(made)
    bpy.context.collection.objects.link(made_object)


def cap(name, profile, x_at, made) -> None:
    """One closed profile filled, at `x_at`: the end of a tube."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(x_at, y, z) for y, z in profile], [],
                     [list(range(len(profile)))])
    mesh.update()
    made_object = bpy.data.objects.new(name, mesh)
    made_object.data.materials.append(made)
    bpy.context.collection.objects.link(made_object)


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
    # The body's own x is not read: the tube runs from `front_face` to
    # `back_face`, which are the same two numbers named for which end is
    # which. It was unpacked here while the shell was five boxes.
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

    # **The shell is a TUBE with a rounded section, not five flat plates.**
    # It was five, and a reader called the result blocky, which a
    # square-cornered box is: a Type-C connector's cross-section is an obround
    # whose ends are half-circles, and that pill is the most recognisable
    # thing about the part. Nothing new is cited for it -- the radius is half
    # the height, so the shape follows from the envelope Seeed state and the
    # aperture the standard fixes, both of which this part already had.
    mid = (by0 + by1) / 2
    outer = obround(mid, height / 2, by1 - by0, height, CAP_STEPS)
    inner = obround(mid, height / 2, opening["width"], opening["height"],
                    CAP_STEPS)
    ring("shell_lip", outer, inner, front, shell)
    skin("shell_outside", outer, front, back, shell)
    skin("shell_inside", inner, front, back - inward * side, shell)
    cap("shell_back", outer, back, shell)

    # The dark end of the inside, seen down the length of the cavity. A PANEL
    # and not a solid: filled, it would swallow the tongue, which is what the
    # USB-B's did until OH-113 found it.
    cap("cavity", inner, back - inward * side, cavity)

    # The tongue the contacts sit on, which is what makes the opening read as
    # a socket rather than a slot. Set back from the lip so it does not share
    # the one face anybody looks at, and given the insulator's own colour
    # rather than the cavity's so it is visible against it. Centred on the
    # BODY rather than on the origin, because a vendor's own outline is not
    # obliged to straddle its footprint's zero.
    tongue = spec["tongue"]
    box("tongue", front + inward * tongue["setback"], back - inward * side,
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
