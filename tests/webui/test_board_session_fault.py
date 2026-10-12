# OpenHardware - a host fault in a board's core stops the board and is answered.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""A fault in the Cortex-M0+ or RISC-V core's own code, to the page (OH-225).

OH-223 gave the i8086 and AVR bindings a `HostFault` for a fault ctypes
catches on the host, and this is the same for the two other board cores, and
for the board session above all three.

**The fault is faked, and only the fault**, as OH-223's tests fake it: for the
length of a test the core's step is wrapped, the real core runs every step --
which is what records where the step began -- and on one step the wrapper then
raises the `OSError` ctypes would. Everything above the foreign call is the
real code: `Cpu.step`, `BoardSession`, the route table, and a server on a
loopback socket.

On Linux the same fault is a signal, which ctypes does not catch, and the
process ends; OH-223's note records why nothing is done about that here.
"""

from __future__ import annotations

import base64
import ctypes
import json
import pathlib
import re
import shutil
import struct
import subprocess
import threading
import urllib.error
import urllib.request

import pytest

from core.avr import abi as avr
from core.cortexm0 import abi as cortexm0
from core.riscv32 import abi as riscv32
from webui import api, emulator_server
from webui.boards import esp32c3

REPO = pathlib.Path(__file__).resolve().parents[2]

#: The text ctypes gives an access violation, reading and writing.
READING = "exception: access violation reading 0x0000000000000010"
WRITING = "exception: access violation writing 0x0000000000000010"

#: Where each test machine's one region begins.
M0_BASE = 0x20000000
RV_BASE = 0x80000000

#: movs r0, #1; movs r1, #2; adds r0, r0, r1; b .
MOVS_R0_1, MOVS_R1_2, ADDS_R0_R0_R1, B_SELF = 0x2001, 0x2102, 0x1840, 0xE7FE
#: b to the halfword after next, which lands on the second `b .`.
B_PLUS_2 = 0xE000

#: addi x1, x0, 1; addi x2, x0, 2; add x3, x1, x2; jal x0, 0
ADDI_X1_1, ADDI_X2_2, ADD_X3_X1_X2, JAL_SELF = (
    0x00100093, 0x00200113, 0x002081B3, 0x0000006F)
#: jal x0, +8
JAL_PLUS_8 = 0x0080006F

#: The Armv6-M System Control Space, which every Cortex-M0+ has.
SCB_ICSR = 0xE000ED04
SCB_VTOR = 0xE000ED08
ICSR_PENDSTSET = 1 << 26
EXC_SYSTICK = 15


def fault_on(lib, step_name: str, pc_of, monkeypatch, fires, text: str) -> None:
    """Wrap `step_name` so a step for which `fires(pc)` is true raises
    `OSError(text)` after the real core has run it.

    The real functions are held here rather than looked up per call, so a
    test can break another of them without breaking this."""
    real = getattr(lib, step_name)

    def step(handle):
        at = pc_of(handle)
        status = real(handle)
        if fires(at):
            raise OSError(text)
        return status

    monkeypatch.setattr(lib, step_name, step)


def m0_pc(lib):
    get = lib.cortexm0_get_regs

    def pc(handle) -> int:
        regs = cortexm0.Registers()
        get(handle, ctypes.byref(regs))
        return regs.r[15]

    return pc


def rv_pc(lib):
    get = lib.riscv32_get_regs

    def pc(handle) -> int:
        regs = riscv32.Registers()
        get(handle, ctypes.byref(regs))
        return regs.pc

    return pc


# --- the Cortex-M0+ binding ----------------------------------------------------


@pytest.fixture
def m0():
    try:
        cpu = cortexm0.Cpu()
    except cortexm0.AbiError as exc:
        pytest.skip(f"cortexm0 core unavailable: {exc}")
    with cpu:
        cpu.add_region(M0_BASE, 0x4000)
        yield cpu


def m0_program(cpu, *halfwords: int) -> None:
    for index, halfword in enumerate(halfwords):
        cpu.write_halfword(M0_BASE + 2 * index, halfword)
    cpu.set_regs([0] * 13 + [M0_BASE + 0x3000, 0, M0_BASE], apsr=0)


def m0_faults_at_the_adds(cpu, monkeypatch, text: str = READING) -> None:
    fault_on(cpu._lib, "cortexm0_step", m0_pc(cpu._lib), monkeypatch,
             lambda at: at == M0_BASE + 4, text)
    m0_program(cpu, MOVS_R0_1, MOVS_R1_2, ADDS_R0_R0_R1, B_SELF)


def test_the_cortexm0_core_records_where_each_step_began(m0):
    """What the binding reads after a fault, read here without one: a branch
    moves the PC, and the record still says where the branch was."""
    m0_program(m0, B_PLUS_2, B_SELF, B_SELF)
    m0.step()
    assert m0.get_regs().r[15] == M0_BASE + 4
    assert m0._lib.cortexm0_step_entry(m0._handle) == M0_BASE
    m0.step()
    assert m0._lib.cortexm0_step_entry(m0._handle) == M0_BASE + 4


def test_the_cortexm0_record_is_taken_before_an_exception_entry(m0):
    """A step with SysTick due enters the handler instead of executing, and
    the record names the instruction it interrupted, not the handler."""
    handler, resume = M0_BASE + 0x1000, M0_BASE + 0x2000
    m0.write_word(SCB_VTOR, M0_BASE)
    m0.write_word(M0_BASE + 4 * EXC_SYSTICK, handler | 1)
    m0.write_halfword(handler, B_SELF)
    m0.write_halfword(resume, B_SELF)
    m0.set_regs([0] * 13 + [M0_BASE + 0x3000, 0, resume], apsr=0)
    m0.write_word(SCB_ICSR, ICSR_PENDSTSET)
    m0.step()
    assert m0.get_regs().r[15] == handler, "no exception was entered"
    assert m0._lib.cortexm0_step_entry(m0._handle) == resume


def test_a_cortexm0_host_fault_is_raised_as_an_abi_error_naming_the_step(
        m0, monkeypatch):
    m0_faults_at_the_adds(m0, monkeypatch)
    m0.step()
    m0.step()
    with pytest.raises(cortexm0.HostFault) as caught:
        m0.step()
    fault = caught.value
    assert isinstance(fault, cortexm0.AbiError), (
        "webui/api.py's run loop stops on AbiError and nothing else")
    assert isinstance(fault.__cause__, OSError)
    assert fault.at == M0_BASE + 4
    assert fault.code == (ADDS_R0_R0_R1, B_SELF)
    assert fault.left == M0_BASE + 6
    message = str(fault)
    assert message.startswith("cortexm0:"), message
    assert READING in message, message
    assert f"0x{M0_BASE + 4:08x}" in message, message
    assert "load the image again" in message, message


def test_what_the_cortexm0_binding_read_back_survives_a_fault_reading_the_rest(
        m0, monkeypatch):
    """Each read back is its own: the halfword read before one faults is
    kept, a register read that faults leaves `left` unknown and says why, and
    neither second `OSError` replaces the `HostFault`."""
    lib = m0._lib
    m0_faults_at_the_adds(m0, monkeypatch)
    real_read = lib.cortexm0_read_block
    reads = []

    def read_block(handle, address, out, length):
        reads.append(address)
        if len(reads) == 2:
            raise OSError("exception: access violation reading 0x0000000000000020")
        return real_read(handle, address, out, length)

    def get_regs(handle, out):
        raise OSError("exception: access violation reading 0x0000000000000030")

    m0.step()
    m0.step()
    monkeypatch.setattr(lib, "cortexm0_read_block", read_block)
    monkeypatch.setattr(lib, "cortexm0_get_regs", get_regs)
    with pytest.raises(cortexm0.HostFault) as caught:
        m0.step()
    fault = caught.value
    assert (fault.at, fault.code, fault.left) == (
        M0_BASE + 4, (ADDS_R0_R0_R1,), None)
    message = str(fault)
    assert "reading 0x0000000000000020" in message, message
    assert "reading 0x0000000000000030" in message, message


def test_a_cortexm0_wild_write_says_to_restart_the_process(m0, monkeypatch):
    """A write that went astray in the core may have landed anywhere in this
    process, not only in the machine a reload replaces."""
    m0_faults_at_the_adds(m0, monkeypatch, WRITING)
    m0.step()
    m0.step()
    with pytest.raises(cortexm0.HostFault) as caught:
        m0.step()
    message = str(caught.value)
    assert "restart" in message, message
    assert "load the image again" not in message, message


def test_a_cortexm0_step_after_close_is_refused_and_not_called_a_core_bug(m0):
    m0.close()
    with pytest.raises(cortexm0.AbiError) as caught:
        m0.step()
    assert type(caught.value) is cortexm0.AbiError, repr(caught.value)
    assert "closed" in str(caught.value)


# --- the RISC-V binding --------------------------------------------------------


@pytest.fixture
def rv():
    try:
        cpu = riscv32.Cpu()
    except riscv32.AbiError as exc:
        pytest.skip(f"riscv32 core unavailable: {exc}")
    with cpu:
        cpu.add_region(RV_BASE, 0x1000)
        yield cpu


def rv_program(cpu, *words: int) -> None:
    for index, word in enumerate(words):
        cpu.write_word(RV_BASE + 4 * index, word)
    cpu.set_regs([0] * 32, pc=RV_BASE)


def rv_faults_at_the_add(cpu, monkeypatch, text: str = READING) -> None:
    fault_on(cpu._lib, "riscv32_step", rv_pc(cpu._lib), monkeypatch,
             lambda at: at == RV_BASE + 8, text)
    rv_program(cpu, ADDI_X1_1, ADDI_X2_2, ADD_X3_X1_X2, JAL_SELF)


def test_the_riscv32_core_records_where_each_step_began(rv):
    """A jump moves the PC, and the record still says where the jump was."""
    rv_program(rv, JAL_PLUS_8, JAL_SELF, JAL_SELF)
    rv.step()
    assert rv.pc == RV_BASE + 8
    assert rv._lib.riscv32_step_entry(rv._handle) == RV_BASE
    rv.step()
    assert rv._lib.riscv32_step_entry(rv._handle) == RV_BASE + 8


def test_a_riscv32_host_fault_is_raised_as_an_abi_error_naming_the_step(
        rv, monkeypatch):
    """The halfwords are the instruction's two parcels, low first, as the
    core fetches them: 0x002081b3 is `add x3, x1, x2`."""
    rv_faults_at_the_add(rv, monkeypatch)
    rv.step()
    rv.step()
    with pytest.raises(riscv32.HostFault) as caught:
        rv.step()
    fault = caught.value
    assert isinstance(fault, riscv32.AbiError)
    assert isinstance(fault.__cause__, OSError)
    assert fault.at == RV_BASE + 8
    assert fault.code == (ADD_X3_X1_X2 & 0xFFFF, ADD_X3_X1_X2 >> 16)
    assert fault.left == RV_BASE + 12
    message = str(fault)
    assert message.startswith("riscv32:"), message
    assert READING in message, message
    assert f"0x{RV_BASE + 8:08x}" in message, message
    assert "load the image again" in message, message


def test_what_the_riscv32_binding_read_back_survives_a_fault_reading_the_rest(
        rv, monkeypatch):
    lib = rv._lib
    rv_faults_at_the_add(rv, monkeypatch)
    real_read = lib.riscv32_read_block
    reads = []

    def read_block(handle, address, out, length):
        reads.append(address)
        if len(reads) == 2:
            raise OSError("exception: access violation reading 0x0000000000000020")
        return real_read(handle, address, out, length)

    def get_regs(handle, out):
        raise OSError("exception: access violation reading 0x0000000000000030")

    rv.step()
    rv.step()
    monkeypatch.setattr(lib, "riscv32_read_block", read_block)
    monkeypatch.setattr(lib, "riscv32_get_regs", get_regs)
    with pytest.raises(riscv32.HostFault) as caught:
        rv.step()
    fault = caught.value
    assert (fault.at, fault.code, fault.left) == (
        RV_BASE + 8, (ADD_X3_X1_X2 & 0xFFFF,), None)
    message = str(fault)
    assert "reading 0x0000000000000020" in message, message
    assert "reading 0x0000000000000030" in message, message


def test_a_riscv32_wild_write_says_to_restart_the_process(rv, monkeypatch):
    rv_faults_at_the_add(rv, monkeypatch, WRITING)
    rv.step()
    rv.step()
    with pytest.raises(riscv32.HostFault) as caught:
        rv.step()
    message = str(caught.value)
    assert "restart" in message, message
    assert "load the image again" not in message, message


def test_a_riscv32_step_after_close_is_refused_and_not_called_a_core_bug(rv):
    rv.close()
    with pytest.raises(riscv32.AbiError) as caught:
        rv.step()
    assert type(caught.value) is riscv32.AbiError, repr(caught.value)
    assert "closed" in str(caught.value)


# --- the board session -----------------------------------------------------------
#
# One board on each core, each running its own committed blink: the XIAO
# RP2040's on the Cortex-M0+ and the XIAO ESP32-C3's on the RISC-V.

#: (board, its blink, where that raw .bin loads, the core's binding, its step).
BOARDS = (
    ("XIAO-RP2040-DIP", REPO / "tests" / "cortexm0" / "blink" / "blink.bin",
     0x10000100, cortexm0, "cortexm0_step"),
    ("XIAO-ESP32-C3-DIP", REPO / "tests" / "riscv32" / "c3blink" / "blink.bin",
     esp32c3.IROM, riscv32, "riscv32_step"),
)

#: The RP2040 board, and an image whose reset vector points into its boot ROM
#: stub, which is mapped and not executable: the first step is a MemoryFault.
#: `tests/webui/test_board_run.py` runs the same two words.
M0_BOARD, M0_LOAD = BOARDS[0][0], BOARDS[0][2]
INTO_THE_ROM = struct.pack("<II", 0x20042000, 0x00000001)
#: And one whose reset vector lands in erased flash, where 0xFFFF is no
#: encoding: the first step is Unimplemented.
INTO_ERASED_FLASH = struct.pack("<II", 0x20042000, M0_LOAD + 0x700 + 1)


def image_of(path: pathlib.Path) -> bytes:
    if not path.is_file():
        pytest.skip(f"{path} is missing")
    return path.read_bytes()


def library(core):
    try:
        return core.load()
    except core.AbiError as exc:
        pytest.skip(f"{core.__name__} unavailable: {exc}")


def fault_on_call(core, step: str, monkeypatch, nth: int,
                  text: str = READING) -> None:
    """Make the core's `nth` step from now fault on the host, wherever it is."""
    calls = []
    fault_on(library(core), step, lambda handle: None, monkeypatch,
             lambda at: calls.append(at) or len(calls) == nth, text)


def name_of(step: str) -> str:
    """`cortexm0_step` -> `cortexm0`, the word a `HostFault` begins with."""
    return step.split("_")[0]


def test_a_board_run_whose_core_faults_on_the_host_stops_and_answers(
        monkeypatch):
    """`BoardSession.run` stops on the core's `AbiError`, so a `HostFault`
    stops a run on either core with the core's sentence as the detail, and
    a second run does not carry on from where the core left the machine."""
    for board, path, base, core, step in BOARDS:
        library(core)
        with api.load_firmware(board, image_of(path), base=base) as session:
            fault_on_call(core, step, monkeypatch, 1000)
            first = session.run(5000)
            assert first.steps == 999, (board, first)
            assert first.status != "running", (board, first)
            assert first.detail.startswith(
                f"{name_of(step)}: the core faulted"), first.detail
            assert session.run(5000) == api.RunResult(
                0, first.status, first.detail), board
            assert session.retired == 999, (board, session.retired)


def test_a_board_that_stopped_on_a_host_fault_steps_no_further(monkeypatch):
    """What OH-223's review saw on the AVR: after a run stopped on a host
    fault, a step stepped the half-executed machine on. A stop is terminal for
    a step as it is for a run. A caller stepping one at a time is told so,
    with what stopped it, and the machine does not move."""
    for board, path, base, core, step in BOARDS:
        library(core)
        with api.load_firmware(board, image_of(path), base=base) as session:
            fault_on_call(core, step, monkeypatch, 10)
            first = session.run(100)
            assert first.steps == 9, (board, first)
            pc = session.state()["pc"]
            with pytest.raises(core.AbiError) as caught:
                session.step()
            assert first.detail in str(caught.value), str(caught.value)
            assert session.state()["pc"] == pc, board
            assert session.retired == 9, (board, session.retired)
            assert (session.status, session.detail) == (
                first.status, first.detail), board


def test_a_step_that_faults_is_recorded_before_it_is_raised(monkeypatch):
    """`step` still raises the core's own exception, and the session says so
    afterwards, as it does after a run: a run that follows takes nothing."""
    for board, path, base, core, step in BOARDS:
        library(core)
        with api.load_firmware(board, image_of(path), base=base) as session:
            fault_on_call(core, step, monkeypatch, 3)
            session.step(2)
            with pytest.raises(core.HostFault) as caught:
                session.step()
            assert session.status != "running", board
            assert session.detail == str(caught.value), board
            assert session.retired == 2, (board, session.retired)
            assert session.run(100) == api.RunResult(
                0, session.status, session.detail), board


def test_a_step_the_firmware_stops_is_recorded_as_a_run_records_it():
    """Not only a host fault: a firmware's own fault through `step` left the
    session saying "running" as well."""
    library(cortexm0)
    with api.load_firmware(M0_BOARD, INTO_THE_ROM, base=M0_LOAD) as session:
        with pytest.raises(cortexm0.MemoryFault) as caught:
            session.step()
        assert (session.status, session.detail) == ("stopped", str(caught.value))
        assert session.run(10) == api.RunResult(0, "stopped", str(caught.value))


# --- the server -------------------------------------------------------------------


@pytest.fixture
def live_server():
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
    """The HTTP status and the JSON body, whatever the status. A dropped
    connection raises, which is the failure these tests exist to catch."""
    request = urllib.request.Request(
        base + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def load_over_http(server: str, board: str, data: bytes, base: int) -> None:
    status, report = call(server, "/api/board/load", {
        "board": board, "image": base64.b64encode(data).decode(),
        "base": hex(base)})
    assert status == 200, (board, status, report)


def test_a_step_route_whose_core_faults_on_the_host_answers(
        live_server, monkeypatch):
    """POST /api/board/step whose step faulted got no reply at all
    (RemoteDisconnected). It answers 200 with the state, as a run that
    faulted answers 200, and the state says the board stopped and why."""
    for board, path, base, core, step in BOARDS:
        library(core)
        load_over_http(live_server, board, image_of(path), base)
        fault_on_call(core, step, monkeypatch, 3)
        status, stepped = call(live_server, "/api/board/step", {"count": 2})
        assert (status, stepped["status"]) == (200, "running"), (board, stepped)
        status, faulted = call(live_server, "/api/board/step", {})
        assert status == 200, (board, status, faulted)
        assert faulted["status"] != "running", (board, faulted["status"])
        assert faulted["detail"].startswith(
            f"{name_of(step)}: the core faulted"), faulted["detail"]


def test_a_step_route_the_firmware_stops_answers(live_server):
    """`Unimplemented` and `MemoryFault` reached that route the same way and
    were dropped the same way. Each answers as a run does: stopped, with the
    core's sentence naming the address."""
    library(cortexm0)
    for image, expected in ((INTO_THE_ROM, "not executable"),
                            (INTO_ERASED_FLASH, "no implementation")):
        load_over_http(live_server, M0_BOARD, image, M0_LOAD)
        status, stepped = call(live_server, "/api/board/step", {})
        assert status == 200, (expected, status, stepped)
        assert stepped["status"] == "stopped", (expected, stepped["status"])
        assert expected in stepped["detail"], stepped["detail"]
        assert "0x" in stepped["detail"], stepped["detail"]


def test_after_a_run_faults_on_the_host_the_step_route_moves_nothing(
        live_server, monkeypatch):
    """Probed by OH-223 on the AVR: after a run stopped on a host fault, POST
    /api/board/step answered 200 and stepped the half-executed machine on
    (its pc moved to 22). It answers with the same stop, and nothing moves."""
    for board, path, base, core, step in BOARDS:
        library(core)
        load_over_http(live_server, board, image_of(path), base)
        fault_on_call(core, step, monkeypatch, 1000)
        status, run = call(live_server, "/api/board/run", {"steps": 5000})
        assert (status, run["steps"]) == (200, 999), (board, status, run)
        status, before = call(live_server, "/api/board/state")
        assert status == 200, (board, before)
        status, stepped = call(live_server, "/api/board/step", {})
        assert status == 200, (board, status, stepped)
        assert (stepped["status"], stepped["detail"]) == (
            run["status"], run["detail"]), board
        assert stepped["pc"] == before["pc"], board
        assert stepped["registers"] == before["registers"], board


# --- "faulted", not "stopped" ---------------------------------------------------
#
# Every board core, the Uno's AVR included: the word is the session's, and a
# core that answered "stopped" for its own bug would be the one place the page
# blamed the firmware for the simulator.

#: The three board cores, each on a board running its own committed blink.
EVERY_CORE = BOARDS + (
    ("Arduino Uno", REPO / "tests" / "avr" / "blink" / "blink.bin", 0, avr,
     "avr_step"),
)


def test_a_host_fault_is_faulted_and_a_firmware_fault_is_stopped(monkeypatch):
    """Two different things to say. "stopped" is the core refusing the
    firmware -- an encoding it lacks, an access off the board's map -- and
    is a fact about the firmware; "faulted" is the core itself broken, a bug
    in the simulator, the word the 8086 debugger has used since OH-223."""
    for board, path, base, core, step in EVERY_CORE:
        library(core)
        with api.load_firmware(board, image_of(path), base=base) as session:
            fault_on_call(core, step, monkeypatch, 1000)
            run = session.run(5000)
            assert (run.steps, run.status) == (999, "faulted"), (board, run)
            assert session.state()["status"] == "faulted", board
        with api.load_firmware(board, image_of(path), base=base) as session:
            fault_on_call(core, step, monkeypatch, 3)
            session.step(2)
            with pytest.raises(core.HostFault):
                session.step()
            assert session.status == "faulted", board

    library(cortexm0)
    with api.load_firmware(M0_BOARD, INTO_THE_ROM, base=M0_LOAD) as session:
        assert session.run(10).status == "stopped"


def test_the_server_says_faulted_for_a_host_fault(live_server, monkeypatch):
    """/api/board/run, /api/board/state and /api/board/step all carry the
    word, so a page can say the simulator is at fault."""
    for board, path, base, core, step in EVERY_CORE:
        library(core)
        load_over_http(live_server, board, image_of(path), base)
        fault_on_call(core, step, monkeypatch, 1000)
        status, run = call(live_server, "/api/board/run", {"steps": 5000})
        assert (status, run["status"]) == (200, "faulted"), (board, run)
        status, state = call(live_server, "/api/board/state")
        assert (status, state["status"]) == (200, "faulted"), board
        status, stepped = call(live_server, "/api/board/step", {})
        assert (status, stepped["status"]) == (200, "faulted"), board


# --- the page -----------------------------------------------------------------------
#
# `webui/static/emulator.js` showed why a board stopped only when its status
# was "stopped", so a "faulted" board stopped with no reason on the page; and
# its Step button showed neither. The run line is a function node can call;
# the clock's tick and the Step button are wiring inside closures, which node
# cannot reach without a DOM, so those are read out of the source the way
# `tests/webui/test_clock.py` reads the clock's wiring.

EMULATOR_JS = REPO / "webui" / "static" / "emulator.js"


def page_source() -> str:
    """emulator.js without its comment lines, which mention statuses too."""
    return "\n".join(
        line for line in EMULATOR_JS.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith(("//", "/*", "*")))


def page_functions() -> str:
    """Every top-level function declaration in emulator.js, and nothing that
    runs at load: each from its `function` line to the first `}` at column 0.
    A declaration this cuts wrongly is a SyntaxError under node, not a pass."""
    kept, inside = [], False
    for line in EMULATOR_JS.read_text(encoding="utf-8").splitlines():
        if re.match(r"(async )?function \w+\(", line):
            inside = True
        if inside:
            kept.append(line)
            if line == "}":
                inside = False
    assert kept, "no top-level functions found in emulator.js"
    return "\n".join(kept)


def run_line(tmp_path: pathlib.Path, report: dict[str, object], board: str,
             where: str) -> str:
    """`runLine(report)` from the page, under node, with the two things it
    reads from the page -- the loaded board and `#where` -- stubbed. From a
    file, because the page's functions are longer than a Windows command
    line."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; runLine is the page's and runs under node")
    script = tmp_path / "run_line.js"
    script.write_text(
        f"const $ = (id) => ({{ textContent: {json.dumps(where)} }});\n"
        f"let boardImage = {{ board: {json.dumps(board)} }};\n"
        f"{page_functions()}\n"
        f"process.stdout.write(JSON.stringify(runLine({json.dumps(report)})));\n",
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_run_line_says_why_for_any_status_that_is_not_running(tmp_path):
    """"faulted" is said with its reason, as "stopped" always was; a board
    still running gets no reason."""
    detail = "cortexm0: the core faulted on the host (exception: ...)"
    for status in ("stopped", "faulted"):
        line = run_line(tmp_path, {"steps": 999, "rate": None, "status": status,
                                   "detail": detail}, "XIAO-RP2040-DIP", "10000138")
        assert f"{status}: {detail}" in line, (status, line)
        assert line.startswith("XIAO-RP2040-DIP: 999 instructions"), line
        assert line.endswith("pc 0x10000138"), line
    line = run_line(tmp_path, {"steps": 5000, "rate": None, "status": "running",
                               "detail": ""}, "XIAO-RP2040-DIP", "10000140")
    assert line == "XIAO-RP2040-DIP: 5,000 instructions. pc 0x10000140", line


def test_the_clock_and_the_step_button_show_why_for_any_status():
    """The clock's tick put the detail under the run line only for
    "stopped"; the Step button redrew the panes and said nothing, though
    its reply carries status and detail (OH-225)."""
    code = page_source()
    assert 'status === "stopped"' not in code, (
        "a reason is still shown for one status only, so a faulted board "
        "stops without one")
    tick = code.split("onTick: async (report) => {", 1)
    assert len(tick) == 2, "the run clock has no onTick to read"
    assert "report.detail" in tick[1].split("},", 1)[0], (
        "the clock's tick no longer shows the core's reason")
    wiring = code.split('$("board-step").addEventListener("click"', 1)
    assert len(wiring) == 2, "the Step button has no click listener"
    # To the listener's own close, at its indent: `api(..., {});` inside it
    # ends in the same three characters.
    listener = wiring[1].split("\n  });", 1)[0]
    assert "boardSays(" in listener and ".detail" in listener, (
        "the Step button shows neither the status nor the reason a step "
        "stopped the board")
