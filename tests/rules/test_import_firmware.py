# OpenHardware — tests for build-artefact discovery.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Every tree here is **synthesised in this file**, and so is every byte. A test
# that needs a 5 MB ELF present is a test that silently stops running the day
# the scratchpad is cleared — which is exactly what happened to this project's
# last set of firmware fixtures.
#
# What the synthesised trees stand in for, measured on this machine on
# 2026-08-24 from a PlatformIO blink build of three environments:
#
#   .pio/build/nucleo_g031k8/       firmware.elf  firmware.bin  firmware.map
#                                   libFrameworkArduino.a  .sconsign314.dblite
#   .pio/build/pico/                firmware.elf  firmware.bin  firmware.uf2
#                                   libFrameworkArduino*.a  cpp.linker_script.ld
#   .pio/build/seeed_xiao_esp32c3/  firmware.elf  firmware.bin  bootloader.bin
#                                   partitions.bin  firmware.map  tmp*.tmp
#
# and the ESP32-C3 application image's own header, likewise measured:
#
#   magic 0xE9, 5 segments, entry 0x40381892, chip id 5, 232,464 bytes
#   0x3C030020 47992 | 0x3FC8A200 7284 | 0x40380000 10236
#   0x42000020 136096 | 0x403827FC 30748          44 trailing bytes
#
# Only the PlatformIO layout was measured. There is no arduino-cli and no
# STM32CubeIDE on this machine, so those two trees prove the path logic and
# nothing about the layout, and the module docstring says so too.

import pathlib
import struct
import typing

import pytest

from tools.import_firmware import (
    ERROR,
    NEEDS_BASE,
    OK,
    ROLE_ORDER,
    Artefact,
    describe,
    find_arduino_cli,
    find_artefacts,
    find_platformio,
    find_stm32cubeide,
    identify_esp_image,
    main,
)

# --- fixtures --------------------------------------------------------------

#: Names a PlatformIO build directory holds that are *not* firmware. The link
#: map is the dangerous one: `firmware.map` is 618 KB for the STM32 and 7.8 MB
#: for the ESP, and a `firmware.*` glob hands it to a firmware parser.
PIO_NOISE = (
    "firmware.map",
    "libFrameworkArduino.a",
    ".sconsign314.dblite",
    "cpp.linker_script.ld",
    "tmp1lq08d9x.tmp",
)


def touch(path: pathlib.Path, data: bytes = b"") -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def pio_env(
    project: pathlib.Path, env: str, names: typing.Iterable[str]
) -> pathlib.Path:
    directory = project / ".pio" / "build" / env
    for name in names:
        touch(directory / name)
    return directory


def esp_image(
    segments: typing.Sequence[tuple[int, bytes]],
    *,
    chip_id: int = 5,
    entry: int = 0x40381892,
    hashed: bool = True,
) -> bytes:
    """An esp-idf application image with the header layout measured above."""
    header = struct.pack("<BBBBI", 0xE9, len(segments), 2, 0x20, entry)
    header += b"\xee\x00\x00\x00"           # wp_pin, spi_pin_drv
    header += struct.pack("<H", chip_id)    # bytes 12..13
    header += b"\x00" * 10                  # to the 24-byte header length
    body = b"".join(struct.pack("<2I", a, len(d)) + d for a, d in segments)
    out = header + body
    out += b"\x00" * ((16 - (len(out) + 1) % 16) % 16) + b"\x5a"
    return (out + b"\x00" * 32) if hashed else out


#: The real C3 image's five segments, with the bytes stubbed out. Lengths are
#: the measured ones divided down: the addresses and the count are what the
#: identifier checks, and 232 KB of zeros in a test file buys nothing.
C3_SEGMENTS = (
    (0x3C030020, b"\x11" * 32),
    (0x3FC8A200, b"\x22" * 16),
    (0x40380000, b"\x33" * 48),
    (0x42000020, b"\x44" * 64),
    (0x403827FC, b"\x55" * 16),
)


def hex_file(address: int, payload: bytes) -> bytes:
    """A one-record Intel HEX plus its EOF, for a self-identifying fixture."""
    body = bytes([len(payload), (address >> 8) & 0xFF, address & 0xFF, 0x00]) + payload
    checksum = (-sum(body)) & 0xFF
    return (":" + body.hex().upper() + f"{checksum:02X}" + "\n:00000001FF\n").encode()


# --- find_platformio -------------------------------------------------------


def test_platformio_finds_every_artefact_name_in_an_esp_environment(tmp_path):
    pio_env(tmp_path, "seeed_xiao_esp32c3",
            ["firmware.elf", "firmware.bin", "bootloader.bin", "partitions.bin"])
    found = find_platformio(tmp_path)
    assert {a.path.name for a in found} == {
        "firmware.elf", "firmware.bin", "bootloader.bin", "partitions.bin"
    }
    assert {a.toolchain for a in found} == {"platformio"}
    assert {a.target for a in found} == {"seeed_xiao_esp32c3"}


def test_platformio_gives_the_esp_extras_their_own_roles(tmp_path):
    pio_env(tmp_path, "esp", ["firmware.bin", "bootloader.bin", "partitions.bin"])
    roles = {a.path.name: a.role for a in find_platformio(tmp_path)}
    assert roles == {
        "firmware.bin": "application",
        "bootloader.bin": "bootloader",
        "partitions.bin": "partitions",
    }


def test_platformio_ignores_everything_that_is_not_firmware(tmp_path):
    """The drift guard. A `firmware.*` glob passes every other test and fails
    this one, because it picks up the 618 KB link map."""
    pio_env(tmp_path, "nucleo_g031k8", ("firmware.elf",) + PIO_NOISE)
    assert [a.path.name for a in find_platformio(tmp_path)] == ["firmware.elf"]


def test_platformio_keeps_environments_apart(tmp_path):
    pio_env(tmp_path, "pico", ["firmware.uf2", "firmware.elf"])
    pio_env(tmp_path, "nucleo_g031k8", ["firmware.elf"])
    assert {(a.target, a.path.name) for a in find_platformio(tmp_path)} == {
        ("pico", "firmware.uf2"),
        ("pico", "firmware.elf"),
        ("nucleo_g031k8", "firmware.elf"),
    }


def test_platformio_finds_nothing_without_a_build_directory(tmp_path):
    touch(tmp_path / "platformio.ini", b"[env:pico]\n")
    assert find_platformio(tmp_path) == []


# --- find_arduino_cli ------------------------------------------------------


def test_arduino_separates_a_merged_image_from_the_parts_it_contains(tmp_path):
    fqbn = tmp_path / "build" / "esp32.esp32.XIAO_ESP32C3"
    for name in ("blink.ino.bin", "blink.ino.elf", "blink.ino.merged.bin",
                 "blink.ino.bootloader.bin", "blink.ino.partitions.bin"):
        touch(fqbn / name)
    roles = {a.path.name: a.role for a in find_arduino_cli(tmp_path)}
    assert roles == {
        "blink.ino.bin": "application",
        "blink.ino.elf": "application",
        "blink.ino.merged.bin": "merged",
        "blink.ino.bootloader.bin": "bootloader",
        "blink.ino.partitions.bin": "partitions",
    }


def test_arduino_ignores_names_that_are_not_exports(tmp_path):
    fqbn = tmp_path / "build" / "arduino.avr.uno"
    for name in ("blink.ino.hex", "blink.ino.map", "compile_commands.json",
                 "core.a", "blink.ino.with_bootloader.hex"):
        touch(fqbn / name)
    roles = {a.path.name: a.role for a in find_arduino_cli(tmp_path)}
    assert roles == {
        "blink.ino.hex": "application",
        "blink.ino.with_bootloader.hex": "merged",
    }


def test_arduino_takes_the_fqbn_from_the_directory_rather_than_spelling_it(tmp_path):
    """Discovery must survive a change in how arduino-cli encodes an fqbn, so
    it names the directory it found rather than one it predicted.

    The dot encoding is not cosmetic: an earlier version of this test tried to
    create `rp2040:rp2040:rpipico` and Windows refused it outright with
    `WinError 123`. A discovery rule that reconstructed the fqbn from
    `board.txt` and looked for the colon form would find nothing here.
    """
    for fqbn in ("esp32.esp32.XIAO_ESP32C3", "rp2040.rp2040.rpipico"):
        touch(tmp_path / "build" / fqbn / "blink.ino.elf")
    assert {a.target for a in find_arduino_cli(tmp_path)} == {
        "esp32.esp32.XIAO_ESP32C3", "rp2040.rp2040.rpipico"
    }


# --- find_stm32cubeide -----------------------------------------------------


def test_cubeide_claims_nothing_without_a_cproject(tmp_path):
    """A `Debug/x.elf` is emitted by CMake, Make and a dozen other builds.
    Calling that an STM32CubeIDE project is a label with no evidence."""
    touch(tmp_path / "Debug" / "blink.elf")
    assert find_stm32cubeide(tmp_path) == []


def test_cubeide_finds_every_configuration_including_a_renamed_one(tmp_path):
    touch(tmp_path / ".cproject")
    for config in ("Debug", "Release", "Flight"):
        touch(tmp_path / config / "blink.elf")
    assert {a.target for a in find_stm32cubeide(tmp_path)} == {
        "Debug", "Release", "Flight"
    }


def test_cubeide_skips_directories_that_hold_no_elf(tmp_path):
    touch(tmp_path / ".cproject")
    touch(tmp_path / "Debug" / "blink.elf")
    touch(tmp_path / "Debug" / "blink.bin")
    touch(tmp_path / "Core" / "main.c")
    touch(tmp_path / "Drivers" / "stm32.bin")
    found = find_stm32cubeide(tmp_path)
    assert {a.target for a in found} == {"Debug"}
    assert {a.path.name for a in found} == {"blink.elf", "blink.bin"}


# --- find_artefacts --------------------------------------------------------


def test_find_artefacts_refuses_a_path_that_is_not_a_directory(tmp_path):
    missing = tmp_path / "nowhere"
    with pytest.raises(ValueError) as caught:
        find_artefacts(missing)
    assert str(missing) in str(caught.value)


def test_find_artefacts_covers_all_three_layouts_in_one_tree(tmp_path):
    pio_env(tmp_path, "pico", ["firmware.uf2"])
    touch(tmp_path / "build" / "arduino.avr.uno" / "blink.ino.hex")
    touch(tmp_path / ".cproject")
    touch(tmp_path / "Debug" / "blink.elf")
    assert {a.toolchain for a in find_artefacts(tmp_path)} == {
        "platformio", "arduino-cli", "stm32cubeide"
    }


def test_find_artefacts_orders_a_merged_image_ahead_of_its_parts(tmp_path):
    fqbn = tmp_path / "build" / "esp32.esp32.XIAO_ESP32C3"
    for name in ("blink.ino.partitions.bin", "blink.ino.bin",
                 "blink.ino.bootloader.bin", "blink.ino.merged.bin"):
        touch(fqbn / name)
    assert [a.role for a in find_artefacts(tmp_path)] == [
        "merged", "application", "bootloader", "partitions"
    ]


def test_find_artefacts_is_the_same_list_twice(tmp_path):
    """`rules/determinism.md` applies to tools too: a scan that follows
    directory iteration order cannot be diffed between two runs."""
    pio_env(tmp_path, "pico", ["firmware.uf2", "firmware.elf", "firmware.bin"])
    pio_env(tmp_path, "esp", ["firmware.bin", "bootloader.bin", "partitions.bin"])
    first = [a.path for a in find_artefacts(tmp_path)]
    assert first == [a.path for a in find_artefacts(tmp_path)]
    assert first == sorted(set(first), key=first.index)


def test_every_role_a_finder_produces_has_a_sort_rank(tmp_path):
    """`Artefact.sort_key` raises on an unknown role rather than sorting it
    last, so a new role must be ranked deliberately. This is what makes that
    raise unreachable in practice."""
    pio_env(tmp_path, "esp", ["firmware.bin", "bootloader.bin", "partitions.bin"])
    touch(tmp_path / "build" / "x.y.z" / "blink.ino.merged.bin")
    touch(tmp_path / ".cproject")
    touch(tmp_path / "Debug" / "blink.elf")
    assert {a.role for a in find_artefacts(tmp_path)} <= set(ROLE_ORDER)


def test_an_unranked_role_is_a_loud_failure_not_a_quiet_one():
    stray = Artefact(pathlib.Path("x.bin"), "platformio", "env", "mystery")
    with pytest.raises(ValueError):
        _ = stray.sort_key


# --- identify_esp_image ----------------------------------------------------


def test_esp_identification_reads_back_the_measured_c3_header():
    image = identify_esp_image(esp_image(C3_SEGMENTS))
    assert image is not None
    assert image.chip == "ESP32-C3"
    assert image.entry == 0x40381892
    assert [address for address, _ in image.segments] == [
        0x3C030020, 0x3FC8A200, 0x40380000, 0x42000020, 0x403827FC
    ]
    assert [length for _, length in image.segments] == [32, 16, 48, 64, 16]


def test_esp_identification_accepts_an_image_with_no_appended_hash():
    image = identify_esp_image(esp_image(C3_SEGMENTS, hashed=False))
    assert image is not None and len(image.segments) == 5


def test_esp_identification_rejects_a_bare_magic_byte():
    """0xE9 is `jmp rel32`. An x86 image from this repository's own 8086 work
    can open with it, so the magic alone must not be enough."""
    assert identify_esp_image(b"\xe9\x05" + b"\x00" * 200) is None


def test_esp_identification_rejects_an_unknown_chip():
    assert identify_esp_image(esp_image(C3_SEGMENTS, chip_id=0x00FF)) is None


def test_esp_identification_rejects_a_truncated_image():
    data = esp_image(C3_SEGMENTS)
    assert identify_esp_image(data[:len(data) // 2]) is None


def test_esp_identification_rejects_a_walk_that_does_not_land():
    """One extra byte moves the checksum off its 16-byte boundary. Without the
    alignment check this passes, and the alignment check is most of what makes
    the identifier stronger than a magic-byte test."""
    assert identify_esp_image(esp_image(C3_SEGMENTS) + b"\x00") is None


def test_esp_identification_rejects_a_zero_segment_count():
    data = bytearray(esp_image(C3_SEGMENTS))
    data[1] = 0
    assert identify_esp_image(bytes(data)) is None


def test_esp_identification_rejects_a_segment_count_above_sixteen():
    data = bytearray(esp_image(C3_SEGMENTS))
    data[1] = 17
    assert identify_esp_image(bytes(data)) is None


def test_esp_identification_rejects_a_segment_count_of_255():
    """The count is one byte, so 255 is what a random 0xE9-led file offers."""
    data = bytearray(esp_image(C3_SEGMENTS))
    data[1] = 255
    assert identify_esp_image(bytes(data)) is None


def test_esp_identification_rejects_a_segment_longer_than_the_file():
    data = bytearray(esp_image(C3_SEGMENTS))
    struct.pack_into("<I", data, 24 + 4, 0x7FFFFFFF)  # first segment's length
    assert identify_esp_image(bytes(data)) is None


# --- describe --------------------------------------------------------------


def test_describe_reads_a_self_identifying_format(tmp_path):
    path = touch(tmp_path / "blink.hex", hex_file(0x0100, b"\xde\xad\xbe\xef"))
    lines, status = describe(path)
    assert status == OK
    assert any("hex" in line for line in lines)


def test_describe_asks_for_a_base_rather_than_inventing_one(tmp_path):
    path = touch(tmp_path / "firmware.bin", b"\x00\x20\x00\x20" + b"\xff" * 60)
    lines, status = describe(path)
    assert status == NEEDS_BASE
    assert any("base" in line for line in lines)


def test_describe_calls_a_corrupt_self_identifying_file_an_error(tmp_path):
    """A truncated ELF is not a raw binary waiting for an address. Reporting it
    as `NEEDS_BASE` would let it exit 0 in a scan beside healthy artefacts."""
    path = touch(tmp_path / "firmware.elf", b"\x7fELF\x01\x01\x01" + b"\x00" * 9)
    _, status = describe(path)
    assert status == ERROR


def test_describe_says_nothing_about_vectors_unless_asked(tmp_path):
    vectors = struct.pack("<II", 0x20002000, 0x080028F5)
    path = touch(tmp_path / "firmware.bin", vectors + b"\xff" * 56)
    lines, _ = describe(path, base=0x08000000)
    assert not any("vector table" in line for line in lines)


def test_describe_reads_the_vector_table_at_the_address_it_is_given(tmp_path):
    """The measured Nucleo-G031K8 figures: MSP 0x20002000, reset 0x080028F5."""
    vectors = struct.pack("<II", 0x20002000, 0x080028F5)
    path = touch(tmp_path / "firmware.bin", vectors + b"\xff" * 56)
    lines, _ = describe(path, base=0x08000000, vectors=0x08000000)
    assert any("SP 0x20002000, reset 0x080028f5" in line for line in lines)


def test_describe_says_so_when_the_vector_address_is_outside_the_image(tmp_path):
    path = touch(tmp_path / "firmware.bin", b"\xff" * 64)
    lines, status = describe(path, base=0x10000000, vectors=0x20000000)
    assert status == OK
    assert any("not covered" in line for line in lines)


def test_describe_names_an_esp_container_instead_of_calling_it_unrecognised(tmp_path):
    path = touch(tmp_path / "firmware.bin", esp_image(C3_SEGMENTS))
    lines, status = describe(path)
    assert status == NEEDS_BASE
    joined = "\n".join(lines)
    assert "ESP32-C3" in joined and "0x3c030020" in joined
    assert "unrecognised" not in joined


def test_describe_never_names_a_flash_offset_it_cannot_know(tmp_path):
    """An earlier draft printed "normally at 0x10000" over every container,
    including `bootloader.bin`, which goes to 0x0 on a C3. Where a container
    lands is a fact about the partition table, not about the container."""
    path = touch(tmp_path / "bootloader.bin", esp_image(C3_SEGMENTS))
    lines, _ = describe(path)
    assert not any("0x10000" in line for line in lines)


# --- main ------------------------------------------------------------------


def test_main_reads_a_project_and_succeeds(tmp_path, capsys):
    pio_env(tmp_path, "pico", ["firmware.bin"])
    touch(tmp_path / ".pio" / "build" / "pico" / "firmware.hex",
          hex_file(0x0000, b"\x01\x02\x03\x04"))
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "platformio  pico" in out and "[application]" in out


def test_main_fails_when_nothing_in_the_project_can_be_read(tmp_path, capsys):
    pio_env(tmp_path, "pico", ["firmware.bin"])
    assert main([str(tmp_path)]) == 1
    assert "without a base address" in capsys.readouterr().err


def test_main_says_where_it_looked_when_it_finds_nothing(tmp_path, capsys):
    assert main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert ".pio/build" in err and "arduino-cli" in err and "cproject" in err.lower()


def test_main_refuses_one_base_for_a_whole_directory(tmp_path, capsys):
    pio_env(tmp_path, "esp", ["firmware.bin", "bootloader.bin", "partitions.bin"])
    assert main([str(tmp_path), "--base", "0x10000"]) == 2
    assert "one file" in capsys.readouterr().err


def test_main_reads_one_file_when_given_its_base(tmp_path, capsys):
    path = touch(tmp_path / "firmware.bin", struct.pack("<II", 0x20002000, 0x080028F5))
    assert main([str(path), "--base", "0x08000000", "--vectors", "0x08000000"]) == 0
    assert "SP 0x20002000" in capsys.readouterr().out


def test_main_fails_on_a_named_file_it_cannot_place(tmp_path, capsys):
    path = touch(tmp_path / "firmware.bin", b"\xff" * 64)
    assert main([str(path)]) == 1
    assert "base" in capsys.readouterr().out


def test_main_reports_a_missing_path_rather_than_raising(tmp_path, capsys):
    assert main([str(tmp_path / "nowhere")]) == 2
    assert "no such file or directory" in capsys.readouterr().err
