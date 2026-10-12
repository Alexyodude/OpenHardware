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
# The message names where the PC was LEFT, with the words up to it, and not
# where the instruction began: `Cpu._host_fault` says why a board core does
# not read its PC before every step.
#
# The fault is faked, and only the fault: the PC moved past the instruction,
# nothing else written, and the `OSError` ctypes raises for an access
# violation. Every other step is the real core's.

import pytest

from core.avr import abi

LDI_R16_1 = 0xE001
LDI_R17_2 = 0xE012
ADD_R16_R17 = 0x0F01
RJMP_SELF = 0xCFFF

#: The word the fake faults at, and where it leaves the PC.
FAULT_AT = 2
LEFT_AT = FAULT_AT + 1


@pytest.fixture
def faults_at_the_add(cpu, monkeypatch):
    """`avr_step` faulting on the host at word `FAULT_AT`, with the program
    below loaded. The real functions are held here rather than looked up per
    call, so a test can break another of them without breaking the fake."""
    lib = cpu._lib
    real, pc, set_pc = lib.avr_step, lib.avr_pc, lib.avr_set_pc

    def step(handle):
        if pc(handle) != FAULT_AT:
            return real(handle)
        # What a core advancing its PC first and then faulting leaves behind.
        set_pc(handle, LEFT_AT)
        raise OSError("exception: access violation reading 0x0000000000000010")

    monkeypatch.setattr(lib, "avr_step", step)
    words = (LDI_R16_1, LDI_R17_2, ADD_R16_R17, RJMP_SELF)
    cpu.write_program_block(0, b"".join(w.to_bytes(2, "little") for w in words))


def test_a_host_fault_is_raised_as_an_abi_error_naming_where_the_pc_was_left(
        cpu, faults_at_the_add):
    cpu.step()
    cpu.step()
    with pytest.raises(abi.HostFault) as caught:
        cpu.step()
    message = str(caught.value)
    assert isinstance(caught.value, abi.AbiError), (
        "webui/api.py's run loop stops on AbiError and nothing else")
    assert isinstance(caught.value.__cause__, OSError)
    assert message.startswith("avr:"), message
    assert f"PC at word 0x{LEFT_AT:04x}" in message, message
    assert "access violation" in message, message
    assert (f"0x{LDI_R17_2:04x} 0x{ADD_R16_R17:04x} 0x{RJMP_SELF:04x}"
            in message), message
    assert cpu.reg(16) == 1, "the fake wrote back nothing, and neither did this"


def test_a_second_fault_reading_the_machine_back_is_said_and_not_raised(
        cpu, faults_at_the_add, monkeypatch):
    """A fault that wrecked more than one instruction can fault the read-back
    too. That second `OSError` must not replace the `HostFault`: the run loop
    stops on `AbiError` and on nothing else."""
    cpu.step()
    cpu.step()

    def unreadable(handle):
        raise OSError("exception: access violation reading 0x0000000000000020")

    monkeypatch.setattr(cpu._lib, "avr_pc", unreadable)
    with pytest.raises(abi.HostFault) as caught:
        cpu.step()
    message = str(caught.value)
    assert "reading 0x0000000000000010" in message, message
    assert "reading the machine back faulted as well" in message, message
    assert "reading 0x0000000000000020" in message, message
