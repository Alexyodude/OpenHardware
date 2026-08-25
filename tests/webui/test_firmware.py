# OpenHardware — tests for the firmware format layer.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Every fixture here is **built in this file**, not read from disk. The rules
# under test were learned from real PlatformIO and Arduino builds, but a test
# that needs a 4 MB artefact present is a test that silently stops running.
# So the measured facts are encoded as constructed bytes, and the constants
# they came from are named in the assertions.
#
# Real-artefact figures these fixtures stand in for, all measured on this
# machine from builds of blink:
#   nucleo_g031k8  firmware.elf  entry 0x080028F5, MSP 0x20002000,
#                                .data LMA 0x080035C0 vs VMA 0x20000000
#   pico           firmware.uf2  292 blocks, family RP2040, vectors at +0x100
#   official       blink.uf2     2048 blocks = 1029 RP2040 + 1019 RP2XXX_ABSOLUTE,
#                                both starting at 0x10000000

import struct

import pytest

from webui.firmware import (
    UF2_MAGIC_END,
    UF2_MAGIC_START0,
    UF2_MAGIC_START1,
    EmptyImage,
    FirmwareError,
    Image,
    Segment,
    load_image,
    parse_bin,
    parse_elf,
    parse_hex,
    parse_uf2,
    read_vector_table,
    uf2_family_name,
)

RP2040 = 0xE48BFF56
RP2XXX_ABSOLUTE = 0xE48BFF57
#: The other end of the wrong-family case: a real chip whose UF2 a person
#: genuinely might hand to an RP2040 board, which is how OH-32 found the defect.
ESP32C3 = 0xD42BA06C
FLAG_FAMILY = 0x2000
FLAG_NOT_MAIN_FLASH = 0x1


def uf2_block(
    address, payload, *, family=RP2040, block_no=0, num_blocks=1, flags=FLAG_FAMILY,
    magic0=UF2_MAGIC_START0, magic_end=UF2_MAGIC_END,
):
    """One 512-byte UF2 block, with every field reachable from a test."""
    block = bytearray(512)
    struct.pack_into(
        "<8I", block, 0,
        magic0, UF2_MAGIC_START1, flags, address,
        len(payload), block_no, num_blocks, family,
    )
    block[32:32 + len(payload)] = payload
    struct.pack_into("<I", block, 508, magic_end)
    return bytes(block)


def elf32(segments, *, entry=0x08000100, cls=1, endian=1):
    """A minimal 32-bit ELF carrying `(p_paddr, p_vaddr, data, memsz)` entries."""
    phnum = len(segments)
    phoff = 52
    body = phoff + phnum * 32
    blobs, headers = bytearray(), bytearray()
    for paddr, vaddr, data, memsz in segments:
        offset = body + len(blobs)
        blobs += data
        headers += struct.pack(
            "<8I", 1, offset, vaddr, paddr, len(data), memsz, 0x5, 4)
    header = bytearray(52)
    header[0:4] = b"\x7fELF"
    header[4], header[5], header[6] = cls, endian, 1
    struct.pack_into("<HHI", header, 16, 2, 0x28, 1)      # ET_EXEC, EM_ARM
    struct.pack_into("<III", header, 24, entry, phoff, 0)
    struct.pack_into("<HHH", header, 40, 52, 32, phnum)   # ehsize, phentsize, phnum
    return bytes(header) + bytes(headers) + bytes(blobs)


def hex_record(kind, address, payload):
    body = bytes([len(payload)]) + address.to_bytes(2, "big") + bytes([kind]) + payload
    return ":" + (body + bytes([(-sum(body)) & 0xFF])).hex().upper()


# --- UF2 -------------------------------------------------------------------


def test_a_single_family_file_reads_back_its_payload():
    data = uf2_block(0x10000000, b"\xaa" * 256, num_blocks=2, block_no=0)
    data += uf2_block(0x10000100, b"\xbb" * 256, num_blocks=2, block_no=1)
    image = parse_uf2(data)
    assert image.format == "uf2"
    assert image.family == "RP2040"
    assert len(image.segments) == 1, "touching blocks should merge into one region"
    assert image.segments[0].address == 0x10000000
    assert image.total_bytes == 512


def test_blocks_are_self_locating_so_order_does_not_matter():
    """The spec's robustness section exists because operating systems reorder
    and rewrite blocks during a drag-and-drop copy."""
    later = uf2_block(0x10000100, b"\xbb" * 256, block_no=1, num_blocks=2)
    first = uf2_block(0x10000000, b"\xaa" * 256, block_no=0, num_blocks=2)
    image = parse_uf2(later + first)
    assert image.segments[0].address == 0x10000000
    assert image.segments[0].data[:1] == b"\xaa"
    assert image.segments[0].data[256:257] == b"\xbb"


def test_a_multi_family_file_is_refused_rather_than_guessed():
    """The official blink.uf2 is exactly this shape, and both images start at
    0x10000000 -- so silently taking all blocks writes one over the other."""
    data = uf2_block(0x10000000, b"\x11" * 256, family=RP2040)
    data += uf2_block(0x10000000, b"\x22" * 256, family=RP2XXX_ABSOLUTE)
    with pytest.raises(FirmwareError) as caught:
        parse_uf2(data)
    message = str(caught.value)
    assert "RP2040" in message and "RP2XXX_ABSOLUTE" in message, (
        "the error must name the families present, or the reader cannot act on it")


def test_choosing_a_family_keeps_only_that_one_and_says_what_it_skipped():
    data = uf2_block(0x10000000, b"\x11" * 256, family=RP2040)
    data += uf2_block(0x10000000, b"\x22" * 256, family=RP2XXX_ABSOLUTE)
    for name, marker in (("RP2040", 0x11), ("RP2XXX_ABSOLUTE", 0x22)):
        image = parse_uf2(data, family=name)
        assert image.total_bytes == 256
        assert set(image.segments[0].data) == {marker}
        assert any("skipped" in note for note in image.notes), (
            "a reader who is not told about the other image believes they "
            "loaded the whole file")


def test_a_mismatched_family_block_contributes_nothing_at_all():
    """The spec says disregard the whole block, *including* blockNo and
    numBlocks. Here the wrong-family block claims 999 blocks; if its header
    were honoured the count note would report 999."""
    data = uf2_block(0x10000000, b"\x11" * 256, family=RP2040, num_blocks=1)
    data += uf2_block(0x20000000, b"\x22" * 256, family=RP2XXX_ABSOLUTE, num_blocks=999)
    image = parse_uf2(data, family="RP2040")
    assert image.total_bytes == 256
    assert image.span == (0x10000000, 0x10000100)
    assert not any("999" in note for note in image.notes)


def test_chunks_that_are_not_uf2_blocks_are_ignored():
    """Which is what lets a UF2 be concatenated with unrelated data."""
    data = uf2_block(0x10000000, b"\xaa" * 256)
    data += uf2_block(0, b"\x00" * 256, magic0=0xDEADBEEF)
    image = parse_uf2(data)
    assert image.total_bytes == 256
    assert any("magic" in note for note in image.notes)


def test_not_main_flash_blocks_are_skipped_but_reported():
    data = uf2_block(0x10000000, b"\xaa" * 256)
    data += uf2_block(0x20000000, b"\xbb" * 256, flags=FLAG_FAMILY | FLAG_NOT_MAIN_FLASH)
    image = parse_uf2(data)
    assert image.total_bytes == 256
    assert any("not-main-flash" in note for note in image.notes)


def test_a_block_count_mismatch_is_reported_because_truncation_hides_there():
    data = uf2_block(0x10000000, b"\xaa" * 256, num_blocks=292)
    image = parse_uf2(data)
    assert any("292" in note for note in image.notes)


def test_uf2_rejects_a_file_that_is_not_whole_blocks():
    with pytest.raises(FirmwareError, match="512-byte blocks"):
        parse_uf2(uf2_block(0, b"\xaa") + b"\x00" * 3)


def test_uf2_rejects_an_impossible_payload_size():
    block = bytearray(uf2_block(0x10000000, b"\xaa" * 256))
    struct.pack_into("<I", block, 16, 477)  # one past what a block can hold
    with pytest.raises(FirmwareError, match="476"):
        parse_uf2(bytes(block))


def test_an_unknown_family_is_shown_as_its_id_not_guessed():
    assert uf2_family_name(0xE48BFF56) == "RP2040"
    assert uf2_family_name(0x12345678) == "0x12345678"


# --- ELF -------------------------------------------------------------------


def test_elf_loads_by_physical_address_not_virtual():
    """The one that matters. A real STM32 .data has LMA 0x080035C0 and VMA
    0x20000000; using the virtual address puts initialisers in RAM, which
    survives until reset and then gets overwritten by startup code."""
    data = elf32([
        (0x08000000, 0x08000000, b"\x01" * 64, 64),
        (0x080035C0, 0x20000000, b"\x02" * 32, 1124),
    ])
    image = parse_elf(data)
    addresses = [s.address for s in image.segments]
    assert 0x080035C0 in addresses, "initialised data must load at its LMA"
    assert 0x20000000 not in addresses, "loading at the VMA is the classic bug"
    assert any("0x20000000" in note for note in image.notes), (
        "the LMA/VMA split should be reported, not silently handled")


def test_elf_skips_bss_and_reports_the_reservation():
    image = parse_elf(elf32([(0x08000000, 0x08000000, b"\x01" * 16, 16),
                             (0x20000100, 0x20000100, b"", 4096)]))
    assert image.total_bytes == 16
    assert any("zero-filled" in note for note in image.notes)


def test_elf_reports_its_entry_point():
    assert parse_elf(elf32([(0x08000000, 0x08000000, b"\x01" * 8, 8)],
                           entry=0x080028F5)).entry == 0x080028F5


def test_elf_rejections_name_what_was_wrong():
    cases = [
        (b"MZ\x90\x00" + b"\x00" * 64, "not an ELF"),
        (elf32([(0, 0, b"\x01" * 8, 8)], cls=2), "32-bit"),
        (elf32([(0, 0, b"\x01" * 8, 8)], endian=2), "little-endian"),
    ]
    for blob, expected in cases:
        with pytest.raises(FirmwareError, match=expected):
            parse_elf(blob)


def test_an_elf_with_nothing_loadable_raises_rather_than_returning_empty():
    with pytest.raises(FirmwareError, match="no loadable"):
        parse_elf(elf32([(0x20000000, 0x20000000, b"", 1024)]))


# --- Intel HEX -------------------------------------------------------------


def test_hex_honours_the_extended_linear_address_record():
    """Without type 04 every address is 16-bit, so a whole image lands in the
    first 64 KiB and looks plausible."""
    text = "\n".join([
        hex_record(0x04, 0, b"\x08\x00"),          # upper half = 0x0800
        hex_record(0x00, 0x0000, b"\xde\xad"),
        hex_record(0x01, 0, b""),
    ])
    image = parse_hex(text)
    assert image.segments[0].address == 0x08000000, (
        "type 04 sets the upper 16 bits of every following address")


def test_hex_reports_a_start_linear_address_as_the_entry():
    text = "\n".join([
        hex_record(0x00, 0x0000, b"\x01\x02"),
        hex_record(0x05, 0, (0x080028F5).to_bytes(4, "big")),
        hex_record(0x01, 0, b""),
    ])
    assert parse_hex(text).entry == 0x080028F5


def test_a_bad_hex_checksum_names_both_values():
    good = hex_record(0x00, 0, b"\x01\x02")
    broken = good[:-2] + "00"
    with pytest.raises(FirmwareError, match="checksum"):
        parse_hex(broken + "\n" + hex_record(0x01, 0, b""))


def test_hex_without_an_end_record_is_treated_as_truncated():
    with pytest.raises(FirmwareError, match="truncated"):
        parse_hex(hex_record(0x00, 0, b"\x01\x02"))


# --- raw binary and sniffing ----------------------------------------------


def test_a_raw_binary_needs_its_base_stated():
    """No default: 0x08000000 on STM32, 0x10000000 on RP2040, 0x0 for an
    ESP32-C3 bootloader. A default is right for one and wrong for the rest."""
    with pytest.raises(FirmwareError, match="base="):
        load_image(b"\x00\x20\x00\x20" * 4)
    assert parse_bin(b"\xff" * 16, 0x08000000).segments[0].address == 0x08000000


def test_load_image_identifies_each_format_from_its_own_bytes():
    samples = [
        (elf32([(0x08000000, 0x08000000, b"\x01" * 8, 8)]), "elf"),
        (uf2_block(0x10000000, b"\xaa" * 256), "uf2"),
        ((hex_record(0x00, 0, b"\x01") + "\n" + hex_record(0x01, 0, b"")).encode(), "hex"),
    ]
    for blob, expected in samples:
        assert load_image(blob).format == expected


# --- reading back ----------------------------------------------------------


def test_read_returns_none_outside_the_image_rather_than_zeroes():
    image = Image(format="bin", segments=(Segment(0x08000000, b"\x01" * 16),))
    assert image.read(0x08000000, 4) == b"\x01\x01\x01\x01"
    assert image.read(0x08000010, 4) is None, "past the end is absent, not zero"
    assert image.read(0x0800000E, 4) is None, "a partial overlap is not a read"


def test_the_vector_table_address_must_be_given_because_rp2040_differs():
    """An earlier version read the lowest segment's first word. That is the
    vector table on STM32 and is boot2 on RP2040 -- 256 bytes of flash-XIP
    setup -- so it returned two instructions as a stack pointer and reported
    success."""
    boot2 = b"\x00\xb5\x32\x4b"
    vectors = struct.pack("<II", 0x20040000, 0x100001E3)
    image = Image(
        format="uf2",
        segments=(Segment(0x10000000, boot2 + b"\x00" * 252 + vectors),),
    )
    assert read_vector_table(image, 0x10000100) == (0x20040000, 0x100001E3)
    assert read_vector_table(image, 0x10000000) != (0x20040000, 0x100001E3)
    assert read_vector_table(image, 0x90000000) is None


def test_overlapping_regions_raise_rather_than_silently_winning():
    with pytest.raises(FirmwareError, match="overlapping"):
        parse_uf2(uf2_block(0x10000000, b"\xaa" * 256)
                  + uf2_block(0x10000080, b"\xbb" * 256))


# --- nothing to load is never a success ------------------------------------
#
# The defect OH-32 found and OH-10 fixed, and the tripwire that stops it
# arriving through a format nobody has written yet.


def test_no_parser_reports_success_with_nothing_to_load():
    """**Every** parser, in one table, so a fifth format has to answer the
    question rather than inherit the bug.

    Two of the four had it. `parse_uf2` returned an empty Image for a family
    the file did not hold -- and labelled it with the family that had been
    *asked for* -- and `parse_hex` did the same for a file with no data
    records. `parse_elf` and `parse_bin` already refused.

    Written as a list rather than four separate tests because the point is the
    *closure*: what would go wrong is somebody adding `parse_srec` and not
    thinking about it, and a table with a missing row is visible in a way that
    a missing test file is not.
    """
    # An extended-linear-address record and an end-of-file record:
    # structurally valid, and not one byte of type-00 payload in it.
    empty_hex = ":020000040800F2\n:00000001FF\n"
    cases = (
        ("uf2, family not in the file",
         lambda: parse_uf2(uf2_block(0x10000000, b"\x11" * 16, family=RP2040),
                           family="ESP32C3")),
        ("uf2, every payload empty",
         lambda: parse_uf2(uf2_block(0x10000000, b"", family=RP2040))),
        ("hex, valid but no type-00 records",
         lambda: parse_hex(empty_hex)),
        ("elf, program headers but no PT_LOAD bytes",
         lambda: parse_elf(elf32([(0x20000000, 0x20000000, b"", 1024)]))),
    )
    for name, parse in cases:
        with pytest.raises(EmptyImage) as caught:
            parse()
        assert str(caught.value), f"{name}: raised with no message"


def test_a_zero_byte_binary_is_a_broken_file_rather_than_an_empty_image():
    """The other half of the rule, and the reason `EmptyImage` is a subclass.

    A UF2 for another chip is a good file this board cannot use; zero bytes is
    not a file anybody could use. The first sends a person to their board
    picker and the second to their build, so they are different types -- and
    both are `FirmwareError`, so a caller that does not care catches both.
    """
    with pytest.raises(FirmwareError) as caught:
        parse_bin(b"", 0x08000000)
    assert not isinstance(caught.value, EmptyImage), (
        "zero bytes is a broken artefact, not a well-formed one holding nothing"
    )
    assert issubclass(EmptyImage, FirmwareError)


def test_the_empty_uf2_names_what_was_asked_for_and_what_was_there():
    """`.claude/CLAUDE.md` rule 9: errors carry the values that caused them.

    The old behaviour carried none, because there was no error -- and the
    Image it returned claimed `family="RP2040"` for a file holding no RP2040
    block at all, which is worse than silence.
    """
    data = uf2_block(0x42000020, b"\x11" * 16, family=ESP32C3)
    with pytest.raises(EmptyImage) as caught:
        parse_uf2(data, family="RP2040")
    message = str(caught.value)
    assert "RP2040" in message, "what was asked for"
    assert "ESP32C3" in message, "what the file holds"
    assert "1 block" in message, "and how much of it"


def test_load_image_lets_the_empty_result_through_as_itself():
    """`load_image` dispatches on the file's own bytes and must not flatten the
    distinction on the way -- `webui/api.py` catches `EmptyImage` by type to
    decide between two refusals that send a person to different places."""
    data = uf2_block(0x42000020, b"\x11" * 16, family=ESP32C3)
    with pytest.raises(EmptyImage):
        load_image(data, family="RP2040")
