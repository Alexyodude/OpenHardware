---
id: OH-99
title: The XIAO nRF54LM20A draws green because a STEP exporter's default was read
  as a colour
status: done
priority: P2
created: '2026-08-29'
---

CLAIMS NOTHING; OH-93's files, same reason as OH-97 and OH-98.

Twenty-two of the twenty-three boards with a model draw a dark board. **The
XIAO nRF54LM20A draws green**, and it is the only one, and the reason is a
default that this repository has already refused once from the other
direction.

## MEASURED

Its vendor STEP is a KiCad assembly export and holds the board as FOUR solids
-- `_PCB`, `_pad`, `_silkscreen`, `_soldermask` -- where every other XIAO mesh
holds one. In the built `nRF54LM20A.glb`:

    #1b1b1b   3,706 verts   x -10.477..10.477  y  0.000..1.510  z -8.890..8.890
    #143324  15,006 verts   x -10.477..10.477  y -0.050..1.560  z -8.890..8.890

So `BOARD_MASK` reached the PCB solid correctly -- `pcb_solid()` identified it,
and it spans the stated 20.955 x 17.780 x 1.510 mm exactly. The green is the
SEPARATE soldermask solid: the same footprint to the micron, 0.05 mm proud on
each face. A film over the board, which is what a solder mask is, and it is
what a reader sees.

## THE POINT: IT IS THE SAME NON-STATEMENT OH-97 ALREADY RULED ON

`#143324` is styled, so `colour_key(styled, is_board)` keeps it -- correctly,
under the rule OH-97 settled: **a face the vendor DID colour is untouched.**

But the vendor did not colour it. Their own project file says so:

    XIAO nRF54LM20A.kicad_pro    "pcb_color": "rgba(0, 0, 0, 0.000)"

**Alpha zero is KiCad's UNSET**, which is the exact reading OH-97 established
and refused to treat as a claim of black. The same file that proves nobody
stated a colour is what makes the green in the STEP the EXPORTER's default
rather than the vendor's statement. OH-97 declined to invent a fact out of
that default; this draws one out of the same default, through a different
tool.

## WHY IT WAS NOT FIXED IN OH-93 5.1

Because the fix reverses a stated invariant and deserves the care OH-97 got,
not a quiet edit at the end of a long change. Overriding `#143324` means
overriding a colour the file DOES carry, which is the first time this
repository would do that, and
`test_the_unstyled_colour_is_given_no_material`'s companion rule -- "a face
the vendor DID colour is untouched" -- has to be re-argued rather than
side-stepped.

## WHAT THE SHAPE PROBABLY IS

The identification is unusually cheap here and should be said out loud rather
than inferred from a colour: a solid whose x/z footprint matches the PCB
solid's to a tight tolerance, which is thinner than it and straddles it, is
the mask ON that PCB -- the same shape-based argument `pcb_solid()` already
makes, extended by one solid. The silkscreen is distinguishable by the same
measurement (`#ffffff` spans x -9.972..10.083, which is NOT the board's
footprint) and must stay put.

What would settle it without any of this: Seeed setting a `pcb_color` with a
non-zero alpha, or somebody measuring a real board. Recorded so the judgement
can be retired rather than inherited -- the same sentence OH-97 ends with, for
the same reason.

## DONE WHEN

The nRF54LM20A draws the same board as the other twenty-two, or this ticket
records why green is right after all; the rule that decides it is written
where `BOARD_MASK` is; and a test covers a styled film over an unstyled board
so the next four-solid export does not re-open it.

## DONE, 2026-08-30, in 4c80cd2

The board draws `BOARD_MASK` like its twenty-two siblings. `is_mask_film`
identifies the film by shape and never by colour; `colour_key` gained the one
case where a stated colour loses, and it is the only one.

**Two things above are wrong and the measurement is recorded here rather than
edited into them, because both were plausible and both cost a reader time.**

  * **It is not four solids.** The STEP holds 794, and the mask is not one of
    them: it is TWO LOOSE FACES belonging to no solid at all. The four names
    `_PCB`, `_pad`, `_silkscreen`, `_soldermask` are real and are what the
    claim came from, but they are XCAF labels rather than the topology.
  * **The footprint claim was right and the thickness one was not.** The films
    carry the PCB's x and y to 0.0000 mm, which is what "the same footprint to
    the micron" says. They are NOT "thinner than it and straddling it": each is
    a sheet at a single z, one 0.05 mm above the board's top face and one 0.05
    below its bottom. A bounding-box straddle test would have found the board's
    own rim as well, which is why both ends of a face are measured against the
    SAME plane.

**And the citation this ticket rests on is the wrong field.** `pcb_color` sits
at `net_settings.classes[0]` in the `.kicad_pro`, beside `clearance`,
`track_width`, `via_drill` and a `schematic_color`. It is a NET CLASS colour --
how nets of that class are highlighted in the two editors, which is why it has
a schematic half at all. Its alpha zero is KiCad's UNSET, so it states nothing,
but it was never about the board and all nine Seeed project files carry the
identical default. OH-97 introduced the citation and this ticket inherited it.

**What replaces it is stronger.** Six of the seven Seeed board files carry a
full `(stackup ...)` -- six copper layers with thicknesses, five FR4
dielectrics with `epsilon_r` and loss tangent, `(copper_finish "None")`, and
both mask layers with `(thickness 0.01)` and no `(color ...)`. That is where
KiCad records a solder-mask colour. A vendor who completed that table and left
that one field empty did not state a colour, which is a far better absence than
an unopened file. The ESP32-C3 is the one board with no stackup at all, and it
is the board OH-97 measured.

So the invariant is narrowed rather than broken: *a face the vendor coloured is
untouched unless it is the solder-mask film on the board this module has
already identified by shape.* `#186b2a`, the RGB LED, is a real vendor colour
on a real part and a test asserts it survives.

Measured on the page against the running server, green excess over every
non-background pixel: before mean 2.20 / p90 10.00; after mean 0.09 / p90 0.00;
the MG24 sibling at the same camera mean 0.05 / p90 0.00. Frames are
`.playwright-mcp/oh99-lm20a-before.png`, `-after.png` and `oh99-mg24-sibling.png`
-- and the before frame shows the incoherence directly, a green top on a dark
rim.

Gate 1,850 -> 1,858 passed, 17 skipped. Seven mutations, all killed.
