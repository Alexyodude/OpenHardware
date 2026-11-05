# OpenHardware — the Armv7E-M interpreter, held to two oracles (OH-64).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What is being checked against what
#
# `core/cortexm0/thumb2.cc` and the `Profile::V7EM` path through
# `core/cortexm0/exec.cc` were written from the Armv7-M ARM. Nothing in this
# file was written from it. Every expected state below was produced by
# `tools/m4_oracle.py` running the same bytes in **Unicorn 2.1.4** (QEMU's
# TCG, cut down) and **icicle-emu 0.0.11** (a SLEIGH interpreter built from
# Ghidra's processor spec), and a case was kept only where the two agreed.
# They share no code, so a case they agree on is evidence about the
# architecture rather than about either emulator, and OH-50's objection --
# that a single oracle can detect a disagreement and not adjudicate it -- does
# not apply.
#
# Two fixtures, two kinds of evidence:
#
# - `m4/vectors.json.gz` is one instruction, or one `IT` block, per case, from
#   random registers and flags, with every byte the case stored into the
#   sandbox. It reaches corners no compiler emits.
# - `m4/traces.json.gz` is two whole images, the probe and the nRF52840 blink,
#   compared state by state. It reaches what compilers DO emit, in the order
#   they emit it, which is where an interpreter that passes every isolated case
#   still loses a flag between two instructions.
#
# ## The oracles' own disagreement, and the case that stands in for it
#
# icicle 0.0.11 leaves C alone on a flag-setting logical operation with a
# modified immediate whose rotation is not zero (imm12[11:10] != 0). The ARM
# says C is bit 31 of the expanded constant (ThumbExpandImm_C), and Unicorn
# does that. The generator therefore drops those cases unless C already equals
# bit 31, where both answers coincide -- which means the vectors cannot catch
# the bug, and `test_a_rotated_immediate_sets_carry_from_its_top_bit` is the
# hand-written case that does, with the architecture's answer.

import gzip
import json
import pathlib

import pytest

from tools import m4_oracle

HERE = pathlib.Path(__file__).resolve().parent
M4 = HERE / "m4"

#: The flag bits a trace or vector carries. Q and GE are not modelled -- the
#: generator drops any case that sets them -- and the rest of xPSR is not APSR.
FLAGS = 0xF0000000


def load(name: str) -> dict:
    return json.loads(gzip.decompress((M4 / name).read_bytes()))


@pytest.fixture
def abi():
    return pytest.importorskip("core.cortexm0.abi")


@pytest.fixture
def m4(cpu, abi):
    """The session core, switched to Armv7E-M and back afterwards.

    Back, because the core is shared by every test in the session and the
    Armv6-M corpus would otherwise run on a decoder that accepts 32-bit
    encodings it is supposed to refuse.
    """
    cpu.set_profile(abi.PROFILE_V7EM)
    yield cpu
    cpu.set_profile(abi.PROFILE_V6M)


def place(cpu, address: int, data: bytes) -> None:
    cpu.write_block(address, data)


# --- the vectors ------------------------------------------------------------


def test_the_vectors_were_made_where_this_test_puts_them():
    """The layout is the generator's, recorded in the fixture; if
    `m4_oracle` moved the code or the sandbox and the fixture was not
    regenerated, every case would be run somewhere it was not made."""
    vectors = load("vectors.json.gz")
    assert vectors["layout"] == {
        "code": m4_oracle.CODE, "code_size": m4_oracle.CODE_SIZE,
        "sandbox": m4_oracle.SANDBOX, "sandbox_size": m4_oracle.SANDBOX_SIZE,
    }
    assert vectors["oracles"] == {"icicle-emu": "0.0.11", "unicorn": "2.1.4"}


def test_every_vector_matches_both_oracles(m4):
    """Every case: registers, flags, and every byte of the sandbox.

    The sandbox is compared whole rather than at the addresses the oracles
    wrote, so a store the interpreter makes and the oracles did not -- to the
    wrong address, or one byte too wide -- fails here as well as a store it
    forgot. Failures are collected and reported together because a decode bug
    usually breaks a family at once, and the family is the useful thing to see.
    """
    vectors = load("vectors.json.gz")
    sandbox = m4_oracle.sandbox_image()
    failures = []
    for case in vectors["cases"]:
        code = bytes.fromhex(case["code"])
        expect = case["expect"]
        want = bytearray(sandbox)
        for address, data in expect["writes"]:
            offset = address - m4_oracle.SANDBOX
            want[offset:offset + len(data) // 2] = bytes.fromhex(data)

        m4.set_itstate(0)
        place(m4, m4_oracle.SANDBOX, sandbox)
        place(m4, m4_oracle.CODE, code)
        m4.set_regs(case["regs"], case["apsr"])
        try:
            for _ in range(case["steps"]):
                m4.step()
        except Exception as stop:  # noqa: BLE001 -- reported, not swallowed
            failures.append(f"{case['text']} [{case['code']}]: {stop}")
            continue
        got = m4.get_regs()
        problems = []
        regs = list(got.r)
        if regs != expect["regs"]:
            problems.append("regs " + ", ".join(
                f"r{i}=0x{g:08x} want 0x{w:08x}"
                for i, (g, w) in enumerate(zip(regs, expect["regs"])) if g != w))
        if got.apsr & FLAGS != expect["apsr"] & FLAGS:
            problems.append(f"apsr 0x{got.apsr & FLAGS:08x} "
                            f"want 0x{expect['apsr'] & FLAGS:08x}")
        if m4.itstate() != 0:
            problems.append(f"itstate 0x{m4.itstate():02x} after the block")
        if m4.read_block(m4_oracle.SANDBOX, len(sandbox)) != bytes(want):
            problems.append("sandbox differs")
        if problems:
            failures.append(f"{case['text']} [{case['code']}]: "
                            + "; ".join(problems))
    assert not failures, (
        f"{len(failures)} of {len(vectors['cases'])} cases disagree:\n"
        + "\n".join(failures[:40])
    )


# --- whole images -----------------------------------------------------------


def run_trace(cpu, image: dict) -> list[str]:
    cpu.clear_regions()
    for base, size in image["regions"]:
        cpu.add_region(base, size)
    # Repository-relative, because the blink lives beside the board test
    # that cites it (`tools/m4_oracle.py`'s `BLINK` says why) and not here.
    cpu.write_block(image["load"], (HERE.parents[1] / image["image"]).read_bytes())
    cpu.set_itstate(0)
    cpu.set_regs([0] * 13 + [image["sp"], 0, image["entry"]], 0)
    for index, row in enumerate(image["trace"]):
        try:
            cpu.step()
        except Exception as stop:  # noqa: BLE001 -- reported, not swallowed
            return [f"step {index + 1}: {stop}"]
        got = cpu.get_regs()
        state = list(got.r) + [got.apsr & FLAGS]
        if state != row:
            return [f"step {index + 1}: " + ", ".join(
                f"{'apsr' if i == 16 else f'r{i}'}=0x{g:08x} want 0x{w:08x}"
                for i, (g, w) in enumerate(zip(state, row)) if g != w)]
    return []


def test_the_probe_runs_in_lockstep_with_both_oracles(m4):
    """The probe was compiled to use the Thumb-2 a Cortex-M4 build emits --
    `ldrd`, `ubfx`, `mla`, `IT` blocks, wide `push` -- and is traced from
    `_start` until it parks."""
    image = load("traces.json.gz")["images"]["probe"]
    assert image["entry"] == m4_oracle.PROBE_ENTRY
    assert run_trace(m4, image) == []


def test_the_nrf52840_blink_runs_in_lockstep_with_both_oracles(m4):
    """The same blink the board test watches toggle LEDs, traced from its
    reset vector for as many steps as the fixture holds."""
    image = load("traces.json.gz")["images"]["blink"]
    assert run_trace(m4, image) == []


# --- what the vectors cannot show -------------------------------------------


def run_one(cpu, halfwords: list[int], regs: list[int] | None = None,
            apsr: int = 0) -> None:
    data = b"".join(h.to_bytes(2, "little") for h in halfwords)
    cpu.set_itstate(0)
    place(cpu, m4_oracle.CODE, data + b"\x00" * 8)
    start = list(regs or [0] * 16)
    start[13] = start[13] or m4_oracle.SANDBOX + 0x4000
    start[15] = m4_oracle.CODE
    cpu.set_regs(start, apsr)


def test_a_rotated_immediate_sets_carry_from_its_top_bit(m4):
    """`movs.w r0, #0x80000000` -- imm12 0x400, 0x80 rotated right by 8 --
    with C clear must leave C set: ThumbExpandImm_C's carry out is bit 31 of
    the constant whenever the rotation is not zero.

    icicle 0.0.11 leaves C clear here, which is why the vectors cannot hold
    this case; see the module docstring.
    """
    run_one(m4, [0xF05F, 0x4000])
    m4.step()
    got = m4.get_regs()
    assert got.r[0] == 0x80000000
    assert got.apsr & FLAGS == 0xA0000000  # N and C, not Z, not V

    # And a constant with no rotation leaves C exactly as it was, both ways.
    for carry in (0, 0x20000000):
        run_one(m4, [0xF05F, 0x0001], apsr=carry)  # movs.w r0, #1
        m4.step()
        assert m4.get_regs().apsr & FLAGS == carry


def test_what_the_interpreter_refuses_it_refuses_untouched(m4, abi):
    """Each of these is either outside what the oracles checked or
    UNPREDICTABLE, and the contract is `step`'s: refused, nothing moved.

    The literal loads are refused because the vectors run at one address and
    cannot tell a PC-relative base that is right from one that is four bytes
    off. The system group (`msr`, `mrs`, the barriers) and `tbb` were not in
    the generator at all.
    """
    refused = {
        "ldr.w r0, [pc, #4]": [0xF8DF, 0x0004],
        "adr.w r0, #4 (addw r0, pc, #4)": [0xF20F, 0x0004],
        "mrs r0, apsr": [0xF3EF, 0x8000],
        "msr apsr_nzcvq, r0": [0xF380, 0x8800],
        "dsb sy": [0xF3BF, 0x8F4F],
        "tbb [r0, r1]": [0xE8D0, 0xF001],
        "blx (wide, to Arm state)": [0xF000, 0xE800],
        "udf #0 (narrow, permanently undefined)": [0xDE00],
        "an IT inside an IT": [0xBF08, 0xBF08],
        "a narrow b<c> inside an IT": [0xBF08, 0xD000],
        "cbz inside an IT": [0xBF08, 0xB100],
        "b.w not last in an IT": [0xBF04, 0xF000, 0xB800, 0x2000],
    }
    for name, halfwords in refused.items():
        run_one(m4, halfwords, apsr=0x40000000)  # Z set: every eq holds
        # An IT is a step of its own; only what follows it is under test.
        if halfwords[0] & 0xFF00 == 0xBF00 and halfwords[0] & 0xF:
            m4.step()
        before = list(m4.get_regs().as_list()) + [m4.get_regs().apsr,
                                                  m4.itstate()]
        with pytest.raises(abi.Unimplemented):
            m4.step()
        after = list(m4.get_regs().as_list()) + [m4.get_regs().apsr,
                                                 m4.itstate()]
        assert after == before, f"{name}: refused, but the processor moved"


#: The System Control Space words the deferral test needs, at the addresses
#: every Cortex-M has them; `test_exceptions.py` spells them the same way.
SCB_ICSR = 0xE000ED04
SCB_VTOR = 0xE000ED08
ICSR_PENDSTSET = 1 << 26


def test_an_it_block_holds_off_an_exception_until_it_ends(m4):
    """An exception pending in the middle of an IT block is taken after it.

    The architecture would take it at once and stack ITSTATE in the frame's
    xPSR. This core's frame is Armv6-M's, whose xPSR has no IT bits, so taking
    it would lose the rest of the block on return; deferring keeps the block
    whole, and is what the core does. The test pends SysTick through ICSR
    between the IT and its first instruction and watches both instructions run
    before the handler is entered.
    """
    vectors, handler = m4_oracle.SANDBOX, m4_oracle.SANDBOX + 0x400
    m4.write_word(SCB_VTOR, vectors)
    m4.write_word(vectors + 4 * 15, handler | 1)
    m4.write_halfword(handler, 0xE7FE)  # b .
    # ite eq; movs r0, #1; movs r0, #2  with Z set: r0 = 1, flags untouched.
    run_one(m4, [0xBF0C, 0x2001, 0x2002, 0xE7FE], apsr=0x40000000)
    m4.step()
    assert m4.itstate() != 0
    m4.write_word(SCB_ICSR, ICSR_PENDSTSET)
    m4.step()
    assert m4.get_regs().r[15] == m4_oracle.CODE + 4, "taken inside the block"
    m4.step()
    got = m4.get_regs()
    assert got.r[0] == 1
    assert got.apsr & FLAGS == 0x40000000  # movs inside an IT sets no flags
    assert m4.itstate() == 0
    assert got.r[15] == m4_oracle.CODE + 6
    m4.step()
    assert m4.get_regs().r[15] == handler, "and not taken after it either"


def test_reset_goes_back_to_armv6m_and_armv6m_still_refuses_thumb2(cpu, abi):
    """A board that never asks for Armv7E-M must not get it: the profile is a
    property of the chip, and every Armv6-M board in this repository relies on
    a wide data-processing encoding being refused rather than run."""
    cpu.set_profile(abi.PROFILE_V7EM)
    cpu.set_itstate(0x08)
    cpu.reset()
    assert cpu.profile() == abi.PROFILE_V6M
    assert cpu.itstate() == 0
    # Reset is power-on and takes the memory map with it; put back the SRAM
    # the conftest fixture gave this test.
    cpu.add_region(0x20000000, 264 * 1024)

    cpu.set_profile(abi.PROFILE_V7EM)
    cpu.set_itstate(0x08)
    cpu.set_profile(abi.PROFILE_V6M)
    assert cpu.itstate() == 0, "switching profile must not carry an IT block"

    run_one(cpu, [0xEB01, 0x0002])  # add.w r0, r1, r2
    with pytest.raises(abi.Unimplemented):
        cpu.step()
    assert cpu.get_regs().r[15] == m4_oracle.CODE

    cpu.set_profile(abi.PROFILE_V7EM)
    run_one(cpu, [0xEB01, 0x0002], [0, 5, 7] + [0] * 13)
    cpu.step()
    assert cpu.get_regs().r[0] == 12
    assert cpu.get_regs().r[15] == m4_oracle.CODE + 4
    cpu.set_profile(abi.PROFILE_V6M)
