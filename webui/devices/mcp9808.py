# OpenHardware - what an MCP9808 answers on its I2C pins.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The Microchip MCP9808 temperature sensor, from DS25095A (fetched
2026-10-13, 54 pages), as far as OH-161 step 5's slice 1 needs: its address, its
pointer and its two ID registers. The register file, the temperature and TA
are slice 2's, and a host asking for them is refused by name, not answered
with a plausible zero.

A bare class with no bus in it: `webui/boards/esp32c3.py`'s `serve_i2c` is the
controller that calls `start`, `write`, `read` and `stop`. Nothing here knows
what an ESP32 is, and nothing here raises anything but `DeviceRefusal`, the
one exception `core/riscv32/abi.py` turns into a stopped session.
"""

from __future__ import annotations

from core.riscv32.abi import DeviceRefusal

#: A6..A3 of the address, 0011, below which the three strap pins A2 A1 A0 sit.
#: DS25095A Table 3-2, p.11. The 1001xxx code the same table lists "contact
#: factory" is not modelled.
ADDRESS_CODE = 0b0011 << 3

#: VPOR 2.2 V typical (p.3), and the operating range VDD 2.7 to 5.5 V (p.3).
VPOR_VOLTS, VDD_MIN, VDD_MAX = 2.2, 2.7, 5.5

#: The ID registers, by pointer. 5.1.4, p.27: manufacturer ID 0x0054. 5.1.5,
#: p.28: device ID 0x04 in the high byte, revision 0x00 in the low.
IDS: dict[int, int] = {6: 0x0054, 7: 0x0400}
_ID_SECTION = {6: "5.1.4", 7: "5.1.5"}

#: The pointer out of reset: 0000. Table 5-3 (p.33) has no pointer row;
#: Register 5-1 (p.16) marks every pointer bit W-0 under the legend "-n =
#: Value at POR", and calls 0000 "RFU, Reserved for Future Use". So a read
#: before any pointer write is refused, as the RFU register it is.
POWER_ON_POINTER = 0

#: The registers DS25095A lists that slice 2 builds (CONFIG, TUPPER, TLOWER,
#: TCRIT, TA, and the resolution register at pointer 8, Table 5-3 p.33).
#: Every other pointer value is RFU or reserved (Register 5-1, p.16), and is
#: refused for good.
SLICE_2_POINTERS = frozenset({1, 2, 3, 4, 5, 8})


class Mcp9808:
    """One MCP9808 on a bus. `straps` is A2 A1 A0 as a number, 0 to 7."""

    def __init__(self, *, straps: int, celsius: float, vdd: float) -> None:
        self.straps = 0
        self.celsius = celsius
        self.pointer = POWER_ON_POINTER
        self._powered = False
        self._writing = False
        self._bytes_in = 0
        self._reads = 0
        self.hold(straps=straps, celsius=celsius, vdd=vdd)

    @property
    def address(self) -> int:
        """The seven-bit address: `ADDRESS_CODE | straps` (Table 3-2, p.11)."""
        return ADDRESS_CODE | self.straps

    def hold(self, *, straps: int, celsius: float, vdd: float) -> None:
        """What the bench holds the part at, a whole statement at every drive.

        Refused, with the values: a strap that is not A2 A1 A0 (0 to 7), and
        a VDD from VPOR up to 2.7 V, where DS25095A describes nothing, and
        one above 5.5 V, past the operating range (p.3) and short of the
        6.0 V absolute maximum (p.2), which "functional operation outside the
        operational listings" is not implied by. Below VPOR the part is
        unpowered and its registers return to power-on (5.3, p.33).
        """
        if isinstance(straps, bool) or not isinstance(straps, int) or not 0 <= straps <= 7:
            raise DeviceRefusal(
                f"MCP9808 address straps A2 A1 A0 are 0 to 7 (Table 3-2, p.11), "
                f"got {straps!r}")
        if VPOR_VOLTS <= vdd < VDD_MIN:
            raise DeviceRefusal(
                f"MCP9808 VDD {vdd!r} V is between VPOR ({VPOR_VOLTS} V) and "
                f"the 2.7 V minimum (p.3): DS25095A describes the part in "
                f"neither state, so it is refused rather than guessed")
        if vdd > VDD_MAX:
            raise DeviceRefusal(
                f"MCP9808 VDD {vdd!r} V is above the 5.5 V maximum operating "
                f"voltage (p.3) and below the 6.0 V absolute maximum (p.2): "
                f"the datasheet does not imply operation there, so it is "
                f"refused rather than guessed")
        self.straps = straps
        self.celsius = celsius
        if vdd < VPOR_VOLTS:
            self.pointer = POWER_ON_POINTER
            self._writing = False
        self._powered = vdd >= VDD_MIN

    def start(self, read: bool) -> bool:
        """A START and this part's address byte; True where it acknowledges.
        The controller has already matched the address, so this answers only
        for power."""
        if not self._powered:
            return False
        self._writing = not read
        self._bytes_in = 0
        self._reads = 0
        return True

    def write(self, byte: int) -> bool:
        """One byte from the host after a write address; True for the ACK."""
        if not self._writing:
            raise DeviceRefusal(
                f"MCP9808 was sent byte {byte:#04x} outside a write transfer")
        self._bytes_in += 1
        if self._bytes_in == 1:
            self._set_pointer(byte)
            return True
        raise DeviceRefusal(
            f"MCP9808 write of {byte:#04x} to pointer {self.pointer} "
            f"(byte {self._bytes_in}): the ID registers are read-only "
            f"(section {_ID_SECTION[self.pointer]})")

    def _set_pointer(self, byte: int) -> None:
        if byte & 0xF0:
            raise DeviceRefusal(
                f"MCP9808 pointer {byte:#04x} has bits 7:4 set; they must be "
                f"written 0 (Register 5-1, p.16)")
        if byte in SLICE_2_POINTERS:
            raise DeviceRefusal(
                f"MCP9808 pointer {byte:#04x}: the register file arrives in "
                f"slice 2; slice 1 answers pointers 6 and 7 (5.1.4, 5.1.5)")
        if byte not in IDS:
            raise DeviceRefusal(
                f"MCP9808 pointer {byte:#04x} is {'0000 = RFU' if byte == 0 else 'not a register'} "
                f"(Register 5-1, p.16): the part has no register there")
        self.pointer = byte

    def read(self) -> int:
        """The next byte of the selected register, MSB first."""
        if self._writing:
            raise DeviceRefusal(
                "MCP9808 read inside a write transfer: the host addressed it "
                "for writing (Table 3-2, p.11)")
        if self.pointer in SLICE_2_POINTERS:
            raise DeviceRefusal(
                f"MCP9808 read at pointer {self.pointer}: the register file "
                f"arrives in slice 2; slice 1 answers pointers 6 and 7")
        if self.pointer not in IDS:
            raise DeviceRefusal(
                f"MCP9808 read at pointer {self.pointer}: 0000 = RFU, reserved "
                f"for future use (Register 5-1, p.16); nothing was written to "
                f"select a register since power-on")
        if self._reads == 2:
            raise DeviceRefusal(
                f"MCP9808 third byte read of pointer {self.pointer}: the "
                f"part does not support sequential register reads (4.1.1, "
                f"p.13); each register needs its own transfer")
        word = IDS[self.pointer]
        self._reads += 1
        return (word >> 8) & 0xFF if self._reads == 1 else word & 0xFF

    def stop(self) -> None:
        """A STOP: the transfer ends, the pointer stays (4.1.1, p.13)."""
        self._writing = False
        self._bytes_in = 0
        self._reads = 0
