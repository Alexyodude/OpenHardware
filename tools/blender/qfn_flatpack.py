# OpenHardware - a QFN flat pack, modelled because nobody published one.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Run by `tools/model_from_datasheet.py`, which reads every dimension out of
# the vendor's own footprint and passes them in as JSON on argv, so that each
# number lives in one place with its source beside it. Nothing is typed here.
#
#   blender --background --python tools/blender/qfn_flatpack.py -- <spec.json>
#
# A path rather than the JSON itself, because Windows rebuilds a command line
# from a single string and a brace-and-quote argument does not survive.
#
# ## Why this file exists at all
#
# The XIAO RP2350's own processor is a QFN-60 in a 7 x 7 mm body on 0.4 mm
# pitch, and **no library anybody publishes has one**: KiCad's
# `Package_DFN_QFN` holds 191 files and not one 60-lead part, Raspberry Pi
# publish reference designs and no STEP for the chip, and Seeed ship a STEP
# beside two of their board files and not this one. So the board drew with a
# hole in the middle of it, which is the most conspicuous absence on any board
# here.
#
# **The nearest published part is `QFN-56-1EP_7x7mm_P0.4mm`** -- right body,
# right pitch, four leads short. It is not used, and that is the whole reason
# this file exists rather than a one-line table entry: drawing it would put
# `U4 (QFN-56...)` in the model's own parts list, which is a false statement
# about what is on the board.
#
# ## The geometry is the vendor's, except one number
#
# From Seeed's `QFN60-0.4-7X7X0.9MM` footprint, read at build time:
#
#     body          the `fp_rect` on F.Fab -- KiCad's own convention for a
#                   part's body outline -- which measures 7.000 x 7.000 mm
#     leads         60 pads, 0.6 x 0.18 mm, ring at +-3.400 mm, 15 a side
#     exposed pad   3.45 x 3.45 mm, centred
#     pin-1 mark    the `fp_circle` on F.Fab, r 0.127 mm
#
# The ONE dimension no geometry in that file carries is the height, and it is
# still Seeed's: their footprint is NAMED `QFN60-0.4-7X7X0.9MM` and the 0.9 is
# the last field of it. A QFN is a moulded slab whose height is the one
# dimension a land pattern cannot express, so a footprint states it in the
# name or nowhere.
#
# `terminal` is the second and last cited number and it is a DRAWING
# thickness, not a measurement -- see the spec for what it does and does not
# affect.

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

    moulding = material("moulding", tuple(spec["colours"]["moulding"]))
    lead = material("lead", tuple(spec["colours"]["lead"]))
    marked = material("mark", tuple(spec["colours"]["mark"]))

    body = spec["body"]
    bx0, bx1 = body["x"]
    by0, by1 = body["y"]
    height = body["height"]
    #: How tall a terminal is drawn. The ONLY thing this number decides: it is
    #: under the chip, the part is surface-mount so nothing hangs below the
    #: board, and it changes no span `confirm` measures.
    thick = spec["terminal"]

    box("moulding", bx0, bx1, by0, by1, 0.0, height, moulding)

    # **The leads' plan is entirely the vendor's**, with no drawing number in
    # it at all: each is that pad's own rectangle CLIPPED to the body. A QFN
    # land reaches past the moulding for the solder fillet -- 0.6 mm long
    # against a body edge 0.2 mm inside it -- so the intersection is exactly
    # the terminal face the plastic exposes, and it is computed rather than
    # inset by a guess.
    for index, pad in enumerate(spec["leads"]):
        x0 = max(pad["x"] - pad["w"] / 2, bx0)
        x1 = min(pad["x"] + pad["w"] / 2, bx1)
        y0 = max(pad["y"] - pad["h"] / 2, by0)
        y1 = min(pad["y"] + pad["h"] / 2, by1)
        if x1 <= x0 or y1 <= y0:
            # A pad entirely outside the body is not a terminal of it. Skipped
            # rather than clamped to nothing, which would emit a degenerate
            # box that reads as a stray face in the export.
            continue
        box(f"lead{index + 1}", x0, x1, y0, y1, 0.0, thick, lead)

    flag = spec["flag"]
    box("exposed_pad",
        flag["x"] - flag["w"] / 2, flag["x"] + flag["w"] / 2,
        flag["y"] - flag["h"] / 2, flag["y"] + flag["h"] / 2,
        0.0, thick, lead)

    # **The only feature that says which way round the part is.** Everything
    # above is four-fold symmetric, so a model built in the file's own y-down
    # frame would draw perfectly and put this dot in the opposite corner --
    # which is why `pack_geometry` negates y, and why the corner is a test.
    mark = spec["mark"]
    if mark is not None:
        bpy.ops.mesh.primitive_cylinder_add(
            radius=mark["radius"], depth=thick, vertices=16,
            location=(mark["x"], mark["y"], height))
        dot = bpy.context.active_object
        dot.name = "pin1"
        dot.data.materials.append(marked)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.wm.obj_export(filepath=spec["out"], export_materials=True,
                          export_selected_objects=True, forward_axis="Y",
                          up_axis="Z", global_scale=1.0)
    print(f"WROTE {spec['out']}")


main()
