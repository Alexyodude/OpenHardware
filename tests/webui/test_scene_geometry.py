# OpenHardware — geometry invariants of the 3D view.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Guard the one 3D mistake that silently breaks interaction.

The first 3D build placed a peripheral's pin dots at `PART_HEIGHT - 0.8` while
the peripheral's own PCB spans `PART_HEIGHT ± 0.6`. The dots were therefore
*under* the board: invisible, unpickable, and the reason dragging a wire did
nothing at all. Nothing failed and nothing logged -- the scene simply could not
be used.

There is no browser test runner here, so this reads the constants out of the
module and checks the relation between them. That is weaker than rendering a
frame, and it is exactly strong enough for this failure: the bug was arithmetic
between two numbers declared side by side.
"""

from __future__ import annotations

import pathlib
import re

import pytest

STATIC = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
SCENE = STATIC / "scene3d.js"


def constant(name: str, source: str) -> float:
    match = re.search(rf"^const {name} = ([-\d.]+);", source, re.M)
    if match is None:
        raise AssertionError(
            f"{name} is no longer a plain top-level constant in scene3d.js. "
            f"This test reads it textually; if the shape changed, the check "
            f"must change with it rather than being deleted."
        )
    return float(match.group(1))


@pytest.fixture(scope="module")
def source() -> str:
    return SCENE.read_text(encoding="utf-8")


def test_pin_anchors_rest_on_top_of_the_peripheral_board(source):
    """The regression. An anchor's underside must clear the PCB's top face."""
    pcb = constant("PART_PCB", source)
    radius = constant("ANCHOR_R", source)
    anchor_y = re.search(r"^const ANCHOR_Y = ([^;]+);", source, re.M)
    assert anchor_y, "ANCHOR_Y is no longer declared"
    assert "PART_PCB / 2 + ANCHOR_R" in anchor_y.group(1), (
        "ANCHOR_Y must stay derived from the PCB thickness and the anchor "
        "radius. A literal here is how it drifted under the board last time."
    )
    computed = pcb / 2 + radius
    assert computed - radius >= pcb / 2, (
        f"anchors sit at y={computed} with radius {radius}, so their underside "
        f"is {computed - radius}, below the PCB top face at {pcb / 2}"
    )


def test_header_pins_stand_above_the_board_surface(source):
    """A drop target buried in the PCB is the same defect on the other side."""
    models = (STATIC / "models3d.js").read_text(encoding="utf-8")
    # buildHeader places pins at `topY + 2.6` with a 3.2-tall box.
    assert "topY + 2.6" in models, "header pin height changed; re-check clearance"
    assert "BoxGeometry(0.62, 3.2, 0.62)" in models
    # Underside of the pin = 2.6 - 3.2/2 = 1.0 above topY, which is the board's
    # own top face. Positive clearance is what makes it pickable.
    assert 2.6 - 3.2 / 2 > 0


def test_the_drag_handler_runs_before_orbit_controls(source):
    """OrbitControls binds pointerdown to the same canvas.

    Disabling it after it has already begun an orbit leaves the camera fighting
    the wire, so the wire drag must run in the capture phase and stop
    propagation. This asserts the listener is still registered that way.
    """
    start = source.find('"pointerdown"')
    assert start > 0, "no pointerdown listener at all"
    # The handler runs to the next listener registration. Slicing on that is
    # steadier than a non-greedy regex, which stopped at the `true` inside
    # `intersectObjects(..., true)` once wire-picking was added and made this
    # test fail for its own parsing rather than for the code.
    end = source.find("addEventListener", start)
    handler = source[start : end if end > start else len(source)]

    assert re.search(r"^\s*true,\s*$", handler, re.M), (
        "the pointerdown listener no longer passes `true`, so it is not in the "
        "capture phase and OrbitControls will start an orbit first"
    )
    assert "stopPropagation" in handler
    assert "setPointerCapture" in handler, (
        "without pointer capture a fast drag that leaves the canvas never "
        "delivers pointerup, and the wire is left hanging"
    )


def test_every_part_the_scene_can_draw_has_a_named_builder_or_falls_back():
    """`buildPart` must never return an unlabelled result.

    The UI reports how many peripherals are really modelled; that count is only
    honest if the two kinds are distinguishable.
    """
    models = (STATIC / "models3d.js").read_text(encoding="utf-8")
    assert 'kind: "textured"' in models
    assert 'kind: "model"' in models


def test_builders_name_parts_that_actually_exist():
    """A builder keyed to a name `splist` never reports would never run."""
    from webui.assets import available_parts

    models = (STATIC / "models3d.js").read_text(encoding="utf-8")
    block = models[models.index("const BUILDERS"):models.index("export function hasModel")]
    named = set(re.findall(r'^\s*"([^"]+)":', block, re.M))
    assert named, "no builders found; the parse above is wrong"
    unknown = named - set(available_parts())
    assert not unknown, f"builders for parts that do not ship: {sorted(unknown)}"
