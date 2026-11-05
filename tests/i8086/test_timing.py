# OpenHardware — the one part of 8088 timing the oracle can check.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why a bound and not a count
#
# OH-8 wants the three F2 cells in `docs/features/i8086.md`: instruction
# cycles, the prefetch queue, and bus activity. All three need a per-opcode
# execution cost, and there is nowhere honest to get one. Fitting a table to
# the corpus and then testing it against the same corpus proves that a table
# was fitted, and nothing else.
#
# The bound is different. `cycles >= 4 * (length - queued)` falls out of two
# architectural facts — the 8088 has an eight-bit external bus and a four-byte
# prefetch queue, so a byte not already queued costs one four-clock bus cycle
# to fetch — and neither number was read off the data. So the corpus can
# *check* it, which is the thing a fitted table can never be.
#
# **Measured: 2,857,000 cases, zero violations, 521,944 tight.**
#
# ## What this does NOT claim
#
# That any cycle count is right. The three F2 cells stay `planned`, and this
# file would pass unchanged against a core that computes no cycles at all —
# because it tests `MinimumCycles`, which is arithmetic over an instruction's
# length, not a simulation. What it establishes is the floor the eventual
# model has to sit on, verified against every case there is.

import collections
import gzip
import json
import pathlib

import pytest

from core.i8086 import abi

CORPUS = pathlib.Path(__file__).resolve().parents[2] / "third_party" / "sst8088" / "v2"

#: Both facts about the part, and the reason the bound is checkable.
QUEUE_BYTES = 4
CLOCKS_PER_BUS_CYCLE = 4


def corpus_files() -> list[pathlib.Path]:
    files = sorted(CORPUS.glob("*.json.gz"))
    if not files:
        pytest.skip(
            f"no SST8088 corpus at {CORPUS}. Fetch a slice:\n"
            f"  bash tools/get_8088_tests.sh --opcodes 00 01 88 89"
        )
    return files


# --- the function itself ----------------------------------------------------


def test_a_byte_already_queued_costs_nothing_to_fetch():
    """A full queue and a short instruction: no bus cycle is needed at all."""
    assert abi.minimum_cycles(2, QUEUE_BYTES) == 0


def test_each_byte_not_queued_costs_one_bus_cycle():
    """Four clocks per byte, because the 8088's external bus is eight bits
    wide. That is the whole difference from an 8086, and it is why the corpus
    was captured on an 8088 rather than its sibling."""
    for length in range(1, 8):
        assert abi.minimum_cycles(length, 0) == CLOCKS_PER_BUS_CYCLE * length


def test_only_the_bytes_beyond_the_queue_are_charged():
    """A six-byte instruction with four queued fetches two."""
    assert abi.minimum_cycles(6, 4) == CLOCKS_PER_BUS_CYCLE * 2


def test_a_queue_deeper_than_the_part_has_is_clamped_and_not_refused():
    """A caller asking about a six-byte queue is asking about an 8086. The
    answer to the question actually asked is "nothing to fetch", which is what
    clamping gives -- and it keeps this total rather than raising on input a
    test could otherwise generate."""
    assert abi.minimum_cycles(2, 9) == abi.minimum_cycles(2, QUEUE_BYTES)


# --- against every case in the corpus ---------------------------------------


#: One file in every `STRIDE`, rather than the first `n`.
#:
#: A prefix of the opcode space is not a sample of it: the first 24 files
#: reach instruction lengths 1 to 5 and never a 6-byte form, because the long
#: encodings -- segment prefix, modrm, disp16, imm16 -- live further up. The
#: adequacy test below caught that, which is what it is for.
STRIDE = 13

#: How many opcode files this reads.
#:
#: **The bound does not depend on the opcode.** It is arithmetic over an
#: instruction's LENGTH and the queue -- so the coverage that matters is every
#: length and both queue states, not every opcode, and
#: `test_the_sample_covers_every_length_and_both_queue_states` asserts exactly
#: that rather than leaving the sample's adequacy to a comment.
#:
#: Reading all 308 files takes 95 seconds, a third of this repository's whole
#: gate. It was run whole once, on 2026-08-26: **2,857,000 cases, zero
#: violations, 521,944 tight.** That number belongs in the record; paying for
#: it on every run does not.


def test_no_captured_instruction_beats_the_bus(request):
    """**The assertion, across every opcode in the corpus.**

    Cases captured from a physical AMD D8088. Not one completes in fewer
    clocks than its un-queued bytes cost to fetch -- which would mean either
    the bound is wrong or the part has a wider bus than it has.
    """
    total = violations = tight = 0
    worst: tuple | None = None

    for path in corpus_files()[::STRIDE]:
        for case in json.loads(gzip.decompress(path.read_bytes())):
            cycles = len(case["cycles"])
            length = len(case["bytes"])
            queued = len(case["initial"].get("queue") or ())
            floor = abi.minimum_cycles(length, queued)
            total += 1
            if cycles < floor:
                violations += 1
                if worst is None:
                    worst = (path.stem, case["name"], cycles, floor, length, queued)
            elif cycles == floor:
                tight += 1

    assert not violations, (
        f"{violations} of {total} cases finish faster than their bytes can be "
        f"fetched; first: {worst}"
    )
    # **A bound nothing reaches is vacuously true.** This is what makes the
    # assertion above mean something: a fifth of the corpus is fetch-bound, so
    # a wrong constant here breaks immediately rather than silently widening a
    # limit nobody tests.
    assert tight > total // 10, (
        f"only {tight} of {total} cases meet the bound exactly. It has gone "
        f"slack -- check the queue size and the bus-cycle length."
    )


def test_the_sample_covers_every_length_and_both_queue_states():
    """**What makes the sample above adequate**, asserted rather than argued.

    The bound is a function of two things only. If every instruction length
    the corpus contains, and both queue states, appear in what is read, then
    reading more files exercises no new arithmetic -- and if one ever stops
    appearing, this fails instead of the sample quietly narrowing.
    """
    lengths: collections.Counter = collections.Counter()
    queues: collections.Counter = collections.Counter()
    for path in corpus_files()[::STRIDE]:
        for case in json.loads(gzip.decompress(path.read_bytes())):
            lengths[len(case["bytes"])] += 1
            queues[len(case["initial"].get("queue") or ())] += 1

    assert set(queues) == {0, QUEUE_BYTES}, dict(queues)
    assert min(lengths) == 1, dict(lengths)
    assert max(lengths) >= 6, dict(lengths)
    # Contiguous: a missing length in the middle is a hole the bound is never
    # exercised at.
    assert set(lengths) == set(range(min(lengths), max(lengths) + 1)), dict(lengths)


def test_the_corpus_only_ever_starts_with_a_full_or_an_empty_queue():
    """A fact about the capture, pinned because nothing else here records it.

    The rig sets each case up with the queue either empty or holding all four
    bytes -- never one, two or three. So the corpus adjudicates the two
    extremes of the fetch cost and says nothing about the middle, which is
    where a real prefetch model would spend most of its time. That is a limit
    on what OH-8 can ever prove here, not a limit on this bound.
    """
    seen: collections.Counter = collections.Counter()
    for path in corpus_files()[:4]:
        for case in json.loads(gzip.decompress(path.read_bytes())):
            seen[len(case["initial"].get("queue") or ())] += 1

    assert set(seen) == {0, QUEUE_BYTES}, dict(seen)


# --- the register form, from Intel's own table ------------------------------
#
# The bound above is the part of 8088 timing that falls out of the
# architecture. This is the next part: what the execution unit costs, for the
# instructions whose cost is one number. It is NOT fitted -- every clock count
# is Intel's, from Table 2-21 of the 8086 Family User's Manual (October 1979,
# 9800722-03), and `core/i8086/timing.cc` cites each row's page. The corpus
# only checks it.
#
# **Measured whole on 2026-11-05: 516,078 cases claimed across 162 opcode
# files, zero mismatches,** in both queue states. Reading those files takes 45
# seconds, so what runs here is one file for every row of Intel's table.
#
# Only the full-queue cases test Intel's figures: from an empty queue the bus
# is never the faster unit, so those cases test the decoding and the length.
# A full queue cannot hold a four-byte instruction and the opcode after it, so
# the two four-byte rows' figures are checked by nothing here, and the row
# test pins that it is exactly those two.

#: One corpus file for each row of Table 2-21 that the core answers for.
#: A row is one claim -- "register, register is 3 clocks" -- and reading one
#: opcode it covers checks that claim; reading every opcode it covers checks
#: the decoding that routes to it, which the whole-corpus run did.
REGISTER_FORM_ROWS = {
    "ALU register, register": "29",
    "ALU accumulator, immed8": "0C",
    "ALU accumulator, immed16": "25",
    "DAA": "27",
    "DAS": "2F",
    "INC/DEC reg16": "4B",
    "ALU register, immed8": "80.7",
    "ALU register, immed16": "81.2",
    "ALU register, sign-extended immed8": "83.5",
    "TEST register, register": "85",
    "XCHG register, register": "86",
    "MOV register, register": "8A",
    "MOV reg16, seg-reg": "8C",
    "MOV seg-reg, reg16": "8E",
    "XCHG reg16, AX": "93",
    "CBW": "98",
    "SAHF": "9E",
    "TEST accumulator, immediate": "A9",
    "MOV reg8, immediate": "B2",
    "MOV reg16, immediate": "BD",
    "shift/rotate register, 1": "D1.5",
    "ESC immediate, register": "DB",
    "flag operations": "FA",
    "TEST register, immediate": "F6.0",
    "TEST reg16, immed16": "F7.0",
    "NOT/NEG register": "F7.3",
    "INC/DEC reg8": "FE.1",
}

#: The rows whose register form is four bytes long. A full queue is four
#: bytes, so it never holds one of these AND the next opcode, and the only
#: claim the corpus can check is the empty queue's, which the bus decides.
#: Intel's figure for these two is tabled and unchecked.
FOUR_BYTE_ROWS = {"ALU register, immed16", "TEST reg16, immed16"}

#: Intel's figures for the instructions the unit tests below spell out.
ADD_REG_REG = 3      # Table 2-21, p. 2-52
TEST_REG_IMM = 5     # p. 2-67


def corpus_file(stem: str) -> list[dict]:
    path = CORPUS / f"{stem}.json.gz"
    if not path.exists():
        pytest.skip(
            f"no {path.name} in the SST8088 corpus at {CORPUS}. Fetch it:\n"
            f"  bash tools/get_8088_tests.sh --opcodes {stem.split('.')[0]}"
        )
    return json.loads(gzip.decompress(path.read_bytes()))


def test_a_full_queue_leaves_only_intels_execution_clocks():
    """ADD AX,CX with the queue holding it and the opcode after it: the bus
    owes nothing, so the count is Table 2-21's figure and nothing else."""
    assert abi.register_form_cycles(b"\x01\xc8", QUEUE_BYTES) == ADD_REG_REG


def test_an_empty_queue_waits_for_the_bus_when_the_bus_is_slower():
    """The same instruction from an empty queue: the opcode arrives on the
    first cycle, then the modrm byte and the next opcode take a bus cycle
    each. Eight clocks against an execution unit that needs three."""
    assert abi.register_form_cycles(b"\x01\xc8", 0) == 2 * CLOCKS_PER_BUS_CYCLE


def test_the_slower_of_the_two_units_decides():
    """TEST AL,imm8 by the long form, F6 /0, is five clocks for three bytes:
    from a full queue that is all there is to it, from an empty one the bus's
    twelve dominate. max(), not a sum -- the two units run in parallel."""
    assert abi.register_form_cycles(b"\xf6\xc0\x12", QUEUE_BYTES) == TEST_REG_IMM
    assert abi.register_form_cycles(b"\xf6\xc0\x12", 0) == 3 * CLOCKS_PER_BUS_CYCLE


def test_a_memory_operand_is_no_claim():
    """ADD [BX],AX: the cost depends on the effective address and on a bus
    transfer competing with prefetch. That is the model this is not."""
    assert abi.register_form_cycles(b"\x01\x07", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\x01\x07", 0) is None


def test_a_queue_holding_the_instruction_but_not_the_next_is_no_claim():
    """A four-byte instruction and a full four-byte queue: the next opcode
    still has to be fetched, and WHEN that fetch starts is a prefetch model.
    So is any partly filled queue. None, rather than a guess."""
    assert abi.register_form_cycles(b"\x81\xc0\x34\x12", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\x01\xc8", 1) is None
    assert abi.register_form_cycles(b"\x01\xc8", 2) is None


def test_a_queue_deeper_than_the_part_is_clamped_not_wrapped():
    """A queue of 256 is deeper than the part's, not empty, so it is the
    full queue's answer -- and still no claim for four bytes, which a
    clamped queue cannot hold with the opcode after them. A negative queue
    is no queue at all."""
    assert abi.register_form_cycles(b"\x01\xc8", 256) == ADD_REG_REG
    assert abi.register_form_cycles(b"\x81\xc0\x34\x12", 10) is None
    assert abi.register_form_cycles(b"\x01\xc8", -1) is None


def test_bytes_of_the_wrong_length_are_no_claim():
    """ADD AX,CX is two bytes; handed three, the third is another
    instruction and the count would be for both."""
    assert abi.register_form_cycles(b"\x01\xc8\x90", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\x01", 0) is None


def test_an_encoding_intel_does_not_table_is_no_claim():
    """83 /1 is OR with a sign-extended byte, which Table 4-13 marks "not
    used"; C6 with mod 3 is MOV into a register by an encoding Intel lists
    only for memory; AAA's cost depends on AL; a prefix is a different
    instruction's length."""
    assert abi.register_form_cycles(b"\x83\xc8\x01", 0) is None
    assert abi.register_form_cycles(b"\xc6\xc0\x01", 0) is None
    assert abi.register_form_cycles(b"\x37", 0) is None
    assert abi.register_form_cycles(b"\x26\x01\xc8", 0) is None


def test_the_other_not_used_encodings_are_no_claim():
    """The rest of Table 4-13's "not used" cells that sit beside a tabled
    row: 82, which is 80 again; MOV to or from a segment register above DS;
    D0 /6; F6 /1. And 8E /1, which is documented -- it loads CS -- but is a
    jump, not a move."""
    assert abi.register_form_cycles(b"\x82\xc0\x01", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\x8c\xe0", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\x8e\xe0", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\x8e\xc8", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\xd0\xf0", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\xd1\xf0", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\xf6\xc8\x12", QUEUE_BYTES) is None
    assert abi.register_form_cycles(b"\xf7\xc8\x34\x12", 0) is None


def test_every_row_of_intels_table_matches_the_part_exactly():
    """**The assertion.** For one opcode under each row, every case the core
    makes a claim for counts exactly what the physical 8088 counted -- and
    each file is claimed from an empty queue, and from a full one in every
    row but the four-byte ones, which a full queue cannot hold with the
    opcode after them.

    Without the table this fails at the first call. With one of Intel's
    figures moved by a clock it fails on that row's full-queue cases -- for
    every row but FOUR_BYTE_ROWS, whose figure nothing here reaches, and the
    last assertion holds that set to exactly what the corpus leaves out.
    """
    unchecked = set()
    for row, stem in REGISTER_FORM_ROWS.items():
        claimed: collections.Counter = collections.Counter()
        for case in corpus_file(stem):
            code = bytes(case["bytes"])
            queued = len(case["initial"].get("queue") or ())
            want = abi.register_form_cycles(code, queued)
            if want is None:
                continue
            got = len(case["cycles"])
            assert got == want, (
                f"{row} ({stem}): {case['name']!r}, bytes {code.hex()}, queue "
                f"{queued}: the part took {got} clocks and the table says {want}"
            )
            claimed[queued] += 1
        assert claimed[0], f"{row} ({stem}): nothing claimed from an empty queue"
        if not claimed[QUEUE_BYTES]:
            unchecked.add(row)
    assert unchecked == FOUR_BYTE_ROWS, (
        f"rows whose figure no full-queue case checked: {sorted(unchecked)}"
    )


def test_lahf_is_left_out_because_the_part_disagrees_with_intel():
    """**A divergence from the datasheet, pinned.** Table 2-21 gives LAHF four
    clocks. Every unprefixed full-queue case the D8088 ran took two. So the
    table makes no claim for it rather than either contradicting the part or
    quietly writing 2 and citing Intel for it. If a later corpus measures
    four, this fails and the row can go in as Intel wrote it.

    Unprefixed, because about half the file carries a segment prefix, which
    is taken from the queue on its own two clocks first -- so those cases
    measure four for a reason that has nothing to do with LAHF, and counting
    them in is how this observation was first got wrong."""
    assert abi.register_form_cycles(b"\x9f", QUEUE_BYTES) is None
    full = [len(c["cycles"]) for c in corpus_file("9F")
            if len(c["initial"].get("queue") or ()) == QUEUE_BYTES
            and len(c["bytes"]) == 1]
    assert full and set(full) == {2}, collections.Counter(full)


def test_a_four_byte_instruction_from_a_full_queue_takes_seven_clocks():
    """Why a full queue and a four-byte instruction is left to a prefetch
    model, as an observation: ADD r16,imm16 is four clocks by Intel's table
    and four bytes long, and the part took seven -- not four, which a queue
    holding the next opcode would give, and not eight, which an empty bus
    would. The bus interface starts the fetch partway through."""
    full = [len(c["cycles"]) for c in corpus_file("81.0")
            if len(c["initial"].get("queue") or ()) == QUEUE_BYTES
            and len(c["bytes"]) == 4 and c["bytes"][1] >> 6 == 3]
    assert full and set(full) == {7}, collections.Counter(full)
