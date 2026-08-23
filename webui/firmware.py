#!/usr/bin/env python3
# OpenHardware — read what PlatformIO, the Arduino IDE and picotool emit.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Turn a build artefact into an address-tagged image.

This is the **format layer only**. It has no transport, no board, and no
opinion about what runs the result — the same split `webui/api.py` keeps
between the operations and the socket underneath them. Everything here is
pure stdlib and takes `bytes` in and an `Image` out, so it is testable with
no toolchain, no hardware and no simulator.

`docs/tickets/OH-10.md` is honest that parsing is most of what can be
delivered today: only XIAO ESP32-C3 has a backend, so firmware for RP2040,
SAMD21, nRF52840 and MG24 can be read and inspected but not executed. Reading
it correctly is still worth doing first, because every one of the rules below
was learned by building real firmware and watching a plausible-looking loader
get it wrong.

## The three rules that are not obvious

**ELF: load by `p_paddr`, never `p_vaddr`.** In a real STM32 build `.data` has
VirtAddr `0x20000000` and PhysAddr `0x080035C0`. The virtual address is where
the linker says the section *lives at run time*; the physical one is where the
initialiser bytes are actually stored in flash. A loader using `p_vaddr` writes
initialisers into RAM, which looks fine until reset, when startup code copies
whatever is at the flash address over them.

**UF2: filter by `familyID`, or corrupt silently.** `numBlocks` is per *family*,
not per file, and the specification says a block whose family does not match
must be disregarded **entirely — including its `blockNo` and `numBlocks`**.
That is what makes concatenated multi-family files legal, and Raspberry Pi now
ships exactly that: the official `blink.uf2` is 2048 blocks holding an RP2040
image *and* an `RP2XXX_ABSOLUTE` image, both starting at `0x10000000`. A loader
that walks every block and writes each payload to its `targetAddr` produces a
file that looks complete and is two programs on top of each other.

**Intel HEX addresses are 16-bit until a type-04 record says otherwise.** The
upper half comes from the most recent extended-linear-address record, and a
parser that ignores those silently packs a whole image into the first 64 KiB.

## What this deliberately does not do

No execution, no relocation, no symbol table. `entry` is reported where the
format states it and left `None` where it does not — a `.bin` has no entry
point, and inventing one from the vector table would be a guess wearing a
fact's clothes. `read_vector_table` exists for callers that want that, and it makes them
name the address rather than assume one.
"""

from __future__ import annotations

import dataclasses
import struct

# --- UF2 -----------------------------------------------------------------

UF2_BLOCK = 512
UF2_MAGIC_START0 = 0x0A324655  # "UF2\n"
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30

UF2_FLAG_NOT_MAIN_FLASH = 0x00000001
UF2_FLAG_FILE_CONTAINER = 0x00001000
UF2_FLAG_FAMILY_ID = 0x00002000
UF2_FLAG_MD5 = 0x00004000
UF2_FLAG_EXTENSION_TAGS = 0x00008000

#: Family IDs, from microsoft/uf2's `utils/uf2families.json`. Only the ones a
#: board on this project's list can actually produce. The RP2350 entries are
#: here because Raspberry Pi ships universal Pico1+Pico2 binaries, which is
#: how a single file comes to hold two images.
UF2_FAMILIES = {
    0xE48BFF56: "RP2040",
    0xE48BFF57: "RP2XXX_ABSOLUTE",
    0xE48BFF58: "RP2XXX_DATA",
    0xE48BFF59: "RP2350_ARM_S",
    0xE48BFF5A: "RP2350_RISCV",
    0xE48BFF5B: "RP2350_ARM_NS",
    0x68ED2B88: "SAMD21",
    0x55114460: "SAMD51",
    0x1851780A: "SAMD21_M0",
    0xADA52840: "NRF52840",
    0x5EE21072: "STM32F103",
    0x57755A57: "STM32F4",
    0x53B80F00: "STM32F7",
    0x5D1A0A2E: "STM32F2",
    0x6D0922FA: "ESP32",
    0xD42BA06C: "ESP32C3",
    0xC47E5767: "ESP32S2",
    0xBFDD4EEE: "ESP32S3",
}


def uf2_family_name(family_id: int) -> str:
    """A readable family name, or the raw id — never a silent guess."""
    return UF2_FAMILIES.get(family_id, f"0x{family_id:08X}")


# --- ELF ------------------------------------------------------------------

ELF_MAGIC = b"\x7fELF"
ELF_CLASS_32 = 1
ELF_DATA_LSB = 1
PT_LOAD = 1


# --- the result -----------------------------------------------------------


class FirmwareError(Exception):
    """An artefact that cannot be read, or can be read two ways."""


@dataclasses.dataclass(frozen=True)
class Segment:
    """A run of bytes and the address they load at."""

    address: int
    data: bytes

    def __len__(self) -> int:
        return len(self.data)

    @property
    def end(self) -> int:
        """One past the last address this segment covers."""
        return self.address + len(self.data)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Segment(0x{self.address:08x}..0x{self.end:08x}, {len(self.data)} bytes)"


@dataclasses.dataclass(frozen=True)
class Image:
    """Everything a loader needs, and a record of what was assumed.

    `notes` is not decoration. A caller that shows an image to a human has to
    be able to say "this file also contained an RP2350 image, which was
    skipped" — otherwise the reader believes they loaded the whole file.
    """

    format: str
    segments: tuple[Segment, ...]
    entry: int | None = None
    family: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(len(s) for s in self.segments)

    @property
    def span(self) -> tuple[int, int] | None:
        """Lowest and highest address touched, or None when empty."""
        if not self.segments:
            return None
        return (min(s.address for s in self.segments),
                max(s.end for s in self.segments))

    def read(self, address: int, count: int) -> bytes | None:
        """`count` bytes from `address`, or None if not wholly present.

        None rather than zero-fill: an address this image does not cover is
        not the same as an address it covers with zeros, and a caller reading
        a vector table needs to tell those apart.
        """
        for segment in self.segments:
            if segment.address <= address and address + count <= segment.end:
                start = address - segment.address
                return segment.data[start:start + count]
        return None


def _merge(pairs: list[tuple[int, bytes]]) -> tuple[Segment, ...]:
    """Sort by address and join runs that touch, so a caller sees regions.

    UF2 and HEX both arrive as hundreds of small pieces. Handing those back
    unmerged would make every consumer re-implement this, and would make a
    genuinely sparse image indistinguishable from a contiguous one delivered
    in fragments.
    """
    if not pairs:
        return ()
    pairs.sort(key=lambda p: p[0])
    out: list[list] = [[pairs[0][0], bytearray(pairs[0][1])]]
    for address, data in pairs[1:]:
        last = out[-1]
        end = last[0] + len(last[1])
        if address == end:
            last[1] += data
        elif address < end:
            raise FirmwareError(
                f"overlapping data at 0x{address:08x}: "
                f"already covered up to 0x{end:08x}"
            )
        else:
            out.append([address, bytearray(data)])
    return tuple(Segment(a, bytes(d)) for a, d in out)


# --- UF2 ------------------------------------------------------------------


def parse_uf2(data: bytes, *, family: int | str | None = None) -> Image:
    """Read a UF2, keeping exactly one family.

    `family` may be an id, a name from `UF2_FAMILIES`, or None. **None is only
    valid when the file holds one family**; a multi-family file raises rather
    than picking, because picking is how the RP2040/RP2350 universal build
    silently becomes two programs at the same addresses.
    """
    if len(data) % UF2_BLOCK:
        raise FirmwareError(
            f"not a whole number of 512-byte blocks: {len(data)} bytes "
            f"({len(data) % UF2_BLOCK} left over)"
        )
    if not data:
        raise FirmwareError("empty file")

    wanted: int | None = None
    if isinstance(family, str):
        matches = [k for k, v in UF2_FAMILIES.items() if v == family]
        if not matches:
            raise FirmwareError(
                f"unknown family name {family!r}; known: "
                + ", ".join(sorted(UF2_FAMILIES.values()))
            )
        wanted = matches[0]
    elif family is not None:
        wanted = int(family)

    seen: dict[int, int] = {}
    pairs: list[tuple[int, bytes]] = []
    skipped_bad_magic = 0
    skipped_not_main_flash = 0
    claimed: int | None = None

    for offset in range(0, len(data), UF2_BLOCK):
        block = data[offset:offset + UF2_BLOCK]
        magic0, magic1, flags, address, payload_size, _block_no, num_blocks, family_id = (
            struct.unpack_from("<8I", block)
        )
        magic_end = struct.unpack_from("<I", block, 508)[0]
        if (magic0 != UF2_MAGIC_START0 or magic1 != UF2_MAGIC_START1
                or magic_end != UF2_MAGIC_END):
            # The spec says ignore the chunk entirely -- this is how a UF2 can
            # be concatenated with unrelated data and still work.
            skipped_bad_magic += 1
            continue

        has_family = bool(flags & UF2_FLAG_FAMILY_ID)
        key = family_id if has_family else -1
        seen[key] = seen.get(key, 0) + 1

        if wanted is not None and (not has_family or family_id != wanted):
            # Disregard the WHOLE block, including blockNo and numBlocks.
            continue
        if flags & UF2_FLAG_NOT_MAIN_FLASH:
            skipped_not_main_flash += 1
            continue
        if payload_size > 476:
            raise FirmwareError(
                f"block at offset {offset}: payloadSize {payload_size} "
                "exceeds the 476 bytes a UF2 block can hold"
            )
        claimed = num_blocks
        pairs.append((address, block[32:32 + payload_size]))

    families = sorted(k for k in seen if k >= 0)
    if wanted is None:
        if len(families) > 1:
            raise FirmwareError(
                "file holds more than one family and none was requested: "
                + ", ".join(f"{uf2_family_name(f)} ({seen[f]} blocks)" for f in families)
                + " -- pass family= to choose, because loading both would write "
                "two images over each other"
            )
        if families:
            wanted = families[0]
            pairs = []
            for offset in range(0, len(data), UF2_BLOCK):
                block = data[offset:offset + UF2_BLOCK]
                m0, m1, flags, address, payload_size, _n, num_blocks, fid = (
                    struct.unpack_from("<8I", block))
                if m0 != UF2_MAGIC_START0 or m1 != UF2_MAGIC_START1:
                    continue
                if fid != wanted or (flags & UF2_FLAG_NOT_MAIN_FLASH):
                    continue
                claimed = num_blocks
                pairs.append((address, block[32:32 + payload_size]))

    notes: list[str] = []
    if skipped_bad_magic:
        notes.append(f"{skipped_bad_magic} chunks ignored: magic did not match")
    if skipped_not_main_flash:
        notes.append(
            f"{skipped_not_main_flash} blocks skipped: not-main-flash flag set")
    for other in families:
        if other != wanted:
            notes.append(
                f"skipped {seen[other]} blocks of {uf2_family_name(other)} -- "
                "this file holds more than one image")
    if claimed is not None and claimed != len(pairs):
        # Not fatal: numBlocks is per family, and a deliberately partial file
        # is a real thing. But a silent mismatch is how truncation hides.
        notes.append(
            f"header claims {claimed} blocks for this family, {len(pairs)} present")

    return Image(
        format="uf2",
        segments=_merge(pairs),
        entry=None,
        family=uf2_family_name(wanted) if wanted is not None else None,
        notes=tuple(notes),
    )


# --- ELF ------------------------------------------------------------------


def parse_elf(data: bytes) -> Image:
    """Read PT_LOAD segments from a 32-bit little-endian ELF, by `p_paddr`."""
    if len(data) < 52 or not data.startswith(ELF_MAGIC):
        raise FirmwareError(
            f"not an ELF: first 4 bytes are {data[:4]!r}, expected {ELF_MAGIC!r}")
    if data[4] != ELF_CLASS_32:
        raise FirmwareError(
            f"only 32-bit ELF is supported; EI_CLASS is {data[4]} "
            "(2 means 64-bit, which no board on this list uses)")
    if data[5] != ELF_DATA_LSB:
        raise FirmwareError(
            f"only little-endian ELF is supported; EI_DATA is {data[5]}")

    entry, phoff = struct.unpack_from("<II", data, 0x18)
    phentsize, phnum = struct.unpack_from("<HH", data, 0x2A)
    if phnum == 0:
        raise FirmwareError("ELF has no program headers, so nothing to load")
    if phentsize < 32:
        raise FirmwareError(f"program header entries are {phentsize} bytes, expected >= 32")

    pairs: list[tuple[int, bytes]] = []
    notes: list[str] = []
    for i in range(phnum):
        base = phoff + i * phentsize
        if base + 32 > len(data):
            raise FirmwareError(
                f"program header {i} at {base} runs past the end of a "
                f"{len(data)}-byte file")
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz = struct.unpack_from(
            "<6I", data, base)
        if p_type != PT_LOAD:
            continue
        if p_memsz > p_filesz:
            # Reported before the .bss skip below, not after. A segment that
            # supplies nothing still reserves RAM, and a caller showing an
            # image to a human needs to say so -- an earlier version dropped
            # pure-.bss segments silently and under-reported the footprint.
            reserved = p_memsz - p_filesz
            notes.append(
                f"segment {i} reserves {reserved} bytes at 0x{p_paddr:08x} "
                + ("and supplies none -- .bss" if p_filesz == 0
                   else "beyond the bytes it supplies")
                + ", zero-filled at run time")
        if p_filesz == 0:
            continue
        if p_offset + p_filesz > len(data):
            raise FirmwareError(
                f"segment {i} wants bytes {p_offset}..{p_offset + p_filesz} "
                f"of a {len(data)}-byte file")
        pairs.append((p_paddr, data[p_offset:p_offset + p_filesz]))
        if p_paddr != p_vaddr:
            notes.append(
                f"segment {i} loads at 0x{p_paddr:08x} but runs at 0x{p_vaddr:08x} "
                "-- initialised data, copied by startup code")

    if not pairs:
        raise FirmwareError("ELF has program headers but no loadable PT_LOAD bytes")
    return Image(format="elf", segments=_merge(pairs), entry=entry, notes=tuple(notes))


# --- Intel HEX ------------------------------------------------------------


def parse_hex(text: str | bytes) -> Image:
    """Read Intel HEX, honouring the extended-address records."""
    if isinstance(text, bytes):
        text = text.decode("ascii", errors="replace")

    upper = 0          # from type 04 (linear) or type 02 (segment), pre-shifted
    entry: int | None = None
    pairs: list[tuple[int, bytes]] = []
    saw_eof = False

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise FirmwareError(f"line {number}: record does not start with ':': {line[:20]!r}")
        try:
            body = bytes.fromhex(line[1:])
        except ValueError as exc:
            raise FirmwareError(f"line {number}: not hex: {exc}") from exc
        if len(body) < 5:
            raise FirmwareError(f"line {number}: {len(body)} bytes, minimum is 5")

        count, address, kind = body[0], int.from_bytes(body[1:3], "big"), body[3]
        payload = body[4:4 + count]
        if len(payload) != count:
            raise FirmwareError(
                f"line {number}: header says {count} data bytes, {len(payload)} present")
        if (sum(body) & 0xFF) != 0:
            raise FirmwareError(
                f"line {number}: checksum is 0x{body[-1]:02x}, "
                f"but the record sums to 0x{sum(body) & 0xFF:02x} (should be 0)")

        if kind == 0x00:
            pairs.append((upper + address, payload))
        elif kind == 0x01:
            saw_eof = True
            break
        elif kind == 0x02:
            upper = int.from_bytes(payload, "big") << 4
        elif kind == 0x03:
            cs, ip = struct.unpack(">HH", payload)
            entry = (cs << 4) + ip
        elif kind == 0x04:
            upper = int.from_bytes(payload, "big") << 16
        elif kind == 0x05:
            entry = int.from_bytes(payload, "big")
        else:
            raise FirmwareError(f"line {number}: unknown record type 0x{kind:02x}")

    if not saw_eof:
        raise FirmwareError("no end-of-file record (type 01) -- the file is truncated")
    return Image(format="hex", segments=_merge(pairs), entry=entry)


# --- raw binary -----------------------------------------------------------


def parse_bin(data: bytes, base: int) -> Image:
    """Wrap a flat binary at an address the caller must supply.

    There is no `base` default on purpose. A `.bin` carries no address, and
    every family puts it somewhere different -- 0x08000000 on STM32,
    0x10000000 on RP2040, 0x0 or 0x1000 for an ESP bootloader. A default would
    be right for one board and quietly wrong for the rest.
    """
    if not data:
        raise FirmwareError("empty file")
    return Image(format="bin", segments=(Segment(base, data),))


# --- sniffing -------------------------------------------------------------


def load_image(
    data: bytes, *, base: int | None = None, family: int | str | None = None
) -> Image:
    """Identify the format from its own bytes and parse it."""
    if data.startswith(ELF_MAGIC):
        return parse_elf(data)
    if len(data) >= 8 and struct.unpack_from("<2I", data) == (
        UF2_MAGIC_START0, UF2_MAGIC_START1
    ):
        return parse_uf2(data, family=family)
    if data[:1] == b":":
        return parse_hex(data)
    if base is None:
        raise FirmwareError(
            "unrecognised format and no base address given. ELF, UF2 and Intel "
            "HEX identify themselves; a raw .bin cannot, so it needs base= "
            "(0x08000000 STM32, 0x10000000 RP2040, 0x0 ESP32-C3 bootloader)"
        )
    return parse_bin(data, base)


# --- a helper the caller has to ask for by name ---------------------------


def read_vector_table(image: Image, address: int) -> tuple[int, int] | None:
    """Initial SP and reset address from the Cortex-M vector table at `address`.

    Armv6-M and Armv7-M put the initial stack pointer in the first word and the
    reset handler in the second, with bit 0 set to mean Thumb. Returns None when
    the image does not cover both words.

    **`address` is required, and that is the whole point of this function's
    shape.** An earlier version read the first word of the lowest segment,
    which is right for STM32 — where flash starts with the vector table — and
    silently wrong for RP2040, where the first 256 bytes are `boot2`, the
    flash-XIP setup blob. On a real Pico image it returned `0x4b32b500`, which
    is not a stack pointer but the first two instructions of boot2, and
    reported success. Same reasoning as `parse_bin`'s required `base`: a
    default that is correct for one family and quietly wrong for another is
    worse than no default.

    Known addresses: `0x08000000` for STM32 (or `0x00000000` through the boot
    alias), `0x10000100` for RP2040 — base plus boot2's 256 bytes.
    """
    words = image.read(address, 8)
    if words is None:
        return None
    sp, reset = struct.unpack("<II", words)
    return sp, reset
