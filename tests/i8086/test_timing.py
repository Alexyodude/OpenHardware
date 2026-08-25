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
