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
#:
#: 13 adds no function and changes no struct -- it is bumped because the
#: library's *behaviour* changed, not its shape: a core with SysTick takes
#: exceptions where the previous one ran straight on. A stale library would
#: load without complaint and then quietly never deliver a tick, which is the
#: silent mismatch this number exists to turn into a message.
#:
#: 14 adds `cortexm0_step_entry` (OH-225).
ABI_VERSION = 14

#: Must match cortexm0::WriteOp. Spelled at call sites rather than numbered.
WRITE_OPS = {"store": 0, "set": 1, "clear": 2, "xor": 3}

#: Must match cortexm0::StepResult and abi.h's documented return values.
OK = 0
UNIMPLEMENTED = 1
MEMORY_FAULT = 2

#: How many halfwords a `HostFault` shows from where its step began: BL, the
#: one 32-bit encoding on this part, is two.
FAULT_HALFWORDS = 2

#: How ctypes words an access violation that WROTE (its SetException formats
#: "exception: access violation writing 0x..."). A wild write in the core may
#: have landed anywhere in this process, not only in the machine a reload
#: replaces, so a `HostFault` from one says to restart the process instead.
WILD_WRITE = "access violation writing"


class AbiError(Exception):
    """The library is missing, or does not match this binding."""


class Unimplemented(AbiError):
    """The core reached an encoding nobody has written yet."""


class MemoryFault(AbiError):
    """An access outside the modelled memory, or a fetch from a region that
    exists but is not executable."""


class HostFault(AbiError):
    """The core's own code faulted on the host during a step.

    A divide error or an access violation in the C++, which is a bug in the
    core and never in the firmware. On Windows ctypes catches the structured
    exception around the foreign call and raises `OSError`; `Cpu.step` raises
    this from it, so a run loop that stops on `AbiError` -- `webui/api.py`'s
    does -- stops here too instead of losing the request. The machine is left
    part-way through the step, PC included, and should be loaded again rather
    than stepped (OH-225, after OH-223).

    A step is an instruction or, when SysTick is due, the exception entry that
    runs instead of one. Where it began is the same address either way: the
    instruction that ran, or the one the entry interrupted.

    **Windows only.** On Linux the same fault is a signal, SIGFPE or SIGSEGV,
    that ctypes does not catch, and the process ends before this can be
    raised. OH-223's note records why nothing is done about that here.
    """

    def __init__(self, message: str, at: int | None,
                 code: tuple[int, ...], left: int | None) -> None:
        super().__init__(message)
        #: The PC the step began at, or None if reading that back faulted.
        self.at = at
        #: The first `FAULT_HALFWORDS` halfwords there, or as many as were
        #: read before reading them faulted or the region ended.
        self.code = code
        #: The PC the core left, or None if reading it faulted.
        self.left = left


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
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int,
         ctypes.c_int],
        None,
    ),
    "cortexm0_map_mirror": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int,
         ctypes.c_uint32],
        None,
    ),
    "cortexm0_map_constant": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32], None
    ),
    "cortexm0_map_stream": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32],
        None,
    ),
    "cortexm0_stream": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
         ctypes.c_uint32],
        ctypes.c_uint32,
    ),
    "cortexm0_map_counter": (
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32], None
    ),
    "cortexm0_executed": ([ctypes.c_void_p], ctypes.c_uint64),
    "cortexm0_step": ([ctypes.c_void_p], ctypes.c_int),
    "cortexm0_step_entry": ([ctypes.c_void_p], ctypes.c_uint32),
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

    def map_alias(self, address: int, target: int, op: str, *,
                  readable: bool = True) -> None:
        """An address whose write applies `op` to `target`'s word.

        `op` is one of "store", "set", "clear", "xor" -- spelled rather than
        numbered, because a bare 2 at a call site is unreadable and the
        difference between clear and xor is a silent wrong answer.

        `readable=False` for a dedicated write-only register, which reads as
        zero on the part. A bus alias window is readable and returns the
        register it aliases; see the core's `map_alias` for why conflating the
        two answers wrongly rather than loudly.
        """
        try:
            code = WRITE_OPS[op]
        except KeyError:
            raise AbiError(
                f"unknown write op {op!r}; expected one of {sorted(WRITE_OPS)}"
            ) from None
        self._lib.cortexm0_map_alias(
            self._handle, address, target, code, 1 if readable else 0
        )

    def map_mirror(self, address: int, source: int, *, invert: bool = False,
                   mask: int = 0xFFFFFFFF) -> None:
        """An address whose read derives from `source`."""
        self._lib.cortexm0_map_mirror(
            self._handle, address, source, 1 if invert else 0, mask
        )

    def map_constant(self, address: int, value: int) -> None:
        """An address whose reads answer `value` and whose writes are ignored.

        A read-only status register. `map_mirror` cannot stand in for it: a
        mirror reads from a source register and a constant has none.
        """
        self._lib.cortexm0_map_constant(self._handle, address, value)

    def map_stream(self, address: int, *, enable: int, enable_mask: int) -> None:
        """An address whose writes append a byte to a captured stream.

        A UART's data register, where `map_register` would keep only the last
        character written. `enable`/`enable_mask` name the bit that has to be
        set for the bytes to be captured -- `UARTCR.UARTEN` on a PL011 --
        because a disabled transmitter sends nothing and a model without the
        gate lets firmware appear to print before it enabled the peripheral.
        """
        self._lib.cortexm0_map_stream(self._handle, address, enable, enable_mask)

    def map_counter(self, address: int, instructions_per_tick: int) -> None:
        """An address whose read answers `executed // instructions_per_tick`.

        A free-running counter such as the RP2040's TIMERAWL. A register that
        does not advance makes a busy-wait spin forever, and that hang cannot
        be made loud the way a missing register can: the address is modelled
        and the read does answer, it just never changes.

        `instructions_per_tick` is a stated approximation -- this core has no
        cycle model, so virtual time is counted in retired instructions. The
        board picks the number and says what it does not claim.
        """
        self._lib.cortexm0_map_counter(self._handle, address, instructions_per_tick)

    def executed(self) -> int:
        """Instructions retired since this core was created.

        Virtual time's only source, and an integer for the reason
        `rules/determinism.md` §3 gives: a float accumulator makes step size
        affect results.
        """
        return int(self._lib.cortexm0_executed(self._handle))

    def stream(self, address: int) -> bytes:
        """Everything written to a `map_stream` address, oldest first.

        Asked for its length first and read second, rather than guessing a
        buffer size.

        **The second call's return is discarded**, which this docstring said
        was "caught" until the OH-161 review read the next two lines. It is
        safe anyway, for a reason worth stating rather than implying: this
        core advances only when Python steps it, so nothing can write to the
        stream between the two calls. The C side does report the true length
        either way, which is what a caller sizing its own buffer needs.
        """
        length = self._lib.cortexm0_stream(self._handle, address, None, 0)
        if length == 0:
            return b""
        buffer = (ctypes.c_uint8 * length)()
        self._lib.cortexm0_stream(self._handle, address, buffer, length)
        return bytes(buffer)

    # --- running ----------------------------------------------------------

    def step(self) -> None:
        """One instruction, or raise saying why not.

        Raising rather than returning a code, because every caller in this
        repository treats both non-zero results as a stop. The PC is untouched
        in both cases, so the exception message can name the address and the
        caller can read the encoding back out of memory.

        A host fault in the core raises `HostFault`, chained from the
        `OSError` ctypes raised. A closed Cpu is refused first: the core would
        fault on its null handle, and that is not a bug in the core.
        """
        if not self._handle:
            raise AbiError("this Cpu has been closed")
        try:
            result = self._lib.cortexm0_step(self._handle)
        except OSError as fault:
            raise self._host_fault(fault) from fault
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

    def _host_fault(self, fault: OSError) -> HostFault:
        """The `HostFault` for `fault`: the PC the step began at, the
        halfwords there, and where the core left the PC.

        The step advances PC before executing, so after a fault PC names the
        next instruction; `cortexm0_step_entry` is where the core recorded the
        step began, read only after a fault, so nothing is read per step.

        Each read back is its own call into the core, and a fault that wrecked
        more than one instruction could fault any of them: each that does is
        said, and what was read before it kept, rather than let a second
        `OSError` replace the one being described.
        """
        failed: list[str] = []
        at: int | None = None
        try:
            at = int(self._lib.cortexm0_step_entry(self._handle))
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
            left = int(self.get_regs().r[15])
        except OSError as unreadable:
            failed.append(f"the registers ({unreadable})")

        said = [f"cortexm0: the core faulted on the host ({fault}) "
                + (f"in the step that began at 0x{at:08x}" if at is not None
                   else "in a step")]
        if code:
            said.append(f"the first {len(code)} halfwords there are "
                        + " ".join(f"0x{halfword:04x}" for halfword in code))
        if left is not None:
            said.append(f"the PC is now 0x{left:08x}")
        if failed:
            said.append(f"reading back {' and '.join(failed)} faulted as well")
        if WILD_WRITE in str(fault):
            after = ("a write in the core went astray, so this process may be "
                     "damaged beyond the machine: restart it rather than reload")
        else:
            after = ("the machine stopped part-way through the step: load the "
                     "image again before running it")
        message = (f"{'; '.join(said)}. That is a bug in core/cortexm0, not in "
                   f"the firmware; {after}.")
        return HostFault(message, at, tuple(code), left)
