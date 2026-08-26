---
id: OH-68
title: The SAMD21 peripherals a real Arduino image asks for before it reaches setup
status: open
priority: P1
created: '2026-08-26'
touches:
- webui/boards/samd21.py
- tests/cortexm0/test_samd21_arduino.py
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
