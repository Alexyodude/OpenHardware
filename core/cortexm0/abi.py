#!/usr/bin/env python3
# OpenHardware - the Python side of the Cortex-M0+ C ABI.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""ctypes binding for `core/cortexm0/abi.h`.

Three files describe one contract: `abi.h` declares it, `abi.cc` implements it,
and this mirrors it. They are kept together because the failure mode when they
drift is silent -- a field added on one side and not the other neither fails to
compile nor fails to load, it reads the wrong bytes and produces a register
value that is merely wrong.

So the binding checks two things at load: the ABI version the library reports,
and `sizeof(CortexM0Registers)` against this module's mirror.

    from core.cortexm0.abi import Cpu

    with Cpu() as cpu:
        cpu.add_region(0x20000000, 0x1000)          # a board would do this
        cpu.write_halfword(0x20000000, 0x1840)      # ADDS r0, r0, r1
        cpu.set_regs([0] * 15 + [0x20000000], apsr=0)
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

#: Must match CORTEXM0_ABI_VERSION in abi.h.
ABI_VERSION = 9

#: Must match cortexm0::WriteOp. Spelled at call sites rather than numbered.
WRITE_OPS = {"store": 0, "set": 1, "clear": 2, "xor": 3}

#: Must match cortexm0::StepResult and abi.h's documented return values.
OK = 0
UNIMPLEMENTED = 1
MEMORY_FAULT = 2


class AbiError(Exception):
    """The library is missing, or does not match this binding."""


class Unimplemented(AbiError):
    """The core reached an encoding nobody has written yet."""


class MemoryFault(AbiError):
    """An access outside the modelled memory, or a fetch from a region that
    exists but is not executable."""


class Registers(ctypes.Structure):
    """Mirrors `CortexM0Registers`.

    Indexed rather than named, matching the corpus, which delivers `regs` as a
    16-element list. The i8086 binding crosses by name instead; the difference
    is deliberate and follows whichever shape the oracle uses, because that is
    the crossing where a transcription error would live.
    """

    _fields_ = [
        ("r", ctypes.c_uint32 * 16),
        ("apsr", ctypes.c_uint32),
    ]

    def as_list(self) -> list[int]:
        return list(self.r)


_SIGNATURES = {
    "cortexm0_abi_version": ([], ctypes.c_int),
    "cortexm0_regs_size": ([], ctypes.c_uint32),
    "cortexm0_new": ([], ctypes.c_void_p),
    "cortexm0_free": ([ctypes.c_void_p], None),
    "cortexm0_reset": ([ctypes.c_void_p], None),
    "cortexm0_get_regs": ([ctypes.c_void_p, ctypes.POINTER(Registers)], None),
    "cortexm0_set_regs": ([ctypes.c_void_p, ctypes.POINTER(Registers)], None),
    "cortexm0_read_word": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)],
        ctypes.c_int,
    ),
    "cortexm0_write_word": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int
    ),
    "cortexm0_write_halfword": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint16], ctypes.c_int
    ),
    "cortexm0_write_block": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
         ctypes.c_uint32],
        ctypes.c_int,
    ),
    "cortexm0_read_block": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
         ctypes.c_uint32],
        ctypes.c_int,
    ),
    "cortexm0_clear_memory": ([ctypes.c_void_p], None),
    "cortexm0_clear_registers": ([ctypes.c_void_p], None),
    "cortexm0_add_region": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int,
         ctypes.c_uint8],
        ctypes.c_int,
    ),
    "cortexm0_clear_regions": ([ctypes.c_void_p], None),
    "cortexm0_map_register": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32], None
    ),
    "cortexm0_is_mapped": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int),
    "cortexm0_map_alias": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int], None
    ),
    "cortexm0_map_mirror": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int,
         ctypes.c_uint32],
        None,
    ),
    "cortexm0_step": ([ctypes.c_void_p], ctypes.c_int),
    "cortexm0_fault_address": ([ctypes.c_void_p], ctypes.c_uint32),
    "cortexm0_fault_was_fetch": ([ctypes.c_void_p], ctypes.c_int),
    "cortexm0_in_range": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int
    ),
}

_library: ctypes.CDLL | None = None


def load(build_if_missing: bool = True) -> ctypes.CDLL:
    """Load the shared library once, checking it matches this binding."""
    global _library
    if _library is not None:
        return _library

    try:
        path = (ensure_built("cortexm0") if build_if_missing
                else library_path("cortexm0"))
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
                f"{path.name} exports no {name!r}. The library is older than this "
                f"binding, or built from a different abi.h."
            ) from exc
        function.argtypes = argtypes
        function.restype = restype

    # Declaring argtypes is not enough on its own: a struct that gained a field
    # on one side still loads, and every read after it is off by four bytes.
    reported = library.cortexm0_abi_version()
    if reported != ABI_VERSION:
        raise AbiError(
            f"library ABI version {reported}, this binding expects {ABI_VERSION}"
        )
    reported_size = library.cortexm0_regs_size()
    if reported_size != ctypes.sizeof(Registers):
        raise AbiError(
            f"library says sizeof(CortexM0Registers) is {reported_size}, "
            f"this binding mirrors {ctypes.sizeof(Registers)}"
        )

    _library = library
    return library


class Cpu:
    """One Cortex-M0+, freed when the context exits."""

    def __init__(self, build_if_missing: bool = True) -> None:
        self._lib = load(build_if_missing)
        self._handle = self._lib.cortexm0_new()
        if not self._handle:
            raise AbiError("cortexm0_new returned null")

    def __enter__(self) -> Cpu:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._handle:
            self._lib.cortexm0_free(self._handle)
            self._handle = None

    # --- state ------------------------------------------------------------

    def get_regs(self) -> Registers:
        out = Registers()
        self._lib.cortexm0_get_regs(self._handle, ctypes.byref(out))
        return out

    def set_regs(self, regs: list[int], apsr: int) -> None:
        if len(regs) != 16:
            raise AbiError(f"expected 16 registers, got {len(regs)}: {regs!r}")
        value = Registers()
        for index, entry in enumerate(regs):
            value.r[index] = entry & 0xFFFFFFFF
        value.apsr = apsr & 0xFFFFFFFF
        self._lib.cortexm0_set_regs(self._handle, ctypes.byref(value))

    def reset(self) -> None:
        self._lib.cortexm0_reset(self._handle)

    # --- memory -----------------------------------------------------------

    def read_word(self, address: int) -> int:
        out = ctypes.c_uint32()
        if not self._lib.cortexm0_read_word(self._handle, address, ctypes.byref(out)):
            raise MemoryFault(f"0x{address:08x} is outside the modelled memory")
        return out.value

    def write_word(self, address: int, value: int) -> None:
        if not self._lib.cortexm0_write_word(self._handle, address, value):
            raise MemoryFault(f"0x{address:08x} is outside the modelled memory")

    def write_halfword(self, address: int, value: int) -> None:
        if not self._lib.cortexm0_write_halfword(self._handle, address, value):
            raise MemoryFault(f"0x{address:08x} is outside the modelled memory")

    def write_block(self, address: int, data: bytes) -> None:
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        if not self._lib.cortexm0_write_block(self._handle, address, buffer, len(data)):
            raise MemoryFault(
                f"0x{address:08x}..0x{address + len(data):08x} leaves the modelled memory"
            )

    def read_block(self, address: int, length: int) -> bytes:
        buffer = (ctypes.c_uint8 * length)()
        if not self._lib.cortexm0_read_block(self._handle, address, buffer, length):
            raise MemoryFault(
                f"0x{address:08x}..0x{address + length:08x} leaves the modelled memory"
            )
        return bytes(buffer)

    def clear_memory(self) -> None:
        self._lib.cortexm0_clear_memory(self._handle)

    def clear_registers(self) -> None:
        """Forget every mapped register. Not implied by `clear_memory`."""
        self._lib.cortexm0_clear_registers(self._handle)

    def add_region(self, base: int, size: int, *, executable: bool = True,
                   fill: int = 0) -> None:
        """A readable, writable region at `base`. **The only way memory exists.**

        The core ships with none, so a board describes its whole map -- which
        is what lets an RP2040 put flash at 0x10000000 and a SAMD21 put it at
        zero over the same core.

        `executable=False` makes a fetch fault while data reads still answer,
        which a stub standing in for contents this project cannot ship needs.
        `fill` is what an untouched byte reads: pass 0xFF for flash, because
        that is what erased flash reads on a real part *and* because 0xFFFF is
        not a valid Thumb encoding, so running off into it stops the core
        instead of executing a million no-ops.
        """
        if not self._lib.cortexm0_add_region(
            self._handle, base, size, 1 if executable else 0, fill
        ):
            raise AbiError(
                f"a region already covers 0x{base:08x}..0x{base + size:08x}. "
                f"Overlapping regions are a mistake in a board description: "
                f"the lookup returns the first match, so the second one's "
                f"writes would go somewhere nothing reads."
            )

    def clear_regions(self) -> None:
        """Forget every region added by `add_region`. Flash and SRAM remain."""
        self._lib.cortexm0_clear_regions(self._handle)

    def map_register(self, address: int, value: int = 0) -> None:
        """Make one memory-mapped word respond, reads-as-written.

        Only what you register responds. Everything else still faults, which
        is what keeps a missing peripheral loud instead of turning a
        wait-for-ready poll into a silent hang.
        """
        self._lib.cortexm0_map_register(self._handle, address, value)

    def in_range(self, address: int, size: int = 4) -> bool:
        """Whether any region covers `address`. Mapped registers are not
        regions, so this is False for them."""
        return bool(self._lib.cortexm0_in_range(self._handle, address, size))

    def is_mapped(self, address: int) -> bool:
        return bool(self._lib.cortexm0_is_mapped(self._handle, address))

    def map_alias(self, address: int, target: int, op: str) -> None:
        """An address whose write applies `op` to `target`'s word.

        `op` is one of "store", "set", "clear", "xor" -- spelled rather than
        numbered, because a bare 2 at a call site is unreadable and the
        difference between clear and xor is a silent wrong answer.
        """
        try:
            code = WRITE_OPS[op]
        except KeyError:
            raise AbiError(
                f"unknown write op {op!r}; expected one of {sorted(WRITE_OPS)}"
            ) from None
        self._lib.cortexm0_map_alias(self._handle, address, target, code)

    def map_mirror(self, address: int, source: int, *, invert: bool = False,
                   mask: int = 0xFFFFFFFF) -> None:
        """An address whose read derives from `source`."""
        self._lib.cortexm0_map_mirror(
            self._handle, address, source, 1 if invert else 0, mask
        )

    # --- running ----------------------------------------------------------

    def step(self) -> None:
        """One instruction, or raise saying why not.

        Raising rather than returning a code, because every caller in this
        repository treats both non-zero results as a stop. The PC is untouched
        in both cases, so the exception message can name the address and the
        caller can read the encoding back out of memory.
        """
        result = self._lib.cortexm0_step(self._handle)
        if result == OK:
            return
        pc = self.get_regs().r[15]
        if result == UNIMPLEMENTED:
            raise Unimplemented(f"no implementation for the encoding at 0x{pc:08x}")
        # The faulting address, not the PC. An earlier version said "fetch at
        # <pc> is outside the modelled SRAM" for every fault, which was wrong
        # twice over on the first real firmware it met: the fault was a *load*,
        # not a fetch, and the address it wanted was 0xD0000000 -- SIO, a
        # peripheral -- while the message pointed at an instruction sitting
        # happily in flash.
        where = self._lib.cortexm0_fault_address(self._handle)
        fetch = bool(self._lib.cortexm0_fault_was_fetch(self._handle))
        exists = bool(self._lib.cortexm0_in_range(self._handle, where, 2))
        # A fetch from a region that exists means the region refused to be
        # executed -- a jump into a stub -- and that sends the reader somewhere
        # entirely different from a missing memory map. Every other case is an
        # address nothing covers.
        why = ("is in a region that is not executable" if exists
               else "is outside the modelled memory")
        kind = "fetch" if fetch else "data access"
        raise MemoryFault(
            f"{kind} at 0x{where:08x} {why} (instruction at 0x{pc:08x})"
        )
