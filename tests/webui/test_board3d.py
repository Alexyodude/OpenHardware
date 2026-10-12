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

import json
import math
import pathlib
import re
import shutil
import struct
import subprocess

import pytest

STATIC = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
RENDERER = STATIC / "board3d.js"
PANEL = STATIC / "board3d-panel.js"
PAGE = STATIC / "emulator.html"
SHEET = STATIC / "emulator.css"


def stripped(source: str) -> str:
    """`source` with its `//` comment lines removed, for source-level
    assertions. **The OH-117 lesson, factored once**: an assertion a comment
    can satisfy is not an assertion about the code, so every structural test
    below greps a comment-stripped body -- and after the twenty-fourth
    inline copy of the same three lines, the idiom earned a name.
    """
    return "\n".join(line for line in source.splitlines()
                      if not line.lstrip().startswith("//"))

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
    # Three exceptions, all deliberate, all named in the source, and all
    # removed by name so that a fourth cannot arrive unnoticed.
    #
    # `#888` is what a custom property nothing defines falls back to, so it
    # cannot itself come from the stylesheet. `NEUTRAL_LIGHT` is illumination
    # rather than a colour: white light leaves each material the colour the
    # stylesheet said, and tinting it would shift all four states and the
    # board together.
    #
    # **`WIRE_COLOURS` is the third and it is the interesting one.** The rule
    # this test enforces is about the UI's palette -- the colours this
    # repository uses to *say* things, which must agree across two themes and
    # two pages. A jumper lead is not one of those: it is a thing on a bench,
    # it is the same colour in either theme, and six of them have to be told
    # apart from each other, which a palette with one accent cannot do. The
    # vendor's solder mask gets the same exemption by arriving in a mesh file
    # rather than in this source.
    body = source.replace('|| "#888"', "")
    body = body.replace("const NEUTRAL_LIGHT = 0xffffff;", "")
    wires = body.split("const WIRE_COLOURS = [", 1)
    assert len(wires) == 2, "WIRE_COLOURS is gone; so is this exception's reason"
    body = wires[0] + wires[1].split("];", 1)[1]

    found = [m for m in COLOUR_LITERAL.findall(body) if not _in_comment(body, m)]
    assert not found, f"colours written down rather than read: {found}"
    # **Counted outside comments, and tied to the lights rather than to a
    # number.** This used to be `count(...) == 2`, and when OH-82 replaced the
    # ambient light with an environment the uses fell to one -- while a new
    # COMMENT mentioning the constant took the count back to two, so the
    # assertion went on passing without ever noticing. A tripwire that a
    # sentence can reset is not a tripwire. What it is actually for is catching
    # the light constant leaking into a material, so it counts uses and
    # compares them with the number of lights there are.
    code = stripped(body)
    lights = code.count("AmbientLight(") + code.count("DirectionalLight(")
    assert code.count("NEUTRAL_LIGHT") == lights, (
        f"NEUTRAL_LIGHT is used {code.count('NEUTRAL_LIGHT')} times outside "
        f"comments and there are {lights} lights: it has reached something "
        f"that is not illumination"
    )
    assert lights >= 1, "the scene has no light at all"


def test_the_only_colours_written_down_are_lead_colours():
    """The exception above, bounded: `WIRE_COLOURS` and nothing else.

    Six, because a bench with six wires on it needs six leads a person can
    tell apart, and because past six a reader is counting rather than seeing.
    """
    source = RENDERER.read_text(encoding="utf-8")
    block = source.split("const WIRE_COLOURS = [", 1)[1].split("];", 1)[0]
    leads = re.findall(r"0x[0-9a-fA-F]{6}", block)
    assert len(leads) == 6, leads
    assert len(set(leads)) == 6, "two leads are the same colour"


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
    into decoration -- and `#49a954` is that board's green in either theme.
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


def test_the_pin_table_sorts_pins_and_the_comparator_really_runs(tmp_path):
    """The table listed rows in whatever order the layout walked the
    vendor's file -- the C3 reads D6, D5, D4, D3, D2, D1, D0, D7 (OH-145).
    `renderTable` now sorts a display copy through `pinOrder`, and the
    comparator is proven by RUNNING it: its own text, extracted from the
    panel, sorting a mixed sample under node -- a grep cannot see that
    D9/BOOT lands before D10 and 13 lands after 2."""
    panel = stripped(PANEL.read_text(encoding="utf-8"))
    table = panel.split("function renderTable(pads) {")[1].split("\n}")[0]
    assert "sort((a, b) => pinOrder(a.label, b.label))" in table, (
        "the table renders the vendor's shuffle again"
    )
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; the comparator is plain JS and needs "
                    "one to run")
    comparator = ("function pinOrder"
                  + panel.split("function pinOrder")[1].split("\n}")[0]
                  + "\n}")
    sample = ["GND", "D10", "D2", "13", "2", "A4", "3V3", "D9/BOOT",
              "A0", "5V", "VBUS", "0", "~11", "~3"]
    script = tmp_path / "probe.mjs"
    script.write_text(
        comparator + "\n"
        + f"const sample = {json.dumps(sample)};\n"
        + "console.log(JSON.stringify(sample.sort(pinOrder)));\n",
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    # ~3 and ~11 hold the place their NUMBER earns -- the tilde is
    # Arduino's PWM mark, not an address -- and digit-leading rails (3V3)
    # follow the bare numbers, before the lettered names.
    assert got == ["0", "2", "~3", "~11", "13", "3V3", "5V", "A0", "A4",
                   "D2", "D9/BOOT", "D10", "GND", "VBUS"], got


def test_the_pin_table_names_the_pin_first():
    """`13 | PB5 | input` under headers reading `Pad | Pin | State` is
    backwards to anyone who has written `digitalWrite(13, ...)` (OH-144):
    "13" IS the pin, and PB5 is the chip's own name for it -- the field the
    API itself calls `chip_pin`. The contents were always right; only the
    words over them were swapped."""
    page = PAGE.read_text(encoding="utf-8")
    assert "<th>Pin</th><th>Chip pin</th><th>State</th>" in page
    assert "<th>Pad</th>" not in page, (
        "the pin-name column is labelled Pad again"
    )


def test_hovering_lights_what_a_press_would_grab():
    """Resting the pointer on a pad or terminal lights it and turns the
    cursor (OH-144), in the SAME `padUnder() ?? terminalUnder()` order the
    drag uses -- so what glows is exactly what a press takes. The restore
    runs from every path that could invalidate the lit mesh, because a glow
    restored only on the next move would outlive a disposed material."""
    code = stripped(RENDERER.read_text(encoding="utf-8"))
    body = code.split("function hover() {")[1].split("\n}")[0]
    assert "padUnder() ?? terminalUnder()" in body, (
        "hover picks in a different order than the drag grabs"
    )
    assert "emissive.setScalar(HOVER_GLOW)" in body
    assert "mesh.visible = true" in body, (
        "an invisible pad post stays invisible under the pointer"
    )
    assert 'cursor = "pointer"' in body
    undo = code.split("function dehover() {")[1].split("\n}")[0]
    assert "setHex(emissive)" in undo, "the glow is never taken back"
    assert "mesh.visible = visible" in undo
    assert 'canvas.style.cursor = ""' in undo
    move = code.split("function onPointerMove(event) {")[1].split("\n}")[0]
    assert "hover();" in move, "a resting pointer never asks what it is on"
    for owner in ("function releasePart(part) {", "function clearBoard() {",
                  "function carvePins(group, pcbThickness) {"):
        assert "dehover();" in code.split(owner)[1].split("\n}")[0], (
            f"{owner} can invalidate the lit mesh without restoring it"
        )
    assert 'addEventListener("pointerleave", dehover)' in code


def test_not_modelled_is_decided_by_the_modelled_flag_and_not_by_the_caption(tmp_path):
    """**OH-172: a caption is not a level.** `chip_pin` says which MCU pin a
    pad reaches, and since OH-167 a board with no module captions its pads
    from its own file -- so a panel that read "has a chip pin" as "something
    reads this pin" told an MG24's `D0`, which reaches `PC0` and has nothing
    reading it, that no program was running. `webui/api.py` now states
    `modelled` per pad, and `tests/webui/test_pin_view.py` holds it to the
    board's own level reader.

    Run rather than grepped: `unknownWords` and its three sentences,
    extracted from the panel and called under node. A pad that does not
    carry the field reads "not modelled", because a view without it is one
    nobody has vouched for.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; the chooser is plain JS and needs one "
                    "to run")
    panel = stripped(PANEL.read_text(encoding="utf-8"))
    sentences = [re.search(rf"^const {name} = .*;$", panel, re.MULTILINE)
                 for name in ("NOT_MODELLED", "IN_USE", "NOTHING_RUNNING")]
    assert all(sentences), sentences
    chooser = ("function unknownWords"
               + panel.split("function unknownWords", 1)[1].split("\n}", 1)[0]
               + "\n}")
    cases = [
        ({"modelled": False, "chip_pin": "PC0"}, False, "not modelled"),
        ({"modelled": False, "chip_pin": "PC0"}, True, "not modelled"),
        ({"modelled": True, "chip_pin": "GPIO2"}, False, "no program running"),
        ({"modelled": True}, True, "in use elsewhere"),
        ({"chip_pin": "PB5"}, False, "not modelled"),
        ({"chip_pin": "PB5"}, True, "not modelled"),
    ]
    script = tmp_path / "probe.mjs"
    script.write_text(
        "\n".join(match.group(0) for match in sentences) + "\n" + chooser + "\n"
        + f"const cases = {json.dumps([[pad, read] for pad, read, _ in cases])};\n"
        + "console.log(JSON.stringify(cases.map(([pad, read]) => "
        + "unknownWords(pad, read))));\n",
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert got == [words for _, _, words in cases], list(zip(cases, got))


def test_a_caption_in_kicad_overbar_markup_is_drawn_overlined_and_kept_verbatim(tmp_path):
    """**OH-172 slice 2's review, LOW-4.** The nRF54L15 SMD's `nRF54_EN`
    reaches the pad its footprint calls `~{RESET}`: KiCad's markup for RESET
    with a bar over it, the active-low mark. The Chip pin column printed the
    markup raw, and a tilde in this table already means something else --
    `pinOrder` reads `~11`'s as Arduino's PWM mark.

    The data stays verbatim, because it is the vendor's own name and the
    tests hold it to the footprint; the panel draws it. `captionParts`
    splits a caption into plain runs and overlined runs, run here under
    node, and `renderTable` draws an overlined run with a CSS overline and
    keeps the verbatim caption in the cell's title. Nothing else in a
    caption is touched: `SWDIO_G2` keeps its ball, as the vendor wrote it.
    """
    panel = stripped(PANEL.read_text(encoding="utf-8"))
    table = panel.split("function renderTable(pads) {")[1].split("\n}")[0]
    assert "captionParts(pad.chip_pin)" in table, "the caption is printed raw again"
    assert 'textDecoration = "overline"' in table
    assert "pin.title = pad.chip_pin" in table, "the verbatim caption is lost"
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; the splitter is plain JS and needs one to run")
    splitter = ("function captionParts"
                + panel.split("function captionParts", 1)[1].split("\n}", 1)[0]
                + "\n}")
    cases = {
        "~{RESET}": [["RESET", True]],
        "RESET": [["RESET", False]],
        "SWDIO_G2": [["SWDIO_G2", False]],
        "P1.08": [["P1.08", False]],
        "A~{B}C": [["A", False], ["B", True], ["C", False]],
        "~{RST}/~{EN}": [["RST", True], ["/", False], ["EN", True]],
        "~11": [["~11", False]],
    }
    script = tmp_path / "probe.mjs"
    script.write_text(
        splitter + "\n"
        + f"const cases = {json.dumps(list(cases))};\n"
        + "console.log(JSON.stringify(cases.map((one) => "
        + "captionParts(one).map((part) => [part.text, part.over]))));\n",
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert got == list(cases.values()), list(zip(cases, got))


def test_a_third_sentence_says_when_there_is_no_program_at_all():
    """**OH-164: a board you picked said 22 of its 32 pads were in use.**

    Two of the three sentences are claims about a RUNNING program -- nothing
    models this pin, or something running has taken it -- and a board that has
    been picked and not loaded satisfies neither. It took the second, so an
    Uno you had merely chosen reported 22 pads in use while nothing was using
    anything. Twelve of the twenty-six boards did, which is the number OH-160
    made it by giving four more modules a generated `HEADER`.

    `tests/webui/test_pin_view.py` measures the counts and asserts the API
    field. What is asserted here is the panel's half, which Python cannot
    execute: the third case exists, it is decided on the fetch and not on the
    pad, and the ORDER is right -- a pin no module knows keeps "not modelled"
    whether or not a program is running, because that is a fact about the
    board description rather than about the moment.

    **The poll does NOT write the fact down**, and an earlier version of this
    change had it do exactly that. `levels(pins)` has no idea which board the
    levels belong to: `/api/board/state` carries no board identity and the
    picker does not stop the clock, so a page showing board B while the
    session runs board A marked B as running a program and B went straight
    back to saying its pins were in use. `/api/board/pins` already decides it
    and decides it WITH the identity check, returning `pin_view` only when
    `session.board == asked`; loading firmware calls `reload()` at once, so
    the answer is re-fetched exactly when it changes.

    **Nine mutations die here, 2026-09-05, and every one of them only here**:
    the third sentence never reached; the third sentence eating the second;
    the ternary SWAPPED, which tells a running board nothing is running and a
    picked one that its pins are in use; the order inverted, which takes "not
    modelled" away from a pin no module knows; the table inferring the case
    from a count instead of reading the field; the chooser handed a literal
    instead of the value the table read; the fallback flipped to true; the
    poll marking the layout again; and the words replaced by ones that name a
    state rather than say what is true.

    **Four assertions here were wrong first, all in one way**, and it is the
    way this file is most prone to: looking for a string rather than for a
    use. One compared `NOT_MODELLED` against the PARAMETER `readLevels`,
    named in the signature before any sentence. One searched the whole file
    for the guess it rejects, which this docstring and the panel's block
    comment both spell out -- `stripped` takes `//` lines only. One asserted
    that the table READS the field without asserting that it HANDS it over,
    so `unknownWords(pad, true)` restored the entire defect with the suite
    green. And one pinned the order of the two sentences without pinning
    which branch reaches which, so swapping the ternary survived.
    """
    panel = PANEL.read_text(encoding="utf-8")
    chooser = stripped(
        panel.split("function unknownWords", 1)[1].split("\n}", 1)[0])
    # Decided on the fetch, not on the pad: a second argument and not a field.
    assert "readLevels" in chooser, (
        "the third case is not decided by whether any levels were read, so a "
        "picked board still reports its pins as in use elsewhere"
    )
    # Order: unmodelled is decided first, so it wins over the third case.
    # Compared against the SENTENCE and not the parameter, which is named in
    # the signature before any of them and made a first draft of this pass
    # for the wrong reason.
    assert "IN_USE" in chooser and "NOTHING_RUNNING" in chooser
    assert chooser.index("NOT_MODELLED") < chooser.index("NOTHING_RUNNING"), (
        "a pin no module knows is 'not modelled' whether or not a program is "
        "running; only the other sentence is about there being one"
    )
    # **Which way round, and a swap survives every assertion above.** The
    # order check passes on `readLevels ? NOTHING_RUNNING : IN_USE`, which
    # says a running board has no program and a picked one has pins in use --
    # the original bug with its sign reversed. So the branch is pinned.
    branch = re.compile(r"readLevels\s*\?\s*IN_USE\s*:\s*NOTHING_RUNNING")
    assert branch.search(chooser), (
        "levels having been read is the branch that gives 'in use elsewhere'; "
        "the other way round tells a running board that nothing is running"
    )
    # The words themselves say what is true rather than naming a state.
    # **Over the stripped source**, because the pattern this looks for is one
    # a `//` line can carry: a decoy comment plus a real constant reading
    # "unknown" passed the unstripped version. That is this file's own OH-117
    # hazard, in the test written to record it.
    words = re.search(r'NOTHING_RUNNING = "([^"]+)"', stripped(panel))
    assert words and "running" in words.group(1), (
        "the third sentence names a state instead of saying that no program "
        "is running, which is the one thing the reader cannot see for himself"
    )
    # The API supplies it and the panel does not infer it. **Checked in the
    # function bodies and not in the file**, because this docstring and the
    # panel's own comments both spell the guess out in order to reject it --
    # `stripped` only takes `//` lines, so a `/** */` block would satisfy a
    # whole-file search. That is the OH-117 lesson arriving from a new angle.
    table = stripped(
        panel.split("function renderTable", 1)[1].split("\n}", 1)[0])
    assert "layout?.read_levels" in table, (
        "the panel works the third case out for itself instead of reading the "
        "field the API states, which is OH-121's re-derivation again"
    )
    assert "pads.length" not in table + chooser, (
        "the third case is inferred from how many pads are unanswerable, "
        "which is equally true of a loaded sketch that has driven nothing"
    )
    # **And that the value REACHES the chooser**, which the two assertions
    # above do not say: `unknownWords(pad, true)` restores the whole defect
    # with every one of them still passing, because the string they look for
    # stays where it is and simply stops being used. The argument has to be
    # the local the line above computed.
    handed = re.compile(r"unknownWords\(pad,\s*readLevels\)")
    assert handed.search(table), (
        "the table reads `read_levels` and then hands `unknownWords` "
        "something else, so a picked board says its pins are in use again"
    )
    # **The fallback, which nothing on screen can reach and which is asserted
    # anyway.** `layout` is either null, and then the table has no rows, or a
    # view that carries the field. So `?? true` changes no picture today and
    # survives every assertion above -- it would only decide if the API
    # stopped sending the field, which is exactly when the wrong answer would
    # be "a program is running" for every board there is.
    assert "?? false" in table, (
        "the table's fallback for a missing `read_levels` is not false, so a "
        "view without the field would report every pad as in use elsewhere"
    )
    # **And a poll does NOT mark the layout**, which an earlier version of
    # this change did. `/api/board/state` carries no board identity and the
    # picker does not stop the clock, so a page showing board B while the
    # session runs board A would have marked B as running a program.
    # `/api/board/pins` already decides it and decides it WITH the identity
    # check, which is the assertion below.
    levels = stripped(panel.split("function levels", 1)[1].split("\n}", 1)[0])
    assert "read_levels" not in levels, (
        "a state poll marks whatever layout is on screen as having levels, "
        "and it cannot know which board they came from"
    )
    server = (STATIC.parents[1] / "webui" / "emulator_server.py").read_text(
        encoding="utf-8")
    route = server.split('if route == "/api/board/pins"', 1)[1]
    pins = route.split("\n    if ", 1)[0]
    assert "session.board == asked" in pins and "pin_view" in pins, (
        "the pins route no longer checks that the session is running the "
        "board being asked about, so the panel has nothing else that does"
    )


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


def test_the_renderer_collides_a_wire_with_the_boards_components():
    """The PCB slab was the whole board until there were components on it.

    `refreshColliders` pushed one box, from `pcb`, and that was right while a
    board was an extruded slab. OH-75 drew a DIP-28 and six headers on the Uno
    and the collider set silently became a description of a board that no
    longer existed.

    The model states its own boxes -- `tools/compose_board_3d.py` measures them
    to check the components land on the board anyway -- so the renderer places
    them rather than deriving them from a mesh it would have to walk.
    """
    source = RENDERER.read_text(encoding="utf-8")
    colliders = source.split("function refreshColliders", 1)[1].split("\n}", 1)[0]
    assert "view.solids" in colliders, (
        "the board's own components are not colliders, so a wire goes through them"
    )
    # **The frame change lives in `boardSolid`, not here.** It was inline when
    # this test was written, and then the PCB slab was moved into the same
    # mechanism -- so both go through one place now and this looks there. That
    # is the fix that mattered: the slab used to be built in scene coordinates
    # of its own and ended up 4.5 units from the board it was supposed to be.
    assert "boardSolid(view.slab)" in colliders, (
        "the PCB does not go through the same frame conversion as the "
        "components, which is how it ended up 4.5 units off the board"
    )
    frame = source.split("function boardSolid(solid) {", 1)[1].split("\n}", 1)[0]
    assert "matrixWorld" in frame, (
        "the boxes are in the model's frame and must be moved into the scene's"
    )
    # Emitted by the composer and read here: one name, so a rename breaks
    # loudly rather than silently dropping every component collider.
    composer = STATIC.parents[1] / "tools" / "compose_board_3d.py"
    assert '"solids"' in composer.read_text(encoding="utf-8")


def test_a_wire_is_told_how_thick_it_is_and_not_only_how_thick_to_draw():
    """**OH-162 step 1, at the one place a wire hears about the scene.**

    `WIRE_RADIUS` was a drawing parameter: `updateTube` built a tube of it and
    the solver moved the centreline, so every settled lead lay with half its
    thickness inside whatever it rested on. `tests/webui/test_wires.py` runs
    the arithmetic and measures that -- 0.16 units of tube in the box, the
    whole radius -- and what is asserted here is only that this file hands the
    number over, next to the colliders and the floor it already hands over.

    **One constant, not two.** A second number written down here would be a
    wire drawn at one thickness and solved at another, which is the shape the
    4.5-unit slab offset had: one quantity arrived at in two places, and the
    fix was to make both go through one.

    **The assertion is a whole line and not a substring**, which the OH-162
    review is why: `wire.rope.radius = WIRE_RADIUS * 0;` and
    `if (own) wire.rope.radius = WIRE_RADIUS;` both CONTAIN the substring the
    first version looked for, both neuter the hand-off, and nothing else in
    this repository executes `board3d.js` -- so either would have survived the
    whole suite. Anchoring both ends of the line is what a grep can do about
    that, and it is the honest limit of a grep.

    Six mutations run, all failing: the line deleted, the constant replaced by
    a literal 0.2, the line left in place as a comment (which is what
    `stripped` is for), the constant multiplied by zero, the line put behind
    `if (own)`, and the assignment aimed at `wire.radius` instead of
    `wire.rope.radius`.
    """
    source = RENDERER.read_text(encoding="utf-8")
    applied = stripped(
        source.split("function applyColliders(wire) {", 1)[1].split("\n}", 1)[0])
    whole_line = re.compile(r"^\s*wire\.rope\.radius = WIRE_RADIUS;$", re.MULTILINE)
    assert whole_line.search(applied), (
        "the solver is never told the tube's radius, so a lead settles with "
        "half of itself inside the chip it is resting on"
    )
    assert "wire.rope.floor" in applied, (
        "the radius arrived and the floor left; both belong to this one place"
    )


def test_every_wire_is_told_about_the_others_on_every_frame():
    """**OH-162 step 2, and the place it is done is the point.**

    A lead may not pass through another lead, so each rope needs the others.
    Which others there are changes in three places -- a wire made, a wire
    dropped before it reaches a terminal, and a part removed taking its wires
    with it -- and a list built at any of them is a list the other two have to
    remember to update. `animate` already reads every wire once a frame to
    move its ends, so a list built there cannot go stale.

    Asserted as three facts about that one function: it refills the shared
    array from `view.wires` rather than keeping a second source of truth, it
    hands that array to each rope, and it does both BEFORE advancing, or the
    first wire of the frame would be solved against the previous frame's set.

    One array shared by every rope, not a copy each: `offNeighbours` skips the
    rope it belongs to, which is what makes that safe and is why the renderer
    does not have to build a different list per wire.

    Three mutations die here and nowhere else in the suite, 2026-09-05: the
    list never rebuilt, no rope told about the others, and the list filled
    after the wires are advanced.
    """
    source = RENDERER.read_text(encoding="utf-8")
    loop = stripped(source.split("function animate(now = 0) {", 1)[1]
                    .split("\n}", 1)[0])
    refill = re.compile(r"^\s*view\.ropes\.length = 0;$", re.MULTILINE)
    assert refill.search(loop), (
        "the neighbour list is not rebuilt each frame, so a wire added or "
        "removed leaves every other wire solving against a set that is gone"
    )
    hand_over = re.compile(r"^\s*wire\.rope\.neighbours = view\.ropes;$", re.MULTILINE)
    assert hand_over.search(loop), (
        "no rope is told about the others, so two leads pass through one"
    )
    assert loop.index("view.ropes.push") < loop.index("wire.rope.advance"), (
        "the list is filled after the wires are advanced, so the first wire "
        "of every frame is solved against the previous frame's neighbours"
    )
    # Derived and not a second source of truth: the only writes are here.
    assert source.count("view.ropes.push") == 1, (
        "view.ropes is written in more than one place, which is the staleness "
        "this arrangement exists to avoid"
    )


def test_a_bench_part_is_drawn_at_the_boards_own_scale():
    """8 px/mm is what a GENERATED board JSON uses, and the Uno's was traced.

    `placeModel` learned to derive the scale from the pad field in OH-76;
    `addPart` kept the constant, so a 5 mm LED was drawn 7.1 mm across beside a
    board drawn at its real 68.58 -- exactly the 8 / 5.638 the two scales
    differ by. One number now, decided when the board is drawn.
    """
    source = RENDERER.read_text(encoding="utf-8")
    bench = source.split("export async function addPart", 1)[1].split("\n}", 1)[0]
    assert "view.mmScale" in bench, "the bench still uses its own scale"
    assert "PX_PER_MM * SCALE" not in bench, (
        "addPart hard-codes the generated-board scale again"
    )
    # And the one place it is decided has to be the one place a model changes it.
    placed = source.split("function placeModel", 1)[1].split("\n}", 1)[0]
    assert "view.mmScale = scale" in placed


def test_the_renderer_can_report_how_far_a_wire_is_inside_something():
    """A wire over a chip and a wire through it are the same picture.

    The screenshot that made this look fixed was taken before the colliders
    existed. `penetration` is the number that is not fooled by the camera, and
    it is exported for exactly that reason -- measured 2.248 mm for a wire laid
    straight from pad 12 through the DIP-28, and 0.000 once it settles.

    **OH-132: and 0.000 was also what it said for a node buried in a face.**
    The arithmetic lives in `wires.js` now, where `test_wires.py` runs it under
    node instead of grepping for it -- which is how a probe that reported
    0.0000 for a half-buried wire survived four handoffs. What is asserted
    here is only that this file goes through it.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "export function penetration()" in source
    assert "export function contact()" in source
    body = source.split("export function penetration()", 1)[1].split("\n}", 1)[0]
    assert "rope.contact()" in body, (
        "penetration must go through Rope.contact, or the geometry is back in "
        "the file no test can execute"
    )
    assert "wire.rope" in body, (
        "it must measure against the set the rope actually solved against, or "
        "it reports a fault on every wire's own part"
    )
    whole = source.split("export function contact()", 1)[1].split("\n}", 1)[0]
    assert "WIRE_RADIUS" in whole, (
        "surface contact is measured against the tube that is drawn, or the "
        "number is about a centreline nobody can see"
    )


# --- a part is lit by a circuit, not by one pad's level ----------------------


def test_no_part_is_driven_from_a_single_pads_level():
    """**The defect OH-79 removed, pinned so it cannot walk back in.**

    `applyState` was four lines: find the pad this one wire came from, read its
    logic level, drive the part with it. That is what lit an LED whose other
    leg was in mid-air -- the user's report, verbatim: *"the led is lighting up
    even though not grounded"*.

    Its absence is the assertion, and so is the absence of the shape it had: a
    `view.pads.get` anywhere near a `setPartState` is that function returning
    under another name.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "function applyState" not in source
    assert "import { analyse }" in source
    solve = source.split("function applyCircuit() {", 1)[1].split("\n}", 1)[0]
    assert "view.pads.get" not in solve, (
        "the circuit is being told about one pad rather than all of them"
    )
    # Every part is handed the word the circuit decided, and there is exactly
    # one place that happens.
    assert source.count("setPartState(") == 1
    assert "report.parts[at].drive" in solve


def test_every_change_to_the_bench_solves_the_circuit_again():
    """A stale answer is the same lie as a wrong one, arriving later.

    Six things change what a circuit is: a state poll, a wire made by hand, a
    wire made by `connect`, a wire removed, a part added, a part removed -- and
    `clearBench`, which does the last two at once. Miss any of them and the
    page keeps showing the previous circuit's verdict.

    **`disconnect` is the one that would be missed**, and it is why this test
    lists them rather than counting calls: it used to set the part back to
    `unknown` itself, so it looks handled.
    """
    source = RENDERER.read_text(encoding="utf-8")
    for name in ("export function setLevels(levels) {",
                 "export function disconnect(id) {",
                 "export async function addPart(kind) {",
                 "export function removePart(index) {",
                 "export function connect(pin, part, terminalName) {",
                 "function onPointerUp(event) {"):
        body = source.split(name, 1)[1].split("\n}", 1)[0]
        assert "applyCircuit()" in body, f"{name.strip()} leaves a stale circuit"
    bench = source.split("export function clearBench(", 1)[1].split("\n}", 1)[0]
    assert "applyCircuit()" in bench


def test_the_boards_supply_reaches_the_renderer_from_the_api():
    """The one number a circuit cannot be solved without, and it is not guessed.

    `webui/boards/atmega328p.py` publishes it, `webui/api.py` sends it with the
    pad map, and this reads it. A default written here would be a fourth place
    a supply voltage lives and the only one with no datasheet behind it.
    """
    source = RENDERER.read_text(encoding="utf-8")
    supply = source.split("function supplyOf(layout) {", 1)[1].split("\n}", 1)[0]
    assert "layout?.supply" in supply
    assert "if (!spec) return null;" in supply, (
        "a board with no published supply must get no circuit, not a default"
    )
    # And nothing here writes a voltage down.
    assert "5.0" not in supply and "3.3" not in supply


def test_a_part_carries_the_circuit_model_its_own_file_states():
    """The parameters travel with the mesh, not with the renderer.

    `tools/import_3d_model.py` writes them into the glTF's `asset.extras` with
    their citations, exactly as `tools/model_from_datasheet.py` writes a
    dimension with its source. A forward voltage typed into a JavaScript file
    would be a second source that could disagree with the part silently --
    which is the failure `lead_tips` records for a lead spacing.
    """
    parts = (STATIC / "parts.js").read_text(encoding="utf-8")
    # The assignment and not merely the words. A version of this test that
    # looked for `extras.electrical` anywhere survived a mutation that read the
    # extras and then threw the answer away -- measured 2026-08-27.
    assert "group.userData.electrical = electricalOf(extras);" in parts
    assert "const spec = extras.electrical;" in parts
    assert "forward_volts" in parts
    assert "2.2" not in parts and "seriesOhms: 30" not in parts
    # The old state -> drive map is gone, because a pin state is an input to a
    # circuit now rather than an answer about a part.
    assert "export const DRIVE = {" not in parts
    assert 'high: "lit"' not in parts


def test_the_bench_says_why_a_part_is_dark_rather_than_only_showing_it():
    """**The half of this that a reader can check against the board.**

    "off" is a picture to interpret; "only its anode is wired, so no current
    can return" is a sentence. And the over-rating warning is the payoff the
    whole exercise was for -- an LED across a pin with no resistor draws twice
    what an UNO rates one for, and the page has to say so rather than lighting
    it prettily.
    """
    panel = PANEL.read_text(encoding="utf-8")
    # The conditions, not the words: a mutation that replaced both with
    # `if (false)` left every mention of `part.reason` in the file and passed
    # a test that only looked for the name.
    assert "if (part.reason) {" in panel
    assert "if (part.warning) {" in panel
    assert "why.textContent = part.reason;" in panel
    assert "warn.textContent = part.warning;" in panel
    sheet = SHEET.read_text(encoding="utf-8")
    warn = sheet.split(".bench-warn {", 1)[1].split("}", 1)[0]
    # The same red every other "this went wrong" on the page uses, read from
    # the stylesheet rather than written down -- the rule the whole of this
    # file exists to keep.
    assert "var(--halt)" in warn


def test_the_bench_lists_parts_and_not_wires():
    """A wire is not a claim about anything on its own.

    An LED needs two of them and a return path before it can be said to be
    doing something, so the row a reader looks at is the part, carrying its
    wires. Listing wires put the same LED in two rows with no verdict on
    either.
    """
    panel = PANEL.read_text(encoding="utf-8")
    bench = panel.split("function renderBench() {", 1)[1].split("\n}", 1)[0]
    assert "for (const [index, part] of onBench.entries())" in bench
    assert "joined.filter((w) => w.part === index)" in bench, (
        "the wires are not being grouped onto the part they reach"
    )


# --- the broken indicator ----------------------------------------------------


def test_the_destroyed_verdict_is_latched_by_the_renderer_and_never_cleared():
    """**Without the latch the indicator is a flicker, not an indicator.**

    A blink drives pin 13 high and then low. `circuit.js` is pure and recomputes
    from the circuit alone, so it is this file that has to remember: the verdict
    goes out with the bench, comes back on the report, and is set once. Nothing
    clears it but `removePart`, which is what a person does with a burnt LED.
    """
    source = RENDERER.read_text(encoding="utf-8")
    solve = source.split("function applyCircuit() {", 1)[1].split("\n}", 1)[0]
    assert "destroyed: part.userData.destroyed === true," in solve, (
        "the solver is not told which parts are already destroyed, so a "
        "verdict would clear on the next state poll"
    )
    assert "if (report.parts[at].destroyed) part.userData.destroyed = true;" in solve
    # Set and never unset. A line that wrote `false` anywhere would be a way
    # back from permanent, and there is not supposed to be one.
    assert "userData.destroyed = false" not in source


def test_a_destroyed_part_is_painted_from_the_stylesheet():
    """`--halt` is what "this went wrong" is in whichever theme is on.

    A hex literal for "charred" would be right in one theme and invisible in
    the other, which is the contrast-not-lightness trap this file's own state
    ramp records twice. And it cannot reuse `off`: dark is already taken by a
    part that is simply not being driven, and a broken LED that looked like one
    would say nothing.
    """
    source = RENDERER.read_text(encoding="utf-8")
    palette = source.split("function readPalette() {", 1)[1].split("\n}", 1)[0]
    assert 'halt: read("--halt")' in palette
    parts = (STATIC / "parts.js").read_text(encoding="utf-8")
    damaged = parts.split('if (drive === "damaged") {', 1)[1].split("  }", 1)[0]
    assert "palette.halt" in damaged
    assert "emissiveIntensity = 0" in damaged, (
        "a destroyed part must not glow, whatever colour it is"
    )
    sheet = SHEET.read_text(encoding="utf-8")
    assert "--halt:" in sheet


def test_the_bench_says_destroyed_in_words_and_not_only_in_colour():
    """At the size a 5 mm LED is drawn, a broken red one and a lit red one are
    both red.

    Colour is the only channel the 3D view has, so it is a cue rather than the
    claim. The row carries the word, and the reason -- which names the limit
    that killed it -- goes red rather than the quiet grey every other verdict
    gets.
    """
    panel = PANEL.read_text(encoding="utf-8")
    assert "if (part.destroyed) {" in panel
    assert 'badge.textContent = "destroyed";' in panel
    assert 'why.className = part.destroyed ? "bench-warn" : "bench-why";' in panel
    sheet = SHEET.read_text(encoding="utf-8")
    dead = sheet.split(".bench-dead {", 1)[1].split("}", 1)[0]
    assert "var(--halt)" in dead
    assert '.bench-list li[data-drive="damaged"]' in sheet


def test_every_number_a_part_publishes_crosses_into_the_renderer():
    """A parameter added to the part and not to `electricalOf` is dropped
    silently.

    That is not hypothetical: `absolute_amps` was added to `LED_ELECTRICAL`
    while `webui/static/parts.js` still mapped three fields, and the page
    carried an LED that could never be declared destroyed while every test went
    on passing. Both sides are checked from the Python table, so a new number
    fails here rather than disappearing in transit.
    """
    from tools.import_3d_model import PARTS

    parts = (STATIC / "parts.js").read_text(encoding="utf-8")
    published = [part for part in PARTS if part.electrical is not None]
    assert published, "no part publishes an electrical model, so this proves nothing"
    for part in published:
        for name in part.electrical.cited:
            assert f"spec.{name}" in parts, (
                f"{part.name} publishes {name} and parts.js never reads it"
            )


def test_the_scene_has_an_environment_for_metal_to_reflect():
    """**Without this, `metalness` is a lie**, and the two are one change.

    A metal's colour IS its reflection. Raise metalness with nothing in front
    of the surface and it renders black, so the finish table in
    `tools/import_3d_model.py` and this environment cannot be split across two
    commits without the first one making the picture worse.

    Built here rather than by vendoring `RoomEnvironment`: `PMREMGenerator` is
    already in the vendored core and `fromScene` takes any scene.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "view.scene.environment = studio(view.renderer)" in source
    room = source.split("function studio(renderer) {", 1)[1].split("\n}", 1)[0]
    assert "PMREMGenerator" in room
    assert "pmrem.dispose()" in room
    # The prefiltered texture is this file's to free, and the six planes that
    # made it are finished with the moment it exists.
    assert "release(object)" in room
    assert "view.scene.environment?.dispose();" in source
    # It is illumination, not a UI surface: the background stays the palette's.
    #
    # **Every assignment, not one of them.** `mount` and `refreshTheme` both
    # set the background, so an `in` check on the string passed while one of
    # the two was changed to show the environment instead -- caught by
    # mutation 2026-08-27. A rule about a field has to be checked against every
    # write to that field.
    backgrounds = re.findall(r"scene\.background\s*=\s*([^;]+);", source)
    assert len(backgrounds) >= 2
    for assigned in backgrounds:
        assert assigned.strip() == "view.palette.ground", (
            f"the scene background is set to {assigned.strip()!r}, which is "
            f"not the palette's ground"
        )


def test_the_environment_is_greyscale_and_writes_down_no_colour():
    """The `NEUTRAL_LIGHT` argument, extended to a room.

    White light leaves every material the colour its own file said. A tinted
    environment would shift every material in the scene together and be wrong
    in whichever theme it was not chosen for -- which is the trap this file's
    state ramp records twice. `setScalar` takes a luminance, so the studio adds
    no colour to a file whose whole rule is that it writes none down.
    """
    source = RENDERER.read_text(encoding="utf-8")
    studio = source.split("const STUDIO = {", 1)[1].split("};", 1)[0]
    assert "ceiling" in studio and "wall" in studio and "floor" in studio
    room = source.split("function studio(renderer) {", 1)[1].split("\n}", 1)[0]
    found = [m for m in COLOUR_LITERAL.findall(room) if not _in_comment(room, m)]
    assert not found, f"the studio writes down a colour: {found}"

    # **This used to assert `setScalar` was in the room, and that check went on
    # passing after the room stopped calling it.** The six flat planes became a
    # graded sphere and a graded disc, both of which write their luminance into
    # a vertex-colour buffer instead -- and `setScalar` survived in a COMMENT
    # explaining the colour space, so a proxy for the rule kept agreeing with a
    # file that no longer contained the thing it named.
    #
    # So the rule is checked directly now: every colour this room writes sets
    # its three channels from one value, which is what "greyscale" means and is
    # what `setScalar` used to guarantee.
    channels = re.findall(r"(\w+)\[vertex \* 3(?: \+ ([12]))?\] = (\w+);", room)
    assert channels, "the room writes no vertex colours at all"
    buffers: dict[str, list[tuple[str, str]]] = {}
    for name, channel, value in channels:
        buffers.setdefault(name, []).append((channel or "0", value))
    for name, writes in buffers.items():
        assert sorted(c for c, _ in writes) == ["0", "1", "2"], (
            f"{name} does not write exactly red, green and blue: {writes}"
        )
        assert len({value for _, value in writes}) == 1, (
            f"{name}'s three channels come from different values: {writes}, "
            f"which is a colour and not a luminance"
        )


def test_the_ambient_light_was_replaced_rather_than_added_to():
    """An image-based light IS the ambient term, with direction.

    Keeping both would double-count the fill and wash the scene out, and the
    directional gradient is the whole reason to have an environment: the top of
    a pin catches the ceiling while its flank catches the wall, which is what
    makes a curved metal surface read as curved.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "AmbientLight" not in source, (
        "an ambient light and an environment are two fills, not one"
    )
    # **Constructions, not mentions, and the difference has cost a session
    # already.** This counted the bare word `DirectionalLight` and went red the
    # moment a comment explained how a directional light takes its direction
    # from position minus target -- a true sentence, worth keeping, and nothing
    # to do with how many lights are in the scene. The same shape of tripwire
    # fired on `NEUTRAL_LIGHT` on 2026-08-27.
    #
    # **And it no longer counts to one, because the answer is now three.**
    # OH-86 samples the hemisphere with three shadowed lights rather than
    # lighting from one direction and calling the rest ambient. What survives
    # of the original rule is the part that was ever true: there is no
    # `AmbientLight` beside the environment, and every directional light in the
    # scene comes from the one table that says how many there are, so a fourth
    # cannot be added anywhere else.
    #
    # **And the table grew a fourth entry in OH-111, which does not weaken
    # this.** What it protects is that there is ONE construction site, so a
    # light cannot be added anywhere else; the bounce is a named constant fed
    # through that same site rather than a `new DirectionalLight` somewhere
    # in a function.
    assert source.count("new THREE.DirectionalLight") == 1, (
        "a light is built outside the LIGHTS table"
    )
    assert "[...LIGHTS, BOUNCE].map((sample) =>" in source


# --- a layout that reads more than the viewport's width ----------------------


def _rule(sheet: str, selector: str) -> str:
    """The declarations of one rule, by its selector."""
    assert selector in sheet, f"no {selector} rule in the stylesheet"
    return sheet.split(selector, 1)[1].split("{", 1)[1].split("}", 1)[0]


def test_the_one_column_rule_fires_on_shape_as_well_as_width():
    """**A portrait monitor is not a narrow one, and the page used to conflate
    them.**

    1065 x 1920 is 1,065 px wide -- past every width threshold in this
    stylesheet -- so it got two columns, and the board came out 382 px wide,
    36% of the page, on a display with 1,920 px of height going spare. Two
    columns costs width, and width is the dimension a portrait display has
    least of.

    Measured after: 999 x 749, 94% of the page.
    """
    sheet = SHEET.read_text(encoding="utf-8")
    assert "(max-width: 900px), (max-aspect-ratio: 5 / 4)" in sheet, (
        "the single-column layout is chosen by width alone, so a tall narrow "
        "viewport is handed a layout meant for a wide one"
    )


def test_the_three_column_rule_is_not_gated_on_height():
    """The fix that was tried, measured, and taken back out.

    A wide short window did give a bad board -- 359 x 269 at 1585 x 620 -- and
    requiring 700 px of height to use three columns looked like the answer.
    Measured, it made things worse: the page went from 2.9 screens to 4.1,
    because two columns stack what three place side by side and vertical room
    is exactly what a short window lacks. The board was starved by a flex
    basis, not by the column count.
    """
    sheet = SHEET.read_text(encoding="utf-8")
    assert "@media (min-width: 1500px) {" in sheet
    assert "min-width: 1500px) and (min-height" not in sheet, (
        "gating the wide layout on height was measured to make a short window "
        "scroll more, not less"
    )


def test_the_layout_is_not_capped_to_a_width_a_reader_did_not_choose():
    """The other fix that was tried and measured away.

    A `max-width` on `main` looked right for an ultrawide, and it cost the
    board 47% of its width there: the canvas went 1037 -> 549 on a 3440 px
    display, because a third of 2,100 is a much smaller column than a third of
    3,425. What the cap was for is already done by `.prose p`'s 74ch, which
    holds the longest measured text line at 558 px however wide the panel gets.
    """
    sheet = SHEET.read_text(encoding="utf-8")
    main = _rule(sheet, "\nmain ")
    # The DECLARATION, not the word: the comment in that rule explains at
    # length why there is no max-width, and a check for the bare word finds
    # the explanation and calls it the thing it explains.
    assert "max-width:" not in main
    # And the thing that made the cap unnecessary is still there.
    assert "max-width: 74ch" in sheet


def test_one_ratio_governs_the_canvas_and_the_wrap_it_forces():
    """**Three places have to agree, so they are all written from one number.**

    The canvas is 4:3. It bounds its height by `--stage` and its width by the
    width that ratio implies -- without the second bound, `max-height` clamps
    the height and leaves the width alone, and the canvas silently becomes a
    letterbox again. And `.pins-stage`'s flex basis is the same expression,
    because the honest rule for whether the 32-row pin table may sit beside the
    board is *only while the board can still be as big as the viewport allows*.

    Two hand-picked bases were tried first and both were wrong somewhere: 320
    left the canvas at 25% of a 1905 x 1080 page, and 420 fixed one window and
    not that one. A derived basis fixed every size at once.

    This test reads the ratio out of the canvas and insists the other two are
    written from it, so changing 4:3 to anything else cannot half-land.
    """
    sheet = SHEET.read_text(encoding="utf-8")
    canvas = _rule(sheet, "#board-pins-canvas ")
    ratio = re.search(r"aspect-ratio:\s*(\d+)\s*/\s*(\d+)", canvas)
    assert ratio, "the canvas no longer states an aspect ratio"
    wide, tall = ratio.group(1), ratio.group(2)
    derived = f"calc(var(--stage) * {wide} / {tall})"
    assert "max-height: var(--stage);" in canvas, (
        "the canvas height is not bounded by the shared number"
    )
    assert derived in canvas, (
        f"the canvas bounds its height but not its width, so a short viewport "
        f"clamps one and not the other and the ratio becomes a letterbox; "
        f"expected max-width: {derived}"
    )
    stage = _rule(sheet, ".pins-stage ")
    assert derived in stage, (
        f"the wrap threshold is not derived from the canvas's own ceiling, so "
        f"it is a number rather than a reason; expected {derived}"
    )
    # `--stage` is declared once, on the parent both of them are inside.
    pins = _rule(sheet, "\n.pins ")
    assert re.search(r"--stage:\s*\d+vh;", pins), (
        "--stage is not defined on .pins, so the canvas and the flex basis "
        "cannot be reading the same one"
    )


# --- shadows, tone mapping, and a room with no edge in it -------------------


def test_the_scene_casts_shadows_and_everything_in_it_takes_part():
    """**Fifteen components floated for as long as this scene had no shadow.**

    The DIP-28, the header shrouds and the pad posts met the board at a hard
    edge with nothing under them, which is what "pasted on" looks like: a
    contact shadow is the thing that says one object is resting on another.

    The flags are set in one traversal rather than at each place a mesh is
    made, and this checks that, because there are six such places -- the slab,
    the pads, the vendor's model, the parts, the wires and the terminal targets
    -- and a seventh is the one that would be forgotten.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "view.renderer.shadowMap.enabled = true;" in source
    # **The effective value, not the written one.** This said
    # `PCFSoftShadowMap` and passed while the renderer logged
    # "PCFSoftShadowMap has been deprecated. Using PCFShadowMap
    # instead." on every load -- a test agreeing with a comment rather
    # than with the program. Deprecated names are refused by name so the
    # next one cannot arrive the same way.
    #
    # Comments stripped before the refusal, because the sentence explaining WHY
    # the deprecated name is refused necessarily contains it -- and the first
    # version of this line went red on its own reasoning. That is the third
    # time in this file: `NEUTRAL_LIGHT`, then `DirectionalLight`, now this.
    assert "THREE.PCFShadowMap" in source
    code = stripped(source)
    assert "PCFSoftShadowMap" not in code, (
        "r185 deprecates it and silently substitutes PCFShadowMap, so the "
        "source would be describing a setting the renderer does not use"
    )
    # Set from the light's own table entry since OH-111 added one that does
    # not cast, and set in the SAME one place, which is what this checks.
    assert "light.castShadow = sample.casts !== false;" in source
    fit = source.split("function castShadows(box, centre) {", 1)[1].split("\n}", 1)[0]
    assert "object.castShadow = true;" in fit
    assert "object.receiveShadow = true;" in fit
    assert "view.scene.traverse" in fit, (
        "the flags are set on named objects rather than on whatever is in the "
        "scene, so the next mesh added will float"
    )
    # And it runs after every change, which is what makes one traversal enough.
    assert "castShadows(box, centre);" in source


def test_the_shadow_camera_is_fitted_to_the_scene_and_not_to_a_number():
    """A board is 68 mm and a XIAO is 20 mm, so a fixed frustum fits neither.

    `frameScene` already computes the scene's box to place the camera, and the
    shadow camera needs exactly that box: too small and the far edge of the
    board casts nothing, too large and every shadow texel covers more than it
    can resolve. Deriving both from one box is also what stops the two answers
    disagreeing.
    """
    source = RENDERER.read_text(encoding="utf-8")
    fit = source.split("function castShadows(box, centre) {", 1)[1].split("\n}", 1)[0]
    assert "box.getBoundingSphere" in fit
    # **All of them, and this is checked because it survived a mutation.**
    # Fitting only the first leaves the other two with three.js's default 5x5
    # frustum, which on a 68 mm board covers a tenth of it: their shadows would
    # appear over a small square in the middle and stop, and every assertion
    # below would still pass because the assignments are all still there.
    assert "for (const light of view.lights) {" in fit, (
        "the frustum is fitted for some of the lights rather than all of them"
    )
    for edge in ("lens.left", "lens.right", "lens.top", "lens.bottom",
                 "lens.near", "lens.far"):
        assert f"{edge} = " in fit, f"{edge} is left at its default"
    assert "lens.updateProjectionMatrix();" in fit, (
        "a frustum changed without this is a frustum the GPU never hears about"
    )
    # The light is moved with it, or the frustum points somewhere else.
    assert "light.position.set" in fit
    assert "light.target.position.copy(centre);" in fit
    # And its target has to be in the scene at all, or it keeps the identity
    # matrix and the light aims at the origin whatever this sets.
    assert "view.scene.add(light.target);" in source


def test_the_shadow_bias_is_stated_in_millimetres():
    """`normalBias` and not `bias`, because one of them has units this scene has.

    `bias` is an offset in the shadow camera's clip space, and that camera is
    refitted to the scene every time a board or a part changes size -- so a
    value tuned against one board is wrong for the next. `normalBias` is in
    world units, and this scene's world unit is the millimetre, so the number
    can be reasoned about: 60 um is wider than a shadow texel across the Uno
    and thinner than a DIP-28's leg.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "light.shadow.normalBias = SHADOW_BIAS_MM;" in source
    assert "shadow.bias" not in source, (
        "a clip-space bias on a frustum that is refitted per board is a number "
        "that cannot be right twice"
    )
    stated = float(re.search(r"const SHADOW_BIAS_MM = ([\d.]+);", source).group(1))
    assert 0.0 < stated < 0.5, f"{stated} mm is not a plausible surface offset"


def test_the_renderer_tone_maps_and_not_with_a_film_look():
    """**The colours in this scene are measurements, so the transfer curve is
    not free to move them.**

    Without tone mapping every value above 1.0 clips flat, which is the default
    that matters least on a diffuse scene and most on one with nine metal
    surfaces and a softbox: measured on the Uno close-up, 6.82% of pixels had a
    channel at 255. With `NeutralToneMapping` that is 0.011% and the frame uses
    248 distinct luminances rather than 217.

    ACES is the popular choice and is refused here on purpose. It is a film
    look: it shifts hue and desaturates on the way through, and #313d63 is the
    Uno's solder mask read out of PICSimLab's own artwork while #ffcf80 is the
    XIAO's gold -- every one of them cited in `FINISHES`. Khronos PBR Neutral
    leaves an in-gamut colour where it is and only compresses what is too
    bright to show.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "view.renderer.toneMapping = THREE.NeutralToneMapping;" in source
    # Comments stripped first, the same way `test_the_renderer_writes_down_no
    # _colour_of_its_own` does it: the reasoning above the line names ACES in
    # order to refuse it, and a check that a sentence can trip is not a check.
    code = stripped(source)
    assert "ACESFilmic" not in code
    assert "toneMappingExposure" not in code, (
        "an exposure other than 1.0 is a second place the picture's brightness "
        "is decided, and the room already decides it"
    )


def test_the_room_has_no_hard_edge_anywhere_in_it():
    """**Every hard edge up there comes back as a straight line on curved metal.**

    The six flat planes this replaced put the corner between their ceiling and
    their wall across the Arduino Uno's electrolytic lids as a dead-straight
    seam, cream one side and black the other -- which the constant's own
    comment had predicted and 0.04 of blur did not hide. A rectangular softbox
    was tried next and drew the same line with its own border.

    So both surfaces in this room are graded: the sky by height and the
    softbox from its middle to its rim. Neither has an edge to reflect.
    """
    source = RENDERER.read_text(encoding="utf-8")
    room = source.split("function studio(renderer) {", 1)[1].split("\n}", 1)[0]
    assert "SphereGeometry" in room and "PlaneGeometry" not in room, (
        "a plane has a border and a border is an edge"
    )
    assert "CircleGeometry" in room
    # Both gradients are eased rather than linear: a straight ramp still has a
    # discontinuity in its slope, and a polished lid finds it.
    assert room.count("(3 - 2 * ") == 2, (
        "one of the two gradients is a straight ramp"
    )


# --- the softbox, and the direction it has to be in -------------------------
#
# **OH-92 is the ticket where the whole lighting chain was correct and aimed
# past the reader.** The clear coat OH-90 measured worked, the albedos OH-91
# corrected were right, and the softbox sat at the zenith while the default
# camera's mirror direction was 48 degrees away -- so none of it reached the
# only view most people ever see. Measured on the Uno, switching nothing but
# the coat at the default camera: the mask's brightest tenth moved 132.7 to
# 132.9 before, and 134.4 to 210.7 after.
#
# The tests below pin the RELATIONSHIP rather than the numbers, because the
# numbers are allowed to move and the relationship is not.


def camera_direction(source):
    """`CAMERA_FROM`, as a dict of floats."""
    written = re.search(r"^const CAMERA_FROM = \{([^}]*)\};$", source,
                        re.MULTILINE)
    assert written, "CAMERA_FROM is not one line of three named numbers"
    return {axis: float(value) for axis, value in
            re.findall(r"([xyz]):\s*(-?[\d.]+)", written.group(1))}


def softbox_direction(source, camera):
    """The vector `studio` builds, resolved against `CAMERA_FROM`.

    Resolved rather than string-matched: the point is that the softbox's
    direction IS the camera's, mirrored, and a test that accepts the literal
    `(-0.1, 0.85, -0.75)` would pass while the two silently drifted apart --
    which is the exact failure OH-92 existed to fix, and the same shape as the
    sRGB conversion that lived in `readPalette` and not in the writer.
    """
    room = source.split("function studio(renderer) {", 1)[1].split("\n}", 1)[0]
    built = re.search(r"new THREE\.Vector3\(([^)]*)\)\s*\.normalize\(\)", room,
                      re.DOTALL)
    assert built, "the softbox's direction is not built from a normalised vector"
    resolved = []
    for argument in built.group(1).split(","):
        argument = argument.strip()
        named = re.fullmatch(r"(-?)CAMERA_FROM\.([xyz])", argument)
        assert named, (
            f"the softbox's direction uses {argument!r} rather than a "
            f"component of CAMERA_FROM, so the two can drift apart"
        )
        resolved.append((-1.0 if named.group(1) else 1.0)
                        * camera[named.group(2)])
    return resolved


def elevation_and_azimuth(vector):
    """Degrees above the board's plane, and around it. The board's normal is +y."""
    across = math.hypot(vector[0], vector[2])
    return (math.degrees(math.atan2(vector[1], across)),
            math.degrees(math.atan2(vector[0], vector[2])) % 360)


def test_the_softbox_sits_where_a_flat_board_reflects_the_default_camera():
    """**A coat returns what lies in the MIRROR direction, and nothing else.**

    The board's normal is +y, so a surface on it returns whatever sits at
    `reflect(view, +y)` -- same elevation, opposite side. The softbox spent
    three tickets at the zenith, where its own 14.5-degree half-angle put it 27
    degrees clear of that direction at the default camera, and every
    improvement made to the coat beneath it was therefore invisible.

    This is the assertion that would have caught it: the two directions are
    computed from the one constant and compared, so moving the camera without
    moving the light fails here rather than in a screenshot nobody takes.
    """
    source = RENDERER.read_text(encoding="utf-8")
    camera = camera_direction(source)
    up, around = elevation_and_azimuth([camera["x"], camera["y"], camera["z"]])
    lit, opposite = elevation_and_azimuth(softbox_direction(source, camera))

    assert lit == pytest.approx(up, abs=0.5), (
        f"the softbox is {lit:.1f} degrees up and the board reflects toward "
        f"{up:.1f}; a mirror does not compromise"
    )
    assert abs(opposite - around) == pytest.approx(180.0, abs=0.5), (
        f"the softbox is at azimuth {opposite:.1f} and the reflection points "
        f"at {(around + 180) % 360:.1f}"
    )
    assert lit > 0, "the softbox is under the board, which is not lit at all"


def test_the_camera_direction_is_written_down_once():
    """**`frameScene` used to hold these three numbers itself**, which is what
    let the light and the camera disagree for as long as both existed. If the
    framing goes back to literals, the test above still passes against a
    `CAMERA_FROM` nothing reads."""
    source = RENDERER.read_text(encoding="utf-8")
    framing = source.split("function frameScene() {", 1)[1].split("\n}", 1)[0]
    assert framing.count("CAMERA_FROM.") == 3, (
        "frameScene does not take all three of its axes from CAMERA_FROM"
    )
    assert not re.search(r"reach \* [\d.]", framing), (
        "frameScene multiplies reach by a literal again"
    )


def test_the_softbox_is_small_enough_to_cross_the_board_rather_than_cover_it():
    """**A source as wide as the board's own sweep is a wash, not a highlight.**

    Perspective makes the mirror direction swing 35 to 69 degrees between the
    Uno's far and near edges -- 34 degrees, measured at the camera
    `describe()` reports. The softbox subtends `2 * atan(radius / reach)`, and
    the first version of OH-92 aimed a 28.9-degree source at the middle of
    that, which lit the whole face evenly and read exactly as flat as the
    zenith version it replaced. Half of the sweep is the ceiling; the measured
    peak, 14.7 degrees, sits comfortably under it.
    """
    source = RENDERER.read_text(encoding="utf-8")
    written = re.search(r"^const SOFTBOX = \{([^}]*)\};$", source, re.MULTILINE)
    assert written, "SOFTBOX is not one line"
    numbers = {name: float(value) for name, value in
               re.findall(r"(\w+):\s*([\d.]+)", written.group(1))}
    subtends = 2 * math.degrees(math.atan(numbers["radius"] / numbers["reach"]))
    assert subtends < 17.0, (
        f"the softbox subtends {subtends:.1f} degrees against a 34-degree "
        f"sweep across the board, which covers it rather than crossing it"
    )
    assert numbers["reach"] < 1.0, (
        "the softbox is outside the sky sphere, which is drawn BackSide and "
        "would hide it"
    )
    # **The room keeps the light it had, which is the rule both shrinks
    # followed and neither wrote down as a check.** `bright` rises with the
    # square of the shrink -- 0.5 to 0.16 took 2.4 to 18.0, and 0.16 to 0.08
    # took 18.0 to 72.0 -- so that a radius sweep compares the SHAPE of the
    # highlight rather than the exposure. Shrinking the disc without paying for
    # it is how a measured setting turns into a dimmer picture nobody meant.
    assert numbers["bright"] * numbers["radius"] ** 2 == pytest.approx(
        18.0 * 0.16 ** 2, rel=0.02), (
        f"radius {numbers['radius']} at bright {numbers['bright']} emits "
        f"{numbers['bright'] * numbers['radius'] ** 2 / (18.0 * 0.16 ** 2):.2f} "
        f"times the light the measured setting did"
    )


def test_the_softbox_turns_to_face_the_board_rather_than_holding_a_rotation():
    """**`rotation.x = PI / 2` was right only while the disc hung overhead.**

    Once the position is derived from `CAMERA_FROM`, a fixed rotation leaves
    the disc edge-on to the board -- and a foreshortened disc is a smaller
    source than the one `SOFTBOX`'s table was measured with, so the constant
    would quietly stop meaning what its comment says.
    """
    source = RENDERER.read_text(encoding="utf-8")
    room = source.split("function studio(renderer) {", 1)[1].split("\n}", 1)[0]
    code = stripped(room)
    assert "light.lookAt(" in code
    assert "rotation.x" not in code, (
        "a fixed rotation cannot follow a derived position"
    )


# --- the hemisphere, sampled three times ------------------------------------


def _numbers(source: str, name: str) -> float:
    """One `const NAME = <number>;` out of the renderer."""
    found = re.search(rf"^const {name} = ([\d.]+);", source, re.MULTILINE)
    assert found, f"no {name} in the renderer"
    return float(found.group(1))


def test_every_light_that_samples_the_sky_casts_a_shadow():
    """**A light that does not cast is a light no crevice can hide from.**

    This is the whole mechanism of OH-86. An image-based light arrives from
    every direction at once, so it casts nothing and darkens nothing: the gap
    under a header shroud was lit exactly as brightly as open board because the
    illumination reaching it did not come from a direction anything could block.

    So the fill is directions now, and each one is blocked separately. Three is
    a coarse estimate of an integral that a per-pixel method computes exactly,
    and the source says so rather than calling it ambient occlusion.

    **OH-111 narrowed this from "every light" to "every light that samples the
    sky", and the narrowing is argued rather than convenient.** The bounce off
    the bench is not sky, and there is nothing under the board for it to be
    blocked by: of the 1 to 21 parts each vendor places on the back of these
    boards, `CORRESPONDENCE` draws none -- they are test points, logos and one
    solder jumper, and not one of them has a body. What must not happen is a
    light in the UPPER hemisphere quietly opting out, which is what the second
    assertion holds.
    """
    source = RENDERER.read_text(encoding="utf-8")
    table = source.split("const LIGHTS = [", 1)[1].split("];", 1)[0]
    entries = re.findall(r"\{[^}]*share:\s*([\d.]+)\s*\}", table)
    assert len(entries) >= 2, (
        "one light is one direction, which is what this ticket replaced"
    )
    assert "casts" not in table, (
        "a light in the upper hemisphere has opted out of casting; the three "
        "that sample the sky are the estimate, and two of them is not it"
    )
    # Built in one place, so `castShadow` cannot be set on some of them
    # anywhere but the light's own entry.
    built = source.split("view.lights = [...LIGHTS, BOUNCE].map", 1)[1]
    assert "light.castShadow = sample.casts !== false;" in built.split("});", 1)[0]


def test_the_lights_shares_add_up_to_one_whole_light():
    """So the three can be rebalanced without the scene changing brightness.

    `share` times `LIGHT_TOTAL` is each light's intensity. If the shares summed
    to something else, moving energy between them would also move the exposure,
    and the next person to adjust the balance would be adjusting two things.
    """
    source = RENDERER.read_text(encoding="utf-8")
    table = source.split("const LIGHTS = [", 1)[1].split("];", 1)[0]
    shares = [float(value) for value in re.findall(r"share:\s*([\d.]+)", table)]
    assert shares, "no shares in the table"
    assert abs(sum(shares) - 1.0) < 1e-9, f"the shares sum to {sum(shares)}"


def test_the_lights_point_down_at_the_board_and_not_up_at_it():
    """A bench is lit from above, and a light from below is a stage effect.

    Every direction in the table is a place the light comes FROM, so its `y`
    has to be positive -- and the flattest of them still needs to be well clear
    of the horizon, or a board 1.6 mm thick starts casting a shadow the length
    of itself across the bench.
    """
    source = RENDERER.read_text(encoding="utf-8")
    table = source.split("const LIGHTS = [", 1)[1].split("];", 1)[0]
    heights = [float(value) for value in re.findall(r"y:\s*(-?[\d.]+)", table)]
    assert heights, "no directions in the table"
    for height in heights:
        assert height > 0.3, f"a light at y={height} is nearly edge-on"


def test_the_room_is_dimmed_by_exactly_what_the_lights_gained():
    """**The trade this ticket is, in one assertion.**

    Every unit of brightness that lives in the environment is a unit no shadow
    can ever subtract from, so the mechanism is moving some of it into lights
    that cast. What it must not do is turn the room off: the environment is the
    only thing a metal has to reflect, and at zero `metalness` is a lie again --
    which is the argument OH-82 made when it built the room in the first place.

    Measured rather than asserted by eye: at 0.30 the capacitor lids come out
    duller than the moulded plastic beside them, which inverts the one
    relationship anybody can check against a real board.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "view.scene.environmentIntensity = ENVIRONMENT_SHARE;" in source
    share = _numbers(source, "ENVIRONMENT_SHARE")
    assert 0.0 < share < 1.0, (
        f"{share} either turns the room off or leaves it undimmed, and the "
        f"whole change is that it is neither"
    )
    # And the lights carry more than they did when the room was undimmed, or
    # the scene simply got darker rather than being re-lit.
    assert _numbers(source, "LIGHT_TOTAL") > 2.4


def test_the_studio_blur_is_inside_what_the_prefilter_can_actually_do():
    """**A setting the generator clips is a setting the source is wrong about.**

    `PMREMGenerator._blur` computes `samples = 1 + floor(STANDARD_DEVIATIONS *
    sigmaPixels)` and warns and clamps above `MAX_SAMPLES = 20`. Samples are
    linear in sigma, and the console gave the conversion when this was briefly
    0.06: *"is too large and will clip, as it requested 30 samples when the
    maximum is set to 20"*. 30 samples at 0.06 puts 20 samples at 0.04, which
    is the ceiling -- and is what three.js's own `RoomEnvironment` passes.

    Every frame measured under OH-85 was rendered at 0.04 while the file said
    0.06, so the picture was never wrong and the file was. The number is
    checked against the vendored constant rather than written twice, so a
    three.js upgrade that raises `MAX_SAMPLES` fails here instead of leaving
    this paragraph quietly stale.
    """
    source = RENDERER.read_text(encoding="utf-8")
    blur = float(re.search(r"^const STUDIO_BLUR = ([\d.]+);", source,
                           re.MULTILINE).group(1))
    vendor = (STATIC / "vendor" / "three.module.js").read_text(encoding="utf-8")
    most = int(re.search(r"const MAX_SAMPLES = (\d+);", vendor).group(1))
    # 0.06 asked for 30, so one sample is 0.002 of sigma and the ceiling is
    # `most` of them.
    ceiling = 0.002 * most
    assert blur <= ceiling + 1e-9, (
        f"STUDIO_BLUR {blur} asks for more than the {most} samples "
        f"PMREMGenerator will do; it would be clipped to {ceiling} and the "
        f"source would be describing a blur that never happens"
    )


# --- a board a reader can actually see --------------------------------------


def test_the_panel_says_what_it_is_waiting_for_when_no_board_is_loaded():
    """**It used to set a variable and return, saying nothing at all.**

    A reader who picked a board from the selector and stopped there got a blank
    area with no explanation -- the canvas at its 300 x 150 default, the caption
    still holding the static sentence from the HTML, and no hint that an image
    has to be loaded first. The `!view.present` branch beside it has always
    spoken, so this was the one exit that forgot to.

    The load address is named in the message because that is the step people
    miss: a raw `.bin` carries no addresses and is refused without one.
    """
    panel = PANEL.read_text(encoding="utf-8")
    refusal = panel.split("if (!response.ok) {", 1)[1].split("return;", 1)[0]
    # **The note line and not the caption** (OH-168). The caption under the
    # canvas was removed with the three geometry sentences it carried, and this
    # message went with it -- so it moved here, which is the only line left that
    # speaks. What is asserted is that the exit still SAYS something and still
    # names the step people miss, which is what this test was always for.
    assert "$(NOTE).textContent = WAITING;" in refusal, (
        "the no-board exit still says nothing"
    )
    assert "CAPTION" not in panel, (
        "the caption is back; this test guards the message, not the element"
    )
    assert "$(CANVAS).hidden = true;" in refusal, (
        "a blank 300x150 rectangle is left where a board should be"
    )
    waiting = panel.split("const WAITING =", 1)[1].split(";", 1)[0]
    assert ".bin" in waiting and "load address" in waiting, (
        "the message does not name the step that is actually missed"
    )


def test_the_panel_asks_the_server_what_it_has_when_the_page_opens():
    """**Nothing asked, so a fresh page never found out there was a board.**

    `reload` was called only by `emulator.js`, after a load, a build or a reset.
    A page opened cold therefore sat on the static caption in the HTML forever
    -- and, because the server keeps its board selection across page loads,
    RELOADING with a board already loaded showed an empty view until something
    was clicked. The board was there; only this panel did not know.

    **OH-94 moved the caller and this test now asserts the BEHAVIOUR rather
    than the file.** The panel used to run `reload()` at module scope, which
    was the only startup path there was. It cannot stay there: it runs before
    `/api/boards` has filled the picker, so it can only ask about no board in
    particular -- a request that cannot succeed when nothing is loaded, and a
    second console error beside the picker's own probe. `fillBoardPicker` now
    owns startup. A test that had gone on naming the panel would have been
    asserting where the code lives instead of what the page does.
    """
    panel = PANEL.read_text(encoding="utf-8")
    page = (STATIC / "emulator.js").read_text(encoding="utf-8")
    both = stripped(panel + "\n" + page)
    # Something, somewhere, draws without waiting to be clicked.
    assert "boardPins?.reload()" in both, (
        "nothing draws the board at startup, so a fresh page never asks"
    )
    # And it asks whether the server already has one, which is the half of
    # OH-89 about reloading the page while a board is running.
    picker = both.split("function fillBoardPicker", 1)[1].split("\n}", 1)[0]
    assert 'api("/api/board/pins")' in picker, (
        "the picker never asks what the server has, so reloading the page "
        "while a board runs would show whichever board sorts first"
    )
    assert "select.value = view.board" in picker


def test_a_board_is_brought_into_view_once_and_not_on_every_poll():
    """Moving the caption fixed every width measured except 1366 x 768.

    There two columns put the whole load-and-run panel above the canvas in the
    same column, and it still starts 1,266 px down. Shortening that panel's
    prose to win a screenful is the trade this repository has refused before,
    so the board comes to the reader instead.

    **Once, and the guard is the point.** `reload` runs on a timer while a board
    is running, so scrolling on every call would drag the page out from under
    anyone reading the panel above while a blink ran. `block: "nearest"` is the
    other half: a reader who can already see the board is not moved at all,
    which is why the 1920 and 2560 cases scroll zero pixels.
    """
    panel = PANEL.read_text(encoding="utf-8")
    assert 'scrollIntoView({ block: "nearest" })' in panel, (
        "either it does not scroll, or it scrolls further than it needs to"
    )
    guarded = panel.split("if (view.board !== shown) {", 1)
    assert len(guarded) == 2, "the scroll is not guarded by a board change"
    assert "scrollIntoView" in guarded[1].split("}", 1)[0]
    assert "let shown = null;" in panel


# --- the coat, on the renderer's side ---------------------------------------


def test_the_reader_understands_the_clearcoat_extension():
    """**This file's glTF reader is its own, and narrow on purpose.**

    `readModel` takes `baseColorFactor`, `metallicFactor` and `roughnessFactor`
    and nothing else, so an extension the importer writes is invisible here
    unless this file is taught it. A board whose coat was written and not read
    would be a measurement travelling in a file that nothing opens.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert 'const CLEARCOAT = "KHR_materials_clearcoat";' in source
    surface = source.split("function surfaceOf(", 1)[1].split("\n}", 1)[0]
    assert "material.extensions?.[CLEARCOAT]" in surface
    assert "clearcoat: coat.clearcoatFactor" in surface
    assert "clearcoatRoughness: coat.clearcoatRoughnessFactor" in surface


def test_the_expensive_material_is_built_only_where_there_is_a_coat():
    """`MeshPhysicalMaterial` is a superset and a heavier shader.

    Every surface in this scene except the two solder masks is a single layer
    that `MeshStandardMaterial` describes exactly, and there are ten materials
    on the Arduino Uno. Building the expensive one for all of them to make one
    of them right is a cost with no picture behind it.
    """
    source = RENDERER.read_text(encoding="utf-8")
    surface = source.split("function surfaceOf(", 1)[1].split("\n}", 1)[0]
    assert "if (!coat) return new THREE.MeshStandardMaterial(settings);" in surface
    assert surface.count("MeshPhysicalMaterial") == 1


def test_the_extruded_slab_is_the_same_substance_as_a_measured_one():
    """A board with no model is a different SHAPE, not a different material.

    The slab is drawn for a board nobody publishes a mesh of, and its caption
    says exactly that. What it must not also say is that the substance changed:
    it was a matte dielectric at roughness 0.85 while the two composed boards
    were 0.35 under a clear coat, so switching boards switched physics.

    The three numbers are duplicated from `FINISHES` in
    `tools/import_3d_model.py` because the slab has no mesh to read them out
    of -- and this is what stops the two copies drifting.
    """
    source = RENDERER.read_text(encoding="utf-8")
    mask = source.split("const SOLDER_MASK = {", 1)[1].split("};", 1)[0]
    numbers = {key: float(value) for key, value in
               re.findall(r"(\w+):\s*([\d.]+)", mask)}
    assert numbers == {"roughness": 0.35, "coat": 0.85, "coatRoughness": 0.08}

    from tools.import_3d_model import FINISHES

    for colour in ("#313d63", "#49a954"):
        finish = FINISHES[colour]
        assert (finish.roughness, finish.coat, finish.coat_roughness) == (
            numbers["roughness"], numbers["coat"], numbers["coatRoughness"]
        ), f"{colour} and the slab no longer agree about what a PCB is"

    # And the slab really is built with them, rather than them being unused.
    slab = source.split("const slab = new THREE.Mesh(", 1)[1].split(");", 1)[0]
    assert "MeshPhysicalMaterial" in slab
    assert "SOLDER_MASK.coat" in slab and "SOLDER_MASK.roughness" in slab


# --- a picked board draws (OH-94) -------------------------------------------
#
# Two lines of JavaScript, and without either of them the picker still draws
# nothing. Python cannot press a select box, so these are source-level -- the
# same reason and the same technique as every other assertion in this file,
# and comments are stripped first because three tripwires here have now fired
# on their own prose.


def test_choosing_a_board_asks_the_server_about_that_board():
    """`reload()` used to fetch `/api/board/pins` bare, which answers for the
    board the SESSION is running -- so a picked board could not be asked
    about at all, whatever called it."""
    source = PANEL.read_text(encoding="utf-8")
    code = stripped(source)
    assert "board-pick" in code, (
        "the panel does not read the picker, so it cannot name the board"
    )
    assert "/api/board/pins?board=" in code
    assert "encodeURIComponent" in code, (
        "board names carry spaces -- 'Arduino Uno' -- so an unencoded query "
        "asks for a board that does not exist"
    )


def test_the_board_picker_redraws_when_it_changes():
    """**The listener that did not exist.** `#board-pick` had none: it was a
    value `loadBoardImage` read when Load was pressed, which is why the 3D
    view first appeared after a firmware load rather than after a choice."""
    source = (STATIC / "emulator.js").read_text(encoding="utf-8")
    code = stripped(source)
    wiring = code.split('$("board-pick").addEventListener("change"', 1)
    assert len(wiring) == 2, "the picker has no change listener"
    # The listener's whole body, to its closing `});` -- it stopped being a
    # one-liner when OH-140 added the buildability reflection ahead of the
    # redraw, and this test's claim is about the redraw existing, not about
    # it being the first statement.
    listener = wiring[1].split("});", 1)[0]
    assert "boardPins?.reload()" in listener, (
        "the picker changes and nothing redraws the board"
    )


def test_the_board_the_picker_opens_on_is_drawn_without_being_touched():
    """**Setting `.value` fires no `change` event.**

    So the default selection has to draw itself, or the picker opens on a
    board nobody drew and a reader has to pick a different one and come back
    to see the one that was already chosen. The draw hangs off `finally` so it
    happens whether or not the server had a board to tell us about.
    """
    source = (STATIC / "emulator.js").read_text(encoding="utf-8")
    code = stripped(source)
    picker = code.split("function fillBoardPicker", 1)[1].split("\n}", 1)[0]
    assert ".finally(" in picker and "boardPins?.reload()" in picker, (
        "filling the picker does not draw, so the default board never appears"
    )


def test_a_board_with_no_core_can_still_be_chosen_and_looked_at():
    """**Fourteen of the twenty-six have pads and no built core.**

    They were `disabled` in the picker, on the reasoning that offering them
    would accept "a click that cannot be honoured". Picking a board now draws
    it, so the click CAN be honoured -- only `Load` cannot, and that refuses
    by name on its own. A XIAO-MG24 has twenty-four pads and was unreachable.

    The label still carries the reason, which is the half of that reasoning
    that has not expired.
    """
    source = (STATIC / "emulator.js").read_text(encoding="utf-8")
    code = stripped(source)
    picker = code.split("function fillBoardPicker", 1)[1].split("\n}", 1)[0]
    assert "option.disabled" not in picker, (
        "a board with no core cannot be selected, so it cannot be drawn"
    )
    assert "boardStatus(board)" in picker, (
        "the option no longer says why a board is not runnable"
    )


# --- the pad marker is the vendor's pin, not a cylinder (OH-95) --------------
#
# Reported as "the cylindrical shapes for wire connections should not exist and
# should use the real pins to connect the wires". On an Arduino Uno the fake
# and the real were in the same place: a disc drawn here hovering over a gold
# header pin the model had already put there.


def test_no_pad_marker_is_ever_drawn():
    """**The disc still exists and is never rendered, which is the whole
    trick.** It does three jobs -- state colour, raycast target, and the
    anchor a wire's end follows -- so deleting it would take the bench with
    it. `placeModel` replaces it with real geometry where there is any, and
    what is left is a collider nobody can see.

    Raycasting does not test visibility: `Raycaster.intersectObjects` calls
    `raycast` on whatever it is handed. So a wire can still be started from a
    pad on the sixteen boards that are drawn as a bare footprint.
    """
    source = RENDERER.read_text(encoding="utf-8")
    made = source.split("const post = new THREE.Mesh(", 1)[1].split("addPad(", 1)[0]
    assert "post.visible = false;" in made, (
        "the drawn cylinder is back"
    )


def test_only_metal_is_carved_out_of_the_model():
    """**A pin conducts and the shroud around it does not.**

    Without this the black plastic within reach of a pad would be carved too
    and turn blue when the pin went high -- a header with a glowing body,
    which looks like a rendering fault rather than a pin state. The models say
    which is which: `FINISHES` sets `metalness` to 0 or 1 because a surface
    either conducts or it does not.
    """
    source = RENDERER.read_text(encoding="utf-8")
    carve = source.split("function carvePins(", 1)[1].split("\n}\n", 1)[0]
    code = stripped(carve)
    assert "metalness > 0.5" in code, (
        "carving is not restricted to conductors, so a shroud can be a pin"
    )


def test_a_pad_cannot_claim_its_neighbours_pin():
    """**Half the pitch is 1.27 mm and this must stay under it.**

    Past that a pad takes the pin next to it, which lights the wrong one and
    looks entirely convincing -- the failure mode this whole file is written
    against. Five of the Uno's pads sit 1.2 to 3.8 mm from any pin (OH-96);
    reaching them would mean crossing that line.
    """
    source = RENDERER.read_text(encoding="utf-8")
    reach = float(re.search(r"^const PIN_REACH_MM = ([\d.]+);", source,
                            re.MULTILINE).group(1))
    assert reach < 2.54 / 2, (
        f"a reach of {reach} mm crosses the midpoint between two pins"
    )


def test_the_carved_triangles_are_moved_and_not_copied():
    """Left in the model as well, a pin would be drawn twice -- once in the
    vendor's colour and once in the state's -- and two coincident surfaces
    z-fight, which reads as a flickering board."""
    source = RENDERER.read_text(encoding="utf-8")
    carve = source.split("function carvePins(", 1)[1].split("\n}\n", 1)[0]
    assert "geometry.setIndex(keep)" in carve, (
        "the source geometry keeps the triangles that were carved out of it"
    )


def test_a_real_pin_keeps_its_metal_and_emits_its_state():
    """**The state is emitted, not painted, and that was measured.**

    Blending the state into the metal was tried first: brass `#dbbc7e` with
    `high` mixed 72% of the way in comes out `#7c8a61`, and `input` comes out
    `#90897b`. Two muddy browns three pixels wide -- the pin had stopped
    looking like brass and the state still could not be read. (Measured on
    the brass's key before OH-214, `#b58136`, as `#66744b` and `#7e726c`;
    `PIN_GLOW`'s comment in `board3d.js` says how it was recomputed.)

    So `color` stays the colour the vendor published and the state goes into
    `emissive`, which is also the right metaphor: the pin is made of the same
    metal it always was, and what changed is that it is doing something.
    """
    source = RENDERER.read_text(encoding="utf-8")
    paint = source.split("function repaint(", 1)[1].split("\n}", 1)[0]
    assert "color.copy(post.userData.metal)" in paint, (
        "a real pin no longer keeps the metal the vendor gave it"
    )
    assert "emissive" in paint, "the state is not emitted"
    assert re.search(r"^const PIN_GLOW = 0\.\d+;", source, re.MULTILINE), (
        "the glow is a hidden literal rather than a named constant"
    )


def test_a_pad_nobody_can_answer_for_does_not_glow():
    """`unknown` is most pads on most boards -- twenty-two of the Uno's
    thirty-two are answerable and every pad of a board with no `pin_states` is
    not. A board whose every pin is lit says nothing, so an unanswerable pad
    stays the plain metal it is and the table beside the canvas is where
    "cannot be answered for" is written in words."""
    source = RENDERER.read_text(encoding="utf-8")
    paint = source.split("function repaint(", 1)[1].split("\n}", 1)[0]
    assert '!== "unknown"' in paint, (
        "an unanswerable pad glows as though something were known about it"
    )


def test_only_the_part_of_a_pin_above_the_board_is_carved():
    """**A header pin is longer than the part you can clip a lead to.**

    Its tail passes through the PCB and out of the underside, and carving that
    would take the solder side of a board nobody is looking at -- and light it
    when the pin went high, so an Uno seen from below would glow through its
    own laminate.

    It is also what keeps a XIAO's castellations OUT: they are plated
    half-holes inside the board's own thickness rather than posts standing on
    it, so they are not carved and their pads stay invisible colliders. That
    is a limitation rather than a decision, and it is written down in OH-95
    rather than left for someone to discover.
    """
    source = RENDERER.read_text(encoding="utf-8")
    carve = source.split("function carvePins(", 1)[1].split("\n}\n", 1)[0]
    code = stripped(carve)
    assert "centre.y > pcbThickness" in code, (
        "a pin's tail below the board is carved with its head"
    )


# --- the light that comes from below (OH-111) ----------------------------------


def _lights() -> list[dict[str, float]]:
    """Every `{x, y, z, share}` the renderer builds a directional light from."""
    source = RENDERER.read_text(encoding="utf-8")
    block = source.split("const LIGHTS = [", 1)[1].split("];", 1)[0]
    bounce = source.split("const BOUNCE = ", 1)[1].split(";", 1)[0]
    out = []
    for entry in re.findall(r"\{[^}]*\}", block + bounce):
        got = dict(re.findall(r"(\w+): (-?[0-9.]+)", entry))
        out.append({key: float(value) for key, value in got.items()})
    return out


def test_something_lights_the_underside_of_the_board():
    """**Every light in this scene used to have a positive y.**

    Which was fine while the underside was a blank slab, and stopped being fine
    when OH-110 put the vendor's own printing on it: 1,514 silkscreen strokes
    on the ESP32-C3 including the words "Seeed Studio", the battery pads with
    their + and -, and 44 castellated half-holes. Shot from beneath, the board
    measured a MEDIAN LUMINANCE OF ZERO against 82.6 from above.
    """
    below = [light for light in _lights() if light["y"] < 0]
    assert below, (
        "no light in this scene comes from below, so the side of the board the "
        "pin names are printed on renders black"
    )
    assert len(below) == 1, "one bounce, not a second key light"


def test_the_three_that_cast_still_share_the_exposure_between_them():
    """The bounce is ADDED to `LIGHT_TOTAL`, not taken out of it.

    A light from below contributes nothing to a surface facing up, so sharing
    it out of the three above would darken a picture it cannot brighten. The
    measurement that says so: across a sweep of the bounce from 0.00 to 0.50
    the topside mean moved 115.6 to 116.4, which is 0.7%.
    """
    above = [light for light in _lights() if light["y"] > 0]
    assert len(above) == 3, "the upper hemisphere is sampled three times"
    assert sum(light["share"] for light in above) == pytest.approx(1.0)


def test_the_bounce_is_dimmer_than_the_key_and_does_not_cast():
    """It is the return off a bench, not a fourth lamp.

    Dimmer, because the underside has to stay the shaded side: at 0.25 its
    median is 41% of the topside's, and at 0.50 the two sides are within a
    fifth of each other and the board stops having a lit side at all.

    Not casting, because the three above cast in order to estimate how much
    sky a crevice can see and this is not sky -- and because there is nothing
    under the board to occlude it. Of the 1 to 21 parts each vendor places on
    the back of these boards, `CORRESPONDENCE` draws none: they are test
    points, logos and one solder jumper, none of which has a body.
    """
    source = RENDERER.read_text(encoding="utf-8")
    bounce = source.split("const BOUNCE = ", 1)[1].split(";", 1)[0]
    assert "casts: false" in bounce, bounce
    key = max(light["share"] for light in _lights() if light["y"] > 0)
    under = next(light for light in _lights() if light["y"] < 0)
    assert 0.0 < under["share"] < key, (
        f"the bounce is {under['share']} against a key of {key}"
    )
    # Mostly straight down: what sideways component it has is there so that a
    # component's side face gets a hint of it, and it is small enough that the
    # topside statistics did not move across the whole sweep.
    assert abs(under["y"]) > 2 * max(abs(under["x"]), abs(under["z"]))


# --- a name can mean several pads (OH-117) -----------------------------------


def test_a_board_really_does_give_three_pads_the_same_name():
    """**The situation the change below exists for, in the data.**

    An Arduino Uno has three GND pads and `webui/boards/Arduino Uno.json`
    lists all three, at three places, because that is what the board has. A
    `Map` keyed by name kept whichever came last and the other two were never
    made -- no raycast target, so no wire could start there, and nothing on
    the page to say why. Measured with `describe()`: 32 pads in, 30 out.

    Asserted against the board file rather than against the renderer, so that
    the renderer's fix cannot be "correct" against a board file somebody has
    quietly de-duplicated.
    """
    import collections
    import json

    boards = STATIC.parents[0] / "boards"
    layout = json.loads((boards / "Arduino Uno.json")
                        .read_text(encoding="utf-8"))
    names = collections.Counter(pad["label"] for pad in layout["pads"])
    repeated = {name: n for name, n in names.items() if n > 1}
    assert repeated == {"GND": 3}, (
        f"the Uno's repeated pad names are now {repeated}. Three GND is what "
        f"the board has; if that changed, this test and the Map-of-lists it "
        f"justifies both need re-reading"
    )
    places = {(pad["x"], pad["y"]) for pad in layout["pads"]
              if pad["label"] == "GND"}
    assert len(places) == 3, (
        "the three GND entries are not three distinct places, so they are a "
        "duplication in the file rather than three real pads"
    )


def test_every_pad_is_kept_and_not_only_the_last_of_its_name():
    """`view.pads` groups by name and holds a LIST, so all three GND pads
    exist.

    **The two helpers are asserted by their BODIES and not by their names**,
    and the first version of this test was not. It checked that the string
    `[...view.pads.values()].flat()` appeared in the file -- and `padMeshes`
    has a docstring saying "rather than `[...view.pads.values()].flat()` in
    six places", so a mutation that gutted the body left the comment behind
    and the test passed. A source assertion that a comment can satisfy is not
    an assertion about the code. Both mutations survived until this was split.
    """
    source = RENDERER.read_text(encoding="utf-8")
    add = source.split("function addPad(pin, post) {", 1)[1].split("\n}", 1)[0]
    assert "here.push(post)" in add, (
        "addPad no longer appends, so a repeated name keeps only its last pad "
        "-- which is the whole of OH-117 returning"
    )
    meshes = source.split("function padMeshes() {", 1)[1].split("\n}", 1)[0]
    assert ".flat()" in meshes, (
        "padMeshes no longer flattens, so a name with two pads yields one of "
        "them and the other is invisible to every caller"
    )
    # The writers go through the helper; nothing sets a bare mesh as the value.
    assert "view.pads.set(pad.pin, post)" not in source
    assert "view.pads.set(pad.pin, pin)" not in source
    # And nothing takes `.values()` as meshes any more.
    for shape in ("[...view.pads.values()], false)",
                  "for (const post of view.pads.values())"):
        assert shape not in source, f"{shape!r} treats the value as a mesh"


def test_a_wire_follows_the_pad_it_was_pulled_from_not_a_pad_with_that_name():
    """**The half of OH-117 that is not about counting.**

    A wire stored only `pin`, and `anchorOf` looked the name back up. That was
    exact while one name meant one pad; with three called GND, a wire dragged
    from the one beside AREF would have had its end snap across the board to
    the one on the power header -- silently, and only once a second pad of
    that name existed to snap to.
    """
    source = RENDERER.read_text(encoding="utf-8")
    anchor = source.split("function anchorOf(wire) {", 1)[1].split("\n}", 1)[0]
    assert "wire.post" in anchor, "the wire no longer remembers its own pad"
    assert "view.pads.get" not in anchor, (
        "anchorOf is looking a pad up by name again, which picks the wrong "
        "one of three"
    )
    assert "post: pad," in source, "beginWire no longer records the pad"


def test_describe_reports_the_number_of_pads_and_not_only_of_names():
    """The two differ wherever a name means several pads -- 32 against 30 on
    an Uno -- and the number of PADS is the one that says whether any were
    lost. Without it the loss is invisible from outside the module, which is
    how it went unnoticed."""
    source = RENDERER.read_text(encoding="utf-8")
    assert "padCount: padMeshes().length," in source


def test_image_y_maps_to_scene_z_with_the_same_sign_as_the_models_pins():
    """**The mirror OH-115 spent three measurements finding, pinned by its
    sign** -- because it is one character away from returning and it fails
    silently: 28 of the Uno's 32 pads still "found" a pin, each the OPPOSITE
    row's, and only the five whose opposite x had no pin showed at all. That
    is what OH-96 measured as "five pads with no pin", two tickets upstream
    of the cause.

    A composed model's pins land at z = -board_y, and the page's image y is
    ALREADY the negation of board y -- so a pad's z takes image y with the
    same sign, and the model group's centring must use the same convention or
    the two halves mirror against each other again. Both lines are asserted.

    Verified in the browser when it landed: all 32 of the Uno's pads found a
    real pin, each its own within 0.1 mm against a 1.27 mm half-pitch.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "post.position.set(pad.x * SCALE - width / 2, top, "\
           "pad.y * SCALE - depth / 2);" in source, (
        "the pad line negates image y again, which mirrors every pad onto "
        "the row opposite its pin"
    )
    # Since OH-216 the model is set by the pads' own scene positions, so the
    # centring takes image y through the same expression as the pad line.
    assert "z: pad.y * SCALE - depth / 2" in source, (
        "the model group's centring flipped back, so the model and the pads "
        "mirror against each other"
    )
    assert "depth / 2 - pad.y * SCALE" not in source
    assert "depth / 2 - centreY * SCALE" not in source


def test_a_carved_pin_carries_its_place_on_the_mesh_and_not_only_in_the_vertices():
    """**Every wire on a board with vendor pins anchored at the board's
    centre-underside** (OH-128). `carvePins` baked the pad's offset into the
    replacement mesh's GEOMETRY and never set its position, so
    `getWorldPosition` -- which `anchorOf` calls every frame, and `beginWire`
    and the drag plane call once each -- answered the model group's origin
    for every carved pad. OH-95's close note claimed the anchor kept working
    through the carve; the raycast did, the anchor did not.

    Verified in the browser when it landed: the Uno's pads report 30 distinct
    world positions spread across 25 x 27 scene units, where before the fix
    every carved pad reported the one origin. Asserted here at the source
    with comments stripped (the OH-117 lesson), written when no headless
    harness could run carvePins -- the gap on OH-128's record. One does now:
    the OH-215 tests at the bottom of this file run it under node, and
    removing either the position line or the x re-bake fails
    `test_carvepins_takes_only_metal_standing_on_the_models_own_header_pads`
    (the position line fails the landing test beside it too; both seen
    2026-10-09). The per-entry buckets are held only here.
    """
    source = RENDERER.read_text(encoding="utf-8")
    body = source.split("function carvePins(", 1)[1].split("\nfunction ", 1)[0]
    code = stripped(body)
    assert "pin.position.copy(pad.at)" in code, (
        "the carved mesh's position is no longer set, so every consumer of "
        "getWorldPosition gets the model group's origin again"
    )
    assert "positions[at] -= pad.at.x" in code, (
        "the vertices are no longer re-baked relative to the pad, so setting "
        "the position DOUBLES the offset and every pin renders off-board"
    )
    # And the buckets live on the wanted ENTRIES, not in a map keyed by pin
    # name: three pads called GND shared one bucket and built three
    # coincident copies of the same mesh.
    assert "claimed" not in code, (
        "a per-name bucket is back, so a repeated name builds duplicate "
        "z-fighting meshes and the slots point at different copies"
    )


def test_a_maps_stated_scale_beats_the_fit_from_mismatched_fields():
    """**A generated map states its scale, and the statement wins** (OH-121).

    `scaleFromPads` divides this page's pixel span by the model's `pad_span`
    -- two descriptions of two DIFFERENT pad fields on an SMD XIAO, 28
    castellation sub-pads against one pad per castellation -- and the
    quotient drew every composed SMD model 9% small, pushing their outermost
    pads past `PIN_REACH_MM`. Verified in the browser when the field landed:
    every SMD board's scale came out at exactly the map's own 8 px/mm and
    every pad on every board found its pin -- 30/30, 22/22, 34/34 -- while
    the traced Uno kept its fitted 5.638.

    Comment lines stripped, the OH-117 lesson.
    """
    source = RENDERER.read_text(encoding="utf-8")
    body = source.split("function placeModel(", 1)[1].split("\nfunction ", 1)[0]
    code = stripped(body)
    at_statement = code.index("layout.px_per_mm")
    at_fit = code.index("scaleFromPads(")
    assert at_statement < at_fit, (
        "the fit runs before the map's own statement, so a generated map is "
        "back to being re-derived from mismatched pad fields"
    )


def test_a_wire_holding_a_released_pad_is_repointed_at_the_carved_pin():
    """**A wire made while the model was in flight kept a disposed cylinder**
    (OH-129). `loadModel` is deliberately not awaited; `beginWire` stores the
    pad MESH in `wire.post` -- the mesh and not the bucket slot, because
    three of an Uno's pads are called GND -- and `carvePins` then released
    that mesh and swapped the bucket. The wire kept the object: a
    null-parented `getWorldPosition` answers board-local coordinates, the
    head froze off the pin, and no later `setLevels` or `refreshTheme` pass
    could repair it because `view.pads` no longer held the mesh. Distinct
    from OH-128, which fixed where a LIVE carved pin reports itself.

    Asserted at the source with comments stripped (the OH-117 lesson).
    `carvePins` does run headless now, under node, in the OH-215 tests at
    the bottom of this file -- but that probe makes no wire, so the repoint
    is held only here.
    """
    source = RENDERER.read_text(encoding="utf-8")
    body = source.split("function carvePins(", 1)[1].split("\nfunction ", 1)[0]
    code = stripped(body)
    assert "for (const wire of view.wires)" in code, (
        "carvePins no longer walks the wires, so a wire made during the "
        "model fetch keeps the released pad mesh forever"
    )
    assert "wire.post === pad.post" in code, (
        "the repoint lost its guard, so every wire is repointed at whatever "
        "pin was carved last instead of only the ones holding this pad"
    )
    assert "wire.post = pin" in code, (
        "the wire is never handed the carved pin, so its anchor still reads "
        "a disposed, null-parented mesh"
    )


def test_every_part_row_carries_the_hatch_the_destroyed_latch_depends_on():
    """**`removePart` had no caller** (OH-131). `destroyed` latches BY DESIGN
    -- past an absolute maximum is permanent -- and the design's own words
    are that the only thing undoing it is `removePart`, what a person does
    with a burnt LED. The page never called it: the panel wired addPart,
    disconnect and clearBench, and a burnt part sat on the bench for the
    life of the tab.

    Comments stripped, the OH-117 lesson.
    """
    panel = PANEL.read_text(encoding="utf-8")
    body = panel.split("function renderBench(", 1)[1].split("\nfunction ", 1)[0]
    code = stripped(body)
    assert "scene.removePart(index)" in code, (
        "no part row calls removePart, so a destroyed part can never leave "
        "the bench"
    )
    after = code.split("scene.removePart(index)", 1)[1]
    assert "renderBench()" in after.split("head.append(drop)", 1)[0], (
        "the bench is not redrawn after a removal, so the dead row lingers "
        "until the next wires-changed event repaints it"
    )
    assert "aria-label" in code.split("bench-remove", 1)[1].split(
        "addEventListener", 1)[0], (
        "the remove control has no accessible name"
    )
    # And the renderer really exports what the panel calls.
    assert "export function removePart(index)" in RENDERER.read_text(
        encoding="utf-8")


def test_removing_a_part_takes_its_wires_and_its_verdict_with_it():
    """What the hatch has to do to be one: the part's own wires go with it
    (a wire into a terminal that no longer exists would anchor on a released
    mesh -- OH-129's disease by another door), its meshes are released, and
    the circuit is re-solved so the survivors' verdicts stop carrying the
    ghost's current. Comments stripped."""
    renderer = RENDERER.read_text(encoding="utf-8")
    body = renderer.split("function removePart(", 1)[1].split(
        "\nfunction ", 1)[0]
    code = stripped(body)
    assert "discardWire(wire)" in code, "the part's wires outlive it"
    assert "releasePart(part)" in code, (
        "the part's own meshes are not released -- and ONLY its own: OH-133 "
        "narrowed the blanket release that disposed geometry shared with the "
        "cache template and every sibling clone"
    )
    assert "applyCircuit()" in code, (
        "the circuit is not re-solved, so every survivor's verdict still "
        "counts the removed part"
    )


def test_a_wires_colour_is_keyed_off_its_id_and_not_the_live_count():
    """**After any disconnect, the next wire repeated a colour on the bench**
    (OH-133): the palette indexed `view.wires.length`, which shrinks when a
    wire is removed, while ids never do -- `nextWireId` exists because "an
    index changes when an earlier wire is removed", and the colour needed
    the identical treatment. Comments stripped, the OH-117 lesson."""
    source = RENDERER.read_text(encoding="utf-8")
    body = source.split("function beginWire(", 1)[1].split("\n}", 1)[0]
    code = stripped(body)
    assert "const id = nextWireId++" in code, (
        "the id is not taken first, so the colour has nothing stable to key on"
    )
    assert "WIRE_COLOURS[(id - 1) % WIRE_COLOURS.length]" in code, (
        "the colour is not keyed off the wire's own id"
    )
    assert "view.wires.length % WIRE_COLOURS.length" not in code, (
        "the colour indexes the live count again, which repeats after any "
        "disconnect"
    )


def test_the_drag_in_progress_does_not_survive_a_cleared_bench():
    """A pointer held across a board change kept writing to a wire whose
    mesh `clearBench` had just released, and the pointerup discarded it a
    second time (OH-133). The drag is one of the bench's wires, so it dies
    with them."""
    source = RENDERER.read_text(encoding="utf-8")
    body = source.split("export function clearBench(", 1)[1].split("\n}", 1)[0]
    code = stripped(body)
    assert "view.dragging = null" in code, (
        "the drag survives clearBench and writes to a released wire"
    )


def test_removing_a_part_releases_only_what_is_the_parts_own():
    """**`release` over a part's whole tree disposed buffers the part never
    owned** (OH-133): `loadPart` hands out `clone(true)` of the cached
    template, and a three.js clone shares geometry and materials with the
    template and every sibling -- so every removal forced a fresh GPU upload
    for every survivor. Per-part is exactly the lens material `dressPart`
    clones and the target spheres `makeTarget` builds fresh; `releasePart`
    is the one place that knows the split, and both removal paths go
    through it. Comments stripped."""
    source = RENDERER.read_text(encoding="utf-8")
    for opener in ("export function removePart(", "export function clearBench("):
        body = source.split(opener, 1)[1].split("\n}", 1)[0]
        code = stripped(body)
        assert "releasePart(part)" in code, (
            f"{opener} does not go through releasePart"
        )
        assert "release(object)" not in code, (
            f"{opener} blanket-releases shared geometry again"
        )
    helper = source.split("function releasePart(", 1)[1].split("\n}", 1)[0]
    helper = stripped(helper)
    assert "part.userData.lens?.material?.dispose()" in helper, (
        "the cloned lens material leaks with every removed part"
    )
    assert "object.userData.terminal !== undefined" in helper, (
        "the target guard is gone, so releasePart is the blanket release "
        "under a new name"
    )


def test_the_cold_page_does_not_ask_about_no_board():
    """`reload()` with an empty picker fetched `/api/board/pins` bare and
    collected the deliberate 400 -- one console error on every fresh page,
    carried through two handoffs as "expected" (OH-142). Nothing picked
    means nothing to ask: the early return is the 400 handler\'s outcome
    without the doomed round-trip. Comments stripped."""
    panel = PANEL.read_text(encoding="utf-8")
    body = panel.split("async function reload(", 1)[1].split("\n}", 1)[0]
    code = stripped(body)
    assert "if (!picked)" in code, "the cold page still asks about no board"
    assert code.index("if (!picked)") < code.index("await fetch"), (
        "the guard sits after the fetch it exists to prevent"
    )
    assert '"/api/board/pins")' not in code, (
        "the bare no-board fetch is still reachable"
    )


def test_the_drag_starts_on_a_part_terminal_too():
    """**The UI half of OH-116, without which the netlist half is dead
    code.** The drag is a THREE.js raycast with no headless harness -- the
    OH-215 tests below run `carvePins` under node, but nothing there drives
    a pointer -- so the wiring is pinned at the source with comments
    stripped: the press falls through to
    `terminalUnder`, the drop refuses the wire\'s own starting anchor, the
    bench wire carries its `from` end, and `removePart` takes the wires
    that BEGIN on the part with it."""
    source = RENDERER.read_text(encoding="utf-8")
    code = stripped(source)
    assert "padUnder() ?? terminalUnder()" in code, (
        "a drag cannot start on a part terminal"
    )
    assert "terminal !== view.dragging.post" in code, (
        "a wire can land on its own starting anchor"
    )
    assert "wire.pin === undefined ? {" in code, (
        "the bench wire never carries its from end, so analyse cannot join "
        "part to part"
    )
    assert "wire.post?.userData?.part === part" in code, (
        "removing a part leaves the wires that began on it dangling"
    )
    panel = PANEL.read_text(encoding="utf-8")
    code = stripped(panel)
    assert "wire.fromLabel" in code, (
        "the panel cannot say which part a part-to-part wire grips"
    )


def test_the_board_s_own_led_is_lit_from_the_same_levels_the_table_reads():
    """**OH-169: the LED never lit, however hard the sketch blinked.**

    The levels were live the whole time -- a compiled blink toggles pin `13`
    forty times in forty samples -- and `setLevels` recoloured every pad and
    re-solved the bench on every poll. What nothing did was light the lamp
    printed on the board, because a user LED is a pin and not a pad: it has a
    state and no coordinate, and the only place it appeared was the table.

    Three joins are asserted here and each is a call site rather than a word,
    which is the OH-164 lesson: a test that finds a string can be satisfied by
    a comment mentioning it.

    **Placed after the model, because it joins the model to the solids.**
    `placeLeds` needs `view.model` set (it parents the glow to it) and
    `view.solids` filled (it looks the component up there), so its call has to
    follow both assignments and not merely appear in the same function.

    **Lit from `setLevels`**, which is the one place a pin's state is decided
    -- the same argument the file already makes for solving the bench circuit
    there. A second source would let the lamp and the row disagree.

    **`high` and nothing else.** `low` is a driven pin with the lamp off,
    `input` is a pin nobody drives, and `unknown` is a board nobody has
    loaded. A board sitting there glowing because its state is unknown would
    be OH-164's mistake in a different medium.
    """
    code = stripped(RENDERER.read_text(encoding="utf-8"))

    # Placed after both of the things it joins.
    assert code.index("view.model = group;") < code.index("placeLeds("), (
        "the glow is parented to a model that has not been set yet"
    )
    assert code.index("view.solids = extras.solids") < code.index("placeLeds("), (
        "the component is looked up in solids that have not been filled yet"
    )

    # Lit from the level poll, inside `setLevels` rather than anywhere else.
    levels = code.split("export function setLevels(levels) {", 1)[1]
    levels = levels.split("\n}", 1)[0]
    assert "lightLeds(levels)" in levels, (
        "the board's LEDs are not lit from the levels the table reads"
    )

    # Only `high`, and it is the emissive intensity that moves.
    lighting = code.split("function lightLeds(levels) {", 1)[1].split("\n}", 1)[0]
    assert '=== "high"' in lighting, (
        "the lamp does not test for high, so some other state can light it"
    )
    assert "emissiveIntensity" in lighting

    # A component the model does not draw is skipped rather than invented.
    placing = code.split("function placeLeds(parts) {", 1)[1].split("\n}\n", 1)[0]
    assert "if (!solid) continue;" in placing, (
        "a board naming a component its mesh has not got would throw or, "
        "worse, draw a lamp at a guessed place"
    )
    # And the body writes down no colour of its own, which the renderer's own
    # rule requires: both come from the palette the stylesheet fills.
    assert "view.palette.states.high" in placing
    assert not COLOUR_LITERAL.search(placing), COLOUR_LITERAL.findall(placing)


def test_a_board_drawn_as_a_footprint_keeps_no_lamp_from_the_last_one():
    """An extruded footprint has no components, so it has no LED to light. The
    list is emptied on that path and when the board is torn down, because a
    stale entry is a freed geometry that `lightLeds` still writes to -- and,
    before that, the previous board's lamp glowing on this one."""
    code = stripped(RENDERER.read_text(encoding="utf-8"))
    footprint = code.split("view.mmScale = PX_PER_MM * SCALE;", 1)[1]
    footprint = footprint.split("refreshColliders();", 1)[0]
    assert "view.leds = []" in footprint, (
        "the footprint path keeps whatever lamp the last model left"
    )
    teardown = code.split("view.model = null;", 1)[1].split("}", 1)[0]
    assert "view.leds = []" in teardown, (
        "the torn-down board leaves its lamps in the list"
    )


# --- OH-215: where the page puts a model, found by running the page ----------
#
# Every test above reads board3d.js. These RUN it, under node: the page's own
# `showBoard`, `loadModel`, `placeModel` and `carvePins`, unextracted and
# unported. `PLACEMENT_HOOKS` resolves the page's import map and appends one
# line naming two of the module's private bindings; the file on disk is not
# touched.

#: Node module hooks: the page's import map, and the probe's handle on `view`
#: and `loadModel`, appended to board3d.js as it loads.
PLACEMENT_HOOKS = r"""
import { pathToFileURL } from "node:url";
import path from "node:path";

let vendor = null;
export async function initialize(data) { vendor = path.join(data.static, "vendor"); }

const MAP = { "three": "three.module.js",
              "three/addons/controls/OrbitControls.js": "OrbitControls.js" };

export async function resolve(specifier, context, next) {
  if (specifier in MAP) {
    return { url: pathToFileURL(path.join(vendor, MAP[specifier])).href,
             shortCircuit: true };
  }
  return next(specifier, context);
}

export async function load(url, context, next) {
  const result = await next(url, context);
  if (!url.endsWith("/board3d.js")) return result;
  const text = typeof result.source === "string"
    ? result.source : new TextDecoder().decode(result.source);
  return { ...result, format: "module", shortCircuit: true,
           source: text + "\nexport const __probe = { view, loadModel };\n" };
}
"""

#: Draws each case's board with `showBoard`, loads its model with `loadModel`
#: (through a `fetch` that reads the disk), and prints per board the model's
#: turn and scale, the top of its PCB, and where every pad sits in the
#: MODEL's frame -- the millimetres the composer writes -- by its index in the
#: layout, its height `y` there, with the centroid `[x, z, y]` of every
#: triangle `carvePins` gave it and whether the page holds it to be on the
#: underside.
PLACEMENT_PROBE = r"""
import { register } from "node:module";
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import path from "node:path";

const [STATIC, HOOKS, CASES] = process.argv.slice(2);
register(pathToFileURL(HOOKS).href, { data: { static: STATIC } });
const THREE = await import(
  pathToFileURL(path.join(STATIC, "vendor", "three.module.js")).href);
const page = await import(pathToFileURL(path.join(STATIC, "board3d.js")).href);
const { view, loadModel } = page.__probe;

globalThis.fetch = async (file) => {
  const bytes = readFileSync(file);
  return { ok: true, arrayBuffer: async () => bytes.buffer.slice(
    bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
};
// What `mount` would have made: enough of a scene for `showBoard` to draw in.
view.renderer = {};
view.scene = new THREE.Scene();
view.camera = new THREE.PerspectiveCamera();
view.controls = { target: new THREE.Vector3(), update() {} };
const grey = new THREE.Color(0.5, 0.5, 0.5);
view.palette = { surface: grey, line: grey,
                 states: { unknown: grey, high: grey, low: grey, input: grey } };

const out = [];
const at = new THREE.Vector3();
for (const { layout, file } of JSON.parse(readFileSync(CASES, "utf-8"))) {
  page.showBoard(layout, null);
  await loadModel(layout, { file });
  const model = view.model;
  view.board.updateWorldMatrix(true, true);
  const pads = [];
  // Each mesh by the layout pad it was made for: `showBoard` adds one per
  // placed pad, in this order, to its pin's bucket, and `carvePins` swaps
  // its pin into the same slot.
  const taken = new Map();
  layout.pads.forEach((entry, index) => {
    if (entry.x === null || entry.y === null) return;
    const nth = taken.get(entry.pin) ?? 0;
    taken.set(entry.pin, nth + 1);
    const mesh = view.pads.get(entry.pin)?.[nth];
    if (mesh?.userData.label !== entry.label) {
      throw new Error(`${layout.board}: layout pad ${index} is ${entry.label}, ` +
                      `its mesh says ${mesh?.userData.label}`);
    }
    mesh.getWorldPosition(at);
    model.worldToLocal(at);
    const pad = { index, label: entry.label, x: at.x, z: at.z, y: at.y, tris: [],
                  underside: Boolean(mesh.userData.underside) };
    if (mesh.userData.carved) {
      // A carved pin's triangles are relative to its own place (OH-128).
      const position = mesh.geometry.getAttribute("position");
      for (let i = 0; i < position.count; i += 3) {
        let x = 0, y = 0, z = 0;
        for (let k = 0; k < 3; k++) {
          x += position.getX(i + k);
          y += position.getY(i + k);
          z += position.getZ(i + k);
        }
        pad.tris.push([mesh.position.x + x / 3, mesh.position.z + z / 3,
                       mesh.position.y + y / 3]);
      }
    }
    pads.push(pad);
  });
  const meshes = [...view.pads.values()].flat().length;
  if (meshes !== pads.length) {
    throw new Error(`${layout.board}: ${meshes} pad meshes for ${pads.length} ` +
                    `placed layout pads`);
  }
  out.push({ board: layout.board, turn: model.rotation.y, scale: model.scale.x,
             pcb: view.slab.max[1], placement: view.placement, pads });
}
console.log(JSON.stringify(out));
"""


def placed_by_the_page(directory: pathlib.Path, cases: list[dict]) -> list[dict]:
    """The page's own placement of each `{"layout": pad_view, "file": glb}`,
    run under node; skips without one, as the comparator test above does."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; the placement is the page's own JS and "
                    "needs one to run")
    hooks = directory / "hooks.mjs"
    probe = directory / "probe.mjs"
    listing = directory / "cases.json"
    hooks.write_text(PLACEMENT_HOOKS, encoding="utf-8")
    probe.write_text(PLACEMENT_PROBE, encoding="utf-8")
    listing.write_text(json.dumps(cases), encoding="utf-8")
    done = subprocess.run([node, str(probe), str(STATIC), str(hooks), str(listing)],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def one_triangle_glb(path: pathlib.Path, pcb: dict[str, float],
                     header_pads: list | None = None) -> None:
    """The narrowest file `readGlb` accepts -- one triangle, one material --
    carrying the `pcb` extra a turn is read from, and `header_pads` where
    given (OH-216)."""
    binary = (struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 0, 1)
              + struct.pack("<9f", 0, 1, 0, 0, 1, 0, 0, 1, 0)
              + struct.pack("<3I", 0, 1, 2))
    document = json.dumps({
        "asset": {"version": "2.0", "extras": {
            "units": "mm", "pcb": pcb,
            **({"header_pads": header_pads} if header_pads is not None else {})}},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": offset, "byteLength": length}
                        for offset, length in ((0, 36), (36, 36), (72, 12))],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5125, "count": 3, "type": "SCALAR"},
        ],
        "materials": [{"name": "probe", "pbrMetallicRoughness": {
            "baseColorFactor": [0.5, 0.5, 0.5, 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 0.5}}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                    "indices": 2, "material": 0}]}],
    }).encode("utf-8")
    document += b" " * (-len(document) % 4)
    body = (struct.pack("<II", len(document), 0x4E4F534A) + document
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def test_a_model_drawn_upright_is_not_turned_onto_a_pad_map_drawn_upright(tmp_path):
    """**OH-215: the turn read one frame and assumed the other.** `placeModel`
    turned a model a quarter whenever the PAD MAP was taller than wide, under
    "the model is always landscape" -- true of every fetched mesh and every
    composed XIAO, false of a board whose vendor drew it upright. The composer
    keeps the vendor's frame, the board file is read out of the same file, so
    both were upright and the page turned one of them a quarter off the other.

    Four cases, all four ways the two frames can meet. Three are real kinds
    of board here: upright on upright (the manifest boards OH-215 names),
    lying on upright (a XIAO SMD footprint under a landscape model -- the
    turn that must survive), and lying on lying. The fourth, an upright
    model on a lying map, is no board yet and must turn too. A model of one
    triangle carrying only the `pcb` extra, so this runs on a fresh checkout
    with no model built.

    Seen red (2026-10-09): with the turn read from `layout.height >
    layout.width` alone, the first case came out turned 90 degrees, and the
    fourth (added in review) 0.
    """
    upright = tmp_path / "upright.glb"
    lying = tmp_path / "lying.glb"
    one_triangle_glb(upright, {"long": 10.0, "short": 20.0, "thickness": 1.6})
    one_triangle_glb(lying, {"long": 20.0, "short": 10.0, "thickness": 1.6})

    def pad_map(board: str, width: int, height: int) -> dict:
        return {"board": board, "width": width, "height": height,
                "px_per_mm": 8.0, "supply": None, "led_parts": None,
                "pads": [{"label": label, "pin": label, "chip_pin": None,
                          "x": x, "y": y, "group": "header", "state": "unknown"}
                         for label, x, y in (("A", 30.0, 30.0), ("B", 70.0, 70.0))]}

    placed = placed_by_the_page(tmp_path, [
        {"layout": pad_map("upright on upright", 100, 200), "file": str(upright)},
        {"layout": pad_map("lying on upright", 100, 200), "file": str(lying)},
        {"layout": pad_map("lying on lying", 200, 100), "file": str(lying)},
        {"layout": pad_map("upright on lying", 200, 100), "file": str(upright)},
    ])
    turns = {case["board"]: round(math.degrees(case["turn"])) for case in placed}
    assert turns == {"upright on upright": 0, "lying on upright": 90,
                     "lying on lying": 0, "upright on lying": 90}, turns


def own_header_pads(compose, spec) -> list[tuple[float, float, float, float,
                                                tuple[str, str]]]:
    """The composer's header pads for `spec` as `(x, z, width, height, name)`
    in the frame it writes the model in: millimetres from the centre of those
    pads, x along the vendor's x and z against its y (`slab`). A DIP
    variant's own pads are the rows `dip_header_elements` hangs there, as
    composed.

    `name` is what a board file generated from the same vendor file
    (`tools/import_board.py`) calls that pad, as `(group or label, number)`:
    a KiCad board groups its pads by footprint reference, so `(reference,
    number)`; an EAGLE board labels each pad with its net, or its number on
    no net, so `(net, number)`."""
    pcb = compose.read_layout(spec.layout)
    kicad = spec.layout.suffix == ".kicad_pcb"
    header = [(element.name, pad) for element in map(pcb.element, spec.headers)
              for pad in element.pads]
    xs = [pad.x_mm for _, pad in header]
    ys = [pad.y_mm for _, pad in header]
    centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    if spec.dip_headers:
        header = [(element.name, pad) for element in
                  compose.dip_header_elements([pad for _, pad in header])
                  for pad in element.pads]
    return [(pad.x_mm - centre[0], centre[1] - pad.y_mm, pad.width_mm,
             pad.height_mm,
             (element if kicad else pad.net or pad.number, pad.number))
            for element, pad in header]


@pytest.fixture(scope="module")
def composed_boards_as_placed(tmp_path_factory):
    """Every board drawn from a composed model built here, as the page places
    it, beside the composer's own header pads and whether its board file
    names the very file the model was composed from -- and, apart, every
    board the model index names that could not be placed here, with why.

    Each placed pad carries `name`: the vendor pad its board file says it is,
    in `own_header_pads`' terms. It is None where the board file names none:
    on every board whose file is not the model's own, and on the Uno, whose
    pad map was traced from Arduino's artwork and labelled from its
    silkscreen, so its labels are not nets and it carries no pad numbers.
    And `group`, the board file's, which says which pads are on the
    underside (OH-216). Each case carries `header_pads`, the pads the model
    itself states it is set by (OH-216), or None on a model composed before
    it stated any.

    Models and vendor files are gitignored, so this skips where nobody has run
    `tools/compose_board_3d.py`, as the Uno's model test in test_pin_view does;
    where some boards are built and some not, each test using this ends in a
    skip naming the ones it left out, after holding the rest.
    """
    index = STATIC / "models" / "index.json"
    if not index.is_file():
        pytest.skip(f"no {index}; run tools/compose_board_3d.py")
    compose = pytest.importorskip("tools.compose_board_3d")
    from tools.import_3d_model import read_extras
    from webui import api

    composed = {spec.board: spec for spec in compose.COMPOSITIONS}
    cases = []
    known = {}
    left_out = []
    for board, entry in json.loads(index.read_text(encoding="utf-8"))["boards"].items():
        model = STATIC / (entry.get("file") or "/").lstrip("/")
        if not model.is_file():
            left_out.append(f"{board}: no {model.name} (so whether it is "
                            f"composed is not known)")
            continue
        extras = read_extras(model)
        if not extras.get("composed"):
            continue
        if extras["board"] not in composed:
            raise LookupError(
                f"{model} was composed for {extras['board']!r}, which "
                f"tools/compose_board_3d.py no longer composes -- it composes "
                f"{sorted(composed)}. A stale model: recompose, or delete it.")
        spec = composed[extras["board"]]
        if not spec.layout.is_file():
            left_out.append(f"{board}: its vendor file {spec.layout} is not "
                            f"fetched")
            continue
        stated = json.loads((STATIC.parent / "boards" / f"{board}.json")
                            .read_text(encoding="utf-8"))
        same_file = (pathlib.PurePosixPath(stated["source"].get("file", "")).name
                     == extras["source"])
        kicad = spec.layout.suffix == ".kicad_pcb"
        names = {(pad["label"], pad["x"], pad["y"]):
                 (pad["group"] if kicad else pad["label"], pad["pad"])
                 for pad in stated["pads"] if same_file and "pad" in pad}
        layout = api.pad_view(board, None, None)
        known[board] = (layout, names, own_header_pads(compose, spec), same_file,
                        extras.get("header_pads"))
        cases.append({"layout": layout, "file": str(model)})
    if not cases:
        pytest.skip(f"no composed model is built here with its vendor file "
                    f"fetched; run tools/compose_board_3d.py. Left out: "
                    f"{left_out}")
    placed = placed_by_the_page(tmp_path_factory.mktemp("placed"), cases)
    boards = []
    for case in placed:
        layout, names, own, same_file, stated = known[case["board"]]
        case["header_pads"] = stated
        for pad in case["pads"]:
            entry = layout["pads"][pad["index"]]
            pad["name"] = names.get((entry["label"], entry["x"], entry["y"]))
            pad["group"] = entry["group"]
        unnamed = [pad["label"] for pad in case["pads"] if pad["name"] is None]
        if names and unnamed:
            raise LookupError(
                f"{case['board']}: its board file names the vendor pad of "
                f"{len(names)} pads, but none of the page's pads {unnamed}")
        boards.append((case, own, same_file))
    return boards, left_out


def on_copper(x: float, z: float, pads, reach) -> bool:
    """Whether (x, z) is within `reach(width, height)` of one of `pads`."""
    return any(math.hypot(x - px, z - pz) <= reach(width, height)
               for px, pz, width, height, _ in pads)


def inscribed(width: float, height: float) -> float:
    """The circle a pad's narrower side spans: inside it is on that pad's
    copper at any rotation, and no pad here is within it of its neighbour."""
    return min(width, height) / 2


def test_every_composed_board_lands_its_pads_on_the_models_own_header_pads(
        composed_boards_as_placed):
    """**OH-215, held over every board a composed model is drawn for.**
    Placed as the page places it, each board-file pad is on the copper of the
    model's own header pad that its board file names.

    Two claims, because two kinds of board are here. Where the board file was
    read out of the very file the model was composed from -- the Uno and
    every manifest board -- EVERY pad must land, and on ITS OWN pad: the one
    its board file names (`own_header_pads`: footprint reference and pad
    number on a KiCad board, net and pad number on an EAGLE one). The Uno's
    file names none, so there each pad must land on one of its four headers'
    pads. A XIAO's board file is Seeed's footprint, which also carries
    underside pads no header pad answers for; there the page's turn must
    land at least as many pads as any other quarter turn would, which is the
    claim a wrong quarter turn breaks. A half turn does not break it, and
    nothing here holds a XIAO against one.

    "On one of the model's header pads", the claim until review, could not
    tell a right turn from a half turn either. With the page turning every
    model a further half (in memory, through `PLACEMENT_HOOKS`), it still
    passed the Adafruit QT Py ESP32-C3 and KB2040, the SparkFun Pro Micro
    ESP32-C3 and Qwiic Pocket ESP32-C6 and both Olimex boards, whose header
    pads a half turn lays onto one another; matched pad by pad, each of them
    lands none of its pads on its own (2026-10-09).

    And the one exactly square board, the SparkFun Qwiic Pocket ESP32-C6, is
    expected unturned where it is built: 25.4 x 25.4 mm on a 219 x 219 px
    map, it is right only because both of `placeModel`'s comparisons tie.

    Tolerance: inside the circle the pad's narrower side spans (`inscribed`).
    The PCBCUPID Glyph Mini sat 0.73 mm off on every pad -- inside it --
    because the composer centres on its castellations as well as its pins;
    since OH-216 the page centres on the pads that land, and the test after
    the next holds that to `CENTRED_MM`.

    Seen red (2026-10-09): with the turn read from the pad map alone, the six
    boards OH-215 names were the six failures, each landing 0 or 4 of its
    pads where one further quarter turn landed every one. In review, as
    matched pad by pad: on that rule the same six, every pad of each off its
    own; with a further half turn, every board read from its model's own
    file, the XIAOs passing; and with `mapUpright` read `>=`, the Qwiic
    Pocket alone, by both claims.
    """
    composed, left_out = composed_boards_as_placed
    quarters = ((1, 0), (0, 1), (-1, 0), (0, -1))
    wrong = []
    for case, own, same_file in composed:
        pads = case["pads"]
        # On the pad its board file names; on any header pad where it names
        # none.
        astray = [(pad["label"], pad["name"]) for pad in pads
                  if not on_copper(pad["x"], pad["z"],
                                   [mine for mine in own
                                    if pad["name"] in (None, mine[4])],
                                   inscribed)]
        # A further turn of the model about its own origin moves each pad's
        # place in the model's frame by the opposite turn; all four are tried.
        landed = [sum(on_copper(pad["x"] * c + pad["z"] * s,
                                pad["z"] * c - pad["x"] * s, own, inscribed)
                      for pad in pads) for c, s in quarters]
        if (same_file and astray) or (not same_file and landed[0] < max(landed)):
            wrong.append(f"{case['board']}: turned "
                         f"{math.degrees(case['turn']):.0f} deg, {len(astray)} "
                         f"of {len(pads)} pads off their own header pad "
                         f"{astray[:4]}; on any header pad, turned a further "
                         f"0/90/180/270 deg: {landed}")
    # The one exactly square board, expected unturned wherever it is built.
    square = "SparkFun Qwiic Pocket ESP32-C6"
    wrong += [f"{square}, 25.4 x 25.4 mm on a 219 x 219 px map, is turned "
              f"{math.degrees(case['turn']):.0f} deg and expected unturned"
              for case, _, _ in composed
              if case["board"] == square and round(math.degrees(case["turn"]))]
    assert not wrong, "\n".join(wrong)
    if left_out:
        pytest.skip(f"SKIPPED in part: the {len(composed)} boards placed here "
                    f"held; left out: {left_out}")


def test_carvepins_takes_only_metal_standing_on_the_models_own_header_pads(
        composed_boards_as_placed):
    """**What a wrong turn does next** (OH-215): `carvePins` turns every metal
    triangle within `PIN_REACH_MM` of a pad into that pad's pin, so a pad
    turned off its header carves a component's legs instead -- or nothing,
    and keeps an invisible collider where its pin should be.

    On every board whose pads ALL land (`test_every_composed_board_lands...`
    says which: those read from the model's own file, and the XIAO DIPs),
    every pad must carve a pin, and every triangle carved must stand on the
    copper of one of the model's own header pads -- within half its diagonal,
    so on it at any rotation. A XIAO SMD's underside pads carve whatever
    topside metal stands over them; that is a separate finding, recorded on
    OH-215 and not asserted here.

    This holds no turn of its own: with the page turning every model a
    further half, it still passed the same six boards the old landing claim
    did (2026-10-09). The landing test above is what holds the turn.

    Seen red (2026-10-09), twice. With the turn read from the pad map alone,
    the six boards OH-215 names were the six failures: 3 to 19 pads each
    carved no pin, and 50 to 2202 triangles each were taken off every header
    pad. And with the turn restored but `PIN_REACH_MM` at 3.0 -- past half
    the 2.54 mm pitch, so a pad reaches its neighbour's metal -- every board
    this covers failed, the Uno with 8 such triangles and each XIAO DIP with
    thousands; the turn tests stayed green, as they should.
    """
    composed, left_out = composed_boards_as_placed
    wrong = []
    for case, own, same_file in composed:
        pads = case["pads"]
        if not same_file and not all(
                on_copper(pad["x"], pad["z"], own, inscribed) for pad in pads):
            continue
        bare = [pad["label"] for pad in pads if not pad["tris"]]
        stray = [(pad["label"], x, z) for pad in pads for x, z, _ in pad["tris"]
                 if not on_copper(x, z, own, lambda w, h: math.hypot(w, h) / 2)]
        if bare or stray:
            wrong.append(f"{case['board']}: {len(bare)} of {len(pads)} pads "
                         f"carved no pin {bare[:6]}; {len(stray)} triangles "
                         f"carved off every header pad, e.g. {stray[:3]}")
    assert not wrong, "\n".join(wrong)
    if left_out:
        pytest.skip(f"SKIPPED in part: the {len(composed)} boards placed here "
                    f"held; left out: {left_out}")


# --- OH-216: a pad carves metal on its own side of the board, and only there --


def metal_triangles_glb(path: pathlib.Path, pcb: dict[str, float],
                        centres: list[tuple[float, float, float]]) -> None:
    """A model of small flat METAL triangles, one centred on each `(x, y, z)`
    in model millimetres, carrying the `pcb` extra: the narrowest model whose
    metal `carvePins` can take."""
    corners = [(x + dx, y, z + dz) for x, y, z in centres
               for dx, dz in ((-0.1, -0.1), (0.2, -0.1), (-0.1, 0.2))]
    count = len(corners)
    binary = (b"".join(struct.pack("<3f", *corner) for corner in corners)
              + struct.pack(f"<{3 * count}f", *(0, 1, 0) * count)
              + struct.pack(f"<{count}I", *range(count)))
    document = json.dumps({
        "asset": {"version": "2.0", "extras": {"units": "mm", "pcb": pcb}},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": offset, "byteLength": length}
                        for offset, length in ((0, 12 * count), (12 * count, 12 * count),
                                               (24 * count, 4 * count))],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": count, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5125, "count": count, "type": "SCALAR"},
        ],
        "materials": [{"name": "brass", "pbrMetallicRoughness": {
            "baseColorFactor": [0.8, 0.6, 0.3, 1.0],
            "metallicFactor": 1.0, "roughnessFactor": 0.3}}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                    "indices": 2, "material": 0}]}],
    }).encode("utf-8")
    document += b" " * (-len(document) % 4)
    body = (struct.pack("<II", len(document), 0x4E4F534A) + document
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def test_an_underside_pad_takes_the_metal_under_the_board_and_never_over_it(
        tmp_path):
    """**OH-216: a pad on the underside carved the metal on TOP of the board
    over it.** `carvePins` took every metal triangle above the PCB within
    `PIN_REACH_MM` of a pad, whichever side the pad was on, so a XIAO's
    underside test point turned the chip lead or trace standing over it into
    its pin, and that metal became the wire's anchor.

    One pad on each side of a 1.6 mm board at the same place, over a metal
    triangle on top and another underneath: each pad takes the one on its own
    side, and the underside pad's marker stands under the board. Synthetic,
    so it runs with no model built; needs node.

    Seen red (2026-10-09), on board3d.js as it was before OH-216: the
    underside pad carved nothing and was not marked as on the underside. In
    review (2026-10-09), with `placeModel` standing every marker on the top:
    the underside pad's marker stood over the board, which nothing asserted
    until then. Each is `(underside, carved heights, marker under the
    board, marker over it)`.
    """
    model = tmp_path / "both.glb"
    metal_triangles_glb(model, {"long": 10.0, "short": 10.0, "thickness": 1.6},
                        [(0.0, 2.0, 0.0), (0.0, -0.5, 0.0)])
    layout = {"board": "one pad each side", "width": 100, "height": 100,
              "px_per_mm": 8.0, "supply": None, "led_parts": None,
              "pads": [{"label": label, "pin": label, "chip_pin": None,
                        "x": 50.0, "y": 50.0, "group": group, "state": "unknown"}
                       for label, group in (("T", "header-top"), ("U", "underside"))]}
    (case,) = placed_by_the_page(tmp_path, [{"layout": layout, "file": str(model)}])
    sides = {pad["label"]: (pad["underside"], [round(y, 2) for _, _, y in pad["tris"]],
                            pad["y"] < 0, pad["y"] > 1.6)
             for pad in case["pads"]}
    assert sides == {"T": (False, [2.0], False, True), "U": (True, [-0.5], True, False)}, sides


def test_every_pad_carves_only_metal_on_its_own_side_of_the_board(
        composed_boards_as_placed):
    """**OH-216, over every board a composed model is drawn for.** A pad the
    board file puts on the underside (`group` "underside", which
    `tools/import_board.py` states from the vendor's footprint and, at its
    edge, from the module's own board file) carves only metal below the PCB;
    every other pad only metal above it, and only on the copper of one of the
    model's own header pads -- within half its diagonal, as the carve test
    above measures.

    Before this, the XIAO SMD boards and the XIAO RP2350 DIP were left out of
    that test because their underside pads land on no header pad, and each
    underside pad took the topside metal standing over it: OH-215's review
    counted 1557 to 5450 such triangles a board.

    Seen red (2026-10-09), twice: with `carvePins` ignoring a pad's side, and
    with the XIAO board files' underside pads tagged `header-top` again -- each
    time the six boards OH-216 names failed, every underside pad's triangles
    on top of the board.
    """
    composed, left_out = composed_boards_as_placed
    wrong = []
    for case, own, _ in composed:
        stray = []
        for pad in case["pads"]:
            for x, z, y in pad["tris"]:
                if pad["group"] == "underside":
                    if y >= 0:
                        stray.append((pad["label"], "over the board", round(y, 2)))
                elif y <= case["pcb"]:
                    stray.append((pad["label"], "not above the board", round(y, 2)))
                elif not on_copper(x, z, own, lambda w, h: math.hypot(w, h) / 2):
                    stray.append((pad["label"], "off every header pad",
                                  round(x, 2), round(z, 2)))
        if stray:
            wrong.append(f"{case['board']}: {len(stray)} triangles carved off "
                         f"their pad's own side or header pad, e.g. {stray[:3]}")
    assert not wrong, "\n".join(wrong)
    if left_out:
        pytest.skip(f"SKIPPED in part: the {len(composed)} boards placed here "
                    f"held; left out: {left_out}")


# --- OH-216: the page sets a model by the pads both sides name ---------------


def named_pad_map(board: str, width: int, height: int,
                  pads: list[tuple[str, float, float]]) -> dict:
    """A pad map at 8 px/mm whose pads are `(label, x_mm, z_mm)` from the
    middle of the image, z down the page as the image's y is."""
    return {"board": board, "width": width, "height": height,
            "px_per_mm": 8.0, "supply": None, "led_parts": None,
            "pads": [{"label": label, "pin": label, "chip_pin": None,
                      "x": width / 2 + x * 8, "y": height / 2 + z * 8,
                      "group": "header", "state": "unknown"}
                     for label, x, z in pads]}


def test_a_model_is_turned_by_the_names_of_its_pads_where_its_outline_cannot_say(
        tmp_path):
    """**OH-216: the turn comes from the pads both sides name.** OH-215's
    rule compared the two outlines' orientations, which cannot say which way
    a square lies or see a half turn. Two models that state their header
    pads, each needing what the outlines cannot give:

    a 10 x 10 mm square whose pads land on their namesakes only turned a
    quarter, on a square map -- the outlines tie, so OH-215's rule left it
    unturned; and a 20 x 10 mm board lying on a lying map whose pads land on
    their namesakes only turned half way round. And the square again with
    no header pads, which is every fetched mesh: set by its outline, and
    saying so. Synthetic, so it runs with no model built; needs node.

    Seen red (2026-10-09), on board3d.js as OH-215 left it: the square and
    the half-turned board both came out unturned.
    """
    pads = [[-2.0, 0.0, 1.0, 1.0, "A"], [2.0, 0.0, 1.0, 1.0, "B"],
            [0.0, -1.0, 1.0, 1.0, "C"]]
    square = tmp_path / "square.glb"
    one_triangle_glb(square, {"long": 10.0, "short": 10.0, "thickness": 1.6}, pads)
    bare = tmp_path / "bare.glb"
    one_triangle_glb(bare, {"long": 10.0, "short": 10.0, "thickness": 1.6})
    lying = tmp_path / "lying.glb"
    one_triangle_glb(lying, {"long": 20.0, "short": 10.0, "thickness": 1.6},
                     [[-4.0, 0.0, 1.0, 1.0, "A"], [4.0, 0.0, 1.0, 1.0, "B"],
                      [0.0, 2.0, 1.0, 1.0, "C"]])
    # Turned by `rotation.y`, a model point (x, z) lands at (z, -x) a quarter
    # round and at (-x, -z) half way.
    placed = placed_by_the_page(tmp_path, [
        {"layout": named_pad_map("square", 100, 100,
                                 [("A", 0, 2), ("B", 0, -2), ("C", -1, 0)]),
         "file": str(square)},
        {"layout": named_pad_map("half", 200, 100,
                                 [("A", 4, 0), ("B", -4, 0), ("C", 0, -2)]),
         "file": str(lying)},
        {"layout": named_pad_map("bare", 100, 100,
                                 [("A", 0, 2), ("B", 0, -2), ("C", -1, 0)]),
         "file": str(bare)},
    ])
    got = {case["board"]: (round(math.degrees(case["turn"])),
                           (case.get("placement") or {}).get("by"),
                           (case.get("placement") or {}).get("named"))
           for case in placed}
    assert got == {"square": (90, "header pads", 3), "half": (180, "header pads", 3),
                   "bare": (0, "PCB outline", None)}, got


def test_two_rows_a_half_turn_lays_on_each_other_are_turned_by_their_names_not_the_outline(
        tmp_path):
    """**Where geometry cannot tell a half turn, the names do, against the
    outline.** Two rows of three pads, which turned half way round lie
    exactly on one another: unturned or turned 180 degrees, every pad lands,
    and at the same distance. The model lies on a lying map, so the outlines
    prefer it unturned (OH-215), and its pads land on their namesakes only
    turned half way round. Turned 180 degrees, all six named.

    The name rule had no test of its own until review: each synthetic case
    above is decided by where its pads are, and a XIAO's two rows by the
    outline's preference as well as by its names.

    Seen red (2026-10-09), with the name term taken out of the ranking: the
    turns tied, the outline's preferred quarter was taken, and every pad
    landed on another pad's name, which the page refused.
    """
    rows = tmp_path / "rows.glb"
    one_triangle_glb(rows, {"long": 20.0, "short": 10.0, "thickness": 1.6},
                     [[-3.0, -2.0, 1.0, 1.0, "A"], [0.0, -2.0, 1.0, 1.0, "B"],
                      [3.0, -2.0, 1.0, 1.0, "C"], [-3.0, 2.0, 1.0, 1.0, "D"],
                      [0.0, 2.0, 1.0, 1.0, "E"], [3.0, 2.0, 1.0, 1.0, "F"]])
    # Half way round, a model point (x, z) lands at (-x, -z).
    (case,) = placed_by_the_page(tmp_path, [{
        "layout": named_pad_map("rows", 200, 100,
                                [("A", 3, 2), ("B", 0, 2), ("C", -3, 2),
                                 ("D", 3, -2), ("E", 0, -2), ("F", -3, -2)]),
        "file": str(rows)}])
    got = (round(math.degrees(case["turn"])), case["placement"]["by"],
           case["placement"]["named"])
    assert got == (180, "header pads", 6), (got, case["placement"])


def test_a_model_no_turn_of_which_lands_the_pads_is_refused_by_name(tmp_path):
    """Where no quarter turn lands every pad of the board file on one of the
    model's header pads, the page refuses, naming the board, what each turn
    lands and the pads, rather than drawing the model somewhere a pad is
    not -- and says that, not that the names disagree.

    Seen red (2026-10-09), on board3d.js as OH-215 left it: nothing refused.
    In review (2026-10-09), with that refusal taken out: nothing refused.
    """
    far = tmp_path / "far.glb"
    one_triangle_glb(far, {"long": 20.0, "short": 10.0, "thickness": 1.6},
                     [[-4.0, 0.0, 1.0, 1.0, "A"], [4.0, 0.0, 1.0, 1.0, "B"]])
    with pytest.raises(AssertionError) as caught:
        placed_by_the_page(tmp_path, [{
            "layout": named_pad_map("nowhere", 200, 100,
                                    [("A", -4, 0), ("B", 1, 0), ("C", 0, 3)]),
            "file": str(far)}])
    message = str(caught.value)
    assert ("nowhere: no quarter turn lands every pad of its board file on one "
            "of the model's header pads -- turned 0/90/180/270 degrees, 0/0/0/0 "
            "of 3 land, and at the best these do not: A, B, C") in message, message
    assert "names disagree" not in message, message


def test_pads_that_all_land_on_pads_of_other_names_are_refused_as_names_that_disagree(
        tmp_path):
    """**A turn landing every pad is taken over one that names more but
    lands fewer, and is refused where the names say it is wrong.** A row of
    four header pads A, B, C, D and one beside it, X; the board file's pads
    stand on all five unturned, but named D, C, B, A and W: four of them on
    a header pad of another name where the model has one of their own, and
    none on its namesake. The page refuses, saying so -- not that no turn
    lands every pad, which is false.

    Seen red (2026-10-09), on board3d.js with names ranked before landing,
    as it was before review: a quarter turn landing one pad, on its
    namesake, outranked the turn landing all five, and the refusal said
    "no quarter turn lands every pad ... 5/1/0/1 of 5 land".
    """
    row = tmp_path / "row.glb"
    one_triangle_glb(row, {"long": 20.0, "short": 10.0, "thickness": 1.6},
                     [[-3.0, 0.0, 1.0, 1.0, "A"], [-1.0, 0.0, 1.0, 1.0, "B"],
                      [1.0, 0.0, 1.0, 1.0, "C"], [3.0, 0.0, 1.0, 1.0, "D"],
                      [0.0, 1.5, 1.0, 1.0, "X"]])
    with pytest.raises(AssertionError) as caught:
        placed_by_the_page(tmp_path, [{
            "layout": named_pad_map("reversed", 200, 100,
                                    [("D", -3, 0), ("C", -1, 0), ("B", 1, 0), ("A", 3, 0),
                                     ("W", 0, 1.5)]),
            "file": str(row)}])
    message = str(caught.value)
    assert ("reversed: turned 0 degrees, every pad of its board file lands on one "
            "of the model's header pads, but their names disagree: 4 land on a "
            "header pad of another name where the model has one of their own, and "
            "0 on their namesakes") in message, message
    assert "no quarter turn lands every pad" not in message, message


#: How near a pad must land to its namesake where the board file and the
#: model were read out of one vendor file: both are that file's numbers, so
#: anything but rounding is a misplacement. OH-215 measured 0.01 mm worst
#: and the Glyph Mini's 0.73.
SAME_FILE_MM = 0.05

#: How far the middle of where a board's pads land may sit from the middle
#: of the pads themselves: a model centred on the pads that land puts it at
#: nothing but rounding, 0.004 mm at worst as measured on every board
#: (2026-10-09). A XIAO SMD footprint's castellation lands stand outward of
#: the module's pads on BOTH rows, which is why each pad may be a quarter
#: millimetre off its own and the middle none.
CENTRED_MM = 0.05


def test_every_composed_board_lands_each_pad_on_a_header_pad_its_model_states(
        composed_boards_as_placed):
    """**OH-216, over every board a composed model is drawn for**: placed as
    the page places it, every pad of the board file on the board's top lands
    on a header pad the MODEL states (`header_pads`), and on one of its own
    name wherever the model has a pad of that name. Where the board file
    names each pad out of the very file the model was composed from, it
    lands within `SAME_FILE_MM` of it. The Uno's map is traced from
    artwork and labelled from its silkscreen, so its pads land inside a
    header pad, any one, as OH-215 held them.

    This catches a XIAO turned half way round, which OH-215's test could
    not: its board file is Seeed's footprint and its model Seeed's module,
    two files, and the names they share -- GND and VBUS, and more on the C3
    -- would land on another name. **What turns a XIAO right on the page is
    not its names alone**: its two rows land every pad turned either way, at
    the same distances, and with the names taken out of the page's ranking
    the outline's preferred quarter (OH-215) breaks that tie the same way
    and this still passes (review, 2026-10-09). The name rule is held by
    `test_two_rows_a_half_turn_lays_on_each_other_are_turned_by_their_names_not_the_outline`,
    where the outline says otherwise. And it holds the centre, to
    `CENTRED_MM`: the PCBCUPID Glyph Mini sat 0.73 mm off every pad, centred
    on 46 pads where its board file has 23; and a XIAO SMD 0.43 to 0.52 mm
    off, centred on its underside pads too.

    Seen red (2026-10-09): on board3d.js as OH-215 left it, every board
    (none said what set it), the Glyph Mini with every pad 0.73 mm off its
    own, and the C3, C5, C6, RP2350 and nRF54L15 SMDs off centre by 0.43 to
    0.52 mm; and with the page turning every model a further half (in
    memory), every board, the XIAO DIPs among them.
    """
    composed, left_out = composed_boards_as_placed
    wrong = []
    for case, _, same_file in composed:
        stated = case["header_pads"]
        if stated is None:
            wrong.append(f"{case['board']}: its model states no header pads -- "
                         f"composed before OH-216; recompose")
            continue
        names = {name for *_, name in stated}
        astray = []
        offsets = []
        for pad in case["pads"]:
            if pad["group"] == "underside":
                continue
            # A traced map's labels are its artwork's silkscreen, not nets:
            # the Uno's "1" is digital pin 1 and its model's "1" a pad on no
            # net. Anywhere else a shared name is one signal.
            traced = same_file and pad["name"] is None
            own = [row for row in stated
                   if traced or pad["label"] not in names or row[4] == pad["label"]]
            gap, row = min((math.hypot(pad["x"] - x, pad["z"] - z), (x, z, w, h, name))
                           for x, z, w, h, name in own)
            reach = SAME_FILE_MM if pad["name"] is not None else inscribed(row[2], row[3])
            if gap > reach:
                astray.append((pad["label"], row[4], round(gap, 3)))
            offsets.append((pad["x"] - row[0], pad["z"] - row[1]))
        middle = (sum(x for x, _ in offsets) / len(offsets),
                  sum(z for _, z in offsets) / len(offsets))
        if math.hypot(*middle) > CENTRED_MM:
            astray.append(("the middle of all of them", "",
                           tuple(round(v, 3) for v in middle)))
        if astray or (case.get("placement") or {}).get("by") != "header pads":
            wrong.append(f"{case['board']}: set by {case.get('placement')}, "
                         f"{len(astray)} pads off their own header pad "
                         f"(pad, nearest it may land on, mm): {astray[:4]}")
    assert not wrong, "\n".join(wrong)
    if left_out:
        pytest.skip(f"SKIPPED in part: the {len(composed)} boards placed here "
                    f"held; left out: {left_out}")


# --- OH-216: a fetched mesh's castellations carve, or its vendor made none ----


def metal_centres(path: pathlib.Path) -> list[tuple[float, float, float]]:
    """The centre `(x, y, z)` of every triangle of a .glb drawn in a metal
    -- `metallicFactor` over a half, the line `carvePins` draws -- in the
    model's own millimetres."""
    raw = path.read_bytes()
    length, _ = struct.unpack_from("<II", raw, 12)
    document = json.loads(raw[20:20 + length])
    at = 20 + length
    size, _ = struct.unpack_from("<II", raw, at)
    binary = raw[at + 8:at + 8 + size]

    def read(index: int) -> list[tuple]:
        accessor = document["accessors"][index]
        view = document["bufferViews"][accessor["bufferView"]]
        width = {"SCALAR": 1, "VEC3": 3}[accessor["type"]]
        kind = {5126: "f", 5125: "I", 5123: "H"}[accessor["componentType"]]
        values = struct.unpack_from(
            f"<{accessor['count'] * width}{kind}", binary,
            view.get("byteOffset", 0) + accessor.get("byteOffset", 0))
        return [values[i:i + width] for i in range(0, len(values), width)]

    centres = []
    for mesh in document["meshes"]:
        for primitive in mesh["primitives"]:
            material = document["materials"][primitive["material"]]
            if material["pbrMetallicRoughness"].get("metallicFactor", 1.0) <= 0.5:
                continue
            corners = read(primitive["attributes"]["POSITION"])
            indices = [index for (index,) in read(primitive["indices"])]
            for k in range(0, len(indices), 3):
                three = [corners[i] for i in indices[k:k + 3]]
                centres.append(tuple(sum(c[axis] for c in three) / 3
                                     for axis in range(3)))
    return centres


#: `PIN_REACH_MM` in board3d.js, and `PAD_RECESS_MM` beside it.
PAGE_REACH_MM = 1.1
PAGE_RECESS_MM = 0.05


def test_every_fetched_meshs_castellations_carve_where_its_vendor_made_them_metal(
        tmp_path):
    """**OH-216: the fetched XIAO meshes carved nothing**, and for two
    different reasons, one per kind of mistake. On the SAMD21 the stated PCB
    thickness was its solid's box, 1.61 mm, which a small feature on that
    solid reaches -- the board's own top face is at 1.21, and its castellation
    copper stops at 1.22. On the ESP32-S3 and nRF52840 the thickness is right
    and the filter was wrong: their pads' copper lies in the mask's openings,
    0.01 mm under the board's face, and "above the board" took none of it.

    Held over every board drawn from a fetched mesh built here, as the page
    places it: each pad on the board's top carves metal standing on the top,
    each underside pad metal on the underside (never the components standing
    over it), and a pad on the top that carves nothing has no metal of its
    vendor's within reach of it at ANY height -- which is why the RP2040's,
    the MG24's and the nRF54LM20A's castellations keep their invisible
    colliders: their STEPs make the half-holes unstyled or part of the
    board, and nothing here says they are metal.

    Seen red (2026-10-09): on board3d.js before PAD_RECESS_MM, every S3 and
    nRF52840 board, castellations and all; and with SAMD21.glb as imported
    before `board_top`, both SAMD21 boards. A board the index names whose
    mesh is not built here is left out and named in a skip, after the rest
    are held: in review (2026-10-09), with ESP32-S3.glb moved away, this
    passed quietly; now it skips in part, naming the three S3 boards.
    """
    index = STATIC / "models" / "index.json"
    if not index.is_file():
        pytest.skip(f"no {index}; run tools/import_3d_model.py --all")
    from tools.import_3d_model import read_extras
    from webui import api

    cases, metal, left_out = [], {}, []
    for board, entry in json.loads(index.read_text(encoding="utf-8"))["boards"].items():
        model = STATIC / (entry.get("file") or "/").lstrip("/")
        if entry.get("composed"):
            continue
        if not model.is_file():
            left_out.append(f"{board}: no {model.name}")
            continue
        if model not in metal:
            metal[model] = metal_centres(model)
        cases.append({"layout": api.pad_view(board, None, None), "file": str(model)})
    if not cases:
        pytest.skip(f"no fetched mesh is built here; run tools/import_3d_model.py "
                    f"--all. Left out: {left_out}")
    wrong = []
    for case, given in zip(placed_by_the_page(tmp_path, cases), cases, strict=True):
        layout = given["layout"]
        top = read_extras(pathlib.Path(given["file"]))["pcb"]["thickness"]
        for pad in case["pads"]:
            under = layout["pads"][pad["index"]]["group"] == "underside"
            off_side = [round(y, 3) for _, _, y in pad["tris"]
                        if (y >= PAGE_RECESS_MM if under else y <= top - PAGE_RECESS_MM)]
            near = [y for x, y, z in metal[pathlib.Path(given["file"])]
                    if math.hypot(x - pad["x"], z - pad["z"]) < PAGE_REACH_MM]
            if off_side:
                wrong.append(f"{case['board']} {pad['label']}: carved metal off its "
                             f"own side of a {top} mm board, at {off_side[:3]}")
            elif not pad["tris"] and near and not under:
                wrong.append(f"{case['board']} {pad['label']}: carved nothing, "
                             f"with its vendor's metal within reach at heights "
                             f"{round(min(near), 3)}..{round(max(near), 3)} mm on "
                             f"a {top} mm board")
    assert not wrong, f"{len(wrong)} pads:\n" + "\n".join(wrong[:20])
    if left_out:
        pytest.skip(f"SKIPPED in part: the {len(cases)} boards placed here held; "
                    f"left out, with no mesh built here (run python "
                    f"tools/import_3d_model.py --all): {left_out}")
