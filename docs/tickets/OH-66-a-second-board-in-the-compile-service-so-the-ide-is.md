---
id: OH-66
title: A second board in the compile service, so the IDE is not an Arduino Uno feature
status: open
priority: P1
created: '2026-08-26'
touches:
- webui/compile.py
- tests/webui/test_compile.py
---

OH-61 built the compile service as one vertical slice and OH-62 put an editor on it. Both work. RECIPES in webui/compile.py has exactly ONE row -- ATmega328P -- so a person can type a sketch and run it on the Arduino Uno and on none of the other twenty-five boards. That was the right scope for OH-61 and it is the wrong place to stop.

TWELVE BOARDS ARE RUNNABLE and eleven of them cannot be built for. The refusal is honest -- recipe_for names the chip and says nothing here knows how to build for it -- but 'honest refusal' is not the product the user asked for twice: 'support standard development workflows like platformio and arduino style'.

WHAT IS INSTALLED HERE, measured 2026-08-26 under $USERPROFILE/.platformio/packages:

  toolchain-atmelavr            avr-gcc 7.3.0            in use
  toolchain-gccarmnoneeabi      arm-none-eabi 12.3.1     unused
  toolchain-riscv32-esp         riscv32-esp-elf 8.4.0    unused
  framework-arduino-samd        cores/arduino, variants for zero/mzero/mkr...
  framework-arduinoespressif32  tools/sdk has esp32, esp32c3, esp32s2, esp32s3
  framework-arduino-mbed        for the Nano RP2040, NOT the XIAO

SO THE TWO CANDIDATES ARE SAMD21 AND ESP32-C3, in that order. Both have a toolchain and a framework already on disk, and both have a board description and a firmware-verified test -- tests/cortexm0/test_samd21_blink.py and tests/riscv32/test_esp32c3_board.py. Neither needs a new download.

WHAT WILL BE DIFFERENT FROM THE AVR ROW, and it is the reason this is a ticket rather than a copy-paste:

(1) A LINKER SCRIPT. The AVR row needs none -- avr-gcc knows where flash starts on an atmega328p from -mmcu alone. An Arm board does not: the SAMD21 has a bootloader at 0x0000 and the sketch at 0x2000, and getting that wrong produces an image that links, loads and executes nothing. Recipe has no field for it yet.

(2) A VARIANT THAT IS NOT THERE. framework-arduino-samd ships variants for Arduino's own boards; a XIAO-SAMD21 variant is Seeed's and is in framework-arduino-seeed-samd, which is NOT installed. Check before promising SAMD21: without the variant, pins_arduino.h does not describe this board and LED_BUILTIN is wrong or absent.

(3) THE BASE ADDRESS. Recipe.base is 0 for a Harvard part whose program space starts there. An Arm board carries its flash origin -- 0x0000 on a SAMD21 after the bootloader question above is settled, 0x42000000 on an ESP32-C3. webui/boards/samd21.py and esp32c3.py already have the numbers with citations; take them from there rather than from the recipe.

(4) ESP32 IS NOT ONE IMAGE. An ESP-IDF build emits bootloader, partitions and application to three addresses -- tools/import_firmware.py already models that with its 'role' field, and OH-10's notes record that boot_app0.bin is a framework constant rather than a build output. A single-image compile service has nowhere to put the other two. Read that before choosing ESP32-C3 over SAMD21.

Done when a sketch typed into the editor builds and runs on a second board, watched by a named test that checks the pin the way tests/webui/test_compile.py checks PB5 -- and when the board's linker script and base address come from its own description rather than from a constant in the recipe.
