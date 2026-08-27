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
    assert body.count("NEUTRAL_LIGHT") == 2, (
        "the light constant is used somewhere other than the two lights"
    )


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
