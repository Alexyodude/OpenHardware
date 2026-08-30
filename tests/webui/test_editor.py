# OpenHardware — the sketch editor, and the route behind it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What can and cannot be checked without a browser
#
# Python cannot execute the front end, so the DOM behaviour here is checked
# structurally: the ids exist, the script parses, nothing is fetched from a
# CDN. That is the same bargain `tests/webui/test_wiring.py` already makes,
# and its reason holds — without `node --check` a script that does not parse
# at all passes every other test in this repository, which is how one shipped
# for about ten minutes.
#
# The route underneath is checked for real, through `handle_board_api`,
# because that is what the browser calls.

import pathlib
import re
import subprocess

import pytest

from webui import compile as compiler
from webui import emulator_server
from webui.boards import atmega328p

STATIC = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
HTML = STATIC / "emulator.html"
SCRIPT = STATIC / "emulator.js"
STYLE = STATIC / "emulator.css"

BOARD = "Arduino Uno"

GOOD = "void setup(){ pinMode(13, OUTPUT); }\nvoid loop(){ digitalWrite(13, HIGH); }"
BAD = "void setup(){}\nvoid loop(){ int x = ; }"


def needs_toolchain() -> None:
    recipe = compiler.recipe_for(BOARD)
    try:
        compiler.toolchain_root(recipe)
        compiler.framework_root(recipe)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))


def compile_through_the_api(slot, source: str) -> dict:
    return emulator_server.handle_board_api(
        slot, "/api/board/compile", {}, {"board": BOARD, "source": source}
    )


# --- the route --------------------------------------------------------------


def test_a_sketch_posted_to_the_route_is_built_and_loaded():
    """One request, not two. The image never crosses the wire in either
    direction, so there is no moment where a build has succeeded and a load
    has not happened yet."""
    needs_toolchain()
    slot = emulator_server.BoardSlot()
    answer = compile_through_the_api(slot, GOOD)

    assert answer["ok"] is True
    assert answer["bytes"] > 0
    assert answer["board"]["board"] == BOARD
    # And the slot really holds it: a route that reported success without
    # loading would look identical from the response alone.
    state = emulator_server.handle_board_api(slot, "/api/board/state", {}, {})
    assert state["board"] == BOARD
    assert state["pc"] == 0, "the board was not entered at its reset vector"


def test_the_built_image_is_not_returned_over_the_wire():
    """Bytes do not survive JSON and the only thing a client could do with an
    image is post it straight back. `bytes` is the count, not the content."""
    needs_toolchain()
    slot = emulator_server.BoardSlot()
    answer = compile_through_the_api(slot, GOOD)
    assert "image" not in answer
    assert isinstance(answer["bytes"], int)


def test_a_sketch_that_does_not_compile_answers_with_the_diagnostics():
    """A 200 with `ok: false`, not an error. It is the commonest outcome there
    is and making it exceptional would be wrong about the shape of the work."""
    needs_toolchain()
    slot = emulator_server.BoardSlot()
    answer = compile_through_the_api(slot, BAD)
    assert answer["ok"] is False
    assert "sketch.cpp:2:" in answer["diagnostics"]


def test_a_failed_build_leaves_the_board_exactly_as_it_was():
    """**A syntax error must not cost a person the program that was running.**

    The board is loaded and stepped first, so there is something to lose;
    after the failed build the same image is still there and the step count
    has not been reset by a reload that should not have happened.
    """
    needs_toolchain()
    slot = emulator_server.BoardSlot()
    compile_through_the_api(slot, GOOD)
    emulator_server.handle_board_api(slot, "/api/board/run", {}, {"steps": 2_000})
    before = emulator_server.handle_board_api(slot, "/api/board/state", {}, {})
    assert before["pc"] != 0, "nothing ran, so there is nothing to lose"

    answer = compile_through_the_api(slot, BAD)
    assert answer["ok"] is False

    # **The PC is the witness.** A reload re-enters at the reset vector, so a
    # board that had run two thousand instructions and now sits at zero is a
    # board the failed build replaced.
    after = emulator_server.handle_board_api(slot, "/api/board/state", {}, {})
    assert after["pc"] == before["pc"], "the failed build reloaded the board"


def test_a_board_with_no_recipe_is_refused_by_name():
    """Refused before anything is compiled, and the answer names the chip --
    which is the actionable half."""
    slot = emulator_server.BoardSlot()
    with pytest.raises(emulator_server.ApiError) as caught:
        emulator_server.handle_board_api(
            slot, "/api/board/compile", {},
            {"board": "XIAO-ESP32-C3-DIP", "source": GOOD},
        )
    assert "ESP32-C3" in str(caught.value)


def test_a_request_without_a_source_is_refused():
    slot = emulator_server.BoardSlot()
    with pytest.raises(emulator_server.ApiError):
        emulator_server.handle_board_api(
            slot, "/api/board/compile", {}, {"board": BOARD}
        )


def test_the_compiled_sketch_actually_drives_the_pin():
    """End to end through the route a browser uses, so nothing between the
    textarea and the pin is assumed."""
    needs_toolchain()
    slot = emulator_server.BoardSlot()
    compile_through_the_api(slot, GOOD)
    emulator_server.handle_board_api(slot, "/api/board/run", {}, {"steps": 5_000})
    board = slot.require()
    assert board.cpu.read_data(atmega328p.DDRB) & (1 << atmega328p.LED_PIN)


# --- the page ---------------------------------------------------------------


def test_the_page_has_somewhere_to_type_and_something_to_press():
    markup = HTML.read_text(encoding="utf-8")
    for element in ('id="sketch-source"', 'id="sketch-build"',
                    'id="sketch-report"', 'id="sketch-errors"'):
        assert element in markup, element


def test_the_script_parses():
    """Without this a script that does not parse at all passes every other
    test here — Python cannot execute the front end."""
    node = subprocess.run(["node", "--check", str(SCRIPT)],
                          capture_output=True, text=True)
    if node.returncode == 127 or "not recognized" in node.stderr:
        pytest.skip("no node on PATH")
    assert node.returncode == 0, node.stderr


def test_the_build_button_is_disabled_for_the_whole_round_trip():
    """Two compilers racing for one temporary directory is what a second press
    would buy, and a build takes a second or two — long enough to press again.

    Checked as source because Python cannot click it: the handler must disable
    the button and re-enable it in a `finally`, so a thrown request does not
    leave it dead for the rest of the session.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    handler = script[script.index("async function buildSketch"):]
    handler = handler[:handler.index("\nasync function runLoadedBoard")]
    assert "button.disabled = true" in handler
    assert "finally" in handler
    assert handler.index("finally") < handler.index("button.disabled = false")


def test_a_build_stops_the_machine_before_it_replaces_the_image():
    """Stop, load, enter — and the order is the point. A free-running machine
    whose flash is replaced underneath it executes half of one program and
    half of another."""
    script = SCRIPT.read_text(encoding="utf-8")
    handler = script[script.index("async function buildSketch"):]
    handler = handler[:handler.index("\nasync function runLoadedBoard")]
    assert "running = false" in handler
    assert handler.index("running = false") < handler.index("/api/board/compile")


def test_the_default_sketch_is_a_real_blink():
    """The first thing anybody does is press the button. A default sketch that
    did nothing would teach nothing about whether the machine works."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "DEFAULT_SKETCH" in script
    for call in ("pinMode(13, OUTPUT)", "digitalWrite(13, HIGH)", "delay(500)"):
        assert call in script, call


def test_nothing_is_fetched_from_another_host():
    """The page is served from loopback and must stay self-contained. A CDN
    would put a third party between a reader and their own machine."""
    for path in (HTML, SCRIPT, STYLE):
        text = path.read_text(encoding="utf-8")
        # `https://` inside a comment or a licence URL is prose, not a fetch.
        # What matters is markup and script that would cause a request.
        for pattern in (r'src\s*=\s*["\']https?://', r'href\s*=\s*["\']https?://',
                        r'@import\s+url\(\s*["\']?https?://',
                        r'fetch\(\s*["\']https?://'):
            assert not re.search(pattern, text), f"{path.name}: {pattern}"


def test_the_diagnostics_pane_quotes_the_source_the_person_typed():
    """`webui/compile.py` prepends `#line 1` so the numbers are right, and the
    cost is gcc dropping its own quoted source. The page quotes the textarea
    instead — which is the text in front of the reader anyway."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "renderDiagnostics" in script
    assert "focusSourceLine" in script
    assert "setSelectionRange" in script, "clicking a location must move the cursor"


def test_a_diagnostic_message_is_rendered_before_the_line_it_quotes():
    """**A browser found this and no test here did.**

    The first version appended the quoted source straight after the location,
    which split every diagnostic in half:

        sketch.cpp:2:16:
              int broken = ;
                           ^ error: expected primary-expression

    A caret belongs under the line it points at and after the sentence it
    explains. Checked by position in the source, because Python cannot render
    the pane -- and the alternative was to keep finding it by looking.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    body = script[script.index("function renderDiagnostics"):]
    body = body[:body.index("\nfunction focusSourceLine")]
    message = body.index("text.slice(afterLocation, messageEnd)")
    quote = body.index('shown.className = "diagnostic-source"')
    assert message < quote, (
        "the quoted source line is appended before the rest of the message, "
        "which puts the caret above the sentence explaining it"
    )


def test_typing_in_the_sketch_editor_does_not_step_the_emulator():
    """**"s" is a letter before it is a shortcut** (OH-134).

    The page-level keydown handler turns "s" and "r" into step and run, with
    preventDefault. It excused INPUT and SELECT and not TEXTAREA -- and the
    sketch editor is a textarea -- so typing "void setup" single-stepped the
    8086 on the s and the letter never appeared. Serial, setup, return, for
    and digitalWrite were all unwritable: an IDE nobody can use, and it was
    reported as exactly that.

    Checked as source because Python cannot type into it: the guard must name
    all three text-entry elements, and it must come BEFORE the key checks.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    handler = source.split('document.addEventListener("keydown"', 1)[1]
    handler = handler.split("});", 1)[0]
    guard_at = handler.index('event.target.tagName')
    step_at = handler.index('"F10"')
    assert guard_at < step_at, "the guard runs after the shortcut fires"
    for element in ('"INPUT"', '"SELECT"', '"TEXTAREA"'):
        guard = handler[:step_at]
        assert element in guard, (
            f"{element} is missing from the keydown guard, so typing into it "
            f"steps the emulator instead"
        )


# --- the 8086 toolbar over a loaded board (OH-137) ---------------------------


def _stripped(body: str) -> str:
    """Comment lines out, the OH-117 lesson: an assertion a comment can
    satisfy is not an assertion about the code."""
    return "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))


def test_the_8086_redraw_refuses_while_a_board_owns_the_panes():
    """**Step over an Uno silently re-drew the AVR's 34 named registers as
    ax/bx/cx/dx** (OH-137): the shared panes have two writers, and the 8086's
    stayed live over a loaded board -- worst as a Run loop left going, which
    overwrote the board's panes on every 20,000-step burst. The guard is in
    `refresh` itself, before the fetch, so a burst already in flight lands
    nowhere."""
    source = SCRIPT.read_text(encoding="utf-8")
    body = _stripped(source.split("async function refresh(", 1)[1]
                     .split("\n}", 1)[0])
    guard = body.index('if (panes !== "i8086") return null;')
    fetch = body.index("await api(")
    assert guard < fetch, (
        "the refusal runs after the fetch, so the 8086 state is already drawn "
        "over the board's panes by the time it fires"
    )


def test_loading_a_board_stands_the_8086_controls_down():
    """`showMachine` is the one place the panes change hands: a board hand
    kills the run loop and disables the five 8086-only controls; the sample
    Load stays live because it is the way back, and `loadSelected` says so by
    handing the panes to "i8086" again."""
    source = SCRIPT.read_text(encoding="utf-8")
    body = _stripped(source.split("function showMachine(", 1)[1]
                     .split("\n}", 1)[0])
    assert "running = false" in body, (
        "a run loop left going keeps overwriting the board's panes every burst"
    )
    assert '["step", "run", "stop", "reset", "at"]' in body, (
        "the 8086-only controls stay live over a board"
    )
    board_redraw = _stripped(source.split("function renderBoardState(", 1)[1]
                             .split("\n}", 1)[0])
    assert "showMachine(" in board_redraw, (
        "a board redraw does not declare the owner, so the toolbar drifts "
        "from the panes"
    )
    way_back = _stripped(source.split("async function loadSelected(", 1)[1]
                         .split("\n}", 1)[0])
    assert 'showMachine("i8086")' in way_back, (
        "nothing hands the panes back, so the 8086 controls stay dead forever"
    )


def test_the_panes_say_which_machine_they_are_showing():
    """The label the desync made necessary: one set of panes, two writers,
    and a reader must not have to deduce the owner from register names."""
    html = HTML.read_text(encoding="utf-8")
    assert 'id="machine"' in html, "no element carries the machine name"
    source = SCRIPT.read_text(encoding="utf-8")
    body = _stripped(source.split("function showMachine(", 1)[1]
                     .split("\n}", 1)[0])
    assert '$("machine").textContent = name' in body, (
        "the label exists and nothing writes it"
    )


def test_the_client_reads_the_status_before_parsing_the_body():
    """A non-JSON error -- the static handler\'s text/plain 404, an unknown
    route -- surfaced as a SyntaxError from response.json() and the status
    that told the story was lost behind it (OH-139). Comments stripped, the
    OH-117 lesson."""
    source = SCRIPT.read_text(encoding="utf-8")
    body = source.split("async function api(", 1)[1].split("\n}", 1)[0]
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("//"))
    assert code.index("response.ok") < code.index("response.json()"), (
        "the body is parsed before the status is read, so a text/plain "
        "error is a SyntaxError instead of its status"
    )


def test_the_default_sketch_actually_compiles():
    """DEFAULT_SKETCH was the one sketch no test compiled -- the exact
    criticism `emulator.js` makes of the old hard-coded samples (OH-142).
    Read out of the page\'s own source, so an edit to the sketch is tested
    as edited rather than as remembered here."""
    needs_toolchain()
    source = SCRIPT.read_text(encoding="utf-8")
    block = source.split("const DEFAULT_SKETCH = [", 1)[1].split("].join", 1)[0]
    lines = re.findall(r'"((?:[^"\\]|\\.)*)"', block)
    sketch = "\n".join(lines)
    assert "void setup" in sketch and "void loop" in sketch
    built = compiler.build(BOARD, sketch)
    assert built.ok, built.diagnostics


def test_the_sketch_survives_a_reload_and_the_watch_rides_every_state_fetch():
    """Two page-side affordances, pinned at the source with comments
    stripped (OH-140): the sketch is kept in localStorage on every input
    and read back ahead of DEFAULT_SKETCH, and every /api/board/state
    fetch goes through `boardStateUrl()` so the words= watch the server
    always answered finally rides the wire."""
    source = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("//"))
    assert 'localStorage.getItem("oh-sketch")' in code, (
        "a reload eats the sketch again"
    )
    assert 'localStorage.setItem("oh-sketch"' in code, (
        "the sketch is never saved, so the restore reads nothing"
    )
    assert 'api("/api/board/state")' not in code, (
        "a state fetch bypasses boardStateUrl, so the watch silently does "
        "not apply there"
    )
    assert code.count("api(boardStateUrl())") >= 4
    assert 'id="board-watch"' in HTML.read_text(encoding="utf-8")
    assert '$("sketch-build").disabled = !can' in code, (
        "the Build button is not greyed by buildability, so 9 boards 400 "
        "only after the attempt again"
    )
