# OpenHardware — the ESP-IDF capability names the ESP32 builds use, and nothing else.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""`webui/arduino/<variant>/soc/soc_caps.h`, one per ESP32 recipe (OH-185).

Each `#define` there follows the ESP-IDF v5.5 file and line it was read
from (docs/esp-idf-reference.md). The value is held to the reference by
NAME, as that document says the tests read the tree, so a tag that moved
a line still passes and one that changed the number fails with both; the
line is held separately, so a moved line fails only the citation. The last
test holds the names defined to the `SOC_` names the build uses: in the
tables compiled with that recipe -- the chip's own and every manifest
row's on that chip -- and in the variant's `oh_board.h`.
"""

import pathlib
import re

import pytest

from tests.riscv32.test_esp32c6_board import defines, idf_root
from tools import board_manifest
from webui import compile as compiler

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


def cited(chip: str, header: pathlib.Path) -> list[tuple[str, str, str, str, str]]:
    """(path, chip directory, line, name, value) for each definition, every
    one of which must have its citation directly above it."""
    text = header.read_text(encoding="utf-8").replace("\r\n", "\n")
    found = _CITED.findall(text)
    assert sorted(name for *_, name, _ in found) == sorted(_DEFINED.findall(text)), (
        f"{header}: a #define with no citation directly above it")
    for path, idf_chip, *_ in found:
        assert idf_chip == chip.lower().replace("-", ""), (header, path)
    return found


def reference() -> pathlib.Path:
    root = idf_root()
    if root is None:
        pytest.skip("SKIPPED: no ESP-IDF checkout; see docs/esp-idf-reference.md")
    return root


def test_each_value_is_the_esp_idf_references_own_by_name():
    root = reference()
    found = headers()
    assert found, "no ESP32 recipe carries a soc/soc_caps.h"
    for chip, header in found.items():
        for path, _, _, name, value in cited(chip, header):
            theirs = defines(root / path).get(name)
            assert theirs == value, (
                f"{header.name} for the {chip} says {name} is {value}; "
                f"{path} says {theirs}")


def test_each_citation_is_the_line_that_defines_its_name():
    """The line number is there so a person can find the value; this keeps
    it pointing at the definition."""
    root = reference()
    for chip, header in headers().items():
        for path, _, line, name, _ in cited(chip, header):
            lines = (root / path).read_text(encoding="utf-8").splitlines()
            there = lines[int(line) - 1] if int(line) <= len(lines) else ""
            assert re.match(rf"#define\s+{name}\b", there), (
                f"{header.name} for the {chip} cites {path}:{line} for {name}, "
                f"which reads {there!r}")


def test_each_header_defines_exactly_the_soc_names_its_build_uses():
    """A chip whose tables are not all fetched is skipped, and said to be,
    after every other chip is checked."""
    found = headers()
    assert found, "no ESP32 recipe carries a soc/soc_caps.h"
    unfetched = []
    for chip, header in found.items():
        recipe = compiler.RECIPES[chip]
        users = [compiler.PACKAGES / include / "pins_arduino.h"
                 for include in recipe.extra_includes]
        users += [compiler.BOARD_SUPPORT / include / "pins_arduino.h"
                  for include in recipe.bsp_includes]
        users += [compiler.BOARD_SUPPORT / row.package / "variants" / row.variant
                  / "pins_arduino.h" for row in board_manifest.ROWS if row.chip == chip]
        users.append(compiler.ARDUINO_LITE / recipe.variant / "oh_board.h")
        missing = [user for user in users if not user.is_file()]
        if missing:
            unfetched.append(f"{chip} (no {missing[0]})")
            continue
        used: set[str] = set()
        for user in users:
            code = _COMMENT.sub(" ", user.read_text(encoding="utf-8", errors="replace"))
            used |= set(_SOC_NAME.findall(code))
        defined = set(_DEFINED.findall(header.read_text(encoding="utf-8")))
        assert defined == used, (chip, header, sorted(defined), sorted(used))
    if unfetched:
        pytest.skip(f"SKIPPED for {', '.join(unfetched)}; python tools/import_pindefs.py --fetch")
