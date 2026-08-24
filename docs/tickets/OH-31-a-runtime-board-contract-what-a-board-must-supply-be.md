---
id: OH-31
title: 'A runtime board contract: what a board must supply before firmware can run
  on it'
status: in-review
priority: P1
created: '2026-08-25'
touches:
- webui/boards/contract.py
- tests/webui/test_board_runtime_contract.py
- webui/boards/rp2040.py
- webui/boards/samd21.py
---

webui/boards/rp2040.py is the only board that can execute anything, and everything it knows about being a board is implicit in one file: the memory map, the reset vector, the atomic SET/CLR/XOR aliases, which peripheral registers exist and their reset values. A second board written by reading the first is how the shape gets copied wrong.

State the contract: chip identity, memory map with regions and permissions, reset behaviour and initial SP and PC, clock, pin mux from the board's pin index to chip GPIO, and the peripheral set with its provenance. Then rp2040.py becomes an instance of it, unchanged in behaviour -- if adopting the contract changes what the blink test does, the contract is wrong.

**This is not tools/check_board_contract.py.** That checker verifies a PICSimLab bsim_/board_ C++ pair covers board.h's pure virtuals; this is our own Python runtime and the two have nothing to do with each other. Two things called 'the board contract' in one repository is a trap -- name this one so the difference survives whoever reads it next.

Keep rp2040.py's growth rule, which is load-bearing: a peripheral is added only when a real image faults on it, and tools/lockstep_armv6m.mjs --profile-peripherals says which. The contract must not become a list of registers a board is expected to fill in.

Done when rp2040.py satisfies a stated contract, tests/cortexm0/test_blink.py still passes unchanged, and a board missing a required part fails with the part named.

Note: webui/boards/** is claimed wholesale by OH-22.

**Note 2026-08-25:** Design constraint discovered by OH-26, and it lands squarely on this ticket's pin mux: the simulator's integer 'pin' field CANNOT represent 8 of the 25 XIAO boards. 123 of 321 resolved pads name a chip pin that has no flat integer index at all -- SAMD21 PA02, MG24 PC0, nRF54L15/LM20A P2.08 -- because those vendors publish no flat GPIO numbering. An nRF54L15's P0 is five pins wide, so the usual 32-per-port arithmetic yields a number that appears in no Nordic document. RP2040, RP2350 and the ESP32 parts are flat, and the nRF52840 Arduino core publishes a flat 32-per-port encoding, so 198 pads do get an integer. Whatever this contract says a pin IS must therefore admit a string chip pin with a null index, or it will be unable to describe a third of the boards. Reproduce with: python tools/import_pindefs.py --all --summary
