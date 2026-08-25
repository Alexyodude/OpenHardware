# OpenHardware — fixtures for the AVR core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import pytest

#: An ATmega328P: 16,384 words of flash and 0x0900 bytes of data space.
#:
#: The data figure is one span covering three things -- the 32 registers at
#: 0x00, the IO window at 0x20, and 2 KB of SRAM ending at RAMEND 0x08FF. They
#: are contiguous on this part by design, which is why the model sizes one
#: range rather than mapping three.
PROGRAM_WORDS = 16 * 1024
DATA_BYTES = 0x0900


@pytest.fixture
def cpu():
    """One AVR, configured as an ATmega328P.

    Function-scoped rather than session-scoped. The Cortex-M0+ fixture is
    shared because its 13,500-case corpus would otherwise pay to build a core
    per case; nothing here is that large, and a fresh machine per test removes
    the whole class of leak that fixture needed an autouse reset to contain.
    """
    abi = pytest.importorskip("core.avr.abi")
    with abi.Cpu() as instance:
        instance.configure(PROGRAM_WORDS, DATA_BYTES)
        yield instance
