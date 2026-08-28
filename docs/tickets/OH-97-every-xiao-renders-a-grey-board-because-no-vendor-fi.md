---
id: OH-97
title: Every XIAO renders a grey board because no vendor file states a mask colour
status: done
priority: P1
created: '2026-08-29'
touches: []
---

CLAIMS NOTHING, and OH-84's history is the reason. These files are OH-93's
territory while that ticket is open; this work landed inside it and a second
open claim on the same paths is a lock nobody is using. The precedent is
OH-84, filed claiming `tools/import_3d_model.py` and then blocking OH-81.

All ten XIAO boards draw a **neutral grey PCB**, and every real XIAO is black.
The composed ESP32-C3 (OH-93) is grey for the same reason the nine imported
ones are: nothing anybody publishes says what colour the board is.

## THE SEARCH, SO NOBODY REPEATS IT

  * **Seeed's own STEP files give the PCB `#808080`**, which is `UNSTYLED` --
    `tools/import_3d_model.py`'s marker for a face the vendor did not colour.
    On the RP2040 that is 16,682 of 18,723 vertices.
  * **Their KiCad project states none either.** `XIAO ESP32C3_v1.3.kicad_pro`
    holds `"pcb_color": "rgba(0, 0, 0, 0.000)"` -- **alpha zero, which is
    KiCad's UNSET**, not a claim that the board is black. Reading that as black
    would be inventing a fact out of a default.
  * **The `.kicad_pcb` has no `(stackup ...)` section**; the only solder-mask
    entries in 697 KB are `solder_mask_margin`, which is a clearance.
  * **The wiki says nothing.** `XIAO_ESP32C3_Getting_Started` and
    `SeeedStudio_XIAO_Series_Introduction` were fetched and searched for
    "black", "colour", "color", "matte", "glossy": zero mentions.

So there is no vendor statement to read. Whatever goes in is a judgement, and
the only honest thing is to label it as one.

## WHY THIS IS NOT SIMPLY OVERRIDING `UNSTYLED`

That constant carries a deliberate position, and a test:

> A face the vendor did not style is a face whose material nobody here knows,
> so giving it one would be exactly the pretending this constant exists to
> avoid. `test_the_unstyled_colour_is_given_no_material` is what keeps that
> true.

That is right and it stays. **The PCB solid is not an arbitrary unstyled
face.** `pcb_solid()` already identifies it -- by shape, as the largest area in
the board's own plane -- because the origin has to be the board's centre rather
than the assembly's. A face this tool has already NAMED as a printed circuit
board is one whose material is known: a PCB has solder mask.

So the narrow change is: the PCB solid's faces, and only those, and only when
the vendor left them unstyled, take a stated board colour. Every other
unstyled face stays grey and the existing test stays green.

## DONE WHEN

All ten XIAOs draw the same colour board; the value is one named constant with
its judgement written beside it and the four searches above recorded so nobody
repeats them; `test_the_unstyled_colour_is_given_no_material` still passes; and
a face the vendor DID colour is untouched.

What would settle it properly, and is not in scope: measuring a real board, or
Seeed stating a colour. Recorded so the judgement can be retired rather than
inherited.

## DONE, 2026-08-29

`BOARD_MASK = "#1b1b1b"`, applied to the PCB solid's own faces and nothing
else. All ten XIAOs draw the same board, and the value is dark grey rather
than black on purpose: a solder mask is a thin translucent film over copper
and glass-epoxy and never reaches the 0.2% reflectance `FINISHES` gives
moulded black epoxy at `#050505`. Sitting above that keeps the board a
different material from the chips standing on it, which anybody can check.

**Measured, on the rebuilt meshes**, the painted group against the PCB each
model states in its own extras:

    RP2040     x -10.50..10.50  y 0.00..1.20  z -8.75..8.75   stated 21.000 x 17.500 x 1.20
    ESP32-S3   x -10.48..10.48  y 0.00..1.25  z -8.89..8.89   stated 20.955 x 17.780 x 1.25

Everything standing ON the board stayed grey -- the RP2040's remaining
`#808080` reaches y 4.41 and x 11.50, which is the USB shell overhanging the
edge. That is the check that says the right solid was repainted, and it is now
a test over every shipped mesh rather than a thing I looked at.

`test_the_unstyled_colour_is_given_no_material` still passes untouched, which
was the point: `UNSTYLED` still means "nobody here knows what this is" for
every face that is not the board.

## THE BUG THIS COST, AND WHAT IT CHANGED

Rewriting `key = colour_of(...) or UNSTYLED` into an explicit `is None` check
broke the import of every board: `colour_of` answers `""` for a face styled
with nothing as well as `None` for one the file does not mention, and the
empty string went through as a colour key and reached `int("", 16)`.

**Nothing would have caught it.** The tests read the shipped `.glb`, which a
mutation does not regenerate, and `tessellate` needs OpenCASCADE and a 34 MB
download to run -- the same gap that hid the seam weld and the sRGB
conversion. So the decision is now `colour_key(styled, is_board)`, eight lines
with no OCC in them, and two tests drive it with `""` and `None`. The mutation
that survived until then is dead.

Byte-identical output before and after that extraction, checked by md5 on
`RP2040.glb` and `XIAO-ESP32-C3-DIP.glb`.

6 new tests; 8 mutations, 8 killed. Gate: 1,766 -> 1,772 passed, 17 skipped;
all eight checkers exit 0.
