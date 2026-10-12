# OpenHardware - a host fault in the i8086 core stops the machine and is answered.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""A fault in the core's own code, from `Cpu.step` to the page (OH-223).

When the DLL faults on the host -- a divide error, an access violation --
ctypes on Windows catches the structured exception around the foreign call and
raises `OSError` out of it. OH-222's review saw what followed, with an
unguarded IDIV: the request got no reply, and the machine carried on from a
state no instruction produced, IP already past the IDIV and status still
"running", so the next step ran the HLT.

**The fault is faked, and only the fault.** There is no core bug to provoke on
purpose -- OH-222 removed the one that was known -- so for the length of a test
`i8086_step` is wrapped: the real core runs every instruction, and at one
address the wrapper then raises the `OSError` ctypes would. The instruction
there is a NOP, so running it for real -- which is what records where the step
began -- leaves exactly what a fault while executing leaves: IP past it,
nothing else written. Everything above the foreign call is the real code:
`Cpu.step`, `Session`, the route table, and a server on a loopback socket.

On Linux the same fault is a signal, which ctypes does not catch, and the
process ends; nothing in-process can see it. OH-223's note records why nothing
is done about that here.
"""

from __future__ import annotations

import ctypes
import json
import pathlib
import sys
import threading
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from core.i8086 import abi  # noqa: E402
from webui import emulator, emulator_server  # noqa: E402

#: mov ax, 1234h; mov bx, 5678h; xchg ax, bx; nop; hlt.
PROBE = bytes.fromhex("B83412" "BB7856" "93" "90" "F4")

#: Where the NOP the fake makes fault begins at the default origin, and where
#: running it leaves IP: on the HLT.
FAULT_AT = emulator.DEFAULT_ORIGIN + 7
LEFT_AT = FAULT_AT + 1

#: The text ctypes gives an access violation, reading and writing.
READING = "exception: access violation reading 0x0000000000000010"
WRITING = "exception: access violation writing 0x0000000000000010"


@pytest.fixture
def core():
    try:
        return abi.load()
    except abi.AbiError as exc:
        pytest.skip(f"i8086 core unavailable: {exc}")


def fault_at(core, monkeypatch, address: int, text: str) -> None:
    """Wrap `i8086_step` so the step at 0000:`address` raises `OSError(text)`
    after the real core has run it.

    The real functions are held here rather than looked up per call, so a
    test can break another of them without breaking this."""
    real, get = core.i8086_step, core.i8086_get_regs

    def step(handle):
        regs = abi.Registers()
        get(handle, ctypes.byref(regs))
        status = real(handle)
        if (regs.cs, regs.ip) == (0, address):
            raise OSError(text)
        return status

    monkeypatch.setattr(core, "i8086_step", step)


@pytest.fixture
def faults(core, monkeypatch):
    fault_at(core, monkeypatch, FAULT_AT, READING)


@pytest.fixture
def session(core):
    with emulator.Session() as live:
        yield live


def faulted_step(session) -> abi.HostFault:
    """Load the probe, run the three moves, and return what the NOP raises."""
    session.load(PROBE)
    for _ in range(3):
        assert session.cpu.step()
    with pytest.raises(abi.HostFault) as caught:
        session.cpu.step()
    return caught.value


# --- the binding -------------------------------------------------------------


def test_the_core_records_where_each_step_began(session, core):
    """What the binding reads after a fault, read here without one: a jump
    moves IP, and the record still says where the jump was."""
    session.load(bytes.fromhex("EB01" "F4" "90"))  # jmp +1; hlt; nop
    assert session.cpu.step()
    assert session.registers()["ip"] == emulator.DEFAULT_ORIGIN + 3
    assert core.i8086_step_entry(session.cpu._handle) == emulator.DEFAULT_ORIGIN
    assert session.cpu.step()
    assert core.i8086_step_entry(session.cpu._handle) == emulator.DEFAULT_ORIGIN + 3


def test_a_host_fault_is_raised_as_an_abi_error_naming_the_instruction(
        session, faults):
    """Where the instruction began and the bytes there, not where IP was
    left: the core had moved IP onto the HLT, and naming the HLT as the
    instruction that faulted would send a reader to the wrong line."""
    fault = faulted_step(session)
    assert isinstance(fault, abi.AbiError)
    assert isinstance(fault.__cause__, OSError)
    assert fault.at == (0, FAULT_AT)
    assert fault.code == bytes.fromhex("90F400000000")
    assert fault.left == (0, LEFT_AT)
    message = str(fault)
    assert message.startswith("i8086:"), message
    assert READING in message, message
    assert "first 6 bytes" in message, message
    assert "reset or load" in message, message


def test_what_was_read_back_survives_a_fault_reading_the_rest(
        session, faults, core, monkeypatch):
    """A fault that wrecked more than one instruction can fault the read-back
    too. Each read is its own: the bytes read before one faults are kept,
    a register read that faults leaves `left` unknown and says why, and
    neither second `OSError` replaces the `HostFault`."""
    real_read = core.i8086_read_byte
    reads = []

    def read_byte(handle, address):
        reads.append(address)
        if len(reads) == 3:
            raise OSError("exception: access violation reading 0x0000000000000020")
        return real_read(handle, address)

    def get_regs(handle, out):
        raise OSError("exception: access violation reading 0x0000000000000030")

    session.load(PROBE)
    for _ in range(3):
        assert session.cpu.step()
    monkeypatch.setattr(core, "i8086_read_byte", read_byte)
    monkeypatch.setattr(core, "i8086_get_regs", get_regs)
    with pytest.raises(abi.HostFault) as caught:
        session.cpu.step()
    fault = caught.value
    assert fault.at == (0, FAULT_AT)
    assert fault.code == bytes.fromhex("90F4")
    assert fault.left is None
    message = str(fault)
    assert "first 2 bytes" in message, message
    assert "reading 0x0000000000000020" in message, message
    assert "reading 0x0000000000000030" in message, message


def test_a_wild_write_says_to_restart_the_process_and_not_to_reset(
        session, core, monkeypatch):
    """A write that went astray in the core may have landed anywhere in this
    process, not only in the machine a reset puts back."""
    fault_at(core, monkeypatch, FAULT_AT, WRITING)
    message = str(faulted_step(session))
    assert WRITING in message, message
    assert "restart" in message, message
    assert "reset or load" not in message, message


def test_a_decoder_fault_is_raised_as_an_abi_error_naming_where(
        session, core, monkeypatch):
    """`Cpu.decode` runs the core's decoder, which `/api/state` calls for
    every line of its listing."""
    real = core.i8086_decode

    def decode(handle, cs, ip, out):
        real(handle, cs, ip, out)
        if (cs, ip) == (0, FAULT_AT):
            raise OSError(READING)

    monkeypatch.setattr(core, "i8086_decode", decode)
    session.load(PROBE)
    with pytest.raises(abi.HostFault) as caught:
        session.cpu.decode(0, FAULT_AT)
    fault = caught.value
    assert isinstance(fault.__cause__, OSError)
    assert fault.at == (0, FAULT_AT)
    assert fault.code == bytes.fromhex("90F400000000")
    assert fault.left == (0, emulator.DEFAULT_ORIGIN)
    message = str(fault)
    assert f"decoding the instruction at 0000:{FAULT_AT:04X}" in message, message
    assert "the machine is as it was" in message, message


# --- the session -------------------------------------------------------------


def test_a_session_whose_core_faults_on_the_host_stops_and_says_why(
        session, faults):
    """The three moves complete and count; the NOP does not."""
    session.load(PROBE)
    result = session.run(100)
    assert (result.steps, result.status) == (3, "faulted")
    assert result.detail.startswith("i8086: the core faulted"), result.detail
    state = session.state()
    assert (state["status"], state["detail"]) == ("faulted", result.detail)
    assert state["steps"] == 3


def test_a_faulted_session_does_not_carry_on_from_where_the_core_left_it(
        session, faults):
    """The defect OH-222's review saw: the next step ran the HLT from a state
    no instruction produced. Faulted is terminal, as halted is, until a reset
    or a load -- and after a reset the same fault comes back at the same
    place, because nothing about it depends on anything but the program."""
    session.load(PROBE)
    first = session.run(100)
    left = session.registers()
    assert left["ip"] == LEFT_AT
    assert session.step() == emulator.RunResult(0, "faulted", first.detail)
    assert session.run(100) == emulator.RunResult(0, "faulted", first.detail)
    assert session.registers() == left
    assert session.status == "faulted"

    session.reset()
    assert (session.status, session.detail) == ("running", "")
    assert session.disassembly()[0]["ip"] == emulator.DEFAULT_ORIGIN
    assert session.run(100) == first


def test_after_a_fault_the_listing_starts_at_and_marks_the_instruction_that_faulted(
        session, faults):
    """IP is on the HLT, and a listing that started there would mark the HLT
    as where the machine stopped. The registers still say where the core
    left IP, because that is true; the listing says which instruction it
    was executing."""
    session.load(PROBE)
    session.run(100)
    listing = session.state()["disassembly"]
    assert (listing[0]["ip"], listing[0]["text"]) == (FAULT_AT, "nop")
    assert [line["current"] for line in listing].count(True) == 1
    assert listing[0]["current"]
    assert session.registers()["ip"] == LEFT_AT


def test_a_decoder_fault_is_a_line_of_the_listing_and_the_state_still_answers(
        session, core, monkeypatch):
    """The listing stops at the instruction the decoder faulted on, and says
    so there; the lines before it are kept. Reading the state runs nothing,
    so the status is left as it was."""
    real = core.i8086_decode

    def decode(handle, cs, ip, out):
        real(handle, cs, ip, out)
        if (cs, ip) == (0, FAULT_AT):
            raise OSError(READING)

    monkeypatch.setattr(core, "i8086_decode", decode)
    session.load(PROBE)
    state = session.state()
    listing = state["disassembly"]
    assert [line["ip"] for line in listing] == [
        emulator.DEFAULT_ORIGIN, emulator.DEFAULT_ORIGIN + 3,
        emulator.DEFAULT_ORIGIN + 6, FAULT_AT]
    assert listing[-1]["text"].startswith("i8086: the core faulted"), listing[-1]
    assert "decoding" in listing[-1]["text"], listing[-1]
    assert listing[-1]["bytes"] == "90 F4 00 00 00 00"
    assert listing[0]["current"] and not listing[-1]["current"]
    assert state["status"] == "running"


# --- the server ----------------------------------------------------------------


@pytest.fixture
def live_server(core):
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


def call(base: str, path: str, body: dict[str, object] | None = None
         ) -> tuple[int, dict[str, object]]:
    """The HTTP status and the JSON body. A dropped connection raises."""
    request = urllib.request.Request(
        base + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read())


def test_the_server_answers_a_run_whose_core_faulted_on_the_host(
        live_server, faults):
    """An answer, not a dropped connection: the run, the state the page
    redraws from, and a step asked for afterwards all come back 200 and say
    faulted, the way an unimplemented opcode comes back."""
    assert call(live_server, "/api/load", {"hex": PROBE.hex()})[0] == 200
    status, run = call(live_server, "/api/run", {"steps": 100})
    assert status == 200
    assert (run["steps"], run["status"]) == (3, "faulted")
    assert run["detail"].startswith("i8086: the core faulted"), run["detail"]

    status, state = call(live_server, "/api/state")
    assert status == 200
    assert (state["status"], state["detail"]) == ("faulted", run["detail"])
    assert state["registers"]["ip"] == LEFT_AT
    assert state["disassembly"][0]["ip"] == FAULT_AT
    assert state["disassembly"][0]["current"]

    status, step = call(live_server, "/api/step", {})
    assert (status, step["steps"], step["status"]) == (200, 0, "faulted")
