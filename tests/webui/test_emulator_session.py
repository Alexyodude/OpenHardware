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


def test_the_only_machine_selector_is_the_board_picker():
    """One control chooses what to emulate, and it is the one that names MCUs.

    A `#target` selector used to sit first in the toolbar. It listed `core/`
    directories — `cortexm0`, `i8086`, `riscv32` — and with one drivable core
    it disabled *itself*, titled "one runnable target; the selector opens when
    a second core is built". So the most prominent control on the page named no
    MCU and could not be used, and someone looking for their board found it
    first and reasonably concluded nothing worked.

    Nothing was lost by removing it: the Targets view's "Runnable now" table is
    built from the same `/api/targets` data and has room for the reason beside
    each row.
    """
    assert 'id="target"' not in HTML, (
        "the core selector is back in the toolbar; it names cores rather than "
        "MCUs and disables itself while one core is drivable"
    )
    assert 'id="board-pick"' in HTML


def test_nothing_in_the_script_still_reaches_for_the_removed_selector():
    """Markup and script have to be removed together. A leftover
    `$("target")` throws on load, which takes the whole page with it —
    the class `test_every_element_the_script_fills_exists_in_the_page`
    guards from the other direction."""
    script = (STATIC / "emulator.js").read_text(encoding="utf-8")
    assert '$("target")' not in script
    assert "selectTarget" not in script, "a function with no caller"


def test_the_page_is_named_for_the_project_and_not_for_one_of_its_machines():
    """The label drifted for five months and nothing noticed.

    The page was built as OH-7's i8086 emulator UI, and boards, targets, the
    board picker and the Arduino Uno were all added into it while the title,
    the brand and the tab icon kept naming one core. By 2026-08-25 a person
    could load an ATmega328P into a window headed "i8086 Emulator" -- a wrong
    label on real data, which this repository ranks above a fault.

    Asserted narrowly, on the **identity** sites only. The word "i8086" appears
    all over this page legitimately: the Targets view explains which cores are
    built, and the emulator half says at length that its panes are showing an
    8086. A test forbidding the string outright would be forbidding the truth.
    """
    assert "<title>OpenHardware</title>" in HTML
    brand = re.search(r'<div class="brand">(.*?)</div>', HTML, re.S)
    assert brand is not None, "no brand element to check"
    assert "OpenHardware" in brand.group(1)
    assert "i8086" not in brand.group(1)
    # The favicon drew the text `86`, url-encoded as `%3E86%3C` between the
    # <text> tags. A tab icon is a name too.
    assert "%3E86%3C" not in HTML


def test_the_machine_that_really_is_an_i8086_is_still_called_one():
    """The other half of the rename, and the one that is easier to get wrong.

    `webui/emulator.py` is an 8086 session and nothing else -- its registers,
    its segmented disassembly and its sample programs are all 8086 -- so
    `DRIVING` and `DRIVABLE` naming it are **correct**. Renaming those to match
    the page would replace a true specific name with a false general one, which
    is the same defect as the one just fixed, pointing the other way.
    """
    from webui import emulator_server

    assert emulator_server.DRIVING == "i8086"
    assert emulator_server.DRIVABLE == frozenset({"i8086"})
    assert emulator_server.SERVER_NAME == "OpenHardware", (
        "the server names the project; the session inside it names its machine"
    )


def test_nothing_in_the_script_indexes_a_board_register_by_position():
    """A defect a browser found, pinned so the next one does not have to.

    `state.registers[15]` is the program counter on Armv6-M and an ordinary
    working register on an AVR. When the wire changed to named registers, one
    of the two places doing this was updated and the other was not -- and the
    survivor rendered `pc 0x[object Object]` into the run report, on a page
    with **zero console errors**, because indexing an array of objects is
    perfectly legal JavaScript.

    That is the failure class this repository ranks worst: not a crash, a
    plausible wrong answer. A test over the source is what catches it, because
    the value only looks wrong to a human reading the pane.
    """
    script = (STATIC / "emulator.js").read_text(encoding="utf-8")
    assert "state.registers[15]" not in script, (
        "the board's registers arrive named; index 15 is the pc on one machine "
        "here and r15 on another"
    )
    assert "state.apsr" not in script, "flags arrive named too"
    assert "ARM_REGISTERS" not in script, "no core's register names live in the page"


def test_the_view_switch_is_still_two_valued():
    """The mechanism the move relied on. A third view would show both halves
    at once, because the rule is written as a pair rather than a state
    machine — worth pinning, since it is what makes 'no new mechanism' true."""
    views = set(re.findall(r'body\[data-view="(\w+)"\]', CSS))
    assert views == {"emulator", "targets"}, f"views are now {sorted(views)}"


# --- what a loaded board shows in the debug panes -----------------------------
#
# These drive the API rather than the browser, for the reason the module header
# gives: the arrangement is checked statically and the behaviour is checked
# here, and a real browser is what found both wrong in the first place.


def test_a_loaded_board_carries_a_listing_around_its_program_counter():
    """The half of OH-46 that makes a board debuggable rather than only
    runnable. Around the PC, not the load address: after a run those are
    nowhere near each other."""
    import pathlib

    from webui import api

    image = pathlib.Path(__file__).resolve().parents[1] / "cortexm0/timer/delay.bin"
    with api.load_firmware("XIAO-RP2040-DIP", image.read_bytes(),
                           base=0x10000100) as session:
        session.step(5000)
        state = session.state()
        listing = state["listing"]
        assert listing["present"]
        assert listing["at"] == state["pc"]
        assert listing["lines"], "a listing with no lines is not a listing"
        current = [line for line in listing["lines"] if line["current"]]
        assert len(current) == 1, "exactly one line is where execution is"
        assert current[0]["address"] == state["pc"]


def test_the_listing_is_thumb_rather_than_whatever_ran_last():
    """The defect a browser found while this was being written: the panes kept
    showing the i8086's x86 listing because a stale server process was still
    answering. Asserting the text is Thumb catches the whole class -- a listing
    from the wrong machine, whatever the reason."""
    import pathlib

    from webui import api

    image = pathlib.Path(__file__).resolve().parents[1] / "cortexm0/uart/hello.bin"
    with api.load_firmware("XIAO-RP2040-DIP", image.read_bytes(),
                           base=0x10000100) as session:
        text = " ".join(line["text"] for line in session.state()["listing"]["lines"])
    # Thumb register names and no x86 ones. `mov cx, 000Ah` was what appeared.
    assert " r" in text or text.startswith("r"), text
    for x86 in (" ax", " cx", " dx", " bx,"):
        assert x86 not in text, f"an x86 operand in a Thumb listing: {text!r}"


def test_a_core_without_a_disassembler_says_so_rather_than_showing_nothing():
    """`present: false` is a claim about this repository; an empty listing is a
    claim about the image, and they are different facts -- the distinction
    `uart_view` already draws. Asserted against a stand-in rather than a real
    board, because every board that runs today happens to have one, and the
    case that needs holding is the one with no example yet."""
    import types

    from webui import api

    runtime = types.SimpleNamespace(
        chip="ESP32-C3", core="riscv32", description=None, board="XIAO-ESP32-C3-DIP",
    )
    view = api.listing_view(runtime, None, 0)
    assert view["present"] is False
    assert view["lines"] == []
    assert "riscv32" in view["note"]
    assert "no disassembler" in view["note"]
