# OpenHardware - the one IDIV whose quotient does not fit in the host either.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""IDIV r/m16 of DX:AX = 0x80000000 by 0xFFFF, per ticket OH-222.

The quotient is +2^31. It does not fit in 16 bits, so the part raises a
divide error, as it does for every other quotient out of range. It does not
fit in a host `int32_t` either: a core that divides before it checks the range
computes INT32_MIN / -1, which is undefined behaviour in C++ and, on x64, a
fault in the host's own `idiv`. On Linux that is SIGFPE, which ends the
process that loaded the core: pytest here, or `webui/emulator_server.py`,
where loading a program is running arbitrary 8086 code by design. On Windows
it is STATUS_INTEGER_OVERFLOW (0xC0000095), which ctypes catches around every
foreign call and raises out of `Cpu.step()` as `OSError: exception: integer
overflow`, abandoning the C++ frames mid-instruction.

**So the instruction runs in a child process.** A regression then fails this
one test with the child's exit code and stderr, instead of taking the suite
down with it where the fault is a signal.
"""

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Vector 0 at B000:1234, a stack at 0000:0200, and `F7 FB` -- IDIV BX -- at
#: 0000:0100. Prints what a divide error would have changed, as JSON.
_CHILD = """
import json, sys
sys.path.insert(0, sys.argv[1])
from core.i8086 import abi

with abi.Cpu() as cpu:
    cpu.write_word(0x00000, 0x1234)
    cpu.write_word(0x00002, 0xB000)
    cpu.set_regs(cs=0x0000, ip=0x0100, ss=0x0000, sp=0x0200,
                 ax=0x0000, dx=0x8000, bx=0xFFFF, flags=0)
    cpu.write_block(0x00100, bytes([0xF7, 0xFB]))
    cpu.step()
    regs = cpu.regs
    print(json.dumps({
        "cs": regs.cs, "ip": regs.ip, "ax": regs.ax, "dx": regs.dx, "sp": regs.sp,
        "pushed_ip": cpu.read_word(0x001FA), "pushed_cs": cpu.read_word(0x001FC),
    }))
"""


@pytest.mark.usefixtures("library")
def test_idiv_of_int32_min_by_minus_one_traps_and_the_host_survives():
    child = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", _CHILD, str(REPO)],
        capture_output=True, text=True, timeout=120,
    )
    assert child.returncode == 0, (
        f"IDIV BX with DX:AX = 8000:0000 and BX = FFFF ended its process with "
        f"exit {child.returncode} ({child.returncode & 0xFFFFFFFF:#010x}). Exit 1 "
        f"with 'OSError: exception: integer overflow' is Windows' "
        f"STATUS_INTEGER_OVERFLOW as ctypes reports it, and -8 is SIGFPE: the "
        f"host's own divide error, not the part's.\n"
        f"stdout: {child.stdout!r}\nstderr: {child.stderr[-2000:]}"
    )
    state = json.loads(child.stdout)
    shown = {name: f"{value:04X}" for name, value in state.items()}
    assert (state["cs"], state["ip"]) == (0xB000, 0x1234), f"no divide error was taken: {shown}"
    assert (state["ax"], state["dx"]) == (0x0000, 0x8000), (
        f"AX and DX must be untouched -- the part writes no partial answer: {shown}"
    )
    assert state["sp"] == 0x01FA, f"the trap pushes FLAGS, CS and IP: {shown}"
    assert (state["pushed_cs"], state["pushed_ip"]) == (0x0000, 0x0102), (
        f"the pushed address is the one after the instruction: {shown}"
    )
