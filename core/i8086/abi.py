#!/usr/bin/env python3
# OpenHardware - the Python side of the i8086 C ABI.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""ctypes binding for `core/i8086/abi.h`.

Three files describe one contract: `abi.h` declares it, `abi.cc` implements
it, and this mirrors it. They are kept together because the failure mode when
they drift is silent -- a field added on one side and not the other does not
fail to compile and does not fail to load, it reads the wrong bytes and
produces a register value that is merely wrong.

So the binding checks two things at load: the ABI version the library reports,
and `sizeof(I8086Registers)` against this module's mirror. Both are cheap, both
run once, and either failing is a clear error rather than a confusing one much
later.

    from core.i8086.abi import Cpu

    with Cpu() as cpu:
        cpu.write_block(0x00400, b"\\x90\\x90")
        cpu.regs.cs, cpu.regs.ip = 0x0040, 0x0000
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

#: Must match I8086_ABI_VERSION in abi.h.
ABI_VERSION = 5

#: Must match abi.h's field order exactly -- this is a struct mirror, and a
#: reordering here reads the wrong bytes. It does NOT need to match the
#: corpus's order: every crossing is by name, never positional.
REGISTER_NAMES = (
    "ax", "bx", "cx", "dx",
    "si", "di", "bp", "sp",
    "cs", "ds", "es", "ss",
    "ip", "flags",
)


class AbiError(Exception):
    """The library is missing, or does not match this binding."""


class Unimplemented(AbiError):
    """The core reached an opcode nobody has written yet."""


class Registers(ctypes.Structure):
    """Mirror of `I8086Registers`. Order and width must match exactly."""

    _fields_ = [(name, ctypes.c_uint16) for name in REGISTER_NAMES]

    def as_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in REGISTER_NAMES}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        inner = " ".join(f"{n}={getattr(self, n):04X}" for n in REGISTER_NAMES)
        return f"<Registers {inner}>"


#: 0=ES 1=CS 2=SS 3=DS 4=none, matching i8086::Segment in decode.h.
SEGMENT_NAMES = ("es", "cs", "ss", "ds", None)


class Decoded(ctypes.Structure):
    """Mirror of `I8086Decoded`. Padding is left to ctypes and the compiler,
    which agree by default -- and `i8086_decoded_size` proves it at load."""

    _fields_ = [
        ("opcode", ctypes.c_uint8),
        ("has_modrm", ctypes.c_uint8),
        ("mod", ctypes.c_uint8),
        ("reg", ctypes.c_uint8),
        ("rm", ctypes.c_uint8),
        ("displacement", ctypes.c_int16),
        ("segment_override", ctypes.c_uint8),
        ("length", ctypes.c_uint8),
        ("valid", ctypes.c_uint8),
        ("has_memory_operand", ctypes.c_uint8),
        ("ea_segment", ctypes.c_uint8),
        ("ea_offset", ctypes.c_uint16),
        ("ea_physical", ctypes.c_uint32),
    ]

    @property
    def override_name(self) -> str | None:
        """The segment a prefix asked for, or None if there was no prefix."""
        return SEGMENT_NAMES[self.segment_override]

    @property
    def segment_name(self) -> str | None:
        """The segment actually used for the memory operand, if any."""
        return SEGMENT_NAMES[self.ea_segment] if self.has_memory_operand else None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        parts = [f"op={self.opcode:02X}", f"len={self.length}"]
        if self.has_modrm:
            parts.append(f"mod={self.mod} reg={self.reg} rm={self.rm}")
            parts.append(f"disp={self.displacement}")
        if self.has_memory_operand:
            parts.append(f"{self.segment_name}:{self.ea_offset:04X}={self.ea_physical:05X}")
        if self.override_name:
            parts.append(f"override={self.override_name}")
        return "<Decoded " + " ".join(parts) + ">"


_SIGNATURES = {
    "i8086_step": ([ctypes.c_void_p], ctypes.c_int),
    "i8086_opcode_info": ([ctypes.c_uint8], ctypes.c_int),
    "i8086_decoded_size": ([], ctypes.c_uint32),
    "i8086_decode": (
        [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.POINTER(Decoded)],
        None,
    ),
    "i8086_abi_version": ([], ctypes.c_int),
    "i8086_regs_size": ([], ctypes.c_uint32),
    "i8086_memory_size": ([], ctypes.c_uint32),
    "i8086_new": ([], ctypes.c_void_p),
    "i8086_free": ([ctypes.c_void_p], None),
    "i8086_reset": ([ctypes.c_void_p], None),
    "i8086_get_regs": ([ctypes.c_void_p, ctypes.POINTER(Registers)], None),
    "i8086_set_regs": ([ctypes.c_void_p, ctypes.POINTER(Registers)], None),
    "i8086_read_byte": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_uint8),
    "i8086_write_byte": ([ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint8], None),
    "i8086_read_word": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_uint16),
    "i8086_write_word": ([ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint16], None),
    "i8086_write_block": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32],
        None,
    ),
    "i8086_read_block": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32],
        None,
    ),
    "i8086_clear_memory": ([ctypes.c_void_p], None),
    "i8086_physical": ([ctypes.c_uint16, ctypes.c_uint16], ctypes.c_uint32),
}

_library: ctypes.CDLL | None = None


def load(build_if_missing: bool = True) -> ctypes.CDLL:
    """Load the shared library once, checking it matches this binding."""
    global _library
    if _library is not None:
        return _library

    try:
        path = ensure_built() if build_if_missing else library_path()
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
    # on one side still loads, and every read after it is off by two bytes.
    reported = library.i8086_abi_version()
    if reported != ABI_VERSION:
        raise AbiError(f"library ABI version {reported}, this binding expects {ABI_VERSION}")
    for label, reported, mirrored in (
        ("I8086Registers", library.i8086_regs_size(), ctypes.sizeof(Registers)),
        ("I8086Decoded", library.i8086_decoded_size(), ctypes.sizeof(Decoded)),
    ):
        if reported != mirrored:
            raise AbiError(
                f"{label} is {reported} bytes in the library and {mirrored} here; "
                f"the mirrors have drifted"
            )

    _library = library
    return library


def physical(segment: int, offset: int) -> int:
    """Segment:offset to a physical address, computed by the core itself."""
    return int(load().i8086_physical(segment & 0xFFFF, offset & 0xFFFF))


def memory_size() -> int:
    return int(load().i8086_memory_size())


class Cpu:
    """One processor and its megabyte, owned for the life of the object."""

    def __init__(self) -> None:
        self._lib = load()
        handle = self._lib.i8086_new()
        if not handle:
            raise AbiError("i8086_new returned null; allocation failed")
        self._handle = handle

    # -- lifetime ----------------------------------------------------------

    def close(self) -> None:
        if getattr(self, "_handle", None):
            self._lib.i8086_free(self._handle)
            self._handle = None

    def __enter__(self) -> Cpu:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - interpreter teardown
        try:
            self.close()
        except Exception:  # noqa: BLE001 - nothing useful to do while collecting
            pass

    def _check(self) -> int:
        if not self._handle:
            raise AbiError("this Cpu has been closed")
        return self._handle

    # -- state -------------------------------------------------------------

    def reset(self) -> None:
        self._lib.i8086_reset(self._check())

    @property
    def regs(self) -> Registers:
        out = Registers()
        self._lib.i8086_get_regs(self._check(), ctypes.byref(out))
        return out

    @regs.setter
    def regs(self, value: Registers) -> None:
        self._lib.i8086_set_regs(self._check(), ctypes.byref(value))

    def set_regs(self, **values: int) -> None:
        """Set named registers, leaving the rest as they are."""
        current = self.regs
        for name, value in values.items():
            if name not in REGISTER_NAMES:
                raise AbiError(f"no register {name!r}; known: {', '.join(REGISTER_NAMES)}")
            setattr(current, name, value & 0xFFFF)
        self.regs = current

    # -- memory ------------------------------------------------------------

    def read_byte(self, address: int) -> int:
        return int(self._lib.i8086_read_byte(self._check(), address & 0xFFFFF))

    def write_byte(self, address: int, value: int) -> None:
        self._lib.i8086_write_byte(self._check(), address & 0xFFFFF, value & 0xFF)

    def read_word(self, address: int) -> int:
        return int(self._lib.i8086_read_word(self._check(), address & 0xFFFFF))

    def write_word(self, address: int, value: int) -> None:
        self._lib.i8086_write_word(self._check(), address & 0xFFFFF, value & 0xFFFF)

    def write_block(self, address: int, data: bytes) -> None:
        """One call per block. A conformance case's `ram` can be thousands of
        bytes, and the corpus has hundreds of thousands of cases."""
        if not data:
            return
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        self._lib.i8086_write_block(self._check(), address & 0xFFFFF, buffer, len(data))

    def read_block(self, address: int, length: int) -> bytes:
        if length <= 0:
            return b""
        buffer = (ctypes.c_uint8 * length)()
        self._lib.i8086_read_block(self._check(), address & 0xFFFFF, buffer, length)
        return bytes(buffer)

    def clear_memory(self) -> None:
        self._lib.i8086_clear_memory(self._check())

    def decode(self, cs: int | None = None, ip: int | None = None) -> Decoded:
        """Decode the instruction at cs:ip without executing it.

        Defaults to the current CS:IP, which is what a disassembly view wants.
        """
        current = self.regs
        out = Decoded()
        self._lib.i8086_decode(
            self._check(),
            current.cs if cs is None else cs & 0xFFFF,
            current.ip if ip is None else ip & 0xFFFF,
            ctypes.byref(out),
        )
        return out

    def step(self) -> None:
        """Execute one instruction, or raise naming the opcode that stopped it.

        Raising rather than returning a status: a caller that ignores a status
        code turns an unimplemented opcode into a silent no-op, and a
        conformance case whose expected state happens to match would then pass.
        """
        status = self._lib.i8086_step(self._check())
        if status != 0:
            current = self.decode()
            raise Unimplemented(
                f"opcode {current.opcode:02X}h at "
                f"{self.regs.cs:04X}:{self.regs.ip:04X} is not implemented"
            )


def opcode_info(opcode: int) -> tuple[bool, bool]:
    """(implemented, has_modrm) for an opcode, from the core's own table."""
    bits = int(load().i8086_opcode_info(opcode & 0xFF))
    return bool(bits & 1), bool(bits & 2)


def opcode_is_wide(opcode: int) -> bool:
    """True when the opcode's operands are 16-bit."""
    return bool(int(load().i8086_opcode_info(opcode & 0xFF)) & 4)
