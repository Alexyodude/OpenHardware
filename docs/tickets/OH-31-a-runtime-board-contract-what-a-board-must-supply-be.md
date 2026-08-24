---
id: OH-31
title: 'A runtime board contract: what a board must supply before firmware can run
  on it'
status: open
priority: P1
created: '2026-08-25'
touches:
- webui/boards/contract.py
- tests/webui/test_board_runtime_contract.py
---

webui/boards/rp2040.py is the only board that can execute anything, and everything it knows about being a board is implicit in one file: the memory map, the reset vector, the atomic SET/CLR/XOR aliases, which peripheral registers exist and their reset values. A second board written by reading the first is how the shape gets copied wrong.

State the contract: chip identity, memory map with regions and permissions, reset behaviour and initial SP and PC, clock, pin mux from the board's pin index to chip GPIO, and the peripheral set with its provenance. Then rp2040.py becomes an instance of it, unchanged in behaviour -- if adopting the contract changes what the blink test does, the contract is wrong.

**This is not tools/check_board_contract.py.** That checker verifies a PICSimLab bsim_/board_ C++ pair covers board.h's pure virtuals; this is our own Python runtime and the two have nothing to do with each other. Two things called 'the board contract' in one repository is a trap -- name this one so the difference survives whoever reads it next.

Keep rp2040.py's growth rule, which is load-bearing: a peripheral is added only when a real image faults on it, and tools/lockstep_armv6m.mjs --profile-peripherals says which. The contract must not become a list of registers a board is expected to fill in.

Done when rp2040.py satisfies a stated contract, tests/cortexm0/test_blink.py still passes unchanged, and a board missing a required part fails with the part named.

Note: webui/boards/** is claimed wholesale by OH-22.
