---
id: OH-68
title: The SAMD21 peripherals a real Arduino image asks for before it reaches setup
status: done
priority: P1
created: '2026-08-26'
touches:
- webui/boards/samd21.py
- tests/cortexm0/test_samd21_arduino.py
- tests/cortexm0/test_board_samd21.py
---

THE OTHER HALF OF WHAT STOPS OH-66, and the same measurement produced it. A real Arduino-core sketch compiled for the XIAO SAMD21 and run on webui/boards/samd21.py faults on its FIRST peripheral access, at NVMCTRL CTRLB, twelve instructions into SystemInit. The board models flash, SRAM and PORT DIR and OUT and nothing else, which was exactly right for the bare-metal blink it was written for and is not enough for a vendor core.

WHAT THE IMAGE ACTUALLY DEMANDS, measured by auto-stubbing every fault and recording the address, 2026-08-26. Twenty-seven chip registers, in first-touch order:

  NVMCTRL  CTRLB
  PM       APBAMASK, CPUSEL, APBCMASK
  SYSCTRL  XOSC32K, PCLKSR, DFLLCTRL, DFLLMUL, OSC8M
  GCLK     CTRL and STATUS (one word), GENCTRL, GENDIV
  the NVM software calibration row at 0x00806020 and 0x00806024
  PORT     PINCFG and WRCONFIG, both groups
  ADC      CTRLB, REFCTRL, AVGCTRL, SAMPCTRL, INPUTCTRL and STATUS
  DAC      CTRLA and CTRLB

That is the whole list. It is short because a blink sketch is short, and it is longer than the current file because SystemInit configures a clock tree whether the sketch needs one or not.

FOUR OF THEM ARE POLLED AND THE POLARITY IS WHAT MATTERS. SYSCTRL PCLKSR is waited on until a bit is SET -- OSC32KRDY, XOSC32KRDY, DFLLRDY, DFLLLCKC and DFLLLCKF -- so a register reading 0 hangs. GCLK STATUS SYNCBUSY, ADC STATUS SYNCBUSY and DAC STATUS SYNCBUSY are waited on until CLEAR, so a register reading all-ones hangs. Getting either backwards produces an infinite loop rather than a fault, which is the failure class core/cortexm0/cpu.h spends its comments refusing. Both directions have to be asserted by a test, not just the one that happens to work.

WHY A CONSTANT IS THE HONEST MODEL AND NOT A SHORTCUT. There is no crystal here and no DFLL. In a simulator with no analogue parts, "the oscillator is ready" and "the register sync is never busy" are the accurate answers rather than convenient ones -- the same argument webui/boards/rp2040.py makes for UARTFR, and map_constant already exists for exactly this. What it CANNOT express is startup time, and the file must say so where it says it.

THE CALIBRATION ROW IS A MEMORY REGION AND NOT A REGISTER. SystemInit reads the DFLL48M coarse and fine trim out of the NVM software calibration area at NVMCTRL_OTP4, 0x00806020, which is outside the 256K program flash and needs its own add_region. Erased-flash 0xFF is the right fill: it is what an unprogrammed part reads, and the DFLL trim it produces is a legal one.

NOT IN SCOPE, deliberately. No USB, because main() only calls USBDevice.init() when USBCON is defined and the recipe does not have to define it. No SERCOM, because Serial on this board is USB CDC rather than a UART, and a SERCOM model that nothing drives would be a peripheral nobody checked. No EIC, no TC and no TCC.

DEPENDS ON OH-67. Even with every register above modelled, the image stalls in delay() because SysTick cannot deliver its exception. Do OH-67 first; this ticket is not verifiable without it.

Done when the real Arduino-core image runs from its reset vector through SystemInit, init and setup into loop with no fault and no stub, and a named test watches PA17 toggle -- the pin webui/boards/samd21.py already cites Seeed's own variant table for.

**Note 2026-08-26:** CLOSED 2026-08-26 in 1d3acbd. Twenty-seven registers, exactly the list this ticket predicted, and the prediction held because it was a measurement rather than a reading -- every fault stubbed, the image re-run, the address recorded, until it reached loop().

THREE CORRECTIONS TO THE TICKET'S OWN LIST, all small and all worth having. PORT WRCONFIG is NOT reached: this framework's pinMode writes PINCFG directly, so WRCONFIG stays unmodelled and still faults. SYSCTRL DFLLVAL is NOT reached either -- startup.c writes it only inside its CRYSTALLESS branch and the XIAO has a crystal. And the calibration row is at 0x00806020, not 0x00800020: a region at 0x00800000 of 0x100 bytes looks right and covers neither word.

PINCFG IS MODELLED AS A WHOLE ARRAY, sixteen words across both groups, where the image touches seven. A PINCFG where pin 20 answers and pin 21 faults would be a stranger model than either all of it or none of it, and init() calls pinMode on every pin on the board anyway.

RESET VALUES MATTER MORE THAN EXPECTED. SystemInit read-modify-writes PM.APBAMASK, PM.APBCMASK and SYSCTRL.OSC8M. A register starting at zero would write back six enables cleared that a real part has set before the first instruction -- silently, with no fault. The header gives all three as RESETVALUE macros.

ONE RESIDUAL, stated in the code rather than buried. GCLK.CTRL.SWRST is write-one-self-clearing on silicon and a stored register keeps it set. Nothing in this framework polls it alone -- startup.c:93 is an AND with STATUS, which reads zero -- so the loop ends on its second term. A constant reading zero would fix that and break CLKCTRL, which shares the word and is genuinely read/write.

A MUTATION FOUND A DEFECT IN THE TESTS before this was called done. Two of them read their expectation from CLOCKS_ALL_READY, the constant they were meant to pin, and stayed green when it was zeroed -- the same shape as OH-17's floor of len(FAMILIES). They spell the five PCLKSR bit positions out now, cited to component/sysctrl.h:270-283.

MEASURED: PA17 blinks at 48,083 instructions per half period against 48,000 derived from SysTick_Config(SystemCoreClock / 1000), and the handler itself runs at exactly 48,000 with no tolerance. The difference between those two numbers is the sketch's own digitalWrite and loop, which is why one test has a tolerance and the other does not.

NOT DONE, and each for a stated reason: no USB, because there is no host to enumerate to; no SERCOM, so Serial1.begin() stops at a named address rather than transmitting into nothing; no converter behind the ADC, so analogRead faults at SWTRIG instead of returning a plausible voltage.
