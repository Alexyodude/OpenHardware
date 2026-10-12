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

import ctypes

import pytest

from core.cortexm0 import abi as cortexm0
from core.riscv32 import abi as riscv32

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
