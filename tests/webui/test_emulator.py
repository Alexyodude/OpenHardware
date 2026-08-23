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
        emulator_server.handle_api(session, "/api/nope", {}, {})


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
