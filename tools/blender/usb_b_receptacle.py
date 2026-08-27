# OpenHardware - a USB Series-B receptacle, modelled because nobody published one.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Run by `tools/model_from_datasheet.py`, which passes the dimensions in as
# JSON on argv so that every number lives in one place with its source beside
# it. Nothing is typed in here.
#
#   blender --background --python tools/blender/usb_b_receptacle.py -- <spec.json>
#
# A path rather than the JSON itself, because Windows rebuilds a command
# line from a single string and a brace-and-quote argument does not survive.
#
# ## Why this file exists at all
#
# `tools/compose_board_3d.py` draws a component only when it can fetch a real
# mesh of it, because a box of invented thickness is the defect this project
# keeps re-learning. The Arduino Uno's USB socket has no such mesh: KiCad's
# `Connector_USB` library has three USB-A, seven USB-C, a Micro-B and a Mini-B
# and no type B at all, and the manufacturer's own download sits behind a
# search this cannot reach. It is also the most recognisable thing on the board
# after the headers, so leaving it out is a visible hole.
#
# ## The geometry is the vendor's, except one number
#
# Everything in plan comes from Arduino's own EAGLE package `PN61729`: the
# body outline, all four signal pins and both shell posts, to three decimals.
# The ONE dimension no file in this repository carries is the height, and it
# is the USB specification's Series-B receptacle shell rather than a guess --
# the height is fixed by the standard, because a plug from any vendor has to
# fit a socket from any other.
#
# That distinction is why the part is marked `modelled` rather than composed:
# a reader deserves to know which numbers came from CAD and which from a
# drawing.

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
    choice -- the primitive spans -0.5..+0.5 and every box comes out at half
    the dimensions asked for. The first run of this file did exactly that and
    produced a tidy, symmetrical, wrong connector.
    """
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    cube = bpy.context.active_object
    cube.name = name
    cube.scale = ((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2)
    cube.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    cube.data.materials.append(made)
    return cube


def post(name, x, y, radius, z0, z1, made) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=(z1 - z0),
                                        vertices=12,
                                        location=(x, y, (z0 + z1) / 2))
    made_object = bpy.context.active_object
    made_object.name = name
    made_object.data.materials.append(made)
    return made_object


def main() -> None:
    handover = sys.argv[sys.argv.index("--") + 1:][0]
    with open(handover, encoding="utf-8") as source:
        spec = json.load(source)
    body = spec["body"]
    clear()

    shell = material("shell", tuple(spec["colours"]["shell"]))
    cavity = material("cavity", tuple(spec["colours"]["cavity"]))
    pin = material("pin", tuple(spec["colours"]["pin"]))

    x0, x1 = body["x"]
    y0, y1 = body["y"]
    height = body["height"]
    wall = body["wall"]

    # The shell, as five plates rather than one solid: a receptacle is a folded
    # metal box and the opening has to go somewhere. Plates also keep the
    # normals outward without a boolean, which is the operation most likely to
    # behave differently between Blender versions.
    box("shell_top", x0, x1, y0, y1, height - wall, height, shell)
    box("shell_bottom", x0, x1, y0, y1, 0.0, wall, shell)
    box("shell_left", x0, x0 + wall, y0, y1, 0.0, height, shell)
    box("shell_right", x1 - wall, x1, y0, y1, 0.0, height, shell)
    box("shell_back", x0, x1, y1 - wall, y1, 0.0, height, shell)

    # The mouth: the dark recess a plug goes into. Inset from the front face so
    # the shell reads as a shell rather than as a painted rectangle.
    mouth = body["mouth"]
    box("cavity", -mouth["width"] / 2, mouth["width"] / 2,
        y0 + wall, y0 + wall + mouth["depth"],
        mouth["floor"], mouth["floor"] + mouth["height"], cavity)

    # The tongue the four contacts sit on, which is what makes the opening read
    # as a USB socket rather than an empty box.
    tongue = body["tongue"]
    box("tongue", -tongue["width"] / 2, tongue["width"] / 2,
        y0 + wall, y0 + wall + tongue["depth"],
        tongue["z"], tongue["z"] + tongue["thickness"], cavity)

    # Legs. **These are the load-bearing part of the whole file**: everything
    # below the board plane is what `compose_board_3d.leads_of` reads to decide
    # where the part's pins are, and therefore where the part goes. Their xy is
    # the vendor's own pad table, unaltered.
    depth = body["lead_depth"]
    for index, (x, y) in enumerate(spec["pins"]):
        box(f"pin{index + 1}", x - 0.3, x + 0.3, y - 0.3, y + 0.3,
            -depth, wall, pin)
    for index, (x, y) in enumerate(spec["posts"]):
        post(f"post{index + 1}", x, y, spec["post_radius"], -depth, wall, shell)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.wm.obj_export(filepath=spec["out"], export_materials=True,
                          export_selected_objects=True, forward_axis="Y",
                          up_axis="Z", global_scale=1.0)
    print(f"WROTE {spec['out']}")


if __name__ == "__main__":
    main()
