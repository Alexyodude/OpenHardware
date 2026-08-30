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

import math
import pathlib
import re

import pytest

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
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
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

    All three captions live in the panel and the choice is the index's `file`,
    so a board whose mesh has not been imported keeps the cautious one.

    **Three, since OH-75.** The Arduino Uno's model is composed here from two
    libraries rather than published by anybody, and calling that "the vendor's
    own 3D model" would be the same untruth in the other direction.
    """
    panel = PANEL.read_text(encoding="utf-8")
    assert "FOOTPRINT_CAPTION" in panel
    assert "MODEL_CAPTION" in panel
    assert "COMPOSED_CAPTION" in panel
    # The body of `caption`, which is where the choice moved when there began
    # to be three of them. Bounded to the function so that a later mention of
    # `model.file` elsewhere in the panel cannot satisfy this by accident.
    chooser = panel.split("function caption(model) {", 1)[1].split("\n}", 1)[0]
    assert "model.file" in chooser, (
        "the caption is not chosen by whether a model was actually found"
    )
    assert "model.composed" in chooser, (
        "a composed model is not told apart from a vendor's own"
    )
    for name in ("FOOTPRINT_CAPTION", "MODEL_CAPTION", "COMPOSED_CAPTION"):
        assert name in chooser, f"{name} is never returned"


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
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "export function penetration()" in source
    body = source.split("export function penetration()", 1)[1].split("\n}", 1)[0]
    assert "rope.colliders" in body, (
        "it must measure against the set the rope actually solved against, or "
        "it reports a fault on every wire's own part"
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


# --- metal, and something for it to reflect ---------------------------------


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
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("//"))
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
    Uno's solder mask read out of PICSimLab's own artwork while #ff9f37 is the
    XIAO's gold -- every one of them cited in `FINISHES`. Khronos PBR Neutral
    leaves an in-gamut colour where it is and only compresses what is too
    bright to show.
    """
    source = RENDERER.read_text(encoding="utf-8")
    assert "view.renderer.toneMapping = THREE.NeutralToneMapping;" in source
    # Comments stripped first, the same way `test_the_renderer_writes_down_no
    # _colour_of_its_own` does it: the reasoning above the line names ACES in
    # order to refuse it, and a check that a sentence can trip is not a check.
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in room.splitlines()
                     if not line.lstrip().startswith("//"))
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


def test_the_canvas_comes_before_the_caption_that_describes_it():
    """**Two full screens, on the commonest laptop size there is.**

    The caption, the bench bar and the bench list were all above the canvas, so
    at 1366 x 768 the 3D view started 1,584 px down -- 2.06 screens -- and a
    reader who loaded the page saw no board anywhere. Measured 2026-08-28 after
    it was reported twice as "no 3D model on 127.0.0.1:8088".

    Nothing was cut to make room, which matters: the caption is the
    honest-degradation statement about a composed model and a previous session
    refused to hide it. A caption belongs under its figure, and moving it there
    costs the prose nothing.
    """
    page = PAGE.read_text(encoding="utf-8")
    canvas = page.index('id="board-pins-canvas"')
    caption = page.index('id="board-pins-caption"')
    bench = page.index('class="bench-bar"')
    assert canvas < caption, (
        "the caption is above the thing it captions, which is what put the "
        "board below the fold"
    )
    assert canvas < bench, "the bench controls are above the board again"


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
    assert "$(CAPTION).textContent = WAITING;" in refusal, (
        "the no-board exit still says nothing"
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
    both = "\n".join(
        line for line in (panel + "\n" + page).splitlines()
        if not line.lstrip().startswith("//")
    )
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

    for colour in ("#313d63", "#116517"):
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
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in carve.splitlines()
                     if not line.lstrip().startswith("//"))
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

    Blending the state into the metal was tried first: brass `#b58136` with
    `high` mixed 72% of the way in comes out `#66744b`, and `input` comes out
    `#7e726c`. Two muddy browns three pixels wide -- the pin had stopped
    looking like brass and the state still could not be read.

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
    code = "\n".join(line for line in carve.splitlines()
                     if not line.lstrip().startswith("//"))
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
    assert "centreY * SCALE - depth / 2" in source, (
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
    with comments stripped (the OH-117 lesson), because no headless harness
    can run carvePins -- that gap is on OH-128's record.
    """
    source = RENDERER.read_text(encoding="utf-8")
    body = source.split("function carvePins(", 1)[1].split("\nfunction ", 1)[0]
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
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

    Asserted at the source with comments stripped (the OH-117 lesson),
    because no headless harness can run `carvePins` -- the gap OH-128's
    record owns.
    """
    source = RENDERER.read_text(encoding="utf-8")
    body = source.split("function carvePins(", 1)[1].split("\nfunction ", 1)[0]
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
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
        code = "\n".join(line for line in body.splitlines()
                         if not line.lstrip().startswith("//"))
        assert "releasePart(part)" in code, (
            f"{opener} does not go through releasePart"
        )
        assert "release(object)" not in code, (
            f"{opener} blanket-releases shared geometry again"
        )
    helper = source.split("function releasePart(", 1)[1].split("\n}", 1)[0]
    helper = "\n".join(line for line in helper.splitlines()
                       if not line.lstrip().startswith("//"))
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
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
    assert "if (!picked)" in code, "the cold page still asks about no board"
    assert code.index("if (!picked)") < code.index("await fetch"), (
        "the guard sits after the fetch it exists to prevent"
    )
    assert '"/api/board/pins")' not in code, (
        "the bare no-board fetch is still reachable"
    )


def test_the_panel_shows_the_composers_own_gaps():
    """**"Not drawn: Y1, Y2" about a board also missing four LEDs and 432
    silkscreen strokes** (OH-125): the caption's claim is now built from
    `model.not_drawn`, the composer's own measurement. Comments stripped,
    the OH-117 lesson."""
    panel = PANEL.read_text(encoding="utf-8")
    code = "\n".join(line for line in panel.splitlines()
                     if not line.lstrip().startswith("//"))
    assert "model.not_drawn" in code, (
        "the panel never reads the gaps the composer now ships"
    )
    for clause in ("turn_unseen", "unmodelled", "cutouts"):
        assert clause in code, f"the caption says nothing about {clause}"
    assert "parts.push(...gaps)" in code, (
        "the gap clauses are built and never reach the caption"
    )
