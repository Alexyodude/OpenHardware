# OpenHardware — the ESP-IDF capability names the ESP32 pin tables use, and nothing else.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""`webui/arduino/<variant>/soc/soc_caps.h`, one per ESP32 recipe whose
tables include ESP-IDF's header of that name (OH-185).

Each `#define` there follows the ESP-IDF v5.5 file and line it was read
from (docs/esp-idf-reference.md). The first test reads that line in the
reference checkout and holds the value to it; the second holds the names
defined to the `SOC_` names the tables compiled with that recipe use -- the
chip's own and every manifest row's on that chip.
"""

import pathlib
import re

import pytest

from tests.riscv32.test_esp32c6_board import idf_root
from tools import board_manifest
from webui import compile as compiler

REPO = pathlib.Path(__file__).resolve().parents[2]

#: A citation and the definition under it.
_CITED = re.compile(
    r"^/\* (components/soc/(\w+)/include/soc/soc_caps\.h):(\d+) \*/\n"
    r"#define (\w+) (\S+)$", re.MULTILINE)
_DEFINED = re.compile(r"^[ \t]*#[ \t]*define[ \t]+(\w+)", re.MULTILINE)
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_SOC_NAME = re.compile(r"\bSOC_\w+")


def headers() -> dict[str, pathlib.Path]:
    """Each `openhardware` recipe's chip to its `soc/soc_caps.h`, where it has one."""
    found = {chip: compiler.ARDUINO_LITE / recipe.variant / "soc" / "soc_caps.h"
             for chip, recipe in compiler.RECIPES.items()
             if recipe.framework == "openhardware"}
    return {chip: path for chip, path in found.items() if path.is_file()}


def tables(chip: str) -> list[pathlib.Path]:
    """Every `pins_arduino.h` a build for `chip` compiles against."""
    recipe = compiler.RECIPES[chip]
    out = [compiler.PACKAGES / include / "pins_arduino.h"
           for include in recipe.extra_includes]
    out += [compiler.BOARD_SUPPORT / include / "pins_arduino.h"
            for include in recipe.bsp_includes]
    out += [compiler.BOARD_SUPPORT / row.package / "variants" / row.variant / "pins_arduino.h"
            for row in board_manifest.ROWS if row.chip == chip]
    return out


def test_each_definition_is_the_esp_idf_references_own_at_the_line_it_cites():
    root = idf_root()
    if root is None:
        pytest.skip("SKIPPED: no ESP-IDF checkout; see docs/esp-idf-reference.md")
    found = headers()
    assert found, "no ESP32 recipe carries a soc/soc_caps.h"
    for chip, header in found.items():
        text = header.read_text(encoding="utf-8").replace("\r\n", "\n")
        cited = _CITED.findall(text)
        assert sorted(name for *_, name, _ in cited) == sorted(_DEFINED.findall(text)), (
            f"{header}: a #define with no citation directly above it")
        for path, idf_chip, line, name, value in cited:
            assert idf_chip == chip.lower().replace("-", ""), (header, path)
            lines = (root / path).read_text(encoding="utf-8").splitlines()
            there = lines[int(line) - 1]
            assert re.fullmatch(rf"#define\s+{name}\s+{re.escape(value)}(\s.*)?", there), (
                f"{header.name} for the {chip} says {name} is {value}, citing "
                f"{path}:{line}, which reads {there!r}")


def test_each_header_defines_exactly_the_soc_names_its_chips_tables_use():
    found = headers()
    assert found, "no ESP32 recipe carries a soc/soc_caps.h"
    for chip, header in found.items():
        used: set[str] = set()
        for table in tables(chip):
            if not table.is_file():
                pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")
            code = _COMMENT.sub(" ", table.read_text(encoding="utf-8", errors="replace"))
            used |= set(_SOC_NAME.findall(code))
        defined = set(_DEFINED.findall(header.read_text(encoding="utf-8")))
        assert defined == used, (chip, header, sorted(defined), sorted(used))
