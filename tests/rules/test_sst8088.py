# OpenHardware — tests for the SST8088 corpus reader.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Read real hardware-captured cases, offline.

These run against `tests/fixtures/sst8088/`, eleven cases excerpted verbatim
from the corpus. Nothing here touches the network: a conformance reader whose
tests fail when GitHub is slow is one people learn to ignore, and
`rules/determinism.md` wants the same input to give the same answer
every run.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from tools.sst8088 import (
    FLAG_BITS,
    REGISTERS,
    CorpusError,
    load,
    opcode_files,
    parse_case,
)

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sst8088"


# --- against the real excerpt ------------------------------------------------


def test_the_sample_files_load():
    files = opcode_files(FIXTURES)
    assert len(files) == 3, [f.name for f in files]
    for path in files:
        assert load(path), f"{path.name} parsed to no cases"


def test_a_nop_case_matches_what_the_hardware_reported():
    """Opcode 90 case 0, verbatim from the corpus.

    It carries a `2E` segment-override prefix before the `90`, which is the
    corpus deliberately prepending overrides to a share of instructions.
    """
    case = load(FIXTURES / "90.json")[0]
    assert case.name == "nop"
    assert case.code == (0x2E, 0x90)
    assert case.initial_regs["ip"] == 37865
    assert case.initial_regs["flags"] == 64646


def test_final_is_a_delta_and_is_merged_into_a_whole_state():
    """The trap this reader exists to remove.

    The NOP case's `final.regs` holds exactly one key, `ip`. A harness
    comparing against it directly would check one register out of fourteen and
    call that a pass.
    """
    raw = json.loads((FIXTURES / "90.json").read_text(encoding="utf-8"))[0]
    assert list(raw["final"]["regs"]) == ["ip"], raw["final"]["regs"]

    case = load(FIXTURES / "90.json")[0]
    assert set(case.expected_regs) == set(REGISTERS)
    assert case.expected_regs["ip"] == 37867
    # Everything else must have been carried over from the initial state.
    assert case.expected_regs["ax"] == case.initial_regs["ax"]
    assert case.changed_registers == ("ip",)


def test_a_memory_writing_case_merges_ram():
    """ADD to a memory operand changes RAM; expected_ram must show it."""
    cases = load(FIXTURES / "00.json")
    writing = [c for c in cases if c.expected_ram != c.initial_ram]
    assert writing, "no case in the 00 sample wrote memory"
    case = writing[0]
    assert set(case.initial_ram).issubset(set(case.expected_ram))


def test_prefetch_state_is_reported():
    """Half the corpus starts with a full queue; the reader must say which."""
    cases = [c for path in opcode_files(FIXTURES) for c in load(path)]
    assert any(c.starts_prefetched for c in cases)


def test_cycles_are_carried_through_untouched():
    """The F2 timing cells need them; nothing decodes them yet."""
    case = load(FIXTURES / "90.json")[0]
    assert len(case.cycles) == 5
    assert isinstance(case.cycles[0], list)


def test_flags_split_into_the_nine_defined_bits():
    case = load(FIXTURES / "90.json")[0]
    bits = case.flag_bits(case.initial_regs["flags"])
    assert set(bits) == set(FLAG_BITS)
    assert all(value in (0, 1) for value in bits.values())
    # Bits 1, 3, 5 and 12-15 are unassigned on this part and must not appear.
    assert "reserved" not in bits and len(bits) == 9


# --- refusals ----------------------------------------------------------------


def test_a_case_missing_a_register_raises():
    """`initial` must be complete; only `final` is allowed to be partial."""
    raw = json.loads((FIXTURES / "90.json").read_text(encoding="utf-8"))[0]
    del raw["initial"]["regs"]["bp"]
    with pytest.raises(CorpusError, match="incomplete, missing"):
        parse_case(raw, "sample")


def test_an_unknown_register_in_final_raises():
    raw = json.loads((FIXTURES / "90.json").read_text(encoding="utf-8"))[0]
    raw["final"]["regs"]["r15"] = 1
    with pytest.raises(CorpusError, match="unknown registers"):
        parse_case(raw, "sample")


def test_an_address_outside_the_1mb_space_raises():
    raw = json.loads((FIXTURES / "90.json").read_text(encoding="utf-8"))[0]
    raw["initial"]["ram"] = [[0x100000, 0]]
    with pytest.raises(CorpusError, match="outside the 1 MB space"):
        parse_case(raw, "sample")


def test_a_non_byte_ram_value_raises():
    raw = json.loads((FIXTURES / "90.json").read_text(encoding="utf-8"))[0]
    raw["initial"]["ram"] = [[0x1000, 256]]
    with pytest.raises(CorpusError, match="is not a byte"):
        parse_case(raw, "sample")


def test_an_empty_corpus_file_raises(tmp_path):
    """Zero failures over zero tests is the defect, not a pass."""
    empty = tmp_path / "99.json"
    empty.write_text("[]", encoding="utf-8")
    with pytest.raises(CorpusError, match="holds no test cases"):
        load(empty)


def test_a_missing_corpus_file_raises(tmp_path):
    with pytest.raises(CorpusError, match="no corpus file"):
        load(tmp_path / "nope.json")


def test_an_empty_corpus_directory_raises_and_says_how_to_fetch(tmp_path):
    with pytest.raises(CorpusError, match="get_8088_tests.sh"):
        opcode_files(tmp_path)
