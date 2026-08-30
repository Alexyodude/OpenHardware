---
id: OH-117
title: Two of the Arduino Uno's three GND pads are dropped by a Map keyed on label
status: done
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. `webui/static/board3d.js`, and it re-claims when it starts.

**Found while disproving OH-115, by counting.** `webui/boards/Arduino Uno.json`
holds 32 pads; the page's `view.pads` holds 30 keys. The two missing are GND:

    GND   x 163.0  y  16.1   pin 22   digital-high
    GND   x 243.5  y 288.2   pin  8   power
    GND   x 257.9  y 288.2   pin 22   power

An Uno really does have three, and the board file is right to list them.
`view.pads` is a `Map<pin, Mesh>` keyed by the LABEL, so the second and third
silently overwrite the first and only the last position keeps a pad.

## WHAT THAT COSTS

  * **Two of the three cannot be wired to.** A pad is the raycast target that
    starts a wire and the anchor its end follows; the two that were overwritten
    have neither, so a drag onto them does nothing and the reason is invisible.
  * A reader building the circuit OH-80 exists for reaches for whichever GND
    is nearest their part. Two times in three that is one that does not work.
  * `circuit.js` already gets this right -- "Three GND pads on an Uno are one
    net, which is what they are on the board" -- so the netlist is expecting
    pads the page never made.

## WHY IT IS NOT SIMPLY "KEY BY POSITION"

The map is read by `repaint`, `setLevels`, `anchorOf`, `describe`, `connect`
and the drag, and `connect(pin, ...)` takes a PIN NAME from outside the
module -- `webui/api.py` sends levels keyed by pin, and three GND pads share
one level because they share one net. So the key is right and the VALUE should
be a list: one net, several pads, all of them lit together and any of them
wirable.

## DONE WHEN

All 32 of the Uno's pads exist as targets, a drag onto any GND works, all
three light together because they are one net, and `describe()` reports 32
rather than 30.

## DONE, 2026-08-30

`view.pads` is `Map<pin, Mesh[]>`. All 32 of the Uno's pads exist; the three
GND pads are three targets on one net, lit together because `setLevels` walks
the list under each name.

**Measured in the browser, before and after, on three boards:**

    board                names   pads   real pins
    Arduino Uno           30      32     25 -> 28
    XIAO-RP2350-DIP       23      24      9 -> 11
    XIAO-ESP32-C3-DIP     14      14      0 ->  0

The RP2350 was losing one too, which nobody had noticed. The C3 is unchanged
in every column: it has no repeated name, and its pads are castellations with
no pin geometry above the board, which is the sixteen-board case `placeModel`
already describes.

`describe()` now reports `padCount` beside `pads`, because the two differ
exactly where a pad was being lost and the loss was invisible from outside the
module -- which is how it survived this long.

## THE OTHER HALF, WHICH WAS NOT ABOUT COUNTING

A wire stored only `pin` and `anchorOf` looked the name back up. Exact while
one name meant one pad; with three called GND, a wire dragged from the one
beside AREF would have had its end snap across the board to the one on the
power header. A wire now carries `post`, the pad it was actually pulled from.

`connect(pin, ...)` still takes a NAME and takes the first pad of it, which is
right and is documented: a caller naming a pin is naming a net.

## A TEST LESSON WORTH KEEPING

The first version of
`test_every_pad_is_kept_and_not_only_the_last_of_its_name` asserted that the
string `[...view.pads.values()].flat()` appeared in the file. **`padMeshes`'s
own docstring contains that string** -- "rather than
`[...view.pads.values()].flat()` in six places" -- so a mutation that gutted
the body left the comment behind and the test passed. Both of the two
mutations that reintroduce this bug survived until the assertions were split
onto the extracted function BODIES, the way this file's `applyCircuit` test
already does it.

**A source assertion a comment can satisfy is not an assertion about the
code**, and a file whose house style is dense commentary makes that easy to do
by accident.

Gate 1,882 -> 1,886 passed, 17 skipped. Five mutations, all killed.
