# OpenHardware — fixtures for the RV32 core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import pathlib

import pytest

from core.riscv32 import abi

from . import lockstep

REPO = pathlib.Path(__file__).resolve().parents[2]

#: The plainest possible board: one flat RAM and nothing else.
#:
#: At rvcpp's testbench base so that a program written for one test can be
#: handed to the lockstep rig unchanged. It is a testbench address rather than
#: any chip's -- an ESP32-C3 has nothing at 0x80000000 -- and it is here rather
#: than in the core because the core knows no addresses at all.
RAM = lockstep.RAM_BASE
RAM_SIZE = lockstep.RAM_SIZE
PC = RAM + lockstep.ENTRY_OFFSET

#: Scratch space for load and store tests, far enough from the code that a
#: runaway program reaches the end of RAM rather than quietly overwriting
#: itself and executing the result.
SCRATCH = RAM + 0x2000


@pytest.fixture(scope="session")
def cpu():
    """One core for the whole session.

    Reused rather than rebuilt per test, because every test starts by
    declaring its own memory and registers anyway -- which is the whole of the
    state this core has.
    """
    with abi.Cpu() as instance:
        yield instance


@pytest.fixture(autouse=True)
def _fresh_board(cpu):
    """Un-install whatever the previous test described.

    The core ships with no memory and no extensions, so every test would
    otherwise inherit the last one's board. Extensions default to an ESP32-C3
    here because that is the part this ticket is for; the tests that care
    about gating set their own and say why.
    """
    cpu.clear_regions()
    cpu.add_region(RAM, RAM_SIZE)
    cpu.set_extensions(abi.ESP32_C3)
    cpu.set_regs([0] * 32, pc=PC)
    yield


@pytest.fixture(scope="session")
def oracle() -> pathlib.Path:
    """The built rvcpp, or skip.

    A skip, never a pass. The same contract the rule checkers keep when they
    cannot find a PICSimLab source tree: a differential test that silently
    became a no-op is worse than one that says it did not run.
    """
    binary = lockstep.executable()
    if binary is None:
        pytest.skip(
            "no rvcpp oracle. Build it:\n"
            "  git clone --depth 1 https://github.com/Wren6991/Hazard3 "
            "third_party/hazard3\n"
            "  python tests/riscv32/oracle/build_rvcpp.py"
        )
    return binary


def load(cpu, words: list[int], at: int = PC) -> None:
    """Put `words` in memory at `at` and point PC there."""
    image = b"".join(int(word & 0xFFFFFFFF).to_bytes(4, "little") for word in words)
    cpu.write_block(at, image)
    cpu.set_regs([0] * 32, pc=at)


def run(cpu, words: list[int], at: int = PC) -> None:
    """Load `words` and execute exactly that many instructions.

    Straight-line programs only, which is every caller. A test with a branch
    steps by hand, because the count is the thing it is checking.
    """
    load(cpu, words, at)
    for _ in words:
        cpu.step()
