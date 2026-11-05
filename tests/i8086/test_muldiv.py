# OpenHardware - IMUL, DIV and IDIV against the 8088's own microcode.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""What the 8088 does that a host multiply and divide do not, per ticket OH-11.

Every case below is a register-form case copied out of SST8088 v2, the
hardware-captured corpus, with its file and index beside it. They run here
without the corpus, which is git-ignored, so the behaviour is held in a
checkout that has never fetched it. The corpus itself is still the stronger
check, and `test_conformance.py` runs all of it when it is present.

Each of these failed before OH-11, when `core/i8086/muldiv.cc` divided in
C++ and computed the undefined flags from the result:

* a REP prefix in front of IDIV negates the quotient, because REP sets the
  microcode's F1 latch and IDIV's correction step reads it;
* IDIV r/m8 traps on a quotient of -128, which fits in a byte, because the
  microcode's range check is on the magnitude before the sign goes on;
* SF, ZF, PF and AF after IMUL, and all six after DIV and IDIV, are what the
  CORX and CORD loops leave in the ALU and not a function of the answer;
* and on a divide error those flags are pushed, so they reach memory.

Flags are compared on the nine bits the part defines; the corpus records the
unassigned top four as set, which says nothing about this code. Only cases
whose operand is AX, BX, CX or DX, or a byte of one, are copied: the harness
here owns SP and sets nothing else.
"""

import pytest

from core.i8086 import abi

#: The nine flag bits the 8086 defines.
DEFINED = 0x0FD5

#: Where the instruction goes, where the stack is, and where vector 0 sends a
#: divide error. Chosen apart from each other and from the vector table.
CODE_CS, CODE_IP = 0x1000, 0x0100
STACK_SS, STACK_SP = 0x2000, 0x0200
TRAP_CS, TRAP_IP = 0x3000, 0x0040


def _run(cpu: abi.Cpu, code: str, **regs: int) -> dict:
    cpu.clear_memory()
    cpu.write_word(0x00000, TRAP_IP)
    cpu.write_word(0x00002, TRAP_CS)
    cpu.write_block((CODE_CS << 4) + CODE_IP, bytes.fromhex(code))
    cpu.set_regs(cs=CODE_CS, ip=CODE_IP, ss=STACK_SS, sp=STACK_SP, **regs)
    cpu.step()
    after = cpu.regs
    out = {"ax": after.ax, "dx": after.dx, "flags": after.flags,
           "trapped": (after.cs, after.ip) == (TRAP_CS, TRAP_IP)}
    if out["trapped"]:
        out["pushed"] = cpu.read_word((STACK_SS << 4) + STACK_SP - 2)
    return out


def _check(cases):
    """Run (inputs, expected) pairs and return every disagreement, described."""
    wrong = []
    with abi.Cpu() as cpu:
        for where, given, want in cases:
            regs = {k: v for k, v in given.items() if k != "code"}
            got = _run(cpu, given["code"], **regs)
            trapped = "pushed" in want
            seen = {
                "ax": got["ax"], "dx": got["dx"], "flags": got["flags"] & DEFINED,
                "trapped": got["trapped"],
            }
            expect = {
                "ax": want["ax"], "dx": want["dx"], "flags": want["flags"] & DEFINED,
                "trapped": trapped,
            }
            if trapped and got["trapped"]:
                seen["pushed"] = got["pushed"] & DEFINED
                expect["pushed"] = want["pushed"] & DEFINED
            if seen != expect:
                shown = lambda d: {k: (f"{v:04X}" if not isinstance(v, bool) else v)
                                   for k, v in d.items()}
                wrong.append(f"{where} ({given['code']}): want {shown(expect)}, "
                             f"got {shown(seen)}")
    return wrong


@pytest.mark.usefixtures("library")
def test_a_rep_prefix_negates_the_quotient_of_idiv():
    """F1 is set by either REP and read by IDIV's correction step, so the
    quotient comes back negated and the remainder does not. Before OH-11 the
    prefix was ignored and these four quotients came back with the other sign
    -- the 5.8% of IDIV cases the ticket could not explain."""
    cases = [
        ("F6.7 [374]",
         dict(code="F2F6F9", ax=0x0448, bx=0xE316, cx=0x784A, dx=0xBA04, flags=0xF093),
         dict(ax=0x3CF2, dx=0xBA04, flags=0xF082)),
        ("F6.7 [1631]",
         dict(code="F3F6F8", ax=0x2051, bx=0xBA58, cx=0xD324, dx=0x7D32, flags=0xF417),
         dict(ax=0x0B9A, dx=0x7D32, flags=0xF482)),
        ("F7.7 [337]",
         dict(code="F3F7FB", ax=0x57E5, bx=0x590C, cx=0xA87C, dx=0x1E53, flags=0xF852),
         dict(ax=0xA8D2, dx=0x43BD, flags=0xF086)),
        ("F7.7 [654]",
         dict(code="F2F7F9", ax=0x742D, bx=0x135F, cx=0x58B4, dx=0x284D, flags=0xF807),
         dict(ax=0x8BB0, dx=0x2BED, flags=0xF086)),
    ]
    wrong = _check(cases)
    assert not wrong, "\n".join(wrong)


@pytest.mark.usefixtures("library")
def test_idiv_r_m8_traps_on_a_quotient_of_minus_128():
    """-128 fits in a signed byte and the part traps on it anyway: CORD
    divides magnitudes, and a magnitude of 128 is out of range before the
    sign is applied. Before OH-11 the core stored -128 and carried on.
    FLAGS is pushed with the microcode's intermediates in it."""
    cases = [
        # AX = -8383, AL = 65: -128.97, truncated to -128.
        ("F6.7 [3944]",
         dict(code="F6F8", ax=0xDF41, bx=0x701D, cx=0xC286, dx=0x94EF, flags=0xF857),
         dict(ax=0xDF41, dx=0x94EF, flags=0xF082, pushed=0xF082)),
        # AX = 10015, CH = -78.
        ("F6.7 [2010]",
         dict(code="F6FD", ax=0x271F, bx=0x2989, cx=0xB24A, dx=0x550B, flags=0xF456),
         dict(ax=0x271F, dx=0x550B, flags=0xF486, pushed=0xF486)),
    ]
    wrong = _check(cases)
    assert not wrong, "\n".join(wrong)


@pytest.mark.usefixtures("library")
def test_idiv_r_m16_traps_on_a_quotient_of_minus_32768():
    """The same rule at the other width. **This one is not from the corpus**,
    which has no register-form IDIV r/m16 case with this quotient: it is the
    microcode's range check, which runs at both widths and which the byte
    case above holds to silicon. DX:AX = -98304, BX = 3. Only the trap is
    asserted -- the pushed flags here have no hardware answer to compare to."""
    with abi.Cpu() as cpu:
        got = _run(cpu, "F7FB", ax=0x8000, dx=0xFFFE, bx=0x0003, flags=0xF000)
    assert got["trapped"], f"IDIV BX of FFFE:8000 by 3 stored {got['ax']:04X}"
    assert (got["ax"], got["dx"]) == (0x8000, 0xFFFE), "a trap writes no answer"


@pytest.mark.usefixtures("library")
def test_imul_leaves_the_flags_its_microcode_leaves():
    """SF, ZF, PF and AF after IMUL come from IMULCOF's 16-bit add of the
    high half and the low half's sign, not from the product. Before OH-11
    the core took them from the product and got these wrong."""
    cases = [
        ("F6.5 [0]",
         dict(code="F6EC", ax=0x4D26, bx=0xB28A, cx=0xA70E, dx=0x710E, flags=0xFC82),
         dict(ax=0x0B6E, dx=0x710E, flags=0xFC03)),
        ("F6.5 [7]",
         dict(code="F6E8", ax=0xDF06, bx=0xE0AE, cx=0x7B3C, dx=0x1872, flags=0xF082),
         dict(ax=0x0024, dx=0x1872, flags=0xF046)),
    ]
    wrong = _check(cases)
    assert not wrong, "\n".join(wrong)


@pytest.mark.usefixtures("library")
def test_div_leaves_the_flags_its_microcode_leaves():
    """Every arithmetic flag after DIV is what CORD's last subtract and rotate
    left. Before OH-11 they were whatever the instruction came in with."""
    cases = [
        ("F7.6 [8]",
         dict(code="F7F3", ax=0xACAA, bx=0xF1E7, cx=0x46E8, dx=0x1739, flags=0xFCD7),
         dict(ax=0x1894, dx=0x2B1E, flags=0xF403)),
        ("F7.6 [208]",
         dict(code="F7F3", ax=0xE1A0, bx=0x5500, cx=0x12EA, dx=0x52ED, flags=0xF452),
         dict(ax=0xF9C3, dx=0x22A0, flags=0xF406)),
    ]
    wrong = _check(cases)
    assert not wrong, "\n".join(wrong)


@pytest.mark.usefixtures("library")
def test_a_divide_error_pushes_the_microcode_s_flags():
    """The trap pushes FLAGS, so the undefined bits reach memory where no
    flag mask can hide them. This is why the divides were excluded from the
    full-corpus check until OH-11."""
    cases = [
        ("F6.6 [13]",
         dict(code="F6F7", ax=0x5942, bx=0x500D, cx=0xFAB8, dx=0x1521, flags=0xF453),
         dict(ax=0x5942, dx=0x1521, flags=0xF406, pushed=0xF406)),
    ]
    wrong = _check(cases)
    assert not wrong, "\n".join(wrong)
