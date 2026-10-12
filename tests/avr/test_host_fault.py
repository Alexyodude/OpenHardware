# OpenHardware — a host fault in the AVR core is raised as the core's own error.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this is here as well as beside the i8086 (OH-223)
#
# The same shape: when the DLL faults on the host, ctypes on Windows raises
# `OSError` out of the foreign call, and `webui/api.py`'s board run loop
# catches only this core's `AbiError`. So an `OSError` left the run loop, and
# the request with it. As `HostFault` it stops the run the way a memory fault
# does, with a message.
#
# The fault is faked, and only the fault: `avr_step` is wrapped, the real core
# runs every instruction -- which is what records where the step began -- and
# at one word the wrapper then raises the `OSError` ctypes would.

import pathlib

import pytest

from core.avr import abi

LDI_R16_1 = 0xE001
LDI_R17_2 = 0xE012
ADD_R16_R17 = 0x0F01
RJMP_SELF = 0xCFFF
RJMP_PLUS_1 = 0xC001

#: The word the fake faults at, and where running it leaves the PC.
FAULT_AT = 2
LEFT_AT = FAULT_AT + 1

READING = "exception: access violation reading 0x0000000000000010"
WRITING = "exception: access violation writing 0x0000000000000010"

#: The Uno's committed blink, as `test_uno_board.py` runs it.
BLINK = pathlib.Path(__file__).resolve().parent / "blink" / "blink.bin"


def image(*words: int) -> bytes:
    return b"".join(word.to_bytes(2, "little") for word in words)


def fault_on(lib, monkeypatch, fires, text: str) -> None:
    """Wrap `avr_step` so a step for which `fires(pc)` is true raises
    `OSError(text)` after the real core has run it.

    The real functions are held here rather than looked up per call, so a
    test can break another of them without breaking this."""
    real, pc = lib.avr_step, lib.avr_pc

    def step(handle):
        at = pc(handle)
        status = real(handle)
        if fires(at):
            raise OSError(text)
        return status

    monkeypatch.setattr(lib, "avr_step", step)


@pytest.fixture
def faults_at_the_add(cpu, monkeypatch):
    fault_on(cpu._lib, monkeypatch, lambda at: at == FAULT_AT, READING)
    cpu.write_program_block(
        0, image(LDI_R16_1, LDI_R17_2, ADD_R16_R17, RJMP_SELF))


def test_the_core_records_where_each_step_began(cpu):
    """What the binding reads after a fault, read here without one: a jump
    moves the PC, and the record still says where the jump was."""
    cpu.write_program_block(0, image(RJMP_PLUS_1, RJMP_SELF, RJMP_SELF))
    cpu.step()
    assert cpu.pc == 2
    assert cpu._lib.avr_step_entry(cpu._handle) == 0
    cpu.step()
    assert cpu._lib.avr_step_entry(cpu._handle) == 2


def test_a_host_fault_is_raised_as_an_abi_error_naming_the_instruction(
        cpu, faults_at_the_add):
    cpu.step()
    cpu.step()
    with pytest.raises(abi.HostFault) as caught:
        cpu.step()
    fault = caught.value
    assert isinstance(fault, abi.AbiError), (
        "webui/api.py's run loop stops on AbiError and nothing else")
    assert isinstance(fault.__cause__, OSError)
    assert fault.at == FAULT_AT
    assert fault.code == (ADD_R16_R17, RJMP_SELF)
    assert fault.left == LEFT_AT
    message = str(fault)
    assert message.startswith("avr:"), message
    assert READING in message, message
    assert "load the image again" in message, message


def test_what_was_read_back_survives_a_fault_reading_the_rest(
        cpu, faults_at_the_add, monkeypatch):
    """A fault that wrecked more than one instruction can fault the read-back
    too. Each read is its own: the word read before one faults is kept, a PC
    read that faults leaves `left` unknown and says why, and neither second
    `OSError` replaces the `HostFault`: the run loop stops on `AbiError` and
    on nothing else."""
    lib = cpu._lib
    real_read = lib.avr_read_program
    reads = []

    def read_program(handle, address, out):
        reads.append(address)
        if len(reads) == 2:
            raise OSError("exception: access violation reading 0x0000000000000020")
        return real_read(handle, address, out)

    def pc(handle):
        raise OSError("exception: access violation reading 0x0000000000000030")

    cpu.step()
    cpu.step()
    monkeypatch.setattr(lib, "avr_read_program", read_program)
    monkeypatch.setattr(lib, "avr_pc", pc)
    with pytest.raises(abi.HostFault) as caught:
        cpu.step()
    fault = caught.value
    assert (fault.at, fault.code, fault.left) == (FAULT_AT, (ADD_R16_R17,), None)
    message = str(fault)
    assert "reading 0x0000000000000020" in message, message
    assert "reading 0x0000000000000030" in message, message


def test_a_wild_write_says_to_restart_the_process_and_not_to_reload(
        cpu, monkeypatch):
    """A write that went astray in the core may have landed anywhere in this
    process, not only in the machine a reload replaces."""
    fault_on(cpu._lib, monkeypatch, lambda at: at == FAULT_AT, WRITING)
    cpu.write_program_block(
        0, image(LDI_R16_1, LDI_R17_2, ADD_R16_R17, RJMP_SELF))
    cpu.step()
    cpu.step()
    with pytest.raises(abi.HostFault) as caught:
        cpu.step()
    message = str(caught.value)
    assert "restart" in message, message
    assert "load the image again" not in message, message


def test_a_step_after_close_is_refused_and_not_reported_as_a_core_bug(cpu):
    """A closed Cpu has no machine to step. Handing the core a null handle
    faults it, and calling that a bug in core/avr would be a wrong lead."""
    cpu.close()
    with pytest.raises(abi.AbiError) as caught:
        cpu.step()
    assert type(caught.value) is abi.AbiError, repr(caught.value)
    assert "closed" in str(caught.value)


def test_a_board_run_whose_core_faults_on_the_host_stops_and_answers(
        monkeypatch):
    """The claim `HostFault` exists for, through `webui/api.py`'s own run
    loop: the Uno's blink stops at the faulting step, says why, and a second
    run does not carry on from where the core left it."""
    api = pytest.importorskip("webui.api")
    with api.load_firmware("Arduino Uno", BLINK.read_bytes(), base=0) as session:
        calls = []
        fault_on(abi.load(), monkeypatch,
                 lambda at: calls.append(at) or len(calls) == 1000, READING)
        first = session.run(5000)
        assert (first.steps, first.status) == (999, "faulted")
        assert first.detail.startswith("avr: the core faulted"), first.detail
        assert session.run(5000) == api.RunResult(0, "faulted", first.detail)
