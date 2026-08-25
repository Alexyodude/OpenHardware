---
id: OH-52
title: The board runtime assumes an Arm-shaped machine, so a Harvard core cannot be
  entered
status: open
priority: P1
created: '2026-08-25'
touches:
- webui/api.py
- webui/boards/contract.py
- webui/boards/catalogue.py
- webui/boards/atmega328p.py
- core/cortexm0/machine.py
- core/avr/machine.py
- webui/static/emulator.js
- tests/webui/test_board_runtime_contract.py
- tests/webui/test_board_run.py
- tests/webui/test_emulator_session.py
- tests/avr/test_uno_board.py
- tests/webui/test_board_catalogue.py
- webui/emulator_server.py
---

OH-49 delivered core/avr and stopped deliberately before webui/boards/atmega328p.py, because webui/boards/contract.py requires VECTOR_TABLE_OFFSETS and an AVR has no vector table. That framing is right and too small. Measured, not assumed:

    Core protocol needs: clear_memory, clear_registers, clear_regions,
      write_block, read_word, read_block, in_range, is_mapped, get_regs,
      set_regs, step, close
    cortexm0   missing 0
    riscv32    missing 2:  clear_registers, is_mapped
    i8086      missing 5:  clear_registers, clear_regions, in_range,
                           is_mapped, get_regs
    avr        missing 10: everything but step and close

So the entry model is 1 of 11 gaps. webui/api.py's `Core` protocol is not "what a core provides"; it is the Armv6-M-shaped subset two flat-address 32-bit cores happen to share. The AVR does not diverge on entry. It diverges on what an address is -- two overlapping spaces, which core/avr/cpu.h refuses to let a caller confuse -- and on what a register file is: `set_regs([0]*13 + [sp, 0, entry], apsr=0)` is the Arm layout written out.

Any fix that addresses entry alone yields a board file that satisfies the contract and still cannot be entered, which is the claim-you-cannot-keep failure rules/board-claims.md exists to prevent, arriving through a third door.

Rejected: widening core/avr/abi.py to the flat Core shape. It is the smallest diff and it is wrong. cpu.h states in bold that every accessor names its address space, because on a Harvard machine 0x0100 is a flash word AND a byte of SRAM; write_block(address, data) re-introduces exactly that ambiguity, and read_word on an 8-bit machine invents a width. A wrong value a caller acts on costs more than a fault.

Chosen: split on divergence. One module per board-capable core, core/<core>/machine.py, resolved the way listing_view already resolves core.<core>.disasm -- an existing mechanism in that file, not a new one. Six functions: blank, load, enter, view, read, readable. The cortexm0 body is _place/_vector_table_at/set_regs moved wholesale; the AVR body sizes two spaces, writes program memory, and starts at word zero.

VECTOR_TABLE_OFFSETS then stays on the boards whose core reads a vector table, and the contract requires it of those boards rather than of every board.

Two measurements that make this cheaper than it looks:
 - tests/cortexm0/test_blink.py and test_samd21_blink.py never call api.load_firmware; they drive core.cortexm0.abi.Cpu and the board module directly. OH-31's "must pass unchanged" condition costs nothing here.
 - vector_table and stack_pointer are on the wire and unrendered -- emulator.js:490 uses only entry and notes -- but tests/webui/test_board_run.py pins both, so the Arm path keeps emitting them.

Wire change, deliberate: board state's `registers` becomes [{name, value, width}] and `apsr` becomes `flags` [{name, on}], because a page cannot render 32 eight-bit AVR registers through a sixteen-name Arm table. A `pc` field is added so a caller stops meaning "index 15". The value assertions in test_board_run.py and test_emulator_session.py keep their values and change shape.

Done when api.load_firmware("Arduino Uno", <a real avr-gcc image>) returns a session that steps, a named test watches PB5 toggle THROUGH webui/api.py rather than through the ABI, ATmega328P is in FIRMWARE_VERIFIED with that test named, and the browser shows the Uno's own registers.

**Note 2026-08-25:** Delivered. Arduino Uno is runnable and firmware-verified; the catalogue reports 5 runnable boards, up from 4.

Shape, as built. core/cortexm0/machine.py and core/avr/machine.py, resolved by webui/api.py the way listing_view already resolves core.<core>.disasm. Seven functions: blank, refuses, write, enter, view, readable/is_register/read/word. api.py's Core protocol shrank from twelve methods to two -- step and close -- which is what a session needs regardless of machine; everything architecture-shaped moved.

The contract asks the CORE what a board owes. webui/boards/contract.py REQUIRED is now one entry (install); core_requirements(core) reads REQUIRES out of core/<core>/machine.py. cortexm0 asks for VECTOR_TABLE_OFFSETS, avr asks for nothing. A core with no machine.py raises rather than answering "this board owes nothing" -- riscv32 is built and has none, and an empty requirement list would make that look like a board satisfying everything.

Residual §6.7.1 of the handoff closed as part of this: api.VECTOR_TABLE_OFFSETS, DEFAULT_VECTOR_TABLE_OFFSETS and RP2040_BOOT2_BYTES are deleted. The drift guard that existed to make that safe is replaced by test_the_offsets_have_exactly_one_home_and_it_is_the_board, which asserts the copy did not come back.

Wire change: registers are [{name,value,width}], flags are [{name,on}], pc is explicit, and vector_table/stack_pointer are ABSENT rather than null on a board that has neither. emulator.js no longer holds any core's register names.

FOUR defects found, three of them silent:

 1. A BROWSER found `pc 0x[object Object]` in the run report, with zero console errors. Two places indexed the register array at position 15 and only one was updated. Indexing an array of objects is legal JavaScript, so nothing threw. Now pinned by test_nothing_in_the_script_indexes_a_board_register_by_position, a source-level tripwire, because the value only looks wrong to a human reading the pane.

 2. MUTATION found the bytes-to-words conversion had no witness. Replacing write_program_block(address // 2, data) with (address, data) passed everything -- the blink is one segment at address zero and 0 // 2 == 0. Same class as OH-49's cpc/Z finding: a blind fixture, not a bad test. Now witnessed by loading eight bytes at 0x100 and checking they land in words 0x80..0x83.

 3. MUTATION found the AVR hexdump had no witness either: read() returning the same byte for every offset passed all 371 tests. The browser had seen the difference and nothing else had. Now pinned, and the pinning also settles the design question of WHICH address space the pane shows -- data, because the listing pane shows program.

 4. The bool predicate lied. An odd program address was refused as "maps nothing at 0x0101" when the board maps it perfectly well and simply cannot split a word. accepts() -> refuses() returning the reason, the same shape _vector_table_at already used; api.py composes rather than writes the sentence.

Eight mutations run in the final round, all applied-and-verified before reading the result, all caught.

Verified in a real browser, one server, listener count checked first: 26 boards / 5 enabled, Arduino Uno among them. Uno shows 34 registers (r0-r31 two hex digits, sp/pc four), 8 SREG flags, hexdump of the DATA space with DDRB 0x24 and PORTB 0x25 both bit-5 set, and a listing pane saying core.avr.disasm does not exist. RP2040 unchanged and byte-for-byte identical to the previous handoff's §8: pc 0x10000108 -> 0x1000012E, same four busy_wait_us listing lines, same vector table in the dump. 0 console messages at warning or above on every check.

NOT DONE, deliberately: PINB is not modelled. It reads the electrical level on the pins, so on PB5 driven high it should read high, and this returns the stored zero. Unlike samd21.py, which leaves PORT_IN unmapped so a read faults instead of lying, there is nothing to unmap -- every byte of an AVR data space exists. Pinned as a limitation by test_reading_the_input_register_is_not_yet_modelled; the fix is a mirror of PORTB masked by DDRB and needs a mapping mechanism core/avr does not have.
