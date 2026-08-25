#!/usr/bin/env python3
# OpenHardware - the Python side of the AVR C ABI.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""ctypes binding for `core/avr/abi.h`.

The same three-files-one-contract arrangement the other cores keep, and the
same reason: a shape agreed twice drifts silently, so the binding checks the
version the library reports before running anything.

**Every accessor names its address space.** This machine has two that overlap,
so `read_data(0x0100)` and `read_program(0x0100)` are different locations and
neither name is a default. See `core/avr/cpu.h`.

    from core.avr.abi import Cpu

    with Cpu() as cpu:
        cpu.configure(program_words=16 * 1024, data_bytes=0x0900)
        cpu.write_program_block(0, image)
        cpu.step()
"""

from __future__ import annotations

import ctypes
import pathlib
import sys

try:
    from tools.build_core import BuildError, ensure_built, library_path
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.build_core import BuildError, ensure_built, library_path

#: Must match AVR_ABI_VERSION in abi.h.
ABI_VERSION = 2

#: Must match avr::StepResult.
OK = 0
UNIMPLEMENTED = 1
MEMORY_FAULT = 2

#: SREG bits, as the datasheet numbers them.
FLAGS = {"C": 0, "Z": 1, "N": 2, "V": 3, "S": 4, "H": 5, "T": 6, "I": 7}

#: `in`/`out` take an address 0x20 lower than a data access to the same
#: register. The single most likely off-by-something in an AVR model, so it is
#: named here as well as in the C.
IO_BASE = 0x20


class AbiError(Exception):
    """The library is missing, or does not match this binding."""


class Unimplemented(AbiError):
    """An encoding this core does not implement. The machine is untouched."""


class MemoryFault(AbiError):
    """An access outside the sized space."""


_SIGNATURES = {
    "avr_abi_version": ([], ctypes.c_int),
    "avr_new": ([], ctypes.c_void_p),
    "avr_free": ([ctypes.c_void_p], None),
    "avr_reset": ([ctypes.c_void_p], None),
    "avr_configure": ([ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32], None),
    "avr_map_timer": (
        [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint16,
         ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint32],
        ctypes.c_int,
    ),
    "avr_timer_count": ([ctypes.c_void_p], ctypes.c_uint8),
    "avr_interrupt_inhibited": ([ctypes.c_void_p], ctypes.c_int),
    "avr_program_words": ([ctypes.c_void_p], ctypes.c_uint32),
    "avr_data_bytes": ([ctypes.c_void_p], ctypes.c_uint32),
    "avr_read_program": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint16)],
        ctypes.c_int,
    ),
    "avr_write_program": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint16], ctypes.c_int
    ),
    "avr_read_data": (
        [ctypes.c_void_p, ctypes.c_uint16, ctypes.POINTER(ctypes.c_uint8)],
        ctypes.c_int,
    ),
    "avr_write_data": (
        [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint8], ctypes.c_int
    ),
    "avr_write_program_block": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
         ctypes.c_uint32],
        ctypes.c_int,
    ),
    "avr_reg": ([ctypes.c_void_p, ctypes.c_uint8], ctypes.c_uint8),
    "avr_set_reg": ([ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8], None),
    "avr_sreg": ([ctypes.c_void_p], ctypes.c_uint8),
    "avr_sp": ([ctypes.c_void_p], ctypes.c_uint16),
    "avr_pc": ([ctypes.c_void_p], ctypes.c_uint32),
    "avr_set_pc": ([ctypes.c_void_p, ctypes.c_uint32], None),
    "avr_executed": ([ctypes.c_void_p], ctypes.c_uint64),
    "avr_step": ([ctypes.c_void_p], ctypes.c_int),
    "avr_fault_address": ([ctypes.c_void_p], ctypes.c_uint32),
    "avr_fault_was_program": ([ctypes.c_void_p], ctypes.c_int),
}

_library: ctypes.CDLL | None = None


def load(build_if_missing: bool = True) -> ctypes.CDLL:
    """Load the shared library once, checking it matches this binding."""
    global _library
    if _library is not None:
        return _library

    try:
        path = ensure_built("avr") if build_if_missing else library_path("avr")
    except BuildError as exc:
        raise AbiError(str(exc)) from exc
    if not path.is_file():
        raise AbiError(f"{path} is missing. Run: python tools/build_core.py")

    library = ctypes.CDLL(str(path))
    for name, (argtypes, restype) in _SIGNATURES.items():
        try:
            function = getattr(library, name)
        except AttributeError as exc:
            raise AbiError(
                f"{path.name} exports no {name!r}. The library is older than "
                f"this binding, or built from a different abi.h."
            ) from exc
        function.argtypes = argtypes
        function.restype = restype

    reported = library.avr_abi_version()
    if reported != ABI_VERSION:
        raise AbiError(
            f"library ABI version {reported}, this binding expects {ABI_VERSION}"
        )

    _library = library
    return library


class Cpu:
    """One AVR, freed when the context exits."""

    def __init__(self, build_if_missing: bool = True) -> None:
        self._lib = load(build_if_missing)
        self._handle = self._lib.avr_new()
        if not self._handle:
            raise AbiError("avr_new returned null")

    def __enter__(self) -> Cpu:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._handle:
            self._lib.avr_free(self._handle)
            self._handle = None

    # --- the two spaces ---------------------------------------------------

    def configure(self, program_words: int, data_bytes: int) -> None:
        """Size program and data memory.

        `program_words` counts 16-bit WORDS, because that is what the PC
        counts. An ATmega328P is 16,384 words of flash and 0x0900 bytes of data
        -- the latter covering the register file, the IO window and 2 KB of
        SRAM, which is why it is one span rather than three.
        """
        self._lib.avr_configure(self._handle, program_words, data_bytes)

    def map_timer(
        self,
        *,
        counter: int,
        flag: int,
        enable: int,
        bit: int,
        vector: int,
        instructions_per_tick: int,
    ) -> None:
        """Give the machine timer 0. Call after `configure`, which resets.

        Keyword-only, because six integers in a row is six chances to swap two
        of them and every one would be a plausible address. `counter`, `flag`
        and `enable` are DATA addresses and `vector` is a WORD address -- the
        two spaces overlap on this machine, so neither name is a default.
        """
        ok = self._lib.avr_map_timer(
            self._handle, counter, flag, enable, bit, vector,
            instructions_per_tick,
        )
        if not ok:
            raise AbiError(
                f"cannot map a timer with counter=0x{counter:04x}, "
                f"flag=0x{flag:04x}, enable=0x{enable:04x} in "
                f"{self.data_bytes} bytes of data, bit={bit}, "
                f"vector=0x{vector:04x} in {self.program_words} words of "
                f"program, instructions_per_tick={instructions_per_tick}"
            )

    @property
    def timer_count(self) -> int:
        """What the counter register reads. 0 with no timer mapped.

        A property beside `sreg` and `sp` rather than a `read_data` of the
        counter's address, so a test can ask what the timer says without
        having to know where the board put it.
        """
        return int(self._lib.avr_timer_count(self._handle))

    @property
    def interrupt_inhibited(self) -> bool:
        """True while `sei` or `reti` is protecting the next instruction.

        The datasheet rule that one instruction runs after either before an
        interrupt can be taken. Exposed because with a single interrupt source
        it is otherwise unobservable -- the flag is cleared on entry, so a
        handler cannot be re-entered soon enough to show the difference -- and
        an ISA rule nothing can assert is an ISA rule that quietly rots.
        """
        return bool(self._lib.avr_interrupt_inhibited(self._handle))

    @property
    def program_words(self) -> int:
        return int(self._lib.avr_program_words(self._handle))

    @property
    def data_bytes(self) -> int:
        return int(self._lib.avr_data_bytes(self._handle))

    def read_program(self, address: int) -> int:
        out = ctypes.c_uint16()
        if not self._lib.avr_read_program(self._handle, address, ctypes.byref(out)):
            raise MemoryFault(self._fault_message(address, program=True))
        return int(out.value)

    def write_program(self, address: int, value: int) -> None:
        if not self._lib.avr_write_program(self._handle, address, value):
            raise MemoryFault(self._fault_message(address, program=True))

    def write_program_block(self, address: int, data: bytes) -> None:
        """Load a compiled image. `data` is little-endian words, which is what
        avr-objcopy emits, and an odd length is refused rather than rounded."""
        if len(data) % 2:
            raise AbiError(
                f"a program image is whole words: {len(data)} bytes is half of "
                f"one, and which half is a question this cannot answer"
            )
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        if not self._lib.avr_write_program_block(
            self._handle, address, buffer, len(data)
        ):
            raise MemoryFault(
                f"{len(data)} bytes at word {address} does not fit in "
                f"{self.program_words} words of program memory"
            )

    def read_data(self, address: int) -> int:
        out = ctypes.c_uint8()
        if not self._lib.avr_read_data(self._handle, address, ctypes.byref(out)):
            raise MemoryFault(self._fault_message(address, program=False))
        return int(out.value)

    def write_data(self, address: int, value: int) -> None:
        if not self._lib.avr_write_data(self._handle, address, value):
            raise MemoryFault(self._fault_message(address, program=False))

    def read_io(self, address: int) -> int:
        """A register by its `in`/`out` address rather than its data address."""
        return self.read_data(IO_BASE + address)

    def write_io(self, address: int, value: int) -> None:
        self.write_data(IO_BASE + address, value)

    # --- state ------------------------------------------------------------

    def reg(self, index: int) -> int:
        return int(self._lib.avr_reg(self._handle, index))

    def set_reg(self, index: int, value: int) -> None:
        self._lib.avr_set_reg(self._handle, index, value)

    @property
    def sreg(self) -> int:
        return int(self._lib.avr_sreg(self._handle))

    def flag(self, name: str) -> bool:
        """One SREG flag by letter -- `cpu.flag("Z")`."""
        try:
            bit = FLAGS[name]
        except KeyError:
            raise AbiError(
                f"unknown flag {name!r}; expected one of {sorted(FLAGS)}"
            ) from None
        return bool(self.sreg & (1 << bit))

    @property
    def sp(self) -> int:
        return int(self._lib.avr_sp(self._handle))

    @property
    def pc(self) -> int:
        """In WORDS, as the machine counts it."""
        return int(self._lib.avr_pc(self._handle))

    @pc.setter
    def pc(self, value: int) -> None:
        self._lib.avr_set_pc(self._handle, value)

    def executed(self) -> int:
        return int(self._lib.avr_executed(self._handle))

    def reset(self) -> None:
        self._lib.avr_reset(self._handle)

    # --- running ----------------------------------------------------------

    def step(self) -> None:
        """One instruction, or raise saying why not.

        On `Unimplemented` the machine is untouched, PC included, so the
        message can name the word that stopped it -- and on a variable-length
        encoding that matters more than on Arm, because resuming from the wrong
        offset runs a program nobody wrote.
        """
        result = self._lib.avr_step(self._handle)
        if result == OK:
            return
        if result == UNIMPLEMENTED:
            at = self.pc
            raise Unimplemented(
                f"no implementation for 0x{self.read_program(at):04x} at word "
                f"0x{at:04x} (byte 0x{at * 2:04x})"
            )
        address = int(self._lib.avr_fault_address(self._handle))
        program = bool(self._lib.avr_fault_was_program(self._handle))
        raise MemoryFault(self._fault_message(address, program))

    def _fault_message(self, address: int, program: bool) -> str:
        space = "program" if program else "data"
        size = self.program_words if program else self.data_bytes
        unit = "words" if program else "bytes"
        return (
            f"0x{address:04x} is outside the {size} {unit} of {space} memory. "
            f"This machine has two address spaces and they overlap, so check "
            f"the access meant the one it named."
        )
