---
id: OH-67
title: SysTick and exception entry and return, which an Arduino core needs to reach
  setup
status: open
priority: P1
created: '2026-08-26'
touches:
- core/cortexm0/exec.cc
- core/cortexm0/cpu.h
- core/cortexm0/cpu.cc
- core/cortexm0/abi.h
- core/cortexm0/abi.cc
- core/cortexm0/abi.py
- tests/cortexm0/test_exceptions.py
- core/cortexm0/exception.h
- core/cortexm0/exception.cc
- core/cortexm0/CMakeLists.txt
- tools/gen_armv6m_exception.mjs
---

OH-66 IS THE TOP OPEN TICKET AND THIS IS WHAT STOPS IT. Measured 2026-08-26, not reasoned: a real Arduino-core sketch was compiled for the XIAO SAMD21 with the installed toolchain-gccarmnoneeabi, the framework-arduino-samd core, Seeed's XIAO_m0 variant and framework-cmsis-atmel, linked at flash 0 with flash_without_bootloader.ld, and run on webui/boards/samd21.py with every faulting register auto-stubbed. It executes 318,216 instructions, gets all the way through SystemInit and init, and then STALLS FOREVER inside delay() at micros().

WHY IT STALLS, from the disassembly at the stalling pc. Arduino SAMD's micros() returns ((count + pend) * 1000) plus a sub-millisecond term, where count is _ulTickCount and pend is SCB->ICSR.PENDSTSET. _ulTickCount is incremented ONLY by SysTick_Handler. With no exception delivery, count stays 0 and pend saturates at 1, so micros() can never exceed about 1000 and delay(2) or larger never returns. main() itself calls delay(1) before setup(), so nothing a person types ever runs.

THE SURFACE IS SMALL AND IT WAS MEASURED, NOT GUESSED. The whole image demands 32 distinct registers, and exactly five of them are architectural rather than chip: SYST_CSR at 0xE000E010, SYST_RVR at 0xE000E014, SYST_CVR at 0xE000E018, SCB ICSR at 0xE000ED04 and SCB SHPR3 at 0xE000ED20. No NVIC ISER, because SysTick is a system exception and not an IRQ. The other 27 are SAMD21 peripherals and belong to OH-68.

WHY THIS IS THE CORE AND NOT A BOARD. cpu.h opens with "Not one address in this file names a chip", and 0xE000E000 does not name a chip: the System Control Space is Armv6-M itself, identical on an RP2040, a SAMD21 and every other Cortex-M0+. Putting SysTick in a board file would make two boards carry the same architectural constant, which is the duplication that moved the memory map OUT of the core in the first place.

THERE IS AN ORACLE, which is what separates this from OH-64 and OH-38. rp2040js is already this repository's Armv6-M oracle and it implements the whole mechanism: exceptionEntry and exceptionReturn in src/cortex-m0-core.ts, and SYST_CSR, SYST_RVR and SYST_CVR in src/peripherals/ppb.ts. ../rp2040js is on disk. So the stack frame layout, the EXC_RETURN values and the SysTick wrap can each be checked against an independent implementation rather than against one reading of DDI0419.

THE ONE APPROXIMATION, and it must be stated where it is made rather than buried. This core has no cycle model, so SysTick has to count something. It counts RETIRED INSTRUCTIONS, the same virtual clock map_counter already uses and for the reason webui/boards/rp2040.py gives at length. rp2040js counts simulated clock cycles instead, so the two agree on the MECHANISM and cannot agree on the RATE. Any lockstep must compare what happens at a wrap rather than when the wrap happens.

WHAT IS DELIBERATELY NOT IN SCOPE. No NVIC, no external interrupts, no PendSV, no SVCall, no process stack, no CONTROL.SPSEL. Handler mode always uses the main stack, which is what an Armv6-M part does out of reset and what every image this repository runs does. Adding the banked stack pointer for a caller that does not exist is what rule 6 forbids. exec.cc currently says the core "models no exceptions, and pretending an SVC returned would let a program continue in a state it never reached" -- that sentence stays true for SVC and stops being true for SysTick, so it has to be rewritten rather than deleted.

CLAIM NOTE. core/cortexm0/exec.cc and core/cortexm0/cpu.h were claimed by OH-64, which is blocked on an oracle it does not have and cannot use them meanwhile. Narrowed off both on 2026-08-26, with a note in that ticket saying it re-claims them when its oracle exists.

Done when a compiled image enables SysTick with TICKINT set, takes the exception at the wrap, runs a handler that increments a counter in memory, returns through EXC_RETURN with r0 to r3, r12, LR, PC and xPSR restored exactly, and does it repeatedly at a steady period -- and when the entry frame is checked word by word against rp2040js rather than against this repository's own reading.
