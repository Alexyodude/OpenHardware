---
id: OH-5
title: 'Interrupts: vectors, INT n, divide error, single step'
status: open
priority: P1
owner: session/irq
created: '2026-08-23'
touches:
- core/i8086/interrupt.*
- tests/i8086/test_interrupts.py
---

Slice 2e. Depends on stack and control flow from the core ISA slice.

**Note 2026-08-23:** The interrupt SEQUENCE already exists, as RaiseInterrupt in core/i8086/exec_core.cc: it pushes FLAGS, clears IF and TF, pushes CS and IP, and jumps through the table at 0000:0000. AAM with a zero divisor and DIV/IDIV overflow raise it today, verified against the corpus. Lift it into core/i8086/interrupt.* rather than writing a second one -- and note the measured detail that the pushed IP is the address AFTER the instruction, not the faulting one, which is the opposite of later x86 parts.
