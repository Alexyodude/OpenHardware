---
id: OH-33
title: 'Adopt the peripheral layer: GPIO first, then UART, then one timer'
status: done
priority: P1
created: '2026-08-25'
touches:
- core/cortexm0/cpu.h
- core/cortexm0/cpu.cc
- core/cortexm0/abi.h
- core/cortexm0/abi.cc
- core/cortexm0/abi.py
- webui/boards/rp2040.py
- tests/cortexm0/uart/*
- tests/cortexm0/test_uart.py
- tests/cortexm0/test_board_rp2040.py
- docs/research/peripheral-layer/README.md
---

docs/research/peripheral-layer/ holds a 34 KB design over nine provenance rounds and 36 chip/regmap/contract JSON files for ESP32-C3, RP2040 and STM32C031, with citations to datasheets and to pico-sdk. OH-18 preserved it and was explicit that preserving is not adopting: 'adopting it is a separate decision, and the design's own section 6 is the scoping test for that.' This is that decision.

Adopt narrowly. webui/boards/rp2040.py already adopts the slice a blink image reaches and says so per register. Widen to the three peripherals that make a board demonstrable rather than merely alive: GPIO so a pin state is observable, UART so a printf arrives, and one timer so delay() is not a spin loop. Everything else stays research.

Run section 6 as the gate before writing code and record the answer, including if it says no. A design that nine agents produced and nobody has executed is evidence, not policy, and the failure mode is adopting all 36 files because they are there.

The RP2040 atomic-alias correction in rp2040.py's docstring is the warning: the research's first reading was wrong and self-corrected once. Adopting a file wholesale adopts its uncorrected passages too.

Done when a firmware printf reaches the UI, a GPIO write is observable at a pad, and every adopted register cites the research file carrying its provenance.

**Note 2026-08-25:** SECTION 6 GATE, RUN 2026-08-25. The answer is NO for the schema, YES for the narrow widening. Recorded here because this ticket asked for the answer to be written down including if it says no.

REJECTED, with reasons:

1. The JSON regmap engine, the 8-kind vocabulary and the SVD drafter. Two working boards together are 29 mapping calls (rp2040.py 19, samd21.py 10). The research produced 9 RP2040 regmaps; the board installs 2 peripherals. The 7 unused ones -- XOSC, PLL, CLOCKS, IO_BANK0, PADS_BANK0, TIMER, UART -- are what pico-sdk firmware needs, and that is blocked on the boot ROM regardless of how it is modelled. A parser plus a kind dispatcher plus a drafter to replace 29 lines is building ahead of demand.

2. design.md section 3's cm0_set_mmio callback seam and section 4's open-bus-and-log default for unmapped space. Verified this session: no callback seam exists in core/cortexm0, and kOpenBus appears only in core/i8086/exec_core.cc. The core went the other way -- a declarative C++ map (map_register/map_alias/map_mirror) driven from Python, with unmapped space raising MemoryFault. For a conformance product, faulting and naming the address beats open-bus-and-log, which requires somebody to read a log. Reversing it would also contradict 30+ tests that pin fault-on-unmapped.

3. The design's own section 6 agrees where it is testable: atomic_aliases is one-chip evidence that already inverted once on a closer datasheet reading, and rp2040.py encodes it in three lines.

The decisive observation from writing samd21.py today: the cost was reading Microchip's CMSIS headers, not encoding the result -- 10 lines of mapping calls behind a morning of provenance work. A schema moves where the facts are written; it does not find them.

KEPT: the citations. Pull the source:/verified: strings into the board file per register as it is modelled, which is what rp2040.py and samd21.py already do.

ACCEPTED for the narrow widening: UART and one timer on the RP2040, hand-written in the existing vocabulary. Two core gaps measured this session and both real: byte/halfword access to a mapped register faults (0x41004410..0x41004411 leaves the modelled memory), and there is no cycle or time API at all, so a counter register cannot advance.

**Note 2026-08-25:** DONE, and the one criterion that is not.

Delivered: the section 6 gate answered and recorded; UART0 modelled and a real compiled image printing 'hello, world' through it; TIMER modelled and a real compiled image delaying on it; every adopted register citing its provenance. Three new core behaviours, each forced by something measured rather than anticipated -- map_stream (a data register is a queue, not a word), map_constant (a read-only status register; map_mirror cannot stand in because a mirror needs a source), map_counter (a register that advances, which is the one hang that cannot be made loud). Plus sub-word MMIO access, which was a listed residual defect: STRB and LDRB never consulted the register map at all.

NOT DONE: 'a firmware printf reaches the UI'. The bytes exist and rp2040.uart0_output() returns them, but putting them on the page means editing webui/emulator_server.py and webui/api.py, and both are claimed by OH-32, which is in-review and held by another session. Filed separately rather than reached into. See the follow-on ticket.

Also not done, and blocked rather than skipped: TIMER's ALARM0-3, which is how sleep_ms() actually waits. It needs an IRQ to deliver and core/cortexm0 has no exceptions. The alarms fault instead of accepting a write that could never fire, so the gap is loud.
