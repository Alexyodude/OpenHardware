---
id: OH-117
title: Two of the Arduino Uno's three GND pads are dropped by a Map keyed on label
status: open
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
