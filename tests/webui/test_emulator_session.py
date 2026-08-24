# OpenHardware — which view operates a machine, and which only describes one.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## The arrangement these tests hold in place
#
# **Emulator view: operate.** Pick a board, upload a compiled image, run it,
# read what it printed — and, as this ticket continues, step it and read its
# registers.
#
# **Targets view: describe.** What has progressed, what is built, what each
# missing core would cost. Nothing there changes the machine.
#
# It was the other way round until 2026-08-25. `#board-run` — the board picker,
# the file input, Load, Run and the console — lived inside `<div id="targets">`
# under the progress tables and eighteen rows of architecture survey, while the
# Emulator view's toolbar carried a selector that with `DRIVING = "i8086"` could
# only ever offer one thing. The research tracker owned the workflow and the
# workflow tab owned a one-item dropdown.
#
# ## Why this is asserted against the files rather than a browser
#
# A layout is easy to check by eye once and never again. These read the markup
# and the stylesheet, so the arrangement is pinned by something that runs on
# every commit — and the browser check that found the arrangement wrong in the
# first place stays the thing that catches what static text cannot.
#
# They deliberately do **not** assert pixel geometry or ordering within a view.
# What matters is which half of the page a control belongs to, and a test that
# also pinned the order would fail on every cosmetic change and get deleted.

import pathlib
import re

STATIC = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
HTML = (STATIC / "emulator.html").read_text(encoding="utf-8")
CSS = (STATIC / "emulator.css").read_text(encoding="utf-8")

#: Controls that change the machine. Every one belongs to the Emulator view.
CONTROLS = ("board-pick", "board-file", "board-base", "board-load", "board-go")


def offset(fragment: str) -> int:
    """Where `fragment` appears in the markup, insisting it appears once."""
    first = HTML.find(fragment)
    assert first >= 0, f"{fragment!r} is not in emulator.html"
    assert HTML.find(fragment, first + 1) < 0, f"{fragment!r} appears twice"
    return first


# --- which half of the page each thing belongs to ----------------------------


def test_loading_an_image_is_not_inside_the_targets_view():
    """The move this ticket is about. `<div id="targets">` opens after the
    board panel, so the panel cannot be inside it."""
    assert offset('id="board-run"') < offset('<div id="targets">')


def test_every_control_that_changes_the_machine_is_in_the_emulator_view():
    """Asserted over the whole set rather than the panel that holds them, so
    moving one control out on its own is caught too."""
    targets = offset('<div id="targets">')
    for control in CONTROLS:
        assert offset(f'id="{control}"') < targets, (
            f"{control} sits in the Targets view, which describes rather than "
            f"operates"
        )


def test_the_targets_view_still_holds_what_it_describes():
    """The other half of the move. Progress tables belong there, and pushing
    them into the Emulator view would just reverse the mistake."""
    targets = offset('<div id="targets">')
    for panel in ('id="boards"', 'id="runnable"', 'id="boards-waiting"'):
        assert offset(panel) > targets


# --- and the stylesheet agrees ------------------------------------------------


def test_the_stylesheet_hides_the_board_panel_on_the_targets_view():
    """Markup placement alone would leave the panel visible in both views.

    No new mechanism was added for this: `#board-run` simply joined `#code`,
    `#state` and `#memory` in the list the Targets view hides, which is the
    two-value rule that was already there.
    """
    rule = re.search(
        r"((?:body\[data-view=\"targets\"\]\s*#[\w-]+,?\s*)+)\{\s*display:\s*none",
        CSS,
    )
    assert rule, "the Targets view's hide list is gone or has changed shape"
    hidden = set(re.findall(r"#([\w-]+)", rule.group(1)))
    assert {"board-run", "code", "state", "memory"} <= hidden, (
        f"the Targets view hides {sorted(hidden)}; it must hide the panels "
        f"that operate a machine"
    )


def test_the_machine_selector_is_scoped_to_the_emulator_view():
    """`#target` sat outside `.only-emulator` on purpose, because the Targets
    view used to be where an image was loaded. It is not any more, so a
    selector there is a control in the room that operates nothing."""
    match = re.search(
        r'<span class="only-emulator">\s*<select id="target"', HTML
    )
    assert match, "the target selector is no longer scoped to the Emulator view"


def test_the_view_switch_is_still_two_valued():
    """The mechanism the move relied on. A third view would show both halves
    at once, because the rule is written as a pair rather than a state
    machine — worth pinning, since it is what makes 'no new mechanism' true."""
    views = set(re.findall(r'body\[data-view="(\w+)"\]', CSS))
    assert views == {"emulator", "targets"}, f"views are now {sorted(views)}"
