# OpenHardware - the emulator session, its API, and the samples it ships.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for webui/emulator.py and webui/emulator_server.py, per ticket OH-7.

Three layers, and the middle one is the point.

**The session**, driven directly. Everything the UI can do is a method call,
so almost everything is tested without a socket in sight.

**The samples**, run to completion and checked against what their names claim.
They began as a hex string inside `emulator.js`, which made them the one part
of this feature no test could reach -- a sample that broke would have shipped
as a broken demonstration and nothing would have said so. Now the suite runs
every one of them.

**The server**, over a real loopback socket, for the handful of things that
only exist at the boundary: the bind refusal, path traversal, and Origin.
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from core.i8086 import abi, disasm  # noqa: E402
from webui import emulator, emulator_server  # noqa: E402


@pytest.fixture(scope="module")
def core():
    """The native core, or skip the whole module with the reason."""
    try:
        return abi.load()
    except abi.AbiError as exc:
        pytest.skip(f"i8086 core unavailable: {exc}")


@pytest.fixture
def session(core):
    with emulator.Session() as live:
        yield live


#: `mov ax, 1234h` then `hlt`. Two instructions, used wherever a test needs a
#: program but not a particular one.
TINY = bytes([0xB8, 0x34, 0x12, 0xF4])


# --- loading and resetting -------------------------------------------------------


def test_a_loaded_program_starts_at_the_origin(session):
    session.load(TINY)
    assert session.registers()["ip"] == emulator.DEFAULT_ORIGIN
    assert session.registers()["cs"] == 0


def test_the_default_origin_is_clear_of_the_vector_table(session):
    """The first 1024 bytes are the interrupt vectors, and the 256 after them
    are the BIOS data area. A program loaded over either overwrites something
    it may want to use.

    This assertion is why DEFAULT_ORIGIN is not 0x0100: it was, with a comment
    claiming it cleared the table, and 0x0100 is 768 bytes inside it.""" 
    assert emulator.DEFAULT_ORIGIN >= 0x0500


def test_an_empty_program_is_refused(session):
    with pytest.raises(emulator.EmulatorError, match="zero bytes"):
        session.load(b"")


def test_a_program_that_runs_off_the_end_of_the_segment_is_refused(session):
    """64 KB, not a megabyte: CS is zero and IP is sixteen bits, so nothing
    above 0xFFFF is reachable at all.

    The check used to compare against the whole address space *after* masking
    the origin to sixteen bits, which made it arithmetically unable to fire.
    """
    with pytest.raises(emulator.EmulatorError, match="runs past"):
        session.load(b"\x90" * 16, origin=0xFFF8)


def test_reset_puts_the_program_back(session):
    session.load(TINY)
    session.run(10)
    assert session.registers()["ax"] == 0x1234
    session.reset()
    assert session.registers()["ax"] == 0
    assert session.registers()["ip"] == emulator.DEFAULT_ORIGIN
    assert session.status == "running"


def test_reset_clears_what_the_last_run_wrote(session):
    """Unlike the processor's own RESET, which leaves DRAM alone. A debugger's
    reset button that left the previous run's memory behind would make every
    second run a different experiment."""
    session.load(bytes([0xC7, 0x06, 0x00, 0x02, 0xEF, 0xBE, 0xF4]))
    session.run(10)
    assert session.memory(0x0200, 2)["bytes"] == [0xEF, 0xBE]
    session.reset()
    assert session.memory(0x0200, 2)["bytes"] == [0x00, 0x00]


# --- running ---------------------------------------------------------------------


def test_a_program_runs_to_its_halt(session):
    session.load(TINY)
    result = session.run(100)
    assert result.status == "halted"
    assert result.steps == 2


def test_halting_is_not_an_error(session):
    """HLT means the program finished. Reporting it the way an unimplemented
    opcode is reported would make every clean run look like a crash."""
    session.load(TINY)
    session.run(100)
    assert session.status == "halted"
    assert session.detail == ""


def test_an_unimplemented_opcode_stops_and_says_which(session):
    session.load(bytes([0xFF, 0xF8]))     # group 5 has no /7
    result = session.step()
    assert result.status == "unimplemented"
    assert "FF" in result.detail


def test_stepping_a_stopped_program_does_nothing(session):
    session.load(TINY)
    session.run(100)
    before = session.registers()
    assert session.step().steps == 0
    assert session.registers() == before


def test_a_run_budget_is_required_to_be_useful(session):
    session.load(TINY)
    with pytest.raises(emulator.EmulatorError, match="would do nothing"):
        session.run(0)


def test_a_run_budget_is_capped(session):
    """Without a ceiling, one request pins the server for as long as the
    program loops and the UI has no moment in which to notice Stop."""
    session.load(TINY)
    with pytest.raises(emulator.EmulatorError, match="exceeds"):
        session.run(emulator.MAX_RUN_STEPS + 1)


def test_a_run_stops_at_its_budget_without_finishing(session):
    """`EB FE` is `jmp $` -- a two-byte program that never ends. The run must
    come back anyway."""
    session.load(bytes([0xEB, 0xFE]))
    result = session.run(500)
    assert (result.steps, result.status) == (500, "running")


# --- what the UI reads ------------------------------------------------------------


def test_the_state_snapshot_has_everything_a_redraw_needs(session):
    session.load(TINY)
    state = session.state()
    assert set(state) == {"registers", "flags", "disassembly", "memory",
                          "status", "detail", "steps", "origin"}


def test_flags_are_named_not_a_number(session):
    """"FLAGS is 0F086h" is not something a person reads, and working it out
    by hand is the job a debugger exists to do for them."""
    session.load(TINY)
    assert set(session.flags()) == {"CF", "PF", "AF", "ZF", "SF",
                                    "TF", "IF", "DF", "OF"}


def test_the_current_instruction_is_marked(session):
    session.load(TINY)
    lines = session.disassembly()
    assert lines[0]["current"] is True
    assert sum(1 for line in lines if line["current"]) == 1


def test_the_disassembly_follows_the_instruction_pointer(session):
    session.load(TINY)
    session.step()
    assert session.disassembly()[0]["ip"] == emulator.DEFAULT_ORIGIN + 3


def test_a_memory_window_is_bounded(session):
    session.load(TINY)
    with pytest.raises(emulator.EmulatorError):
        session.memory(0, 0)
    with pytest.raises(emulator.EmulatorError, match="more than a view"):
        session.memory(0, 100_000)


# --- the samples, held to their own names -----------------------------------------


def test_every_sample_runs_to_completion_and_produces_what_it_claims(core):
    """The test this whole file exists for.

    Each sample states an address and the bytes it leaves there. If a sample
    stops doing what its name says, this fails -- rather than the UI quietly
    demonstrating something else.
    """
    failures = []
    for sample in emulator.SAMPLES:
        with emulator.Session() as live:
            live.load(sample.program)
            result = live.run(emulator.MAX_RUN_STEPS)
            address, expected = sample.produces
            got = bytes(live.memory(address, len(expected))["bytes"])
            if result.status != "halted":
                failures.append(f"{sample.name}: ended {result.status}, not halted")
            elif got != expected:
                failures.append(
                    f"{sample.name}: [{address:04X}] is {got.hex(' ')}, "
                    f"expected {expected.hex(' ')}"
                )
    assert not failures, "; ".join(failures)


def test_there_are_samples_and_each_has_a_listing(core):
    assert len(emulator.SAMPLES) >= 5
    for sample in emulator.SAMPLES:
        assert sample.listing, f"{sample.name} has no listing to show"
        assert sample.program, f"{sample.name} assembles to nothing"


# --- the disassembler -------------------------------------------------------------


def test_a_relative_branch_shows_its_destination_not_its_displacement(session):
    """`E2 FC` is "loop back four bytes", and the four is the one number a
    reader cannot use. The address is."""
    session.load(bytes([0x90, 0x90, 0xE2, 0xFC, 0xF4]))
    line = disasm.disassemble(session.cpu, 0x0000, emulator.DEFAULT_ORIGIN + 2)
    assert line.text == f"loop 0{emulator.DEFAULT_ORIGIN:03X}h"


def test_a_repeat_prefix_is_shown_on_the_instruction_it_repeats(session):
    session.load(bytes([0xF3, 0xA4]))
    assert disasm.disassemble(session.cpu).text == "rep movsb"


def test_a_repeat_before_a_compare_is_named_repne(session):
    session.load(bytes([0xF2, 0xAE]))
    assert disasm.disassemble(session.cpu).text == "repne scasb"


def test_a_segment_override_is_shown(session):
    session.load(bytes([0x26, 0x8B, 0x07]))
    assert disasm.disassemble(session.cpu).text == "mov ax, es:[bx]"


def test_an_operand_with_no_implied_width_states_one(session):
    """`inc [bx]` is ambiguous and `inc byte [bx]` is not."""
    session.load(bytes([0xFE, 0x07]))
    assert disasm.disassemble(session.cpu).text == "inc byte [bx]"


def test_hex_that_would_start_with_a_letter_gains_a_zero(session):
    """`0BEEFh`, not `BEEFh`. Every assembler needs it to tell a number from a
    label, and a listing that omits it is one nobody can paste back."""
    session.load(bytes([0xB8, 0xEF, 0xBE]))
    assert disasm.disassemble(session.cpu).text == "mov ax, 0BEEFh"


# --- the page's own scripts -------------------------------------------------------


def test_the_browser_scripts_parse():
    """`node --check` on every script this UI serves.

    Python's test suite cannot execute the front end, so nothing here would
    have noticed that `emulator.js` did not parse at all -- which is exactly
    what happened: a patch turned `join("\\n")` into a string containing a
    real newline, the file became a syntax error, and every Python test still
    passed while the page rendered nothing.

    Skipped, loudly, where node is absent. A skip that names its reason is
    honest; silently passing would put this back where it started.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed, so the browser scripts are unchecked")

    static = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
    scripts = sorted(p for p in static.glob("*.js"))
    assert scripts, "no scripts found to check"

    broken = []
    for script in scripts:
        done = subprocess.run([node, "--check", str(script)],
                              capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            broken.append(f"{script.name}: {done.stderr.strip().splitlines()[-1]}")
    assert not broken, "; ".join(broken)


# --- the server, at its boundary --------------------------------------------------


def test_the_server_refuses_to_bind_a_public_interface():
    """It loads and runs code on request. That is the entire product, and it
    is exactly why it may not listen anywhere but loopback."""
    with pytest.raises(ValueError, match="loopback-only"):
        emulator_server.build_server("0.0.0.0", 0)


def test_static_paths_cannot_escape_the_static_directory():
    assert emulator_server.resolve_static("/../../webui/emulator.py") is None
    assert emulator_server.resolve_static("/..%2f..%2fsetup.py") is None


def test_only_the_four_declared_extensions_are_served():
    assert emulator_server.resolve_static("/emulator.html") is not None
    assert emulator_server.resolve_static("/emulator.js") is not None
    # A .py file inside static/ would still not be served.
    assert emulator_server.resolve_static("/emulator.py") is None


def test_an_unknown_route_is_a_named_error(session):
    with pytest.raises(emulator_server.ApiError, match="no such route"):
        emulator_server.handle_api(
            session, "/api/nope", {}, {}
        )


@pytest.fixture
def live_server(core):
    """A real server on a real loopback port, stopped afterwards."""
    server = emulator_server.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get(base: str, path: str, origin: str | None = None):
    request = urllib.request.Request(base + path)
    if origin:
        request.add_header("Origin", origin)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def post(base: str, path: str, body: dict[str, object]):
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def test_the_page_is_served_at_the_root(live_server):
    with urllib.request.urlopen(live_server + "/", timeout=10) as response:
        body = response.read()
    assert response.headers["Content-Type"].startswith("text/html")
    assert b"i8086" in body


def test_a_program_can_be_loaded_and_run_over_the_api(live_server):
    """The whole feature, end to end, through the transport the UI uses."""
    sample = emulator.SAMPLES[0]
    assert post(live_server, "/api/load", {"hex": sample.hex})["loaded"] > 0
    assert post(live_server, "/api/run", {"steps": 1000})["status"] == "halted"
    state = get(live_server, f"/api/state?at={sample.produces[0]}&len=2")
    assert bytes(state["memory"]["bytes"]) == sample.produces[1]


def test_the_samples_are_served(live_server):
    served = get(live_server, "/api/samples")["samples"]
    assert [s["name"] for s in served] == [s.name for s in emulator.SAMPLES]


def test_a_bad_request_is_a_400_with_a_reason(live_server):
    with pytest.raises(urllib.error.HTTPError) as caught:
        post(live_server, "/api/load", {"hex": "not hex at all"})
    assert caught.value.code == 400
    assert "hex" in json.loads(caught.value.read())["error"]


def test_a_foreign_origin_is_refused(live_server):
    """A page you visit can POST to localhost; the same-origin policy does not
    stop it. This does."""
    with pytest.raises(urllib.error.HTTPError) as caught:
        get(live_server, "/api/state", origin="https://example.invalid")
    assert caught.value.code == 403


def test_the_pages_own_origin_is_allowed(live_server):
    port = live_server.rsplit(":", 1)[1]
    assert get(live_server, "/api/state", origin=f"http://127.0.0.1:{port}")


# --- a client that goes away is not an error --------------------------------


def _raise_inside_handle_error(server, exception: BaseException) -> str:
    """Call `handle_error` with `exception` in flight, return what it printed.

    `handle_error` reads `sys.exc_info()`, so the exception has to be genuinely
    being handled -- constructing one and passing it in would exercise nothing.
    """
    import contextlib
    import io

    caught = io.StringIO()
    try:
        raise exception
    except BaseException:  # noqa: BLE001 - re-raised into the thing under test
        with contextlib.redirect_stderr(caught):
            server.handle_error(None, ("127.0.0.1", 55568))
    return caught.getvalue()


def test_a_client_that_hangs_up_mid_response_prints_nothing():
    """**The user's report, and the reason it arrived attached to another
    question.**

    `emulator.js` polls `/api/board/state` on a timer, so reloading a page with
    a board running leaves a response half-written to a socket nobody is
    reading. The write raises WinError 10053 on Windows, and
    `http.server`'s own `handle_error` answers with a twenty-line traceback --
    during entirely normal use. It was reported as part of "why is the 3D model
    not loading", which is what a stack trace during normal use does: it becomes
    the explanation for whatever else was confusing.

    All three names are checked because the platforms disagree about which one
    they raise, and a fix that only covered the POSIX spelling would leave the
    Windows report exactly as it was.
    """
    from webui import emulator_server

    server = emulator_server.build_server("127.0.0.1", 0)
    try:
        for name in (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            printed = _raise_inside_handle_error(server, name("the peer went"))
            assert printed == "", f"{name.__name__} still printed {printed!r}"
    finally:
        server.server_close()


def test_a_handler_that_fails_for_any_other_reason_still_says_so():
    """**The half that stops this being catch-and-default.**

    Declining to report a peer disconnect is only safe while everything else is
    still reported in full. Without this test the fix could be widened to
    `except Exception: return` and nothing would notice until a real failure in
    a handler thread disappeared -- which is the exact shape
    `.claude/rules/python.md` rule 1 refuses.
    """
    from webui import emulator_server

    server = emulator_server.build_server("127.0.0.1", 0)
    try:
        printed = _raise_inside_handle_error(server, ValueError("a real bug"))
        assert "ValueError" in printed and "a real bug" in printed, printed
        assert "Traceback" in printed
    finally:
        server.server_close()


def test_the_hung_up_set_is_the_three_that_mean_the_peer_left():
    """Named as a set, so the three read as one fact and not three exceptions.

    Nothing broader belongs here: `OSError` would swallow a full disk and a
    refused bind along with them, and each of those is a failure this program
    made rather than one its peer did.
    """
    from webui import emulator_server

    assert set(emulator_server.HUNG_UP) == {
        ConnectionAbortedError, ConnectionResetError, BrokenPipeError,
    }
    assert OSError not in emulator_server.HUNG_UP, (
        "OSError covers failures this program made, not ones its peer did"
    )


# --- a picked board, before anything is loaded (OH-94) ----------------------
#
# `/api/board/pins` used to call `boards.require()` first, so the pin view
# existed only after a firmware load. `reload()` in board3d-panel.js is the
# only thing that draws the board, so PICKING one drew nothing at all -- the
# cause behind the symptom OH-89 fixed.


def test_the_pins_of_a_board_nobody_has_loaded_are_served(session):
    """**The whole of OH-94 in one call.** No session, no built core, and a
    board that has no `webui/boards/mg24.py` at all -- and its twenty-four
    pads come back, because where they sit is not an execution."""
    view = emulator_server.handle_api(
        session, "/api/board/pins",
        {"board": ["XIAO-MG24-DIP"]}, {}, emulator_server.BoardSlot(),
    )
    assert view["present"] is True
    assert len(view["pads"]) == 24
    assert view["unknown"] == 24, "nothing is running, so nothing is answerable"


def test_asking_for_pins_with_no_board_and_no_session_still_refuses_by_name():
    """The no-parameter form is the old contract and keeps it. A caller that
    forgot the parameter must get the sentence that says what to do, not an
    empty board."""
    with pytest.raises(emulator_server.ApiError, match="no board is loaded"):
        emulator_server.handle_api(
            emulator.Session(), "/api/board/pins",
            {}, {}, emulator_server.BoardSlot(),
        )


def test_an_unknown_board_name_says_there_is_nothing_to_draw(session):
    """Not a traceback out of the middle of a request, and not an empty board
    either: a named `present: false` with the reason, which is the shape the
    panel already renders."""
    view = emulator_server.handle_api(
        session, "/api/board/pins",
        {"board": ["no such board"]}, {}, emulator_server.BoardSlot(),
    )
    assert view["present"] is False
    assert "no pad map" in view["note"]


def test_a_picked_board_is_answered_for_and_not_the_one_that_is_running(session):
    """**Liveness is an overlay, and it is keyed on the board.**

    If the page asks about a board the session is not running, merging that
    session's levels in would report one board's pins on another board's pads
    -- the shape of mistake this repository ranks worst, because every pad
    would show a state and every state would be about something else.
    """
    slot = emulator_server.BoardSlot()

    class _Running:
        """Just the three attributes the route reads off a session."""

        board = "Arduino Uno"
        runtime = None
        cpu = None

    slot.session = _Running()
    view = emulator_server.handle_api(
        session, "/api/board/pins",
        {"board": ["XIAO-MG24-DIP"]}, {}, slot,
    )
    # It reached `pad_view` rather than `pin_view`: had it taken the live path
    # it would have raised on `runtime=None` instead of answering.
    assert view["board"] == "XIAO-MG24-DIP"
    assert view["unknown"] == len(view["pads"])


# --- a compile no longer freezes the page (OH-136) ---------------------------


def test_a_state_poll_answers_while_a_build_runs(live_server):
    """**The page looked hung for every second of every build**: one lock
    wraps every route and the whole build used to run inside it -- measured
    before the split, a GET /api/state issued 0.7 s into a SAMD21 build
    answered after 15.79 s. The build now runs before the lock is taken, so
    a poll lands while the compiler grinds.

    The build is real and skips without the toolchain. The poll must land
    while the build is STILL RUNNING -- a poll after a finished build
    proves nothing, and the assertion says so rather than passing
    vacuously."""
    import time

    from webui import compile as compile_service
    try:
        recipe = compile_service.recipe_for("XIAO-SAMD21-DIP")
        compile_service.toolchain_root(recipe)
        compile_service.framework_root(recipe)
        compile_service.variant_root(recipe)
        compile_service.include_roots(recipe)
    except compile_service.CompileError as exc:
        pytest.skip(str(exc))

    finished: dict[str, object] = {}

    def build() -> None:
        finished["reply"] = post(live_server, "/api/board/compile", {
            "board": "XIAO-SAMD21-DIP",
            "source": "void setup(){} void loop(){}",
        })

    # Two attempts, and only the VACUOUS case retries: a cold toolchain can
    # finish its (cached) build before the probe point, and a run where the
    # build already ended proves nothing about the lock. A lock regression
    # is structural and fails every attempt; cold-start noise clears on the
    # second. The latency assertion stays strict on the attempt that counts.
    for _attempt in range(2):
        builder = threading.Thread(target=build)
        started = time.monotonic()
        builder.start()
        time.sleep(0.7)                  # the survey's own probe point
        began = time.monotonic()
        state = get(live_server, "/api/state?at=0&len=16")
        waited = time.monotonic() - began
        still_building = builder.is_alive()
        builder.join(timeout=120)
        built = time.monotonic() - started
        if still_building:
            break
    assert "registers" in state
    assert still_building, (
        "the build finished before the poll landed on both attempts, so "
        "nothing here measured the lock; a SAMD21 build takes seconds"
    )
    # **Against the build's own duration, not a wall clock** (OH-166 item 2).
    # This read `waited < 3.0`, which is a fact about the machine: three
    # seconds is generous on an idle box and not enough on a loaded one, and
    # the test failed for a session that was doing something else entirely.
    #
    # What the lock regression actually looks like is a RATIO. The poll is
    # issued 0.7 s in, so if the handler serialises behind the build it
    # answers when the build does and `waited` is very nearly the whole
    # build: OH-136 measured 15.79 s against a build of about the same,
    # which is a ratio near 1. With the build outside the lock the poll
    # answers in milliseconds, a ratio near zero. Load moves both numbers
    # together and leaves the ratio alone, which is the property this test
    # is actually about.
    #
    # Measured here 2026-09-08 by tightening the bound until it printed:
    # the poll waited 0.0018 s of a 4.07 s build, 0.04%. The bound is 25%
    # and a serialised handler is near 100%, so there are about three
    # orders of magnitude between passing and the regression -- which is
    # the headroom the wall clock did not have.
    assert waited < built / 4, (
        f"a state poll waited {waited:.2f} s of a {built:.2f} s build "
        f"({waited / built:.0%} of it); the lock is holding the page "
        f"hostage again"
    )
    reply = finished.get("reply")
    assert isinstance(reply, dict) and reply.get("ok"), f"the build itself failed: {reply}"


def test_a_compile_with_a_wrong_shaped_body_is_refused_by_name(live_server):
    """The validation moved out of the locked handler into
    `prepare_compile` (OH-136), and the refusal must not have moved with
    it: a number where a board name belongs is still a 400 naming the
    field, from the same door the browser uses."""
    request = urllib.request.Request(
        live_server + "/api/board/compile",
        data=json.dumps({"board": 5, "source": "void setup(){}"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10):
            raise AssertionError("a non-string board was accepted")
    except urllib.error.HTTPError as caught:
        assert caught.code == 400
        body = json.loads(caught.read())
        assert "board must be a string" in body["error"]


def test_the_locked_handler_consumes_the_prepared_build():
    """A handler that rebuilt inside the lock would compile every sketch
    TWICE and hold the lock for the second one -- the freeze OH-136
    removed, wearing a disguise. Asserted at the source with comments
    stripped, because the double build is invisible to a caller who only
    reads the reply."""
    source = pathlib.Path(emulator_server.__file__).read_text(encoding="utf-8")
    body = source.split('if route == "/api/board/compile":', 1)[1]
    body = body.split("\n    if route", 1)[0]
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "prepared if prepared is not None" in code, (
        "the locked handler ignores the build the unlocked prelude already "
        "did, so every sketch compiles twice and the second holds the lock"
    )


def test_a_query_error_names_the_parameter(live_server):
    """`at=zz` used to answer "invalid literal for int() with base 0: \'zz\'"
    -- true, and useless in a reply to a request carrying three parameters,
    while the body path already named its fields (OH-139)."""
    request = urllib.request.Request(live_server + "/api/state?at=zz&len=16")
    try:
        with urllib.request.urlopen(request, timeout=10):
            raise AssertionError("at=zz was accepted")
    except urllib.error.HTTPError as caught:
        assert caught.code == 400
        body = json.loads(caught.read())
        assert "at" in body["error"] and "zz" in body["error"]
        assert "invalid literal" not in body["error"], (
            "the reply is still int()'s own message, naming no field"
        )


# --- a GET cannot mutate (OH-141) --------------------------------------------


def test_a_get_cannot_reset_the_machine(live_server):
    """**`<img src="/api/reset">` executed** (OH-141): a missing Origin is
    allowed by design -- curl sends none -- and an img tag sends none
    either, so any page in any tab could reset this session or burn steps
    on a loaded board. Corruption, not disclosure (the tag cannot read the
    reply), and a 405 closes it while the posture stays. The proof is
    behavioural: the step count survives the refused GET, and the same
    route still answers POST."""
    post(live_server, "/api/step", {})
    before = get(live_server, "/api/state?at=0&len=16")
    request = urllib.request.Request(live_server + "/api/reset")
    try:
        with urllib.request.urlopen(request, timeout=10):
            raise AssertionError("GET /api/reset was accepted")
    except urllib.error.HTTPError as caught:
        assert caught.code == 405
        body = json.loads(caught.read())
        assert "POST" in body["error"]
    after = get(live_server, "/api/state?at=0&len=16")
    assert after["steps"] == before["steps"], (
        "the refused GET still reset the machine"
    )
    reset = post(live_server, "/api/reset", {})
    assert isinstance(reset, dict), "POST /api/reset stopped working"


def test_every_route_states_its_methods():
    """The table and the dispatch are two lists of the same routes, and
    this is what holds them together: a route added to `handle_api` without
    a `ROUTE_METHODS` row fails HERE, by name, instead of shipping with
    whatever verb reaches it first."""
    import re
    source = pathlib.Path(emulator_server.__file__).read_text(encoding="utf-8")
    dispatched = set(re.findall(r'route == "(/api/[^"]+)"', source))
    assert dispatched == set(emulator_server.ROUTE_METHODS), (
        f"only in dispatch: {dispatched - set(emulator_server.ROUTE_METHODS)}; "
        f"only in the table: {set(emulator_server.ROUTE_METHODS) - dispatched}"
    )


def test_the_dead_target_route_is_gone(session):
    """/api/target had no caller and only accepted the value already
    selected (OH-142): the route, the `Selection` it wrote, and the
    `selected` echo nobody read left together. A route that exists only to
    be a no-op teaches a reader the server does something it does not."""
    with pytest.raises(emulator_server.ApiError, match="no such route"):
        emulator_server.handle_api(session, "/api/target", {},
                                   {"name": "i8086"})
    assert not hasattr(emulator_server, "Selection"), (
        "the state the dead route wrote is still defined"
    )


def test_each_server_serves_only_its_own_page():
    """Both servers read one static/ directory, and each served the
    other\'s page broken there -- :8088/index.html renders and then hangs
    dialing a websocket :8088 does not speak (OH-142). The assets stay
    common property; the ENTRY pages name a transport each."""
    assert emulator_server.resolve_static("/index.html") is None
    assert emulator_server.resolve_static("/emulator.html") is not None
    from webui import bridge
    assert bridge.resolve_static("/emulator.html") is None
    assert bridge.resolve_static("/index.html") is not None
