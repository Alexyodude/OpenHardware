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
from collections.abc import Callable, Mapping

try:
    from tools.build_core import BuildError, ensure_built, library_path
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.build_core import BuildError, ensure_built, library_path

#: Must match RISCV32_ABI_VERSION in abi.h.
ABI_VERSION = 7

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
EXT_ZCB = 32
EXT_ZCMP = 64
EXT_ZCMT = 128
EXT_ZBB = 256
EXT_ZBKB = 512
EXT_XH3BEXTM = 1024

#: The ISA of the parts this core is for, spelled once. `docs/
#: architectures.md` 4.2 is the citation, and the C3 row is the one that
#: matters: **RV32IMC, no A**, quoted from the datasheet.
ESP32_C3 = EXT_M | EXT_C
ESP32_C6 = EXT_M | EXT_A | EXT_C

#: The ESP32-C5, whole (OH-146): the datasheet spells it
#: `RV32IMAC + Zcb/Zcmp/Zcmt` and every group now has a bit and an
#: implementation, so this constant describes the part rather than a
#: modelled subset of it.
ESP32_C5 = EXT_M | EXT_A | EXT_C | EXT_ZCB | EXT_ZCMP | EXT_ZCMT

#: The RP2350's Hazard3: every group of the datasheet's own string that has
#: a bit,
#:
#:     rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp
#:
#: -- M, A, `EXT_C` for Zca, Zba, Zbb, Zbs, Zbkb, Zcb and Zcmp. The mask
#: `webui/boards/rp2350.py` configures, and the one
#: `tests/rv32/test_gating.py` holds equal to that file's datasheet row
#: through its `MODELLED` list. `kExtC` stands for Zca -- see the note on
#: `Extension` in cpu.h for why that is sound for a part with no FPU and
#: would stop being sound for one with an FPU. Zicsr and Zifencei have no
#: bit: this core has no CSRs and answers both `Unimplemented`, a hole in
#: the model rather than a refusal, and it answers A the same way.
#:
#: **And Xh3bextm (OH-219)**, which that string does not name because it
#: names no custom extension. The datasheet's 3.8 does, PDF p.227:
#: "Additionally, RP2350 enables the following Hazard3 custom extensions",
#: Xh3power, Xh3bextm, Xh3irq and Xh3pmpm. Xh3bextm is the one with
#: encodings of its own, and it runs here, in lockstep with rvcpp. The
#: other three are CSRs, `Unimplemented` like every CSR, and two `slt`
#: hints that run as the base ISA's no-op; `tests/riscv32/test_xh3.py`
#: holds each answer.
#:
#: **One constant since OH-219.** OH-208 left two: this one, and a
#: narrower `RP2350_MODELLED` without Zbb and Zbkb, which the gating test
#: held because its `MODELLED` named neither group. Until OH-208 the board
#: configured the narrower mask, and a XIAO RP2350 refused `clz`, `minu`
#: and `rev8` as `Illegal` -- the word for "the silicon lacks this" --
#: where its silicon executes them. Until OH-219 it refused `h3.bextm` the
#: same way.
RP2350 = (EXT_M | EXT_A | EXT_C | EXT_ZBA | EXT_ZBB | EXT_ZBS | EXT_ZBKB
          | EXT_ZCB | EXT_ZCMP | EXT_XH3BEXTM)

#: Must match `riscv32::StepResult` and abi.h's documented return values.
OK = 0
UNIMPLEMENTED = 1
MEMORY_FAULT = 2
ILLEGAL = 3
#: abi.h's `RISCV32_RANG`: the instruction retired, and rang a doorbell. ABI
#: only: `riscv32::StepResult` has no such value, and `Cpu.step` never returns
#: it, because it runs the service the doorbell names.
RANG = 4

#: `riscv32_fault_reason`, as the words a `MemoryFault` is worded with. 0, an
#: address nothing maps, has none: the older words say it.
FAULT_REASONS = {
    1: "the FIFO holds nothing to read",
    2: "the FIFO's enable register is not mapped",
    3: "a byte or halfword read of a FIFO above byte 0 would pop a byte and "
       "answer zero; read byte 0",
    4: "the register is an alias onto a FIFO or a doorbell, which an alias "
       "bypasses",
}

#: How many halfwords a `HostFault` shows from where its step began: an RV32
#: instruction is one 16-bit parcel or two, and the core fetches it as such.
FAULT_HALFWORDS = 2

#: How ctypes words an access violation that WROTE (its SetException formats
#: "exception: access violation writing 0x..."). A wild write in the core may
#: have landed anywhere in this process, not only in the machine a reload
#: replaces, so a `HostFault` from one says to restart the process instead.
WILD_WRITE = "access violation writing"


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


class HostFault(AbiError):
    """The core's own code faulted on the host while executing an instruction.

    A divide error or an access violation in the C++, which is a bug in the
    core and never in the firmware. On Windows ctypes catches the structured
    exception around the foreign call and raises `OSError`; `Cpu.step` raises
    this from it, so a run loop that stops on `AbiError` -- `webui/api.py`'s
    does -- stops here too instead of losing the request. The machine is left
    part-way through an instruction, PC included, and should be loaded again
    rather than stepped (OH-225, after OH-223).

    **Windows only.** On Linux the same fault is a signal, SIGFPE or SIGSEGV,
    that ctypes does not catch, and the process ends before this can be
    raised. OH-223's note records why nothing is done about that here.
    """

    def __init__(self, message: str, at: int | None,
                 code: tuple[int, ...], left: int | None) -> None:
        super().__init__(message)
        #: The PC the step began at, or None if reading that back faulted.
        self.at = at
        #: The first `FAULT_HALFWORDS` halfwords there, low parcel first, or
        #: as many as were read before reading them faulted or the region
        #: ended.
        self.code = code
        #: The PC the core left, or None if reading it faulted.
        self.left = left


class Refused(AbiError):
    """A doorbell was rung and nothing could answer it.

    Either the service registered for the doorbell raised `ValueError`, saying
    what the device refuses -- the cause is chained -- or none was registered.
    **The instruction that rang it retired**, so a caller counting
    instructions counts this one: `pc` is where that instruction began, and
    the PC register is past it. Not a fault of the core and not of the
    firmware's memory map: the firmware asked a device for something the
    device's model refuses.
    """

    #: What a caller that counts instructions asks of any `AbiError`: this
    #: one came after the instruction retired. The others come instead of it.
    retired = True

    def __init__(self, pc: int, address: int, reason: str) -> None:
        super().__init__(
            f"pc=0x{pc:08x}: the doorbell at 0x{address:08x} was rung and "
            f"{reason}"
        )
        #: Where the ringing instruction began.
        self.pc = pc
        #: The doorbell's word address.
        self.address = address
        #: The service's reason, or that there was no service.
        self.reason = reason


class DeviceRefusal(ValueError):
    """What a doorbell's service raises to say its device refuses this.

    A `ValueError` subclass, but **only this** becomes `Refused`: a service
    that raised some other `ValueError` -- `int("x")` -- has a bug, and is a
    `ServiceFault`.
    """


class ServiceFault(AbiError):
    """A doorbell's service raised something that is not a device refusal.

    A bug in the host-side model, as `HostFault` is a bug in the core, and
    like it stops a session as "faulted" and not "stopped". **The ringing
    instruction retired**, as for `Refused`. Chained from what the service
    raised.
    """

    retired = True
    #: What a session asks of any `AbiError` to word its stop as a fault of
    #: this host's own code. `HostFault` is told by its type.
    host_side = True

    def __init__(self, pc: int, address: int, error: Exception) -> None:
        super().__init__(
            f"pc=0x{pc:08x}: the service for the doorbell at 0x{address:08x} "
            f"raised {type(error).__name__}: {error}"
        )
        self.pc = pc
        self.address = address


def _fits_32(name: str, number: int, address: int) -> None:
    """Refuse a number the C side's `uint32_t` would take truncated."""
    if not 0 <= number <= 0xFFFFFFFF:
        raise AbiError(
            f"{name} for 0x{address:08x} must fit in 32 bits, got {number!r}: "
            f"ctypes would pass it as {number & 0xFFFFFFFF:#010x} without "
            f"saying so")


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
    "riscv32_map_stream": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32],
        None,
    ),
    "riscv32_stream": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
         ctypes.c_uint32],
        ctypes.c_uint32,
    ),
    "riscv32_map_snapshot_counter": (
        [ctypes.c_void_p] + [ctypes.c_uint32] * 9,
        None,
    ),
    "riscv32_map_input": (
        [ctypes.c_void_p] + [ctypes.c_uint32] * 9,
        None,
    ),
    "riscv32_drive_input": (
        [ctypes.c_void_p] + [ctypes.c_uint32] * 3,
        ctypes.c_int,
    ),
    "riscv32_map_sampler": (
        [ctypes.c_void_p] + [ctypes.c_uint32] * 9,
        None,
    ),
    "riscv32_hold_samples": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
         ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32],
        ctypes.c_int,
    ),
    "riscv32_map_doorbell": (
        [ctypes.c_void_p] + [ctypes.c_uint32] * 4,
        ctypes.c_int,
    ),
    "riscv32_rang_at": ([ctypes.c_void_p], ctypes.c_uint32),
    "riscv32_map_fifo": (
        [ctypes.c_void_p] + [ctypes.c_uint32] * 3,
        ctypes.c_int,
    ),
    "riscv32_written_count": (
        [ctypes.c_void_p, ctypes.c_uint32], ctypes.c_uint32
    ),
    "riscv32_take_written": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
         ctypes.c_uint32],
        ctypes.c_uint32,
    ),
    "riscv32_hold_readable": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
         ctypes.c_uint32],
        ctypes.c_int,
    ),
    "riscv32_fault_reason": ([ctypes.c_void_p], ctypes.c_int),
    "riscv32_peek_word": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
         ctypes.POINTER(ctypes.c_int)],
        ctypes.c_int,
    ),
    "riscv32_is_doorbell": (
        [ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int
    ),
    "riscv32_is_fifo": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int),
    "riscv32_is_mapped": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int),
    "riscv32_clear_mmio": ([ctypes.c_void_p], None),
    "riscv32_step": ([ctypes.c_void_p], ctypes.c_int),
    "riscv32_step_entry": ([ctypes.c_void_p], ctypes.c_uint32),
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
        #: Doorbell word address -> what answers it (`on_ring`).
        self._services: dict[int, Callable[[Cpu, int], None]] = {}

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

        Underscore groups spell the named extensions, the way real ISA
        strings do: `RV32IMAC_ZCB_ZCMP_ZCMT` is the ESP32-C5 (OH-146), and
        `RV32IMAC_ZBA_ZBB_ZBS_ZBKB_ZCB_ZCMP_XH3BEXTM` is `RP2350` (OH-208,
        OH-219) -- a vendor's extension spelled the way its `X` prefix is in
        a real string. Every `EXT_*` bit has a letter or a group name here,
        so a group that raises -- `ZBC`, or `ZICSR` -- is one this core has
        no bit for. An unknown group name raises exactly as an unknown
        letter does.
        """
        text = letters.upper()
        if not text.startswith("RV32"):
            raise AbiError(
                f"{letters!r} is not an RV32 ISA string; expected something "
                f"like 'RV32IMC'"
            )
        groups = text[len("RV32"):].split("_")
        rest = groups[0]
        if not rest.startswith("I"):
            raise AbiError(
                f"{letters!r} does not name the I base, which this core "
                f"assumes and cannot switch off"
            )

        known = {"M": EXT_M, "A": EXT_A, "C": EXT_C}
        named = {"ZBA": EXT_ZBA, "ZBB": EXT_ZBB, "ZBS": EXT_ZBS,
                 "ZBKB": EXT_ZBKB, "ZCB": EXT_ZCB, "ZCMP": EXT_ZCMP,
                 "ZCMT": EXT_ZCMT, "XH3BEXTM": EXT_XH3BEXTM}
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
        for group in groups[1:]:
            if group not in named:
                raise AbiError(
                    f"{letters!r} names extension group {group!r}, which "
                    f"this core cannot represent. Known: "
                    f"{', '.join(sorted(named))}. An extension dropped "
                    f"rather than refused would make a part look like one "
                    f"it is not."
                )
            mask |= named[group]
        self.set_extensions(mask)

    def set_extensions(self, mask: int) -> None:
        """Say which part this is. See `ESP32_C3` and `ESP32_C6`."""
        self._lib.riscv32_set_extensions(self._handle, mask)

    # --- memory -----------------------------------------------------------

    def _fault_why(self, reason: int | None = None) -> str | None:
        """The core's reason for the access it just refused, where it names
        one besides an address nothing maps. `reason` is a peek's own: a peek
        leaves the core's record alone."""
        if reason is None:
            reason = self._lib.riscv32_fault_reason(self._handle)
        return FAULT_REASONS.get(reason)

    def read_word(self, address: int) -> int:
        out = ctypes.c_uint32()
        if not self._lib.riscv32_read_word(self._handle, address, ctypes.byref(out)):
            raise self._refused_access(address)
        return out.value

    def peek_word(self, address: int) -> int:
        """`read_word` that changes nothing. A FIFO answers the byte its next
        read will pop, so a viewer watching one takes nothing the firmware was
        to read; use this and not `read_word` to look at a register."""
        out = ctypes.c_uint32()
        reason = ctypes.c_int()
        if not self._lib.riscv32_peek_word(
                self._handle, address, ctypes.byref(out), ctypes.byref(reason)):
            raise self._refused_access(address, reason.value)
        return out.value

    def _refused_access(self, address: int, reason: int | None = None) -> MemoryFault:
        why = self._fault_why(reason)
        if why is None:
            return MemoryFault(f"0x{address:08x} is outside the modelled memory")
        return MemoryFault(f"0x{address:08x} is mapped, and refuses the access: {why}")

    def write_word(self, address: int, value: int) -> None:
        if not self._lib.riscv32_write_word(self._handle, address, value):
            raise self._refused_access(address)

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
        """An address that holds a word: reads answer it, writes replace it.

        A `value` that does not fit 32 bits is refused with the value: ctypes
        would pass `1 << 33` as 0 without saying so."""
        _fits_32("value", value, address)
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
        for kind, test in (("doorbell", self._lib.riscv32_is_doorbell),
                           ("FIFO", self._lib.riscv32_is_fifo)):
            if test(self._handle, target):
                raise AbiError(
                    f"0x{address:08x} cannot alias the {kind} at 0x{target:08x}: "
                    f"an alias reaches the stored word and bypasses what the "
                    f"{kind} does, so a write through it would store a "
                    f"trigger bit and a read of an empty FIFO would answer 0")
        self._lib.riscv32_map_alias(
            self._handle, address, target, code, 1 if readable else 0
        )

    def map_stream(self, address: int, *, enable: int, enable_mask: int) -> None:
        """An address whose writes append a byte to a captured stream.

        A UART's transmit FIFO, where `map_register` would keep only the last
        character written -- so a program that printed `hello` would leave an
        `o` behind, which reads back as a plausible letter rather than as a
        wrong answer.

        `enable`/`enable_mask` name the bit that has to be set for the bytes
        to be captured. On the three ESP32 parts described here that is
        `UART_TX_SCLK_EN`, bit 24 of each part's `UART_CLK_CONF_REG`, whose
        reset value the vendor sets to 1; the gate exists so that firmware
        which switched the transmitter off goes quiet, as the part does.
        """
        self._lib.riscv32_map_stream(self._handle, address, enable, enable_mask)

    def stream(self, address: int) -> bytes:
        """Everything written to a `map_stream` address, oldest first.

        Asked for its length first and read second, rather than guessing a
        buffer size.

        **The second call's return is discarded, and that is safe here for a
        reason worth stating**: this core advances only when Python steps it,
        so nothing can write to the stream between the two calls and the
        length cannot change. The C side reports the true length either way --
        `riscv32_stream` with a three-byte buffer over eight buffered bytes
        answers 8 and copies 3 -- which is what a caller sizing its own buffer
        needs. This docstring claimed that return was checked here until the
        OH-161 review read the next two lines.
        """
        length = self._lib.riscv32_stream(self._handle, address, None, 0)
        if length == 0:
            return b""
        buffer = (ctypes.c_uint8 * length)()
        self._lib.riscv32_stream(self._handle, address, buffer, length)
        return bytes(buffer)

    def map_snapshot_counter(self, *, op: int, update_mask: int, valid_mask: int,
                             low: int, high: int, high_mask: int, enable: int,
                             enable_mask: int, instructions_per_tick: int) -> None:
        """A free-running counter that firmware reads through a snapshot.

        A write carrying `update_mask` to `op` copies the count into `low`
        and `high` (kept to `high_mask`), and from then `op` reads
        `valid_mask` -- an ESP32 SYSTIMER unit's UPDATE / VALUE_VALID
        handshake. It counts once every `instructions_per_tick` retired
        instructions while `enable & enable_mask` is set.

        `instructions_per_tick` is a stated approximation -- this core has no
        cycle model -- and below one is refused here with the value, rather
        than passed to a core that would have to divide by it. So is anything
        past 0xFFFFFFFF: the C side takes a `uint32_t`, and ctypes passes a
        larger int truncated without a word -- 2**32 would arrive as zero,
        which the core corrects to one.
        """
        if instructions_per_tick < 1:
            raise AbiError(
                f"instructions_per_tick must be at least 1, got "
                f"{instructions_per_tick!r}: a counter that never advances is "
                f"the hang this behaviour exists to prevent"
            )
        if instructions_per_tick > 0xFFFFFFFF:
            raise AbiError(
                f"instructions_per_tick must fit in 32 bits, got "
                f"{instructions_per_tick!r}: ctypes would pass it as "
                f"{instructions_per_tick & 0xFFFFFFFF}, a different rate, "
                f"without saying so"
            )
        self._lib.riscv32_map_snapshot_counter(
            self._handle, op, update_mask, valid_mask, low, high, high_mask,
            enable, enable_mask, instructions_per_tick,
        )

    def map_input(self, address: int, *, out: int, enable: int, pad_base: int,
                  pad_stride: int, pads: int, input_enable: int, pull_up: int,
                  pull_down: int) -> None:
        """A read-only register whose read answers the level on each pin.

        For each pin `n` named in `pads`: 0 where the pad register at
        `pad_base + n * pad_stride` has `input_enable` clear; `out`'s bit
        where `enable`'s is set; what `drive_input` last said, where it
        drives the pin; 1 where only `pull_up` is set; 0 otherwise, which
        for a pin with neither pull is a floating pin. An ESP32's `GPIO_IN`,
        whose IO_MUX pad registers carry `FUN_IE`, `FUN_PU` and `FUN_PD`.
        A pin outside `pads` reads 0. See `cpu.h` for every case.
        """
        self._lib.riscv32_map_input(
            self._handle, address, out, enable, pad_base, pad_stride, pads,
            input_enable, pull_up, pull_down,
        )

    def drive_input(self, address: int, *, driven: int, levels: int) -> None:
        """What the outside drives onto the pins of the input register at
        `address`: `driven` which pins, `levels` to what. Replaces the last
        call's whole statement, so a pin left out is driven by nothing.

        Refused, with the values, where `address` is no input register,
        where a mask does not fit the 32 bits the C side takes -- ctypes
        would pass `1 << 32` as 0, a drive of nothing said nowhere -- and
        where `levels` gives a level to a pin `driven` does not name, which
        the core would read past without a word.
        """
        for name, mask in (("driven", driven), ("levels", levels)):
            if not 0 <= mask <= 0xFFFFFFFF:
                raise AbiError(
                    f"{name} must fit in 32 bits, got {mask!r}: ctypes would "
                    f"pass it as {mask & 0xFFFFFFFF:#010x} without saying so")
        if levels & ~driven:
            raise AbiError(
                f"levels {levels:#010x} name pins driven {driven:#010x} does "
                f"not: {levels & ~driven:#010x} would be levels nothing drives")
        if not self._lib.riscv32_drive_input(self._handle, address, driven, levels):
            raise AbiError(
                f"0x{address:08x} is no input register; map_input maps one")

    def map_sampler(self, control: int, *, value: int, start_mask: int,
                    key_mask: int, result: int, status: int, done_mask: int,
                    enable: int, enable_mask: int) -> None:
        """A converter firmware starts with a write to `control`.

        `control` stores as a register from `value`. A write that raises
        `start_mask` -- set now, clear in the word before -- copies the word
        `hold_samples` holds for `written & key_mask` into `result` and sets
        `done_mask` in `status`, both registers the board maps itself, while
        `enable & enable_mask` is set. An ESP32's SAR ADC one-time sample,
        whose control word names the unit, the channel and the attenuation.
        A start through an unreadable gate, for a key nothing holds, or with
        `result` or `status` unmapped faults naming `control`. See `cpu.h`.
        """
        _fits_32("value", value, control)
        self._lib.riscv32_map_sampler(
            self._handle, control, value, start_mask, key_mask, result, status,
            done_mask, enable, enable_mask,
        )

    def hold_samples(self, control: int, samples: Mapping[int, int]) -> None:
        """The word each key converts to at the sampler at `control`, key ->
        word. Replaces the last call's whole statement, so a key left out
        converts to nothing, and a start that names it faults.

        Refused, with the values, where `control` is no sampler and where a
        key or a word does not fit the 32 bits the C side takes: ctypes would
        pass `1 << 32` as 0 without saying so.
        """
        for key, word in samples.items():
            for name, number in (("key", key), ("word", word)):
                if not 0 <= number <= 0xFFFFFFFF:
                    raise AbiError(
                        f"a {name} must fit in 32 bits, got {number!r} (key "
                        f"{key!r} -> word {word!r}): ctypes would pass it as "
                        f"{number & 0xFFFFFFFF:#010x} without saying so")
        count = len(samples)
        keys = (ctypes.c_uint32 * count)(*samples.keys())
        words = (ctypes.c_uint32 * count)(*samples.values())
        if not self._lib.riscv32_hold_samples(self._handle, control, keys, words,
                                              count):
            raise AbiError(
                f"0x{control:08x} is no sampler; map_sampler maps one")

    def map_doorbell(self, address: int, *, value: int, ring_mask: int,
                     write_trigger: int = 0) -> None:
        """A register that rings when written, for a device Python owns.

        `address` stores as a register from `value`, except that every bit of
        `write_trigger` stores as 0. A write carrying a bit of `ring_mask`
        retires as a store and then `step` runs the service `on_ring` gave
        for `address`. A write with no ring bit does not ring. An ESP32 I2C
        controller's CTR, whose TRANS_START is both. The core knows nothing of
        the device; see `cpu.h`.

        A `ring_mask` of zero is refused, with the values: a doorbell that can
        never ring is a device that silently never answers. So is a mask that
        does not fit 32 bits, which ctypes would pass truncated.
        """
        for name, mask in (("ring_mask", ring_mask),
                           ("write_trigger", write_trigger),
                           ("value", value)):
            if not 0 <= mask <= 0xFFFFFFFF:
                raise AbiError(
                    f"{name} must fit in 32 bits, got {mask!r}: ctypes would "
                    f"pass it as {mask & 0xFFFFFFFF:#010x} without saying so")
        if ring_mask == 0:
            raise AbiError(
                f"ring_mask 0 for the doorbell at 0x{address:08x} never "
                f"rings: a device behind it would never be asked anything")
        if not 0 <= address <= 0xFFFFFFFF:
            raise AbiError(
                f"the doorbell address must fit in 32 bits, got {address:#x}: "
                f"ctypes would pass it as {address & 0xFFFFFFFF:#010x} without "
                f"saying so")
        if address & ~3 == 0:
            raise AbiError(
                f"a doorbell at address {address:#x} could never ring: the "
                f"core says no doorbell rang with 0, so 0 cannot be one")
        if not self._lib.riscv32_map_doorbell(
                self._handle, address, value, ring_mask, write_trigger):
            raise AbiError(
                f"0x{address:08x} is a register of a snapshot counter: "
                f"replacing one of its three would leave the other two as "
                f"plain words that read back what was written")
        self._services.pop(address & ~3, None)

    def on_ring(self, address: int,
                service: Callable[[Cpu, int], None]) -> None:
        """What answers the doorbell at `address`: `service(cpu, address)`,
        called by `step` once the ringing instruction has retired. Replaces
        any earlier service for it.

        A `DeviceRefusal` from the service is the device refusing, and `step`
        raises `Refused` from it; anything else it raises is a bug in the
        service, and `step` raises `ServiceFault` from that. Refused, naming
        the address, where it is no doorbell: a service registered before
        `map_doorbell` would be dropped by it, and the ring would then say
        no service was registered.
        """
        if not self._lib.riscv32_is_doorbell(self._handle, address):
            raise AbiError(
                f"0x{address:08x} is no doorbell; map_doorbell maps one, and "
                f"before on_ring")
        self._services[address & ~3] = service

    def map_fifo(self, address: int, *, enable: int, enable_mask: int) -> None:
        """A byte FIFO on each side of `address`.

        A write appends its low byte for `take_written` while `enable &
        enable_mask` is set, and faults through a gate that is not mapped. A
        read pops the oldest byte `hold_readable` gave, and **faults when
        nothing is held**: a plausible byte one instruction late would be
        read as the device's answer. See `cpu.h`.

        An `enable_mask` of zero is refused, with the values: a gate that is
        never open captures nothing. So is one that does not fit 32 bits,
        which ctypes would pass truncated.
        """
        if not 1 <= enable_mask <= 0xFFFFFFFF:
            raise AbiError(
                f"enable_mask for the FIFO at 0x{address:08x} must be 1 to "
                f"0xffffffff, got {enable_mask!r}: a gate that is never open "
                f"captures nothing, and ctypes would pass a wider mask as "
                f"{enable_mask & 0xFFFFFFFF:#010x} without saying so")
        for name, at in (("address", address), ("enable", enable)):
            if not 0 <= at <= 0xFFFFFFFF:
                raise AbiError(
                    f"the FIFO's {name} must fit in 32 bits, got {at!r}: "
                    f"ctypes would pass it as {at & 0xFFFFFFFF:#010x} without "
                    f"saying so")
        if not self._lib.riscv32_map_fifo(
                self._handle, address, enable, enable_mask):
            raise AbiError(
                f"0x{address:08x} is a register of a snapshot counter: "
                f"replacing one of its three would leave the other two as "
                f"plain words that read back what was written")

    def take_written(self, address: int) -> bytes:
        """Everything written to the FIFO at `address` since it was last
        taken, oldest first, and forget it. Empty where `address` is no FIFO
        or nothing was written.

        The core takes nothing when the buffer is too small, and says how many
        there were; a mismatch here is raised with both numbers, not
        returned as a prefix.
        """
        count = self._lib.riscv32_written_count(self._handle, address)
        if count == 0:
            return b""
        buffer = (ctypes.c_uint8 * count)()
        taken = self._lib.riscv32_take_written(
            self._handle, address, buffer, count)
        if taken != count:
            raise AbiError(
                f"the FIFO at 0x{address:08x} held {count} bytes and then "
                f"{taken}: nothing steps this core between the two calls")
        return bytes(buffer)

    def hold_readable(self, address: int, data: bytes) -> None:
        """The bytes reads of the FIFO at `address` pop, oldest first.
        Replaces what was held and not yet read. Refused, naming the address,
        where it is no FIFO."""
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        if not self._lib.riscv32_hold_readable(
                self._handle, address, buffer, len(data)):
            raise AbiError(
                f"0x{address:08x} is no FIFO; map_fifo maps one")

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

        A fourth, `HostFault`, means the core itself is broken: it faulted on
        the host, and is raised chained from the `OSError` ctypes raised. A
        closed Cpu is refused first: the core would fault on its null handle,
        and that is not a bug in the core.

        And two that follow a RETIRED instruction, when it rang a doorbell:
        `Refused`, the service's `DeviceRefusal` or no service at all, and
        `ServiceFault`, the service raising anything else. Both carry the
        PC the ringing instruction began at; the PC register is past it.
        """
        if not self._handle:
            raise AbiError("this Cpu has been closed")
        try:
            result = self._lib.riscv32_step(self._handle)
        except OSError as fault:
            raise self._host_fault(fault) from fault
        if result == OK:
            return
        if result == RANG:
            self._answer_ring()
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
        present = self._fault_why() or (
            "present but not executable" if self.in_range(address, 2)
            else "unmapped")
        raise MemoryFault(
            f"pc=0x{pc:08x}: {kind} at 0x{address:08x} refused ({present})"
        )

    def _answer_ring(self) -> None:
        """Run the service for the doorbell the step just rang.

        Called with the ringing instruction retired. `Refused` carries the PC
        that instruction began at, from `riscv32_step_entry`: the PC register
        is already past it.
        """
        address = self._lib.riscv32_rang_at(self._handle)
        entry = self._lib.riscv32_step_entry(self._handle)
        service = self._services.get(address)
        if service is None:
            raise Refused(
                entry, address,
                "no service is registered for it; on_ring registers one")
        try:
            service(self, address)
        except DeviceRefusal as reason:
            raise Refused(entry, address, str(reason)) from reason
        except Exception as error:
            raise ServiceFault(entry, address, error) from error

    def _host_fault(self, fault: OSError) -> HostFault:
        """The `HostFault` for `fault`: the PC the step began at, the
        halfwords there, and where the core left the PC.

        Once an instruction has moved PC, PC names the next one;
        `riscv32_step_entry` is where the core recorded the step began, read
        only after a fault, so nothing is read per step.

        Each read back is its own call into the core, and a fault that wrecked
        more than one instruction could fault any of them: each that does is
        said, and what was read before it kept, rather than let a second
        `OSError` replace the one being described.
        """
        failed: list[str] = []
        at: int | None = None
        try:
            at = int(self._lib.riscv32_step_entry(self._handle))
        except OSError as unreadable:
            failed.append(f"where the step began ({unreadable})")
        code: list[int] = []
        if at is not None:
            try:
                for address in range(at, at + 2 * FAULT_HALFWORDS, 2):
                    if not self.in_range(address, 2):
                        break
                    code.append(int.from_bytes(self.read_block(address, 2), "little"))
            except OSError as unreadable:
                failed.append(f"the halfwords there ({unreadable})")
        left: int | None = None
        try:
            left = int(self.get_regs().pc)
        except OSError as unreadable:
            failed.append(f"the registers ({unreadable})")

        said = [f"riscv32: the core faulted on the host ({fault}) "
                + (f"in the step that began at 0x{at:08x}" if at is not None
                   else "in a step")]
        if code:
            said.append(f"the first {len(code)} halfwords there, low first, are "
                        + " ".join(f"0x{halfword:04x}" for halfword in code))
        if left is not None:
            said.append(f"the PC is now 0x{left:08x}")
        if failed:
            said.append(f"reading back {' and '.join(failed)} faulted as well")
        if WILD_WRITE in str(fault):
            after = ("a write in the core went astray, so this process may be "
                     "damaged beyond the machine: restart it rather than reload")
        else:
            after = ("the machine stopped part-way through the instruction: "
                     "load the image again before running it")
        message = (f"{'; '.join(said)}. That is a bug in core/riscv32, not in "
                   f"the firmware; {after}.")
        return HostFault(message, at, tuple(code), left)

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
