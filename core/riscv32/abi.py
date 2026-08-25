#!/usr/bin/env python3
# OpenHardware - the Python side of the RV32 C ABI.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""ctypes binding for `core/riscv32/abi.h`.

Three files describe one contract: `abi.h` declares it, `abi.cc` implements it,
and this mirrors it. They are kept together because the failure mode when they
drift is silent -- a field added on one side and not the other neither fails to
compile nor fails to load, it reads the wrong bytes and produces a register
value that is merely wrong.

So the binding checks two things at load: the ABI version the library reports,
and `sizeof(Riscv32Registers)` against this module's mirror.

    from core.riscv32.abi import Cpu, EXT_C, EXT_M

    with Cpu() as cpu:
        cpu.add_region(0x80000000, 0x1000)      # a board would do this
        cpu.set_extensions(EXT_M | EXT_C)       # ...and this: it is an ESP32-C3
        cpu.write_word(0x80000000, 0x00500093)  # addi x1, x0, 5
        cpu.set_regs([0] * 32, pc=0x80000000)
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

#: Must match RISCV32_ABI_VERSION in abi.h.
ABI_VERSION = 2

#: `riscv32::WriteOp`, by the name a board description uses.
#:
#: Named rather than numbered at the call site, because "2" and "clear" are
#: equally short and only one of them is readable in a board file. The same
#: four spellings `webui/boards/rp2040.py` and `samd21.py` already pass to the
#: Cortex-M0 core, so a board author who has read one has read both.
WRITE_OPS = {"store": 0, "set": 1, "clear": 2, "xor": 3}

#: Must match `riscv32::Extension`. Nothing is enabled until a board says so,
#: because a core that arrived believing it had M and C would be making a claim
#: about a part before anyone had said which part.
EXT_M = 1
EXT_A = 2
EXT_C = 4
EXT_ZBA = 8
EXT_ZBS = 16

#: The ISA of the parts this core is for, spelled once. `docs/
#: architectures.md` 4.2 is the citation, and the C3 row is the one that
#: matters: **RV32IMC, no A**, quoted from the datasheet.
ESP32_C3 = EXT_M | EXT_C
ESP32_C6 = EXT_M | EXT_A | EXT_C

#: The RP2350's Hazard3, **as far as this core models it, which is not all of
#: it.** The datasheet's own string is
#:
#:     rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp
#:
#: so Zbb, Zbkb, Zcb and Zcmp are missing here, and `kExtC` is standing in
#: for Zca -- see the note on `Extension` in cpu.h for why that is sound for a
#: part with no FPU and would stop being sound for one with an FPU.
#:
#: **This constant therefore describes a part that does not exist**, and it is
#: named for a real one. That is only safe because nothing derives "the RP2350
#: must refuse X" from it: `tests/rv32/conftest.py` keeps the datasheet's full
#: set separately as the citable truth and intersects it with what is modelled,
#: so an unmodelled extension shows up as a gap rather than as the silicon
#: lacking it. Adding Zbb here without adding it there is the mistake this
#: paragraph exists to prevent.
RP2350_MODELLED = EXT_M | EXT_A | EXT_C | EXT_ZBA | EXT_ZBS

#: Must match `riscv32::StepResult` and abi.h's documented return values.
OK = 0
UNIMPLEMENTED = 1
MEMORY_FAULT = 2
ILLEGAL = 3


class AbiError(Exception):
    """The library is missing, or does not match this binding."""


class Unimplemented(AbiError):
    """The core reached an encoding nobody has written yet.

    A hole in this emulator. Distinct from `Illegal`, which is a fact about
    the part -- see that class.
    """


class Illegal(AbiError):
    """The part must refuse this encoding, because its extension is off.

    Not a worse `Unimplemented`. This is what an ESP32-C3 does when it meets an
    atomic, and it is correct behaviour rather than missing behaviour. rvcpp
    executes every extension unconditionally, so no lockstep run will ever
    reach this class -- which is why OH-35 exists and why it is a separate
    exception rather than a flag on the one above.
    """


class MemoryFault(AbiError):
    """An access outside the modelled memory, a fetch from a region that
    exists and is not executable, or a misaligned access."""


class Registers(ctypes.Structure):
    """Mirrors `Riscv32Registers`.

    Indexed and in architectural order, matching rvcpp's `RVCore::regs[32]`,
    because every crossing with the oracle is positional there.
    """

    _fields_ = [
        ("x", ctypes.c_uint32 * 32),
        ("pc", ctypes.c_uint32),
    ]

    def as_list(self) -> list[int]:
        return list(self.x)


_SIGNATURES = {
    "riscv32_abi_version": ([], ctypes.c_int),
    "riscv32_regs_size": ([], ctypes.c_uint32),
    "riscv32_new": ([], ctypes.c_void_p),
    "riscv32_free": ([ctypes.c_void_p], None),
    "riscv32_reset": ([ctypes.c_void_p], None),
    "riscv32_get_regs": ([ctypes.c_void_p, ctypes.POINTER(Registers)], None),
    "riscv32_set_regs": ([ctypes.c_void_p, ctypes.POINTER(Registers)], None),
    "riscv32_extensions": ([ctypes.c_void_p], ctypes.c_uint32),
    "riscv32_set_extensions": ([ctypes.c_void_p, ctypes.c_uint32], None),
    "riscv32_read_word": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)],
        ctypes.c_int,
    ),
    "riscv32_write_word": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int
    ),
    "riscv32_write_block": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
         ctypes.c_uint32],
        ctypes.c_int,
    ),
    "riscv32_read_block": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
         ctypes.c_uint32],
        ctypes.c_int,
    ),
    "riscv32_clear_memory": ([ctypes.c_void_p], None),
    "riscv32_add_region": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int,
         ctypes.c_uint8],
        ctypes.c_int,
    ),
    "riscv32_clear_regions": ([ctypes.c_void_p], None),
    "riscv32_map_register": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32], None
    ),
    "riscv32_map_alias": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int,
         ctypes.c_int],
        None,
    ),
    "riscv32_is_mapped": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int),
    "riscv32_clear_mmio": ([ctypes.c_void_p], None),
    "riscv32_step": ([ctypes.c_void_p], ctypes.c_int),
    "riscv32_fault_address": ([ctypes.c_void_p], ctypes.c_uint32),
    "riscv32_fault_was_fetch": ([ctypes.c_void_p], ctypes.c_int),
    "riscv32_in_range": (
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
        path = (ensure_built("riscv32") if build_if_missing
                else library_path("riscv32"))
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
    reported = library.riscv32_abi_version()
    if reported != ABI_VERSION:
        raise AbiError(
            f"library ABI version {reported}, this binding expects {ABI_VERSION}"
        )
    reported_size = library.riscv32_regs_size()
    if reported_size != ctypes.sizeof(Registers):
        raise AbiError(
            f"library says sizeof(Riscv32Registers) is {reported_size}, "
            f"this binding mirrors {ctypes.sizeof(Registers)}"
        )

    _library = library
    return library


class Cpu:
    """One RV32 hart, freed when the context exits."""

    def __init__(self, build_if_missing: bool = True) -> None:
        self._lib = load(build_if_missing)
        self._handle = self._lib.riscv32_new()
        if not self._handle:
            raise AbiError("riscv32_new returned null")

    def __enter__(self) -> Cpu:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._handle:
            self._lib.riscv32_free(self._handle)
            self._handle = None

    # --- state ------------------------------------------------------------

    def get_regs(self) -> Registers:
        out = Registers()
        self._lib.riscv32_get_regs(self._handle, ctypes.byref(out))
        return out

    def set_regs(self, regs: list[int], pc: int) -> None:
        if len(regs) != 32:
            raise AbiError(f"expected 32 registers, got {len(regs)}: {regs!r}")
        value = Registers()
        for index, entry in enumerate(regs):
            value.x[index] = entry & 0xFFFFFFFF
        value.pc = pc & 0xFFFFFFFF
        self._lib.riscv32_set_regs(self._handle, ctypes.byref(value))

    def reg(self, index: int) -> int:
        return self.get_regs().x[index]

    @property
    def pc(self) -> int:
        return self.get_regs().pc

    def reset(self) -> None:
        self._lib.riscv32_reset(self._handle)

    def extensions(self) -> int:
        return self._lib.riscv32_extensions(self._handle)

    def set_isa(self, letters: str) -> None:
        """Say which part this is, as its datasheet spells its ISA.

        `set_extensions` takes a bitmask, which is a fact about this binding.
        A **board** knows its part's ISA string -- `RV32IMC` for an ESP32-C3,
        `RV32IMAC` for a C6 -- because that is what the datasheet prints and
        what `webui/boards/catalogue.py` already records. Translating letters
        to bits belongs here, where the bits are defined, so a board never
        restates them and the two cannot drift.

        Raises on a letter this core cannot represent rather than dropping it.
        A part described as RV32IMAC on a core that silently ignored the `A`
        would execute atomics an ESP32-C3 must trap, and would do it quietly --
        which is the one distinction this whole core is shaped around.
        """
        text = letters.upper()
        if not text.startswith("RV32"):
            raise AbiError(
                f"{letters!r} is not an RV32 ISA string; expected something "
                f"like 'RV32IMC'"
            )
        rest = text[len("RV32"):]
        if not rest.startswith("I"):
            raise AbiError(
                f"{letters!r} does not name the I base, which this core "
                f"assumes and cannot switch off"
            )

        known = {"M": EXT_M, "A": EXT_A, "C": EXT_C}
        mask = 0
        for letter in rest[1:]:
            if letter not in known:
                raise AbiError(
                    f"{letters!r} names extension {letter!r}, which this core "
                    f"cannot represent. Known: {''.join(sorted(known))}. An "
                    f"extension dropped rather than refused would make a part "
                    f"look like one it is not."
                )
            mask |= known[letter]
        self.set_extensions(mask)

    def set_extensions(self, mask: int) -> None:
        """Say which part this is. See `ESP32_C3` and `ESP32_C6`."""
        self._lib.riscv32_set_extensions(self._handle, mask)

    # --- memory -----------------------------------------------------------

    def read_word(self, address: int) -> int:
        out = ctypes.c_uint32()
        if not self._lib.riscv32_read_word(self._handle, address, ctypes.byref(out)):
            raise MemoryFault(f"0x{address:08x} is outside the modelled memory")
        return out.value

    def write_word(self, address: int, value: int) -> None:
        if not self._lib.riscv32_write_word(self._handle, address, value):
            raise MemoryFault(f"0x{address:08x} is outside the modelled memory")

    def write_block(self, address: int, data: bytes) -> None:
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        if not self._lib.riscv32_write_block(self._handle, address, buffer, len(data)):
            raise MemoryFault(
                f"0x{address:08x}..0x{address + len(data):08x} leaves the modelled memory"
            )

    def read_block(self, address: int, length: int) -> bytes:
        buffer = (ctypes.c_uint8 * length)()
        if not self._lib.riscv32_read_block(self._handle, address, buffer, length):
            raise MemoryFault(
                f"0x{address:08x}..0x{address + length:08x} leaves the modelled memory"
            )
        return bytes(buffer)

    def clear_memory(self) -> None:
        self._lib.riscv32_clear_memory(self._handle)

    def add_region(self, base: int, size: int, executable: bool = True,
                   fill: int = 0) -> None:
        if not self._lib.riscv32_add_region(
            self._handle, base, size, 1 if executable else 0, fill
        ):
            raise AbiError(
                f"region 0x{base:08x}+0x{size:x} overlaps one already added, or "
                f"runs off the end of the address space"
            )

    def clear_regions(self) -> None:
        self._lib.riscv32_clear_regions(self._handle)

    # --- memory-mapped registers -----------------------------------------

    def map_register(self, address: int, value: int = 0) -> None:
        """An address that holds a word: reads answer it, writes replace it."""
        self._lib.riscv32_map_register(self._handle, address, value)

    def map_alias(self, address: int, target: int, op: str,
                  readable: bool = True) -> None:
        """An address whose write applies `op` to `target`'s word.

        `op` is one of `store`, `set`, `clear`, `xor`. An unknown name raises
        here rather than being passed through as a number the C side would
        quietly read as `store` -- a board that meant `clear` and silently got
        `store` would turn a W1TC register into one that overwrites.
        """
        try:
            code = WRITE_OPS[op]
        except KeyError:
            raise AbiError(
                f"unknown write op {op!r}; expected one of {sorted(WRITE_OPS)}"
            ) from None
        self._lib.riscv32_map_alias(
            self._handle, address, target, code, 1 if readable else 0
        )

    def is_mapped(self, address: int) -> bool:
        """Whether `address` is a mapped register rather than bulk memory."""
        return bool(self._lib.riscv32_is_mapped(self._handle, address))

    def clear_mmio(self) -> None:
        self._lib.riscv32_clear_mmio(self._handle)

    def in_range(self, address: int, bytes_: int = 1) -> bool:
        return bool(self._lib.riscv32_in_range(self._handle, address, bytes_))

    # --- execution --------------------------------------------------------

    def step(self) -> None:
        """Execute one instruction, raising rather than returning a code.

        Three exception types for three different readings, because a caller
        that has to compare integers will eventually compare the wrong one:
        `Unimplemented` means finish the emulator, `Illegal` means the part is
        behaving correctly, and `MemoryFault` means the board is incomplete.
        """
        result = self._lib.riscv32_step(self._handle)
        if result == OK:
            return
        pc = self.pc
        if result == UNIMPLEMENTED:
            raise Unimplemented(
                f"pc=0x{pc:08x}: encoding 0x{self._word_at(pc):08x} is not "
                f"implemented by this core"
            )
        if result == ILLEGAL:
            raise Illegal(
                f"pc=0x{pc:08x}: encoding 0x{self._word_at(pc):08x} is illegal "
                f"for extensions 0x{self.extensions():x}"
            )
        address = self._lib.riscv32_fault_address(self._handle)
        kind = "fetch" if self._lib.riscv32_fault_was_fetch(self._handle) else "access"
        present = "present but not executable" if self.in_range(address, 2) else "unmapped"
        raise MemoryFault(
            f"pc=0x{pc:08x}: {kind} at 0x{address:08x} refused ({present})"
        )

    def _word_at(self, address: int) -> int:
        """The encoding at `address`, or zero if it cannot be read.

        Only ever called to build a message about an instruction that has
        already been fetched successfully, so the fallback is unreachable in
        practice -- it exists so that a diagnostic can never itself raise and
        replace the failure it was describing.
        """
        try:
            return self.read_word(address)
        except MemoryFault:
            return 0
