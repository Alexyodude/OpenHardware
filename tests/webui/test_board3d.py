# OpenHardware — the 3D board view, checked the only way Python can check it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What these tests are, and what they honestly are not
#
# **Python cannot render a WebGL scene**, so nothing here proves the board
# looks right. What it can do is pin the properties that are decidable from the
# source, and every one of them below is a rule the panel would otherwise break
# silently:
#
#   * every CSS custom property the renderer reads is one the stylesheet
#     defines -- a typo'd variable is a silent fallback to grey
#   * no colour is written as a literal, which is what "shares the UI's
#     palette" means mechanically
#   * a theme change repaints the pads and not only the slab
#   * the panel says, in words, that it is a footprint and not a board model
#
# `test_a_diagnostic_message_is_rendered_before_the_line_it_quotes` is the
# precedent: it checks a rendering rule by position in the source, for exactly
# this reason.
#
# ## The two bugs that are the reason for the theme tests
#
# Both were found by taking a screenshot and looking, and neither would have
# failed any assertion about the DOM -- the table beside the canvas was correct
# throughout:
#
#   1. `refreshTheme` recoloured the slab and the outline and left the posts
#      alone, so switching to the light theme gave a white board carrying
#      dark-theme pins.
#   2. The state ramp was ordered by lightness, which flips between themes: in
#      the light theme `low` (`--sunken`) and `unknown` (`--line`) are two
#      nearly identical whites on a white board.
#
# So these tests do not replace looking. They stop the specific regressions
# from coming back quietly.

import pathlib
import re

STATIC = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
RENDERER = STATIC / "board3d.js"
PANEL = STATIC / "board3d-panel.js"
PAGE = STATIC / "emulator.html"
SHEET = STATIC / "emulator.css"

#: `#abc`, `#aabbcc` or `0x` followed by six hex digits -- a colour written
#: down rather than read from the stylesheet.
COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|0x[0-9a-fA-F]{6}\b")

#: `--name` inside a `read(...)` call: the three colours the scene itself uses.
DIRECT_READ = re.compile(r'read\("(--[a-z-]+)"\)')

#: `--name` on the right of a `STATE_VARIABLE` entry: the four a pad uses.
#:
#: **Both patterns are needed and finding that out is why this comment
#: exists.** The first version had only the one above, and the four state
#: colours reach the stylesheet through `read(name)` inside a loop -- a
#: variable, not a literal -- so they matched nothing. A deliberate typo of
#: `--changed` left all eleven tests in this file green, which is the exact
#: failure the test claims to prevent, in the test itself.
STATE_READ = re.compile(r'^\s*\w+: "(--[a-z-]+)",', re.MULTILINE)


def wanted_variables() -> set[str]:
    """Every custom property the renderer reaches the stylesheet for."""
    source = RENDERER.read_text(encoding="utf-8")
    block = source.split("const STATE_VARIABLE = {", 1)[1].split("};", 1)[0]
    return set(DIRECT_READ.findall(source)) | set(STATE_READ.findall(block))


def test_the_renderer_reads_only_custom_properties_the_stylesheet_defines():
    """**A typo'd variable does not throw, it falls back to grey.**

    `getPropertyValue` on a name nothing defines returns an empty string, and
    the renderer's own default takes over -- so `--changd` would paint every
    high pin the same grey as every low one, with no error anywhere.
    """
    source = RENDERER.read_text(encoding="utf-8")
    block = source.split("const STATE_VARIABLE = {", 1)[1].split("};", 1)[0]
    # **Both patterns must match something**, asserted rather than assumed.
    # A pattern that silently found nothing is how the first version of this
    # test stayed green against a deliberate typo of `--changed`.
    #
    # Not a count of the union: `--line` paints both the board's outline and
    # the `unknown` state, so seven usages are six names, and a number here
    # would break the next time two states sensibly shared a colour.
    assert DIRECT_READ.findall(source), "no direct colour reads found"
    assert len(STATE_READ.findall(block)) == 4, "not every pad state was matched"
    wanted = wanted_variables()
    declared = set(re.findall(r"^\s*(--[a-z-]+):", SHEET.read_text(encoding="utf-8"),
                              re.MULTILINE))
    assert wanted <= declared, sorted(wanted - declared)


def test_every_custom_property_it_reads_is_defined_in_both_themes():
    """One board, two themes. A colour declared only in the light block would
    render the dark theme with a light-theme value and look almost right."""
    sheet = SHEET.read_text(encoding="utf-8")
    # The dark theme is declared twice -- once under `prefers-color-scheme` and
    # once under an explicit `[data-theme="dark"]`, because the toggle has to
    # beat the operating system in both directions.
    dark = sheet.split("prefers-color-scheme: dark", 1)[1]
    wanted = wanted_variables()
    declared_dark = set(re.findall(r"^\s*(--[a-z-]+):", dark, re.MULTILINE))
    assert wanted <= declared_dark, sorted(wanted - declared_dark)


def test_the_renderer_writes_down_no_colour_of_its_own():
    """OH-16 folded two pages into one so there would not be two palettes
    drifting apart. A hex literal here is a third."""
    source = RENDERER.read_text(encoding="utf-8")
    # Two exceptions, both deliberate and both named in the source. `#888` is
    # what a custom property nothing defines falls back to, so it cannot come
    # from the stylesheet. `NEUTRAL_LIGHT` is illumination rather than a
    # colour: white light leaves each material the colour the stylesheet said,
    # and tinting it would shift all four states and the board together.
    body = source.replace('|| "#888"', "")
    body = body.replace("const NEUTRAL_LIGHT = 0xffffff;", "")
    found = [m for m in COLOUR_LITERAL.findall(body) if not _in_comment(body, m)]
    assert not found, f"colours written down rather than read: {found}"
    assert body.count("NEUTRAL_LIGHT") == 2, (
        "the light constant is used somewhere other than the two lights"
    )


def _in_comment(source: str, needle: str) -> bool:
    """Whether every occurrence of `needle` sits on a comment line.

    The header explains the two palette bugs by quoting the hex values that
    collided, and a test that banned colours from prose would make the file
    less able to explain itself.
    """
    for line in source.splitlines():
        if needle in line and not line.lstrip().startswith(("//", "*", "/*")):
            return False
    return True


def test_a_theme_change_repaints_the_pads_and_not_only_the_board():
    """**The regression guard for the bug a screenshot found.**

    Both places that set a pad's colour go through one function, so a future
    edit that adds a third cannot forget one of them -- and `refreshTheme`
    calling it is what makes the pins follow the theme.
    """
    source = RENDERER.read_text(encoding="utf-8")
    theme = source.split("export function refreshTheme", 1)[1]
    assert "repaint(post)" in theme, (
        "refreshTheme does not repaint the pads; a theme change leaves them "
        "coloured for the theme that was on when they were drawn"
    )
    levels = source.split("export function setLevels", 1)[1].split("\n}", 1)[0]
    assert "repaint(post)" in levels


def test_the_state_a_pad_is_in_is_kept_on_the_pad():
    """A colour cannot be turned back into a state, so a theme change would
    have nothing to recolour from. This is the field that makes the test above
    possible rather than a hope."""
    source = RENDERER.read_text(encoding="utf-8")
    assert "post.userData.state" in source


def test_the_four_states_are_the_four_the_api_reports():
    """A fifth here would never be painted and a missing one would fall back
    to `unknown`, which is a wrong answer rather than a loud one."""
    from webui import api

    source = RENDERER.read_text(encoding="utf-8")
    block = source.split("const STATE_VARIABLE = {", 1)[1].split("};", 1)[0]
    assert set(re.findall(r"^\s*(\w+):", block, re.MULTILINE)) == set(api.PIN_STATES)


# --- the page ---------------------------------------------------------------


def test_the_page_resolves_three_from_the_vendored_copy_and_not_a_cdn():
    """The page talks to its own origin and nothing else, which is also why it
    works with the network unplugged. An importmap pointing at a CDN would be
    the one line that quietly stopped being true."""
    page = PAGE.read_text(encoding="utf-8")
    assert '"three": "/vendor/three.module.js"' in page
    assert "://" not in page.split("importmap", 1)[1].split("</script>", 1)[0]
    assert (STATIC / "vendor" / "three.module.js").is_file()


def test_the_panel_says_it_is_a_footprint_and_not_a_model_of_the_board():
    """**OH-30's honest-degradation rule, in the page rather than in a
    comment.** A reader who is not told will reasonably assume they are looking
    at a render of the real thing.

    This is the markup's caption, which is what a board with no vendor model
    keeps -- three XIAO ESP32-C3 boards, and any board added before its model
    is found. It is also what shows before the index has been fetched, so it
    has to be the cautious one of the two rather than the confident one.
    """
    page = PAGE.read_text(encoding="utf-8")
    caption = page.split('id="board-pins-caption"', 1)[1].split("</p>", 1)[0]
    assert "not a model of" in caption
    assert "vendor" in caption


def test_the_caption_stops_disclaiming_a_model_once_there_is_one():
    """**OH-72 made that sentence false for nine boards**, and a page that goes
    on disclaiming a model it is showing is wrong in the same direction as one
    claiming a model it has not got: either way a reader cannot tell which they
    are looking at, which is the only thing the sentence was ever for.

    Both captions live in the panel and the choice is the index's `file`, so a
    board whose mesh has not been imported keeps the cautious one.
    """
    panel = PANEL.read_text(encoding="utf-8")
    assert "FOOTPRINT_CAPTION" in panel
    assert "MODEL_CAPTION" in panel
    # **The last assignment, not the first.** There are two: a board with no
    # header pins at all gets `view.note`, and only then does the model choice
    # happen. Splitting on the first found the wrong one and this test failed
    # on its own pattern before it ever failed on the code.
    chooser = panel.rsplit("$(CAPTION).textContent =", 1)[1].split(";", 1)[0]
    assert "model" in chooser and "file" in chooser, (
        "the caption is not chosen by whether a model was actually found"
    )


def test_the_renderer_is_handed_the_model_rather_than_finding_one():
    """`board3d.js` knows three.js and the page's palette and nothing else --
    not which boards this repository has meshes for. That belongs to the panel,
    which is already the file that fetches things and writes words.

    It also means the renderer cannot go looking for `/models/index.json` on a
    checkout that has never run the importer.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "index.json" not in source, "the renderer fetches the model index itself"
    assert "export function showBoard(layout, model" in source


def test_the_vendors_own_colours_are_not_repainted_by_the_theme():
    """A board's solder mask is a measurement and the pad states are this
    repository's reading of a register. **Only the second follows the theme**,
    because tinting the first would turn the one sourced thing in the picture
    into decoration -- and `#116517` is that board's green in either theme.
    """
    source = RENDERER.read_text(encoding="utf-8")
    # Bounded to the function's own body: everything after it is another
    # function, and `clearBoard` mentions `view.model` for a different reason.
    theme = source.split("export function refreshTheme", 1)[1].split("\n}", 1)[0]
    assert "repaint(post)" in theme, "the pad markers must still follow the theme"
    assert "view.model" not in theme, (
        "refreshTheme touches the vendor's mesh; its colours are the vendor's"
    )


def test_the_renderer_is_loaded_separately_from_the_rest_of_the_page():
    """A browser with no WebGL, or a vendored three.js that would not parse,
    must still get the table -- the numbers are what somebody debugging a
    sketch actually needs."""
    page = PAGE.read_text(encoding="utf-8")
    assert '<script src="/emulator.js"></script>' in page
    assert '<script type="module" src="/board3d-panel.js"></script>' in page
    # The panel imports the renderer lazily, so a failure to construct a WebGL
    # context is caught rather than taking the module down at load.
    panel = PANEL.read_text(encoding="utf-8")
    assert 'await import("/board3d.js")' in panel
    assert "catch" in panel


def test_the_page_asks_the_renderer_for_nothing_it_cannot_do_without():
    """Every hook is optional. A page where `board3d-panel.js` failed to load
    behaves exactly as it did before the pin view existed, which is the
    property that makes the whole thing safe to add to a working page."""
    emulator = (STATIC / "emulator.js").read_text(encoding="utf-8")
    calls = re.findall(r"window\.boardPins[.?]*\.?\w*", emulator)
    assert calls, "the page never talks to the pin panel"
    for call in calls:
        assert call.startswith("window.boardPins?."), call


def test_the_stylesheet_keeps_the_table_readable_without_the_canvas():
    """The table is not a caption for the 3D view, it is the same data in the
    form that survives having no WebGL -- so it keeps its own width."""
    sheet = SHEET.read_text(encoding="utf-8")
    assert ".pins-table" in sheet
    assert 'tr[data-state="unknown"]' in sheet, (
        "nothing distinguishes a pad nobody models from a pad reading low"
    )


# --- the two sentences an `unknown` pad gets, which is OH-70's ---------------
#
# Both of these were found in a browser and neither failed a DOM assertion,
# which is the third and fourth entry in this file's own list of reasons to go
# and look. `webui/api.py` said `unknown` and meant it; what was wrong was the
# words beside it and a number that had stopped moving.


def test_an_unknown_pad_with_a_pin_behind_it_does_not_read_not_modelled():
    """**The self-contradicting row.** `1 | PD1 | not modelled` names the pin
    in the same row that says nothing models it.

    An Arduino Uno running a `Serial` sketch produces it: the USART takes PD0
    and PD1 and leaves no trace in `DDRD`, so `webui/boards/atmega328p.py`
    answers `unknown` -- correctly, because what it cannot say is what the
    transmitter is doing to the pad. A pad with no MCU pin behind it at all is
    a different fact and needs different words.
    """
    panel = PANEL.read_text(encoding="utf-8")
    assert "not modelled" in panel
    assert "in use elsewhere" in panel
    # The state column must not reach a single fixed string for `unknown`, or
    # the two facts collapse back into one sentence.
    assert '  unknown: "not modelled",' not in panel


def test_the_two_sentences_are_told_apart_by_the_pin_and_not_by_a_guess():
    """`chip_pin` is exact rather than convenient, and this is where that is
    asserted rather than assumed.

    `webui/api.py` fills `chip_pin` from the board's `PIN_NAMES`, which is
    derived from the same `HEADER` its `pin_states` walks -- so a pad carries a
    chip pin **if and only if** the board answered for it. A panel that guessed
    from the label, or from the group, would be right on an Uno and wrong on
    the next board.
    """
    panel = PANEL.read_text(encoding="utf-8")
    chooser = panel.split("function unknownWords", 1)[1].split("\n}", 1)[0]
    assert "chip_pin" in chooser
    from webui.boards import atmega328p

    assert set(atmega328p.PIN_NAMES) == set(atmega328p.HEADER)


def test_the_answerable_count_is_recomputed_when_the_states_change():
    """**The count moves now, and it did not used to.**

    Before OH-70 a pad was `unknown` because the board's table had no row for
    it, which is fixed for the life of a board -- so the number the layout
    fetch carried stayed true however long a sketch ran. Then the Uno's USART
    started taking PD0 and PD1 partway through a `Serial` sketch, and the note
    went on reading `22 of 32` beside two rows that had stopped answering.

    `/api/board/pins` still carries `unknown` and it is not wrong; it is that
    endpoint's answer at the moment it was asked. It cannot be current, because
    the states arrive afterwards from `/api/board/state`.
    """
    panel = PANEL.read_text(encoding="utf-8")
    levels = panel.split("function levels", 1)[1].split("\n}", 1)[0]
    assert "renderCount()" in levels, (
        "a state poll repaints the rows and leaves the count where it was"
    )
    counter = panel.split("function renderCount", 1)[1].split("\n}", 1)[0]
    assert "layout.pads.filter" in counter
    assert "view.unknown" not in counter, (
        "the count is read from the layout fetch, so it cannot follow a poll"
    )
