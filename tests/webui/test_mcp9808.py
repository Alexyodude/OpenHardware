# OpenHardware - what an MCP9808 answers on its I2C pins, slice 1 (OH-161 step 5).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""`webui/devices/mcp9808.py` against DS25095A, slice 1: the address, the
pointer and the two ID registers. Everything else the part has is slice 2's, and
each refusal here names the section that makes it a refusal.

Loops and not `parametrize`: `tools/inventory.py` counts `def test_*` by `ast`.
"""

from __future__ import annotations

import pytest

from core.riscv32.abi import DeviceRefusal
from webui.devices import mcp9808
from webui.devices.mcp9808 import Mcp9808


def part(**kwargs) -> Mcp9808:
    return Mcp9808(**{"straps": 0, "celsius": 25.0, **kwargs})


def read_register(device: Mcp9808, pointer: int) -> int:
    """The bus a host runs: write the pointer, stop, read two bytes, stop."""
    assert device.start(False) and device.write(pointer)
    device.stop()
    assert device.start(True)
    msb, lsb = device.read(), device.read()
    device.stop()
    return msb << 8 | lsb


def test_the_address_is_the_code_with_the_three_straps_below_it():
    """Table 3-2, p.11: A6..A3 = 0011, then A2 A1 A0."""
    assert mcp9808.ADDRESS_CODE == 0x18
    for straps in range(8):
        assert part(straps=straps).address == 0x18 | straps, straps


def test_a_strap_outside_three_bits_is_refused_with_the_value():
    for straps in (-1, 8, 0x18):
        with pytest.raises(DeviceRefusal) as caught:
            part(straps=straps)
        assert repr(straps) in str(caught.value), straps


def test_the_part_acknowledges_its_own_address_and_no_other():
    device = part(straps=5)
    assert device.start(False) is True
    device.stop()
    assert device.start(True) is True
    device.stop()
    assert mcp9808.ADDRESS_CODE | 5 == device.address


def test_the_manufacturer_and_device_ids_read_as_the_datasheet_gives_them():
    """5.1.4, p.27: 0x0054. 5.1.5, p.28: device ID 0x04, revision 0x00."""
    device = part()
    assert read_register(device, 6) == 0x0054
    assert read_register(device, 7) == 0x0400


def test_the_pointer_is_kept_across_a_repeated_read():
    """4.1.1, p.13: 'The MCP9808 retains the previously selected register.'"""
    device = part()
    assert read_register(device, 6) == 0x0054
    assert device.start(True)
    assert (device.read(), device.read()) == (0x00, 0x54)
    device.stop()


def test_each_thing_slice_one_does_not_model_is_refused_by_name_and_section():
    cases = []

    def another_pointer(pointer):
        def run():
            device = part()
            device.start(False)
            device.write(pointer)
        return run

    for pointer in (0, 1, 2, 3, 4, 5):
        cases.append((another_pointer(pointer), "slice 2"))
    for pointer in (0x10, 0x86, 0x80, 0xF6):
        cases.append((another_pointer(pointer), "Register 5-1"))

    def third_byte():
        device = part()
        read_register(device, 6)
        device.start(True)
        device.read()
        device.read()
        device.read()
    cases.append((third_byte, "4.1.1"))

    def write_to_an_id():
        device = part()
        device.start(False)
        device.write(7)
        device.write(0x12)
    cases.append((write_to_an_id, "5.1.5"))

    def write_to_the_manufacturer_id():
        device = part()
        device.start(False)
        device.write(6)
        device.write(0x12)
    cases.append((write_to_the_manufacturer_id, "5.1.4"))

    for run, citation in cases:
        with pytest.raises(DeviceRefusal) as caught:
            run()
        assert citation in str(caught.value), (citation, str(caught.value))


def test_a_refusal_carries_the_value_that_caused_it():
    device = part()
    device.start(False)
    with pytest.raises(DeviceRefusal) as caught:
        device.write(0x86)
    assert "0x86" in str(caught.value)


def test_vdd_bounds_the_part_answers_within():
    """p.3: VDD 2.7 to 5.5 V; VPOR 2.2 V typical. Between VPOR and 2.7 V the
    part is in no state the datasheet describes, so the hold is refused."""
    assert (mcp9808.VPOR_VOLTS, mcp9808.VDD_MIN, mcp9808.VDD_MAX) == (2.2, 2.7, 5.5)
    for vdd in (2.7, 3.3, 5.5):
        assert part(vdd=vdd).start(False) is True, vdd
    for vdd in (0.0, 1.0, 2.19):
        assert part(vdd=vdd).start(False) is False, vdd
    for vdd in (2.2, 2.5, 2.69):
        with pytest.raises(DeviceRefusal) as caught:
            part(vdd=vdd)
        assert repr(vdd) in str(caught.value), vdd
    assert part(vdd=5.6).start(False) is False


def test_dropping_below_vpor_resets_the_pointer():
    """5.3, p.33: a VDD glitch below VPOR 'resets the registers to the
    power-on default settings', the pointer with them."""
    device = part()
    assert read_register(device, 6) == 0x0054
    device.hold(straps=0, celsius=25.0, vdd=0.0)
    device.hold(straps=0, celsius=25.0, vdd=3.3)
    device.start(True)
    with pytest.raises(DeviceRefusal) as caught:
        device.read()
    assert "slice 2" in str(caught.value), "back at the power-on pointer, TA"


def test_hold_rereads_the_straps_and_keeps_the_pointer_while_powered():
    device = part(straps=1)
    assert read_register(device, 7) == 0x0400
    device.hold(straps=6, celsius=30.0, vdd=3.3)
    assert device.address == 0x18 | 6
    assert device.start(True)
    assert (device.read(), device.read()) == (0x04, 0x00)
