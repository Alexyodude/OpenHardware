# OpenHardware - what an MCP9808 answers on its I2C pins.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The Microchip MCP9808 temperature sensor, from DS25095A (fetched
2026-10-13, 54 pages): its address, its pointer, its register file (CONFIG,
TUPPER, TLOWER, TCRIT, TA and the resolution register), its two ID registers,
and the temperature the bench holds it at. What DS25095A does not describe --
a write that stops early, a third byte read, the Alert output, THYST on a TA
read -- is refused by name and section, not answered with a plausible value.

A bare class with no bus in it: `webui/boards/esp32c3.py`'s `serve_i2c` is the
controller that calls `start`, `write`, `read` and `stop`. Nothing here knows
what an ESP32 is, and nothing here raises anything but `DeviceRefusal`, the
one exception `core/riscv32/abi.py` turns into a stopped session.

**Two places DS25095A disagrees with itself**, carried here as citations.
(a) Register 5-4's note 2 says the power-up resolution is 0.25 C/bit; Register
5-7 (p.29) and Table 5-3 (p.33) give 0x03, 0.0625 C, and 5.1.6 and 5.2.4 agree
with them, so the model follows them and
`test_conflict_a_25_0625_c_reads_401_at_the_power_on_resolution` names it.
(b) 5.1.6 (p.29) says the resolution "is also reflected in the Capability
register (see Register 5-2)", and this part has no Capability register:
Register 5-2 is CONFIG and Register 5-1 lists no such pointer.

**tCONV is not modelled** (p.3, Table 5-2 p.31): TA is the held temperature at
the moment it is read, where silicon would show the last conversion.
"""

from __future__ import annotations

import math

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

CONFIG, TUPPER, TLOWER, TCRIT, TA, RESOLUTION = 1, 2, 3, 4, 5, 8

#: The writable registers' power-on data. Table 5-3, p.33: CONFIG, TUPPER,
#: TLOWER and TCRIT 0x0000; resolution 0x03 (+0.0625 C, Register 5-7 p.29).
#: TA has no stored data; it is the held temperature.
POWER_ON: dict[int, int] = {CONFIG: 0x0000, TUPPER: 0x0000, TLOWER: 0x0000,
                            TCRIT: 0x0000, RESOLUTION: 0x03}

#: Each register's width in bytes. Register 5-1 (p.16) lists them; the 16-bit
#: ones are Table 5-1's MSB and LSB rows (p.17) and the resolution register is
#: one 8-bit row (Register 5-7, bit 7 to bit 0).
WIDTH: dict[int, int] = {CONFIG: 2, TUPPER: 2, TLOWER: 2, TCRIT: 2, TA: 2,
                         6: 2, 7: 2, RESOLUTION: 1}

#: Where each register is described, for the refusals that name it.
_WHERE = {CONFIG: "CONFIG, Register 5-2, p.18", TUPPER: "TUPPER, Register 5-3, p.22",
          TLOWER: "TLOWER, Register 5-3, p.22", TCRIT: "TCRIT, Register 5-3, p.22",
          TA: "TA, Register 5-4, p.24", 6: "manufacturer ID, 5.1.4, p.27",
          7: "device ID, 5.1.5, p.28", RESOLUTION: "resolution, Register 5-7, p.29"}

#: The registers a host may not write: TA is "read-only" (5.1.3, p.24, "16-bit
#: read-only Ambient Temperature register"), and the IDs are Register 5-5's and
#: 5-6's "READ-ONLY" (p.27, p.28).
_READ_ONLY = {TA: "5.1.3 and Register 5-4, p.24", 6: "5.1.4, Register 5-5, p.27",
              7: "5.1.5, Register 5-6, p.28"}

#: Register 5-2 (p.18-19) bits the host can hold: THYST 10:9, SHDN 8, Crit
#: Lock 7, Win Lock 6, Alert Cnt 3, Alert Sel 2, Alert Pol 1, Alert Mod 0.
#: Bits 15:11 are unimplemented, Int Clear (5) "returns to 0" and Alert Stat
#: (4) is R-0, so none of those four is stored.
CONFIG_STORED = 0x07CF
_THYST, _SHDN, _CRIT_LOCK, _WIN_LOCK = 0x0600, 0x0100, 0x0080, 0x0040
_ALERT_CNT, _ALERT_SEL, _ALERT_POL_MOD = 0x0008, 0x0004, 0x0003

#: Register 5-3 (p.22): bits 12 (sign) to 2 hold data, bits 15:13 and 1:0 are
#: unimplemented and read 0. Register 5-7 (p.29): bits 1:0, 7:2 read 0.
LIMIT_MASK, RESOLUTION_MASK = 0x1FFC, 0x03

#: The temperature range the part is specified over, p.4 ("Specified
#: Temperature Range", -40 to +125 C).
CELSIUS_MIN, CELSIUS_MAX = -40.0, 125.0

#: The pointer out of reset: 0000. Table 5-3 (p.33) has no pointer row;
#: Register 5-1 (p.16) marks every pointer bit W-0 under the legend "-n =
#: Value at POR", and calls 0000 "RFU, Reserved for Future Use". So a read
#: before any pointer write is refused, as the RFU register it is.
POWER_ON_POINTER = 0

#: Every other pointer value than WIDTH's keys is RFU or reserved (Register
#: 5-1, p.16), and is refused for good.


def _signed(word: int) -> int:
    """The 13-bit two's complement a TA or limit word holds, in sixteenths of
    a degree (bit 0 = 2^-4 C, bit 12 the sign: Register 5-4 p.24)."""
    word &= 0x1FFF
    return word - 0x2000 if word & 0x1000 else word


def ta_word(celsius: float, resolution: int, tupper: int, tlower: int,
            tcrit: int) -> int:
    """What the TA register reads for `celsius`: the 13-bit temperature in
    bits 12:0 and, in 15:13, TA >= TCRIT, TA > TUPPER and TA < TLOWER
    (Register 5-4, p.24; the limits are Register 5-3's words).

    `resolution` is Register 5-7's two bits. The temperature is rounded
    **toward minus infinity** to the step they choose -- 0.5, 0.25, 0.125 or
    0.0625 C, which is clearing bits 2:0 of the two's complement word, the
    reading of Register 5-4 note 2 ("bits 2, 1 and 0 may remain clear") this
    model takes (design item 6; DS25095A does not say which way it rounds).
    The flags compare the temperature the register shows with the limits.
    """
    if not isinstance(resolution, int) or not 0 <= resolution <= 3:
        raise ValueError(f"MCP9808 resolution bits are 0 to 3 (Register 5-7), got {resolution!r}")
    step = 1 << (3 - resolution)
    shown = math.floor(celsius * 16) // step * step
    flags = (shown >= _signed(tcrit)) << 15 | (shown > _signed(tupper)) << 14 \
        | (shown < _signed(tlower)) << 13
    return flags | shown & 0x1FFF


class Mcp9808:
    """One MCP9808 on a bus. `straps` is A2 A1 A0 as a number, 0 to 7."""

    def __init__(self, *, straps: int, celsius: float, vdd: float) -> None:
        self.straps = 0
        self.celsius = celsius
        self.pointer = POWER_ON_POINTER
        self.registers = dict(POWER_ON)
        #: The temperature TA holds while CONFIG's SHDN is set (5.2.1, p.30:
        #: "TA holds the previous temperature data"), None when it follows
        #: `celsius`.
        self._frozen: float | None = None
        self._powered = False
        self._writing = False
        self._bytes_in = 0
        self._pending: list[int] = []
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
        one above 5.5 V, past the operating range (p.3); the absolute maximum
        is 6.0 V (p.2) and "functional operation of the device at those or any
        other conditions above those indicated in the operational listings
        ... is not implied". Below VPOR the part is
        unpowered and its registers return to power-on (5.3, p.33).

        `celsius` is the temperature the bench holds the part at, and a new
        one at a later drive changes what TA reads and nothing else: the
        pointer, the limits, CONFIG and the resolution are the part's own.
        Refused, with the value, outside the specified -40 to +125 C (p.4),
        which a NaN is.
        """
        if not CELSIUS_MIN <= celsius <= CELSIUS_MAX:
            raise DeviceRefusal(
                f"MCP9808 held at {celsius!r} C, outside the specified "
                f"{CELSIUS_MIN} to +{CELSIUS_MAX} C range (p.4)")
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
                f"MCP9808 VDD {vdd!r} V is past the 2.7-5.5 V operating range "
                f"(p.3); the absolute maximum is 6.0 V (p.2), and 'functional "
                f"operation of the device at those or any other conditions "
                f"above those indicated in the operational listings ... is not "
                f"implied': refused rather than guessed")
        self.straps = straps
        self.celsius = celsius
        if vdd < VPOR_VOLTS:
            self.pointer = POWER_ON_POINTER
            self.registers = dict(POWER_ON)
            self._frozen = None
            self._writing = False
            self._pending = []
        self._powered = vdd >= VDD_MIN

    def _close(self) -> None:
        """End the transfer in progress, and refuse it if it was a write that
        gave the register fewer bytes than its width. A START or a STOP both
        end a transfer (4.1.3, p.13), and the register is left as it was."""
        pending, self._pending = self._pending, []
        self._writing = False
        self._bytes_in = 0
        self._reads = 0
        if pending:
            raise DeviceRefusal(
                f"MCP9808 write to pointer {self.pointer} ended after "
                f"{len(pending)} of {WIDTH[self.pointer]} data bytes "
                f"({bytes(pending).hex()}): Figure 5-4 (p.23) writes the "
                f"pointer, the MSB and the LSB, and 4.1.1 (p.13) has no "
                f"sequential write; DS25095A does not describe a partial "
                f"write, so the register is left as it was")

    def start(self, read: bool) -> bool:
        """A START and this part's address byte; True where it acknowledges.
        The controller has already matched the address, so this answers only
        for power."""
        if not self._powered:
            return False
        self._close()
        self._writing = not read
        return True

    def write(self, byte: int) -> bool:
        """One byte from the host after a write address; True for the ACK.
        The first is the pointer (Register 5-1), the rest the register's
        data, its width in all and no more (4.1.1, p.13)."""
        if not self._writing:
            raise DeviceRefusal(
                f"MCP9808 was sent byte {byte:#04x} outside a write transfer")
        self._bytes_in += 1
        if self._bytes_in == 1:
            self._set_pointer(byte)
            return True
        pointer = self.pointer
        if pointer in _READ_ONLY:
            raise DeviceRefusal(
                f"MCP9808 write of {byte:#04x} to pointer {pointer} "
                f"(byte {self._bytes_in}): {_WHERE[pointer]} is read-only "
                f"({_READ_ONLY[pointer]})")
        if self._bytes_in - 1 > WIDTH[pointer]:
            self._pending = []
            raise DeviceRefusal(
                f"MCP9808 write of {byte:#04x} to pointer {pointer} "
                f"(byte {self._bytes_in}) after its {WIDTH[pointer]} data "
                f"bytes ({_WHERE[pointer]}): the part does not support "
                f"sequential register writes (4.1.1, p.13)")
        self._pending.append(byte)
        if len(self._pending) == WIDTH[pointer]:
            word = int.from_bytes(bytes(self._pending), "big")
            self._pending = []
            self._store(pointer, word)
        return True

    def _store(self, pointer: int, word: int) -> None:
        """A whole register written. The lock bits are read from before the
        write, so one write cannot lock a register and change it too."""
        config = self.registers[CONFIG]
        if pointer == CONFIG:
            self._store_config(config, word)
        elif pointer == RESOLUTION:
            self.registers[RESOLUTION] = word & RESOLUTION_MASK
        elif config & (_CRIT_LOCK if pointer == TCRIT else _WIN_LOCK):
            return   # Register 5-2 bits 7:6: "can not be written"
        else:
            self.registers[pointer] = word & LIMIT_MASK

    def _store_config(self, old: int, word: int) -> None:
        """Register 5-2 (p.18-19). Once set, Crit Lock and Win Lock stay
        until a power-on reset; while either is set THYST, Alert Cnt, Alert
        Pol and Alert Mod can not be altered and SHDN can only be cleared;
        Alert Sel is held by Win Lock alone. The Alert output is not
        modelled, so a write that would turn Alert Cnt on is refused."""
        new = word & CONFIG_STORED
        locked = old & (_CRIT_LOCK | _WIN_LOCK)
        result = old | new & (_CRIT_LOCK | _WIN_LOCK)
        free = _ALERT_SEL if not old & _WIN_LOCK else 0
        if not locked:
            free |= _THYST | _SHDN | _ALERT_CNT | _ALERT_POL_MOD
        result = result & ~free | new & free
        if locked:
            result = result & ~_SHDN | old & new & _SHDN
        if result & _ALERT_CNT:
            raise DeviceRefusal(
                f"MCP9808 CONFIG write {word:#06x} sets Alert Cnt (Register "
                f"5-2 bit 3, p.19): the Alert output is not modelled, so the "
                f"write is refused and CONFIG stays {old:#06x}")
        if not result & _SHDN:
            self._frozen = None
        elif not old & _SHDN:
            self._frozen = self.celsius
        self.registers[CONFIG] = result

    def _set_pointer(self, byte: int) -> None:
        if byte & 0xF0:
            raise DeviceRefusal(
                f"MCP9808 pointer {byte:#04x} has bits 7:4 set; they must be "
                f"written 0 (Register 5-1, p.16)")
        if byte not in WIDTH:
            raise DeviceRefusal(
                f"MCP9808 pointer {byte:#04x} is "
                f"{'0000 = RFU, reserved for future use' if byte == 0 else 'a reserved test and calibration register'} "
                f"(Register 5-1, p.16, Note 1): it is not to be accessed")
        self.pointer = byte

    def read(self) -> int:
        """The next byte of the selected register, MSB first."""
        if self._writing:
            raise DeviceRefusal(
                "MCP9808 read inside a write transfer: the host addressed it "
                "for writing (Table 3-2, p.11)")
        if self.pointer not in WIDTH:
            raise DeviceRefusal(
                f"MCP9808 read at pointer {self.pointer}: 0000 = RFU, reserved "
                f"for future use (Register 5-1, p.16); nothing was written to "
                f"select a register since power-on")
        width = WIDTH[self.pointer]
        if self._reads == width:
            raise DeviceRefusal(
                f"MCP9808 byte {self._reads + 1} read of pointer "
                f"{self.pointer}, {_WHERE[self.pointer]}, which is {width} "
                f"bytes wide: the part does not support sequential register "
                f"reads (4.1.1, p.13); each register needs its own transfer")
        word = self._word(self.pointer)
        self._reads += 1
        return word >> 8 * (width - self._reads) & 0xFF

    def _word(self, pointer: int) -> int:
        """What the register reads right now."""
        if pointer in IDS:
            return IDS[pointer]
        if pointer != TA:
            return self.registers[pointer]
        config = self.registers[CONFIG]
        if config & _THYST:
            raise DeviceRefusal(
                f"MCP9808 TA read with CONFIG {config:#06x} THYST "
                f"{(config & _THYST) >> 9} (Register 5-2, p.18; 5.2.2, p.30): "
                f"the hysteresis applies to the Alert limits as the "
                f"temperature falls, and DS25095A does not say what it does "
                f"to TA's flag bits, so TA is not answered")
        held = self.celsius if self._frozen is None else self._frozen
        r = self.registers
        return ta_word(held, r[RESOLUTION], r[TUPPER], r[TLOWER], r[TCRIT])

    def stop(self) -> None:
        """A STOP: the transfer ends, the pointer stays (4.1.1, p.13). A write
        that stopped short of its register's width is refused (`_close`)."""
        self._close()
