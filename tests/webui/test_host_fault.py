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
`i8086_step` is replaced by a function that does what the unguarded IDIV was
seen to do: move IP past the instruction, write nothing else, and raise the
`OSError` ctypes raises for STATUS_INTEGER_OVERFLOW. Every other instruction
goes to the real core. Everything above the foreign call is the real code:
`Cpu.step`, `Session`, the route table, and a server on a loopback socket.

On Linux the same fault is SIGFPE, which ctypes does not catch, and the
process ends; nothing in-process can see it. OH-223's note records why
nothing is done about that here.
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

#: OH-222's probe: mov dx, 8000h; mov ax, 0; mov bx, 0FFFFh; idiv bx; hlt.
PROBE = bytes.fromhex("BA0080" "B80000" "BBFFFF" "F7FB" "F4")

#: Where the IDIV begins at the default origin, and where its fault leaves IP:
#: past the two bytes of `idiv bx`, on the HLT.
IDIV_AT = emulator.DEFAULT_ORIGIN + 9
LEFT_AT = IDIV_AT + 2


@pytest.fixture
def core():
    try:
        return abi.load()
    except abi.AbiError as exc:
        pytest.skip(f"i8086 core unavailable: {exc}")


@pytest.fixture
def idiv_faults(core, monkeypatch):
    """`i8086_step` faulting on the host at every IDIV r/m16 (F7 /7).

    The real functions are held here rather than looked up per call, so a
    test can break another of them without breaking the fake."""
    real, read, get, put = (core.i8086_step, core.i8086_read_byte,
                            core.i8086_get_regs, core.i8086_set_regs)

    def step(handle):
        regs = abi.Registers()
        get(handle, ctypes.byref(regs))
        opcode = read(handle, abi.physical(regs.cs, regs.ip))
        modrm = read(handle, abi.physical(regs.cs, regs.ip + 1))
        if opcode != 0xF7 or (modrm >> 3) & 7 != 7:
            return real(handle)
        # What the unguarded core did: `ExecuteOne` moves IP past the
        # instruction before executing it, and the divide faulted before
        # anything was written back.
        regs.ip += 2
        put(handle, ctypes.byref(regs))
        raise OSError("exception: integer overflow")

    monkeypatch.setattr(core, "i8086_step", step)


@pytest.fixture
def session(core):
    with emulator.Session() as live:
        yield live


def test_a_host_fault_is_raised_as_an_abi_error_naming_the_instruction(
        session, idiv_faults):
    """Where the IDIV began and the bytes there, not where IP was left: the
    core moved IP onto the HLT before it faulted, and naming the HLT as the
    instruction that overflowed would send a reader to the wrong line."""
    session.load(PROBE)
    for _ in range(3):
        assert session.cpu.step()
    with pytest.raises(abi.HostFault) as caught:
        session.cpu.step()
    message = str(caught.value)
    assert isinstance(caught.value, abi.AbiError)
    assert isinstance(caught.value.__cause__, OSError)
    assert message.startswith("i8086:"), message
    assert f"instruction at 0000:{IDIV_AT:04X}" in message, message
    assert "F7 FB F4" in message, message
    assert f"CS:IP at 0000:{LEFT_AT:04X}" in message, message
    assert "integer overflow" in message, message


def test_a_second_fault_reading_the_machine_back_is_said_and_not_raised(
        session, idiv_faults, core, monkeypatch):
    """A fault that wrecked more than one instruction can fault the read-back
    too. That second `OSError` must not replace the `HostFault`, or the caller
    is back to an exception nothing above it expects."""
    session.load(PROBE)
    for _ in range(3):
        assert session.cpu.step()

    def unreadable(handle, address):
        raise OSError("exception: access violation reading 0x0000000000000020")

    monkeypatch.setattr(core, "i8086_read_byte", unreadable)
    with pytest.raises(abi.HostFault) as caught:
        session.cpu.step()
    message = str(caught.value)
    assert "integer overflow" in message, message
    assert "reading the machine back faulted as well" in message, message
    assert "reading 0x0000000000000020" in message, message


def test_a_session_whose_core_faults_on_the_host_stops_and_says_why(
        session, idiv_faults):
    """The three moves complete and count; the IDIV does not."""
    session.load(PROBE)
    result = session.run(100)
    assert (result.steps, result.status) == (3, "faulted")
    assert f"instruction at 0000:{IDIV_AT:04X}" in result.detail, result.detail
    state = session.state()
    assert (state["status"], state["detail"]) == ("faulted", result.detail)
    assert state["steps"] == 3


def test_a_faulted_session_does_not_carry_on_from_where_the_core_left_it(
        session, idiv_faults):
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
    assert session.run(100) == first


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
        live_server, idiv_faults):
    """An answer, not a dropped connection: the run, the state the page
    redraws from, and a step asked for afterwards all come back 200 and say
    faulted, the way an unimplemented opcode comes back."""
    assert call(live_server, "/api/load", {"hex": PROBE.hex()})[0] == 200
    status, run = call(live_server, "/api/run", {"steps": 100})
    assert status == 200
    assert (run["steps"], run["status"]) == (3, "faulted")
    assert f"instruction at 0000:{IDIV_AT:04X}" in run["detail"], run["detail"]

    status, state = call(live_server, "/api/state")
    assert status == 200
    assert (state["status"], state["detail"]) == ("faulted", run["detail"])
    assert state["registers"]["ip"] == LEFT_AT

    status, step = call(live_server, "/api/step", {})
    assert (status, step["steps"], step["status"]) == (200, 0, "faulted")
