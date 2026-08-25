---
id: OH-5
title: 'Interrupts: vectors, INT n, divide error, single step'
status: done
priority: P1
owner: session/irq
created: '2026-08-23'
touches:
- core/i8086/interrupt.*
- tests/i8086/test_interrupts.py
- core/i8086/exec_core.cc
- core/i8086/CMakeLists.txt
---

Slice 2e. Depends on stack and control flow from the core ISA slice.

**Note 2026-08-23:** The interrupt SEQUENCE already exists, as RaiseInterrupt in core/i8086/exec_core.cc: it pushes FLAGS, clears IF and TF, pushes CS and IP, and jumps through the table at 0000:0000. AAM with a zero divisor and DIV/IDIV overflow raise it today, verified against the corpus. Lift it into core/i8086/interrupt.* rather than writing a second one -- and note the measured detail that the pushed IP is the address AFTER the instruction, not the faulting one, which is the opposite of later x86 parts.

**Note 2026-08-26:** CLOSED 2026-08-26.

LIFTED, NOT REWRITTEN. RaiseInterrupt moved from exec_core.cc into core/i8086/interrupt.{h,cc} -- the file its own comment said it would move to "when OH-5 arrives". The body is byte-identical apart from a local PushWord; 216 i8086 tests including the 2.8M-case conformance run pass unchanged across the move, which is the evidence that it was a lift.

THE TRAP FLAG WAS INERT. kTrap was set and cleared and never acted on, so a program that turned on single-stepping got no trap and no error. Step now wraps ExecuteOne and raises vector 1.

TF IS SAMPLED BEFORE AND CHECKED AGAIN AFTER, and each end earns its keep. Before, so a POPF that SETS TF does not trap after itself -- an 8086 behaviour; reading TF only at the end traps immediately, which is a 386 behaviour. After, so an INT n executed while stepping takes ONE vector, because the interrupt sequence clears TF and the second check sees that without naming the four raising opcodes.

THE CORPUS CANNOT ADJUDICATE THE TRAP, and this is the finding worth keeping. All 308 files, 2,857,000 cases, ZERO with TF set. That is not a gap in the capture -- a rig that single-steps the part to record one instruction at a time cannot arm a trap that fires at the end of every instruction, because it would be capturing its own mechanism. TF is therefore the one flag in this processor with no hardware-captured evidence anywhere. tests/i8086/test_interrupts.py asserts it against the 8086 manual, the same arrangement tests/avr/test_datasheet_edges.py uses for the two AVR rules its oracle gets wrong.

VERIFIED RED: forcing stepping=false fails exactly the three trap tests and none of the seven about the sequence.

NOT MODELLED, recorded rather than silently absent: the MOV-SS inhibit. Real hardware suppresses interrupts for one instruction after an instruction loads SS, so MOV SS,AX / MOV SP,BX cannot be split by a handler that would run on a half-built stack. No oracle, nothing has needed it, and inventing it would be a claim with no evidence.

Gate: 1,443 passed, 17 skipped; all eight checkers exit 0.
