# OpenHardware - what an MCP9808 answers on its I2C pins (OH-161 step 5).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""`webui/devices/mcp9808.py` against DS25095A: the address, the pointer, the
two ID registers (slice 1) and the register file with the temperature as an
input (slice 2). Each refusal here names the section that makes it a refusal.

Loops and not `parametrize`: `tools/inventory.py` counts `def test_*` by `ast`.
"""

from __future__ import annotations

import pytest

from core.riscv32.abi import DeviceRefusal
from webui.devices import mcp9808
from webui.devices.mcp9808 import Mcp9808


def part(**kwargs) -> Mcp9808:
    return Mcp9808(**{"straps": 0, "celsius": 25.0, "vdd": 3.3, **kwargs})


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

    for pointer in (0, 9, 0xF, 0x10, 0x86, 0x80, 0xF6):
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
    for vdd in (5.6, 6.0):
        with pytest.raises(DeviceRefusal) as caught:
            part(vdd=vdd)
        assert repr(vdd) in str(caught.value), vdd
        assert "p.3" in str(caught.value) and "p.2" in str(caught.value), vdd
        assert "below the 6.0 V" not in str(caught.value), "false at 6.0 V and above"


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
    assert "RFU" in str(caught.value) and "Register 5-1" in str(caught.value), (
        "back at the power-on pointer, 0000")


def test_pointers_9_to_f_are_reserved_test_and_calibration_registers():
    """Register 5-1 '1xxx = Reserved' and its Note 1."""
    for pointer in range(9, 16):
        device = part()
        device.start(False)
        with pytest.raises(DeviceRefusal) as caught:
            device.write(pointer)
        assert "test and calibration" in str(caught.value), pointer
        assert "no register" not in str(caught.value), pointer


def test_a_read_inside_a_write_transfer_is_refused():
    """Table 3-2: the address byte's R/W bit chose write."""
    device = part()
    assert device.start(False)
    with pytest.raises(DeviceRefusal) as caught:
        device.read()
    assert "write transfer" in str(caught.value)


def test_hold_rereads_the_straps_and_keeps_the_pointer_while_powered():
    device = part(straps=1)
    assert read_register(device, 7) == 0x0400
    device.hold(straps=6, celsius=30.0, vdd=3.3)
    assert device.address == 0x18 | 6
    assert device.start(True)
    assert (device.read(), device.read()) == (0x04, 0x00)


# --- slice 2: the register file and the temperature -------------------------

CONFIG, TUPPER, TLOWER, TCRIT, TA, RESOLUTION = 1, 2, 3, 4, 5, 8


def read_bytes(device: Mcp9808, pointer: int, count: int = 2) -> list[int]:
    """Write the pointer, stop, then read `count` bytes in one transfer."""
    assert device.start(False) and device.write(pointer)
    device.stop()
    assert device.start(True)
    got = [device.read() for _ in range(count)]
    device.stop()
    return got


def write_register(device: Mcp9808, pointer: int, *data: int) -> None:
    """Pointer then the data bytes, one transfer, as Figure 5-4 (p.23) draws."""
    assert device.start(False)
    for byte in (pointer, *data):
        assert device.write(byte)
    device.stop()


def write_word(device: Mcp9808, pointer: int, word: int) -> None:
    write_register(device, pointer, word >> 8, word & 0xFF)


def refused(run, *citations: str) -> str:
    with pytest.raises(DeviceRefusal) as caught:
        run()
    for citation in citations:
        assert citation in str(caught.value), (citation, str(caught.value))
    return str(caught.value)


def test_the_power_on_registers_are_table_5_3s():
    """Table 5-3, p.33: CONFIG, TUPPER, TLOWER, TCRIT 0x0000, resolution 0x03
    (+0.0625 C). The conflict (a): Register 5-4's note says the power-up
    resolution is 0.25 C/bit; Register 5-7 and Table 5-3 say 0x03, and the
    model follows them."""
    assert mcp9808.POWER_ON == {CONFIG: 0x0000, TUPPER: 0x0000, TLOWER: 0x0000,
                                TCRIT: 0x0000, RESOLUTION: 0x03}
    device = part()
    for pointer in (CONFIG, TUPPER, TLOWER, TCRIT):
        assert read_register(device, pointer) == 0, pointer
    assert read_bytes(device, RESOLUTION, 1) == [0x03]


def test_ta_is_the_held_temperature_in_sixteenths_with_the_flags_above():
    """Register 5-4 (p.24), Equation 5-1 (p.25): 13-bit two's complement, bit
    0 = 2^-4 C, flags 15:13 = TA>=TCRIT, TA>TUPPER, TA<TLOWER. With power-on
    limits of 0 C: 25.0 C is 0xC190 = 49552 (Figure 5-5, p.26 draws 25.25 C
    as 0x0194) and -10.5 C is 0x3F58 = 16216."""
    assert mcp9808.ta_word(25.0, 3, 0, 0, 0) == 0xC190 == 49552
    assert mcp9808.ta_word(-10.5, 3, 0, 0, 0) == 0x3F58 == 16216
    assert mcp9808.ta_word(0.0, 3, 0, 0, 0) == 0x8000, "0 C: >= TCRIT 0, not > TUPPER"
    assert mcp9808.ta_word(25.25, 3, 0x0FFC, 0, 0x0FFC) & 0x1FFF == 0x0194
    assert read_register(part(celsius=25.0), TA) == 49552
    assert read_register(part(celsius=-10.5), TA) == 16216


def test_conflict_a_25_0625_c_reads_401_at_the_power_on_resolution():
    """Conflict (a), named: 0.0625 C is one step at Register 5-7's 0x03
    default, so 25.0625 C is 401 sixteenths; at the 0.25 C Register 5-4's
    note claims it would be 400."""
    assert mcp9808.ta_word(25.0625, 3, 0, 0, 0) & 0x1FFF == 401
    assert read_register(part(celsius=25.0625), TA) & 0x1FFF == 401
    assert mcp9808.ta_word(25.0625, 1, 0, 0, 0) & 0x1FFF == 400


def test_each_resolution_rounds_toward_minus_infinity_to_its_step():
    """Register 5-7 (p.29) and Register 5-4 note 2: bits 2:0 may remain clear
    at coarser resolution. Clearing low bits of a two's complement word rounds
    toward minus infinity, which is the model's reading (design item 6)."""
    steps = {0: 8, 1: 4, 2: 2, 3: 1}
    for resolution, step in steps.items():
        for sixteenths in range(-400, 401, 7):
            celsius = sixteenths / 16
            got = mcp9808.ta_word(celsius, resolution, 0x1000, 0x1000, 0x1000) & 0x1FFF
            want = (sixteenths // step * step) & 0x1FFF
            assert got == want, (resolution, celsius, got, want)
    assert mcp9808.ta_word(-10.5625, 0, 0x1000, 0x1000, 0x1000) & 0x1FFF == 0x1F50
    assert mcp9808.ta_word(-0.0625, 3, 0x1000, 0x1000, 0x1000) & 0x1FFF == 0x1FFF
    # A temperature between two sixteenths goes down, not to the nearest: 25.1
    # C is 401.6 sixteenths and -0.01 C is -0.16.
    assert mcp9808.ta_word(25.1, 3, 0x1000, 0x1000, 0x1000) & 0x1FFF == 401
    assert mcp9808.ta_word(-0.01, 3, 0x1000, 0x1000, 0x1000) & 0x1FFF == 0x1FFF
    assert read_register(part(celsius=25.1), TA) & 0x1FFF == 401
    assert read_register(part(celsius=-0.01), TA) & 0x1FFF == 0x1FFF


def test_the_flags_compare_ta_with_each_limit_as_register_5_4_says():
    """Register 5-4 (p.24): bit 15 TA >= TCRIT, bit 14 TA > TUPPER, bit 13
    TA < TLOWER."""
    limit = 0x0190   # +25 C
    def flags(celsius):
        return mcp9808.ta_word(celsius, 3, limit, limit, limit) >> 13
    assert flags(25.0) == 0b100, "equal: >= TCRIT only"
    assert flags(25.0625) == 0b110
    assert flags(24.9375) == 0b001
    assert flags(0.0) == 0b001
    assert flags(-1.0) == 0b001
    assert mcp9808.ta_word(-5.0, 3, 0, 0, 0x1FFC) >> 13 == 0b001, (
        "TCRIT 0x1FFC is -0.25 C: limits compare as signed, so -5 C is below it")


def test_the_limit_registers_store_register_5_3s_eleven_bits():
    """Register 5-3 (p.22): bits 15:13 and 1:0 read 0, bit 12 is the sign,
    11:2 the data. Figure 5-4 (p.23) writes +90 C as 0x05A0."""
    for pointer in (TUPPER, TLOWER, TCRIT):
        device = part()
        write_word(device, pointer, 0x05A0)
        assert read_register(device, pointer) == 0x05A0, pointer
        write_word(device, pointer, 0xFFFF)
        assert read_register(device, pointer) == 0x1FFC, pointer
        write_word(device, pointer, 0x0003)
        assert read_register(device, pointer) == 0, pointer


def test_limits_move_the_flags_a_sketch_reads():
    device = part(celsius=25.0)
    write_word(device, TUPPER, 25 * 16)
    write_word(device, TCRIT, 30 * 16)
    assert read_register(device, TA) == 0x0190, "not > 25, below 30, not < 0"
    write_word(device, TUPPER, 20 * 16)
    assert read_register(device, TA) == 0x4190
    write_word(device, TLOWER, 26 * 16)
    assert read_register(device, TA) == 0x6190


def test_the_resolution_register_is_two_bits_and_sets_ta_s_step():
    """Register 5-7 (p.29): bits 7:2 unimplemented, read 0."""
    device = part(celsius=25.0625)
    assert read_register(device, TA) & 0x1FFF == 401
    write_register(device, RESOLUTION, 0x00)
    assert read_bytes(device, RESOLUTION, 1) == [0x00]
    assert read_register(device, TA) & 0x1FFF == 400
    write_register(device, RESOLUTION, 0xFE)
    assert read_bytes(device, RESOLUTION, 1) == [0x02]
    write_register(device, RESOLUTION, 0x03)
    assert read_register(device, TA) & 0x1FFF == 401


def test_config_keeps_what_register_5_2_lets_it_and_reads_the_rest_as_zero():
    """Register 5-2 (p.18-19): bits 15:11 read 0; Int Clear returns to 0;
    Alert Stat is read-only; THYST, SHDN, the locks, Alert Sel, Pol and Mod
    are stored."""
    device = part()
    for word in (0x0100, 0x0600, 0x0007, 0x07C7):
        write_word(device, CONFIG, 0)
        write_word(device, CONFIG, word)
        assert read_register(device, CONFIG) == word, hex(word)
    device = part()
    write_word(device, CONFIG, 0xF830)
    assert read_register(device, CONFIG) == 0, "unimplemented, Int Clear, Alert Stat"


def test_the_lock_bits_stay_until_power_on_and_hold_back_what_5_1_1_says():
    """Register 5-2: Crit Lock stops TCRIT, Win Lock stops TUPPER and TLOWER,
    either stops THYST, SHDN being set, Alert Pol and Mod, neither bit is
    cleared by a write, and a VDD glitch below VPOR (5.3, p.33) clears it."""
    for lock, writables, stoppeds in ((0x80, (TUPPER, TLOWER), (TCRIT,)),
                                      (0x40, (TCRIT,), (TUPPER, TLOWER))):
        device = part()
        write_word(device, CONFIG, lock)
        for writable in writables:
            write_word(device, writable, 0x0190)
            assert read_register(device, writable) == 0x0190, writable
        for stopped in stoppeds:
            write_word(device, stopped, 0x0190)
            assert read_register(device, stopped) == 0, (stopped, "can not be written")
        write_word(device, CONFIG, 0x0000)
        assert read_register(device, CONFIG) == lock, "cleared only by a reset"
        write_word(device, CONFIG, lock | 0x0600 | 0x0100 | 0x0003)
        assert read_register(device, CONFIG) == lock, (
            "THYST, SHDN, Alert Pol and Alert Mod can not be altered")
        device.hold(straps=0, celsius=25.0, vdd=0.0)
        device.hold(straps=0, celsius=25.0, vdd=3.3)
        assert read_register(device, CONFIG) == 0
        for writable in writables:
            assert read_register(device, writable) == 0, "the limits went with it"
    device = part()
    write_word(device, CONFIG, 0x0100)
    write_word(device, CONFIG, 0x0100 | 0x40)
    write_word(device, CONFIG, 0x0040)
    assert read_register(device, CONFIG) == 0x40, "SHDN can be cleared while locked"


def test_alert_sel_is_held_by_win_lock_alone():
    """Register 5-2 bit 2 (p.19): 'When the Alarm Window Lock bit is set, this
    bit cannot be altered until unlocked (bit 6)'. Crit Lock does not hold it."""
    device = part()
    write_word(device, CONFIG, 0x0080)
    write_word(device, CONFIG, 0x0084)
    assert read_register(device, CONFIG) == 0x0084, "Crit Lock alone: Alert Sel is free"
    write_word(device, CONFIG, 0x0080)
    assert read_register(device, CONFIG) == 0x0080, "and can be cleared"
    device = part()
    write_word(device, CONFIG, 0x0040)
    write_word(device, CONFIG, 0x0044)
    assert read_register(device, CONFIG) == 0x0040, "Win Lock: bit 2 unchanged"
    device = part()
    write_word(device, CONFIG, 0x0004)
    write_word(device, CONFIG, 0x0044)
    assert read_register(device, CONFIG) == 0x0044
    write_word(device, CONFIG, 0x0040)
    assert read_register(device, CONFIG) == 0x0044, "set before the lock, held by it"


def test_shutdown_holds_ta_and_leaving_it_follows_the_temperature_again():
    """5.2.1 (p.30): in shutdown TA holds the previous temperature data."""
    device = part(celsius=25.0)
    write_word(device, CONFIG, 0x0100)
    device.hold(straps=0, celsius=30.0, vdd=3.3)
    assert read_register(device, TA) == 0xC190
    write_word(device, CONFIG, 0x0000)
    assert read_register(device, TA) == 0xC000 | 30 * 16


def test_shutdown_holds_ta_s_data_through_a_resolution_write_and_all_registers_stay_writable():
    """5.2.1: 'In Shutdown mode, all registers can be read or written', and TA
    holds the previous temperature data. A resolution write after SHDN does not
    re-round the held bits: at 25.0625 C TA is 0xC191, and stays so at 0.5 C."""
    device = part(celsius=25.0625)
    assert read_register(device, TA) == 0xC191
    write_word(device, CONFIG, 0x0100)
    write_register(device, RESOLUTION, 0x00)
    assert read_bytes(device, RESOLUTION, 1) == [0x00], "writable in shutdown"
    assert read_register(device, TA) == 0xC191
    device.hold(straps=0, celsius=-10.5, vdd=3.3)
    assert read_register(device, TA) == 0xC191
    # The judgement in `Mcp9808._frozen`'s comment: the flags are recomputed
    # against the limits as they are, the temperature bits are held.
    write_word(device, TUPPER, 26 * 16)
    assert read_register(device, TA) == 0x8191
    write_word(device, CONFIG, 0x0000)
    assert read_register(device, TA) == mcp9808.ta_word(-10.5, 0, 26 * 16, 0, 0)


def test_shutdown_freezes_at_the_resolution_in_force_when_it_is_set():
    """25.3 C is 404.8 sixteenths: 0x190 at the 0.5 C step, 0x194 at the power-on
    0.0625 C. Set SHDN at 0.5 C and then raise the resolution: TA keeps the
    bits it had, and does not look at the finer step the held temperature
    would now allow."""
    device = part(celsius=25.3)
    write_register(device, RESOLUTION, 0x00)
    assert read_register(device, TA) == 0xC190
    write_word(device, CONFIG, 0x0100)
    write_register(device, RESOLUTION, 0x03)
    assert read_register(device, TA) == 0xC190
    write_word(device, CONFIG, 0x0000)
    assert read_register(device, TA) == 0xC194, "and leaving shutdown looks again"


def test_the_power_on_reset_restores_every_register():
    device = part()
    write_word(device, CONFIG, 0x0100)
    write_word(device, TUPPER, 0x0190)
    write_register(device, RESOLUTION, 0x00)
    device.hold(straps=0, celsius=25.0, vdd=0.0)
    device.hold(straps=0, celsius=25.0, vdd=3.3)
    assert [read_register(device, pointer) for pointer in (CONFIG, TUPPER)] == [0, 0]
    assert read_bytes(device, RESOLUTION, 1) == [0x03]
    assert read_register(device, TA) == 0xC190, "and TA follows the temperature again"


def test_a_new_temperature_keeps_the_part_and_its_registers():
    """The bench's drive calls `hold` with a new temperature: the pointer, the
    limits and the resolution are the part's own and survive it."""
    device = part()
    write_word(device, TLOWER, 0x0190)
    write_register(device, RESOLUTION, 0x01)
    write_register(device, TA)
    device.hold(straps=0, celsius=-10.5, vdd=3.3)
    assert device.pointer == TA
    assert read_register(device, TA) == mcp9808.ta_word(-10.5, 1, 0, 0x0190, 0)
    assert read_register(device, TLOWER) == 0x0190


def test_a_temperature_outside_the_specified_range_is_refused_with_the_value():
    """p.4: Specified Temperature Range -40 to +125 C."""
    for celsius in (-40.0, 0.0, 125.0):
        part(celsius=celsius)
    for celsius in (-40.0625, 125.0625, float("nan"), float("inf"), -300.0):
        refused(lambda: part(celsius=celsius), repr(celsius), "p.4")
    device = part()
    refused(lambda: device.hold(straps=0, celsius=130.0, vdd=3.3), "130.0")
    assert device.celsius == 25.0, "a refused hold changes nothing"


def test_a_pointer_only_write_selects_ta_and_a_repeated_read_keeps_it():
    device = part(celsius=25.0)
    write_register(device, TA)
    for _ in range(2):
        assert device.start(True)
        assert (device.read(), device.read()) == (0xC1, 0x90)
        device.stop()


def test_a_third_byte_of_any_register_is_refused_citing_sequential_read():
    """4.1.1 (p.13): 'does not support sequential register read/write'."""
    for pointer in (CONFIG, TUPPER, TLOWER, TCRIT, TA, 6, 7):
        device = part()
        write_register(device, pointer)
        device.start(True)
        device.read()
        device.read()
        refused(device.read, "4.1.1", f"pointer {pointer}")
    device = part()
    write_register(device, RESOLUTION)
    device.start(True)
    device.read()
    refused(device.read, "4.1.1", "Register 5-7")


def test_a_write_that_stops_early_or_carries_extra_bytes_is_refused():
    """Figure 5-4 (p.23) writes the pointer, the MSB and the LSB, and 4.1.1
    (p.13) has no sequential write. Neither an MSB alone nor a third data byte
    is in DS25095A, and a refused write stores nothing."""
    for pointer in (CONFIG, TUPPER, TLOWER, TCRIT):
        device = part()
        device.start(False)
        device.write(pointer)
        device.write(0x01)
        refused(device.stop, "4.1.1", "Figure 5-4", f"pointer {pointer}")
        assert read_register(device, pointer) == 0, pointer

        device = part()
        device.start(False)
        device.write(pointer)
        device.write(0x01)
        device.write(0x90)
        refused(lambda: device.write(0x00), "4.1.1", "0x00")
        assert read_register(device, pointer) == {CONFIG: 0x0180}.get(pointer, 0x0190), (
            "the two bytes it was given, and not the third")
    device = part()
    device.start(False)
    device.write(RESOLUTION)
    device.write(0x01)
    refused(lambda: device.write(0x02), "4.1.1", "Register 5-7")
    device = part()
    device.start(False)
    device.write(TUPPER)
    device.write(0x01)
    refused(lambda: device.start(True), "4.1.1", "Figure 5-4")


def test_a_write_to_ta_or_an_id_is_refused_citing_its_register():
    """Register 5-4 (p.24), 5.1.4 (p.27), 5.1.5 (p.28): read-only."""
    for pointer, citation in ((TA, "Register 5-4"), (6, "5.1.4"), (7, "5.1.5")):
        device = part()
        device.start(False)
        device.write(pointer)
        refused(lambda: device.write(0x12), citation, "0x12")


def test_alert_cnt_is_refused_because_the_alert_pin_is_not_modelled():
    """Register 5-2 bit 3 (p.19): the Alert output control. A write that would
    enable it is refused and stores nothing; one the lock bits stop is not."""
    device = part()
    refused(lambda: write_word(device, CONFIG, 0x0008), "Alert Cnt", "Register 5-2", "0x0008")
    assert read_register(device, CONFIG) == 0
    write_word(device, CONFIG, 0x00C0)
    write_word(device, CONFIG, 0x00C8)
    assert read_register(device, CONFIG) == 0x00C0, "not altered: nothing to refuse"


def test_a_ta_read_with_thyst_set_is_refused_citing_the_hysteresis():
    """5.2.2 (p.30) and Figure 5-10 (p.32): the figure gives TA bits 15:13
    against conditions such as TA < TLOWER - THYST, which disagrees with
    5.1.3's plain comparisons, and needs the temperature's history."""
    device = part()
    write_word(device, CONFIG, 0x0200)
    assert read_register(device, CONFIG) == 0x0200
    write_register(device, TA)
    device.start(True)
    message = refused(device.read, "5.2.2", "THYST", "Figure 5-10", "5.1.3", "history")
    assert "does not say" not in message, "Figure 5-10 does say something"
    write_word(device, CONFIG, 0x0000)
    assert read_register(device, TA) == 0xC190


# --- what the page shows of the part (OH-161 step 5, slice 4c) -----------------


def test_view_is_what_the_bench_shows_of_the_part_and_follows_it():
    """`view()` is the page's read-only look at the part: its address, whether
    it is powered, the temperature the bench holds it at, the pointer, CONFIG,
    the resolution register and the TA word a read would return right now.
    It moves with the part: a pointer write, a resolution write (25.3 C is
    404 sixteenths at 0.0625 C and 400 at 0.5 C) and a new temperature."""
    device = part(straps=5, celsius=25.3)
    assert device.view() == {
        "address": 0x1D, "powered": True, "celsius": 25.3, "pointer": 0,
        "config": 0x0000, "resolution": 3, "ta": 0xC194}, device.view()
    write_register(device, TA)
    write_register(device, RESOLUTION, 0x00)
    write_register(device, TA)
    assert device.view()["pointer"] == TA
    assert (device.view()["resolution"], device.view()["ta"]) == (0, 0xC190), device.view()
    device.hold(straps=5, celsius=-10.5, vdd=3.3)
    assert device.view()["celsius"] == -10.5
    assert device.view()["ta"] == mcp9808.ta_word(-10.5, 0, 0, 0, 0), device.view()


def test_view_changes_nothing_a_transfer_in_progress_needs():
    """A look in the middle of a read must not move the read: the page polls
    many times a second and the sketch's transfer is in flight between two
    of them."""
    device = part()
    write_register(device, TA)
    assert device.start(True)
    msb = device.read()
    assert device.view()["ta"] == 0xC190
    assert (msb, device.read()) == (0xC1, 0x90)
    device.stop()


def test_view_has_no_ta_where_the_part_would_refuse_one_and_says_why():
    """A TA read with THYST set is refused (`_word`), and so there is no TA to
    show: `ta` is None and `why` is the refusal's own sentence, citing the
    section. The rest of the view is still true."""
    device = part()
    write_word(device, CONFIG, 0x0200)
    seen = device.view()
    assert seen["ta"] is None, seen
    assert all(word in seen["why"] for word in ("5.2.2", "THYST", "Figure 5-10")), seen
    assert (seen["config"], seen["pointer"], seen["powered"]) == (0x0200, CONFIG, True), seen
    write_word(device, CONFIG, 0x0000)
    assert device.view()["ta"] == 0xC190 and "why" not in device.view(), device.view()


def test_view_of_an_unpowered_part_says_so_and_reports_no_ta():
    """Below VPOR the part is unpowered and answers nothing (5.3, p.33): it is
    not shown at the temperature the bench would hold it at as if it were
    reading it."""
    device = part(vdd=0.0)
    seen = device.view()
    assert seen["powered"] is False and seen["ta"] is None, seen
    assert "VPOR" in seen["why"] and "2.2" in seen["why"], seen
    device.hold(straps=0, celsius=25.0, vdd=3.3)
    assert device.view()["powered"] is True and device.view()["ta"] == 0xC190
