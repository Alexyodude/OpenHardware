# OpenHardware - a moulded package, drawn as the slab the vendor says it is.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Run by `tools/model_from_datasheet.py`, which reads the plan out of the
# vendor's `F.Fab` assembly outline and the height out of their own footprint
# name, and passes both in as JSON on argv. Nothing is typed here.
#
#   blender --background --python tools/blender/moulded_slab.py -- <spec.json>
#
# A path rather than the JSON itself, because Windows rebuilds a command line
# from a single string and a brace-and-quote argument does not survive.
#
# ## Why this file exists at all
#
# The XIAO ESP32-C6 and nRF54L15 draw a chip antenna 5.2 x 2 x 1.1 mm, which
# is the largest thing on either board after the USB socket and the processor.
# The RP2350 has two buttons and two RGB LEDs. The nRF54L15's own processor is
# a 47-ball wafer-level CSP. **No library publishes any of them** -- KiCad's
# RF_Antenna holds four models and none is 5.2 mm long; its smallest
# surface-mount switch is twice the size of Seeed's; its Package_CSP has no
# WLCSP-47 -- so the boards drew with holes where a person expects a part.
#
# ## The whole shape is the vendor's, which is why a slab is honest here
#
# A moulded package IS a slab. It is not a simplification of one, the way a
# USB receptacle would be: the plastic is a rectangular block, and what this
# leaves off is a lens or a port hole rather than a shape.
#
# Both numbers come from Seeed, and each checks the other:
#
#     plan     the `fp_rect`/`fp_line` on `F.Fab`, KiCad's assembly layer,
#              to three decimals
#     height   the last field of the footprint's own NAME -- the one
#              dimension a land pattern cannot express, so it is stated there
#              or nowhere
#
# The name states the plan too, and `slab_geometry` refuses the part when the
# two disagree by more than half a millimetre. That comparison is what makes
# reading dimensions out of a string safe: a name parsed wrongly misses by
# millimetres.

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


def main() -> None:
    handover = sys.argv[sys.argv.index("--") + 1:][0]
    with open(handover, encoding="utf-8") as source:
        spec = json.load(source)
    clear()

    made = bpy.data.materials.new(name="body")
    made.use_nodes = True
    made.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        *spec["colour"], 1.0
    )

    x0, x1 = spec["x"]
    y0, y1 = spec["y"]
    height = spec["height"]

    # `size=2.0`, so the primitive spans -1..+1 and a scale of the HALF extent
    # gives the whole one. With `size=1.0` -- which reads like the obvious
    # choice -- every box comes out at half the dimensions asked for; the
    # USB-B script records the run where that produced a tidy, symmetrical,
    # wrong connector.
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    cube = bpy.context.active_object
    cube.name = "body"
    cube.scale = ((x1 - x0) / 2, (y1 - y0) / 2, height / 2)
    # **z starts at the board and rises**, which is what `compose_board_3d`'s
    # `place` assumes: it adds the PCB thickness to every z it reads. A body
    # centred on z = 0 would sit half inside the board.
    cube.location = ((x0 + x1) / 2, (y0 + y1) / 2, height / 2)
    cube.data.materials.append(made)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.wm.obj_export(filepath=spec["out"], export_materials=True,
                          export_selected_objects=True, forward_axis="Y",
                          up_axis="Z", global_scale=1.0)
    print(f"WROTE {spec['out']}")


main()
